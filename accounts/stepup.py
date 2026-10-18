"""安全验证（Step-up）：敏感操作前的「是本人」确认（ADR-0026）。

与「认证」（原验证系统，更名后）正交：
- 认证回答「账号是不是可信社员」——低频、面向入社；
- 安全验证回答「现在这个操作是不是本人」——每次危险操作前的二次确认。

组成（P1）：
- 验证方式：① 邮箱验证码（只发**已认证邮箱**，即 ``User.email`` 非空） ② 安全问题（预设题库、
  答案哈希存储）；方式可扩展（TOTP 等后续接入）。
- 作用域（scope）：change_password / manage_questions / change_email。
- 令牌（grant）：验证通过后签发 Django signing 令牌（账号 + scope + 时间戳），TTL 10 分钟；
  服务端**无状态、不入库**；前端存 sessionStorage，随请求带 ``X-StepUp-Grant`` 头；
  同 scope 窗口内复用（10 分钟内免复验）。

规格（设计稿 §B3.6 / §B3.7）：
- 邮箱码：6 位数字 / TTL 10 分钟 / 同码最多试 5 次 / 60 秒重发冷却 / 每小时上限入站点策略；
- 安全问题：每账号 1–3 题（预设题库，不出自定义题）；验证时抽 1 题作答；答案归一
  （NFKC 全半角 / 去空白 / 大小写）；连错 5 次锁 10 分钟；
- Bootstrap：首次设置问答＝重输登录密码（防「偷到会话但没有密码」）；之后更换 = grant。
"""
from __future__ import annotations

import logging
import secrets
import unicodedata
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import JsonResponse
from django.utils import timezone

from .models import SecurityQuestion, StepUpEmailCode, StepUpEvent

logger = logging.getLogger(__name__)

# ---- 常量 ----
CODE_TTL = timedelta(minutes=10)
CODE_MAX_ATTEMPTS = 5
CODE_COOLDOWN_SECONDS = 60
QUESTION_MAX_FAILS = 5
QUESTION_LOCK_SECONDS = 600
GRANT_TTL_SECONDS = 600
_GRANT_SALT = "nanhui.stepup.grant"

# 作用域 → 用户可读名称（前端 StepUpPage 展示用；新动作在此登记即接通架构）
SCOPES = {
    "change_password": "修改密码",
    "manage_questions": "管理安全问题",
    "change_email": "换绑邮箱",
}

# 预设题库（不出自定义题——防「答案就写在题干里」）
STEPUP_QUESTION_BANK = [
    ("primary_school", "你小学的名称是？"),
    ("first_teacher", "你印象最深的一位老师的姓氏是？"),
    ("favorite_book", "你最喜欢的一本书是？"),
    ("birth_city", "你出生的城市是？"),
    ("pet_name", "你养过的第一只宠物的名字是？"),
    ("favorite_song", "你最喜欢的一首歌是？"),
    ("best_friend", "你关系最好的一位朋友的称呼是？"),
    ("childhood_toy", "你童年最珍视的玩具是？"),
    ("favorite_dish", "你最喜欢的一道菜是？"),
    ("dream_place", "你最想去旅行的地方是？"),
]


class StepUpError(Exception):
    """安全验证失败（文案直接回给用户）。"""


def normalize_answer(raw: str) -> str:
    """答案归一：NFKC（全角→半角）→ 去全部空白 → 大小写折叠。"""
    text = unicodedata.normalize("NFKC", raw or "")
    return "".join(text.split()).casefold()


# ---- 安全问题 ----
def question_bank() -> list[dict]:
    return [{"key": key, "text": text} for key, text in STEPUP_QUESTION_BANK]


def set_security_questions(user, items: list[dict]) -> None:
    """设置 / 更换 /（items 为空时）清除：1–3 题、须在题库内、答案非空；整体替换。"""
    if not items:
        user.security_questions.all().delete()
        return
    if len(items) > 3:
        raise StepUpError("最多设置 3 个安全问题。")
    bank = dict(STEPUP_QUESTION_BANK)
    rows = []
    for item in items:
        key = (item.get("key") or "").strip()
        answer = normalize_answer(item.get("answer") or "")
        if key not in bank:
            raise StepUpError("包含未知的题目。")
        if not answer:
            raise StepUpError("答案不能为空。")
        rows.append((key, bank[key], make_password(answer)))
    user.security_questions.all().delete()
    SecurityQuestion.objects.bulk_create([
        SecurityQuestion(user=user, question_key=key, question_text=text, answer_hash=hashed)
        for key, text, hashed in rows
    ])


def check_security_answer(user, question_id: int, answer: str) -> None:
    """校验一条安全问题答案；失败抛 ``StepUpError``。连错 5 次锁 10 分钟。"""
    lock_key = f"stepup_q_lock:{user.pk}"
    if cache.get(lock_key):
        raise StepUpError("尝试次数过多，请 10 分钟后再试。")
    question = user.security_questions.filter(pk=question_id).first()
    if question is None:
        raise StepUpError("题目不存在。")
    if not check_password(normalize_answer(answer), question.answer_hash):
        fails_key = f"stepup_q_fails:{user.pk}"
        fails = cache.get(fails_key, 0) + 1
        cache.set(fails_key, fails, QUESTION_LOCK_SECONDS)
        if fails >= QUESTION_MAX_FAILS:
            cache.set(lock_key, True, QUESTION_LOCK_SECONDS)
            cache.delete(fails_key)
        raise StepUpError("答案不正确。")
    cache.delete(f"stepup_q_fails:{user.pk}")


# ---- 邮箱验证码 ----
def email_available(user) -> bool:
    """邮箱验证方式可用性：只发**已认证邮箱**（``User.email`` 非空）。"""
    return bool((user.email or "").strip())


def email_cooldown_remaining(user) -> int:
    """重发冷却剩余秒数（0 = 可发）。"""
    expires_ts = cache.get(f"stepup_email_cd:{user.pk}")
    if not expires_ts:
        return 0
    return max(0, int(float(expires_ts) - timezone.now().timestamp()))


def send_email_code(user) -> StepUpEmailCode:
    """生成并发送 6 位验证码；旧未用码作废。返回码行（明文不落库、只进邮件）。"""
    if not email_available(user):
        raise StepUpError("当前账号没有已认证邮箱，无法使用邮箱验证码。")
    code = f"{secrets.randbelow(1_000_000):06d}"
    StepUpEmailCode.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
    row = StepUpEmailCode.objects.create(
        user=user,
        code_hash=make_password(code),
        sent_to=user.email,
        expires_at=timezone.now() + CODE_TTL,
    )
    send_mail(
        subject="安全验证码 - 南汇一中传媒社",
        message=(
            f"你好！你的安全验证码是：{code}\n\n"
            "有效期 10 分钟，请勿泄露给他人。\n"
            "若非本人操作，请忽略本邮件，并考虑修改密码。\n\n"
            "——南汇一中传媒社 信息组"
        ),
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )
    cache.set(
        f"stepup_email_cd:{user.pk}",
        timezone.now().timestamp() + CODE_COOLDOWN_SECONDS,
        CODE_COOLDOWN_SECONDS + 5,
    )
    return row


def verify_email_code(user, code: str) -> None:
    """校验最新一条验证码；错误统一文案（不泄露细节）。"""
    code = (code or "").strip()
    if not code:
        raise StepUpError("请输入验证码。")
    row = (
        StepUpEmailCode.objects.filter(user=user, used_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if row is None or row.expires_at <= timezone.now() or row.attempts >= CODE_MAX_ATTEMPTS:
        raise StepUpError("验证码错误或已过期。")
    if not check_password(code, row.code_hash):
        row.attempts += 1
        row.save(update_fields=["attempts"])
        raise StepUpError("验证码错误或已过期。")
    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])


# ---- 令牌（grant）----
def issue_grant(user, scope: str) -> str:
    return signing.dumps({"u": user.pk, "s": scope}, salt=_GRANT_SALT)


def check_grant(user, scope: str, token: str | None) -> bool:
    if not token:
        return False
    try:
        data = signing.loads(token, salt=_GRANT_SALT, max_age=GRANT_TTL_SECONDS)
    except signing.BadSignature:
        return False
    return data.get("u") == user.pk and data.get("s") == scope


def grant_from_request(request, scope: str) -> bool:
    """受保护端点入口：请求头 ``X-StepUp-Grant`` 校验（须登录态）。"""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    return check_grant(user, scope, request.headers.get("X-StepUp-Grant"))


def stepup_required_response(scope: str) -> JsonResponse:
    """受保护端点缺令牌的统一 403（前端按 reason 跳转验证页）。"""
    return JsonResponse(
        {"error": "需要先完成安全验证。", "reason": "step_up_required", "scope": scope},
        status=403,
    )


# ---- 审计 ----
def _request_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")
    if forwarded and forwarded[-1].strip():
        return forwarded[-1].strip()
    return request.META.get("REMOTE_ADDR")


def record_event(user, scope: str, method: str, result: str, request=None) -> None:
    """轻量审计：谁 / 何时 / 哪种方式 / 成败（供「安全验证」面板展示）。"""
    try:
        StepUpEvent.objects.create(
            user=user, scope=scope, method=method, result=result, ip=_request_ip(request),
        )
    except Exception:  # 审计失败不影响主流程
        logger.exception("记录 StepUpEvent 失败：user_pk=%s scope=%s", getattr(user, "pk", None), scope)
