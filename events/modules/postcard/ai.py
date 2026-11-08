"""明信片互寄 · AI 审核客户端与审核流（方案 docs/plans/postcard-exchange.md §7）。

OpenAI 兼容协议（``{base_url}/chat/completions``），**urllib 零依赖**：
JSON + base64 图片（data URL），单次调用带超时（默认 30s，绝不挂起 worker）。

判定输出强制严格 JSON（解析失败视为本次失败）::

    {"matched": bool, "mismatched_items": [str], "blacklist_hit": bool,
     "blacklist_names": [str], "comment": str}

- 判定不匹配（含黑名单命中）→ ``ai_failed``，``mismatched_items`` 告知用户
  哪一项填错（用户可申请人工复核）；
- 调用 / 解析失败 → **5 次重试**（指数退避 1/2/4/8s）全败 → 自动转人工复核
  队列 + 连续失败告警计数（**连续 5 个不同用户**失败 → 邮件通知所有绑定
  邮箱的管理员，1h 冷却防轰炸）。

审核粒度 = 一张明信片（``PostcardItem``，正反两面一起送审）；状态写回两面
照片行（同进同出）。照片文件生命周期（通过即删 / 失败 TTL 删 / 活动结束
全删）由 ``lifecycle`` 收口，本模块只产出判定与状态翻转。

调度：``queue_registration_review`` 在登记建单后调用——AI 未配置/未启用时
**同步**转人工（零延迟、无线程）；启用时后台 daemon 线程审（Semaphore(2)
限并发，2C2G 服务器保护），登记接口立即返回。
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from .models import PostcardAIConfig, PostcardAISample, PostcardItem, PostcardPhoto, PostcardRegistration

#: 「5 次重试机会」= 1 次初始调用 + 5 次退避重试（共 6 次尝试，2026-11-08 用户确认）。
RETRY_ATTEMPTS = 6
RETRY_BACKOFF = (1, 2, 4, 8, 16)

#: 后台 AI 线程并发上限（每进程；2C2G 服务器保护，登记侧已有双轨限流）。
REVIEW_CONCURRENCY = 2

#: 连续失败告警阈值 / 计数 TTL / 邮件冷却。
FAIL_STREAK_THRESHOLD = 5
FAIL_STREAK_TTL = 86400
ALERT_COOLDOWN_SECONDS = 3600

_FAIL_STREAK_KEY = "postcard:ai:fail-streak"
_FAIL_USERS_KEY = "postcard:ai:fail-users"
_ALERT_COOLDOWN_KEY = "postcard:ai:alert-cooldown"

_SYSTEM_PROMPT = (
    "你是明信片信息审核员。对照「填写样例」与用户登记信息，判断用户照片中的"
    "明信片填写是否规范、与登记信息一致。只输出一个 JSON 对象，不要任何其他文字。"
)

_review_slots = threading.Semaphore(REVIEW_CONCURRENCY)

#: 可注入的 sleep（测试 patch 掉退避等待）。
_sleep = time.sleep


class AIReviewError(Exception):
    """单次调用失败（网络 / 超时 / 响应形状 / JSON 解析）——可重试。

    message 只面向日志与内部判定，**绝不回显给用户**（用户侧只见「转人工复核」）。
    """


class AIRetryExhausted(Exception):
    """5 次调用机会全部失败——转人工复核。"""


# ---------------------------------------------------------------------------
# 判定解析（严格 JSON）
# ---------------------------------------------------------------------------


def parse_verdict(text: str) -> dict:
    """从模型输出提取并校验判定 JSON；任何不合规 → AIVerdictInvalid（可重试）。"""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise AIReviewError("verdict: no json object")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise AIReviewError("verdict: bad json") from exc
    if not isinstance(data, dict):
        raise AIReviewError("verdict: not an object")
    matched = data.get("matched")
    blacklist_hit = data.get("blacklist_hit")
    if not isinstance(matched, bool) or not isinstance(blacklist_hit, bool):
        raise AIReviewError("verdict: schema mismatch")

    def _str_list(value, limit=10, item_limit=200):
        if not isinstance(value, list):
            return []
        return [str(x)[:item_limit] for x in value[:limit] if x is not None]

    return {
        "matched": matched,
        "mismatched_items": _str_list(data.get("mismatched_items")),
        "blacklist_hit": blacklist_hit,
        "blacklist_names": _str_list(data.get("blacklist_names")),
        "comment": str(data.get("comment") or "")[:500],
    }


# ---------------------------------------------------------------------------
# OpenAI 兼容调用（urllib 零依赖）
# ---------------------------------------------------------------------------


def _image_part(filefield) -> dict:
    """照片 → data URL 消息段（重编码后一律 JPEG，无用户可控 Content-Type 面）。"""
    with filefield.open("rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def build_messages(cfg: PostcardAIConfig, item: PostcardItem, samples: list) -> list:
    """组装判定输入：登记信息 + 样例（图 + 说明）+ 用户正反面照片 + 黑名单规则。"""
    reg = item.registration
    form_text = (
        f"寄出人：{reg.sender_name}（{reg.grade_label} {reg.class_no}班）\n"
        f"寄达区：{reg.dest_region}\n"
        f"寄达校：{reg.dest_school}\n"
        f"明信片条码：{item.barcode.code}"
    )
    blacklist = "、".join(cfg.ip_blacklist or []) or "（空）"
    sample_captions = "；".join(
        (s.caption or "（无说明）") for s in samples
    ) or "（无样例）"
    content = [
        {
            "type": "text",
            "text": (
                "对照「填写样例」与用户登记信息，审核用户照片中的明信片。\n"
                f"【用户登记信息】\n{form_text}\n"
                f"【填写样例说明】{sample_captions}\n"
                f"【网络动漫产品黑名单（形象 IP）】{blacklist}\n"
                "规则：\n"
                "1) 照片与登记信息不一致或填写不规范 → matched=false，"
                "mismatched_items 列出具体哪一项（面向学生的简短中文）；\n"
                "2) 照片文字或图案出现黑名单形象 → blacklist_hit=true 且 matched=false，"
                "blacklist_names 写命中名称；\n"
                "3) 不是黑名单形象、或无法确认 → blacklist_hit=false（通过）；\n"
                "4) 只输出 JSON：{\"matched\":bool,\"mismatched_items\":[...],"
                "\"blacklist_hit\":bool,\"blacklist_names\":[...],\"comment\":\"...\"}"
            ),
        },
    ]
    for s in samples[:4]:  # 样例最多 4 张，防 token 爆炸
        content.append(_image_part(s.image))
    for photo in item.photos.order_by("side"):
        if photo.file:
            content.append(_image_part(photo.file))
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def call_once(cfg: PostcardAIConfig, messages: list) -> dict:
    """单次调用 + 严格解析。任何失败 raise AIReviewError（可重试）。"""
    url = cfg.base_url.strip().rstrip("/") + "/chat/completions"
    payload = {"model": cfg.model.strip(), "messages": messages, "temperature": 0}
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    for key, value in (cfg.extra_headers or {}).items():
        # 管理员自定义头（如 x-api-key）；只收 str:str，防类型注入。
        if isinstance(key, str) and isinstance(value, str) and key.strip():
            headers[key.strip()] = value
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout_seconds or 20) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise AIReviewError(f"network: {type(exc).__name__}") from exc
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIReviewError("response: unexpected shape") from exc
    if not isinstance(text, str) or not text.strip():
        raise AIReviewError("response: empty content")
    return parse_verdict(text)


def review_item_with_retry(cfg: PostcardAIConfig, item: PostcardItem, samples: list) -> dict:
    """单张明信片：最多 RETRY_ATTEMPTS 次调用机会（指数退避），全败抛 AIRetryExhausted。"""
    messages = build_messages(cfg, item, samples)
    last_error: AIReviewError | None = None
    for attempt in range(RETRY_ATTEMPTS):
        if attempt:
            _sleep(RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)])
        try:
            return call_once(cfg, messages)
        except AIReviewError as exc:
            last_error = exc
    raise AIRetryExhausted(str(last_error))


# ---------------------------------------------------------------------------
# 连续失败告警（Redis / cache 计数，按用户去重）
# ---------------------------------------------------------------------------


def _user_key(reg: PostcardRegistration) -> str:
    """用户标识（三轨取一，稳定即可）：ncdid > 指纹哈希 > 登录用户。"""
    if reg.device_id:
        return f"d:{reg.device_id}"
    if reg.fingerprint_hash:
        return f"f:{reg.fingerprint_hash[:16]}"
    return f"u:{reg.user_id}"


def note_review_success(user_key: str) -> None:
    """任一成功调用即打断「连续失败」streak。"""
    cache.delete(_FAIL_STREAK_KEY)
    cache.delete(_FAIL_USERS_KEY)


def note_review_failure(user_key: str) -> None:
    """技术失败（非判定不匹配）计数；连续 5 个不同用户 → 邮件告警 + 重置。"""
    streak = cache.get(_FAIL_STREAK_KEY) or 0
    users = cache.get(_FAIL_USERS_KEY) or []
    if user_key in users:
        return  # 同一用户重复失败不重复计数
    users = users + [user_key]
    streak += 1
    cache.set(_FAIL_STREAK_KEY, streak, FAIL_STREAK_TTL)
    cache.set(_FAIL_USERS_KEY, users, FAIL_STREAK_TTL)
    if streak >= FAIL_STREAK_THRESHOLD and not cache.get(_ALERT_COOLDOWN_KEY):
        _send_admin_alert(streak, users)
        cache.set(_ALERT_COOLDOWN_KEY, 1, ALERT_COOLDOWN_SECONDS)
        cache.delete(_FAIL_STREAK_KEY)
        cache.delete(_FAIL_USERS_KEY)


def _admin_recipients() -> list:
    """所有「被标记为管理员」且绑定了邮箱的用户（staff / 超管 / 持明信片权限）。"""
    perms = ("manage_postcard", "review_postcard")
    return list(
        User.objects.filter(
            Q(is_staff=True)
            | Q(is_superuser=True)
            | Q(user_permissions__codename__in=perms)
            | Q(groups__permissions__codename__in=perms)
        )
        .exclude(email="")
        .exclude(email__isnull=True)
        .values_list("email", flat=True)
        .distinct()
    )


def _send_admin_alert(streak: int, users: list) -> None:
    recipients = _admin_recipients()
    if not recipients:
        return
    send_mail(
        "【明信片互寄】AI 审核连续失败告警",
        (
            f"AI 审核已连续 {streak} 个用户调用失败（均已自动转人工复核）。\n"
            "请尽快检查 AI 配置：Base URL / API Key / 模型可用性。\n"
            "——社团网站自动告警（1 小时内不重复发送）"
        ),
        settings.DEFAULT_FROM_EMAIL,
        recipients,
        fail_silently=True,
    )


# ---------------------------------------------------------------------------
# 审核流（登记单 → 逐张明信片）
# ---------------------------------------------------------------------------


def review_registration(reg: PostcardRegistration) -> dict:
    """同步审核一张登记单的全部明信片（重入安全：已终态 / 已删文件的跳过）。

    返回统计 {passed, failed, manual}。调用方：后台线程 _review_worker，
    或测试直接同步调用。
    """
    from . import lifecycle

    cfg = PostcardAIConfig.load()
    if cfg is None or not cfg.ready:
        # 双保险：调度层已挡，这里再挡一次（配置中途被关）。
        lifecycle.settle_registration(reg, PostcardPhoto.REVIEW_MANUAL_PENDING,
                                      verdict={"reason": "ai_unavailable"})
        return {"passed": 0, "failed": 0, "manual": reg.items.count()}

    samples = list(reg.event.postcard_ai_samples.all())
    user_key = _user_key(reg)
    stats = {"passed": 0, "failed": 0, "manual": 0}
    any_call_failure = False
    for item in reg.items.select_related("barcode", "registration").prefetch_related("photos"):
        photos = list(item.photos.all())
        if not photos:
            continue
        # 重入安全：文件已删（审过）或已离开 pending 的不再动。
        if any(not p.file for p in photos) or any(
            p.review_state != PostcardPhoto.REVIEW_PENDING for p in photos
        ):
            continue
        try:
            verdict = review_item_with_retry(cfg, item, samples)
        except AIRetryExhausted:
            any_call_failure = True
            lifecycle.settle_item_photos(
                item, PostcardPhoto.REVIEW_MANUAL_PENDING,
                verdict={"reason": "ai_retry_exhausted"},
            )
            stats["manual"] += 1
            continue
        note_review_success(user_key)
        if verdict["matched"] and not verdict["blacklist_hit"]:
            lifecycle.settle_item_photos(
                item, PostcardPhoto.REVIEW_AI_PASSED, verdict=verdict, purge_files=True,
            )
            stats["passed"] += 1
        else:
            lifecycle.settle_item_photos(
                item, PostcardPhoto.REVIEW_AI_FAILED, verdict=verdict,
            )
            stats["failed"] += 1
    if any_call_failure:
        note_review_failure(user_key)
    if stats["manual"]:
        _notify_manual(reg)
    return stats


def _review_worker(reg_pk: int) -> None:
    """后台线程体：任何未捕获异常 → 兜底转人工（照片绝不卡 pending）。"""
    from . import lifecycle

    with _review_slots:
        reg = (
            PostcardRegistration.objects.select_related("event")
            .filter(pk=reg_pk)
            .first()
        )
        if reg is None or reg.status == PostcardRegistration.STATUS_CANCELLED:
            return
        try:
            review_registration(reg)
        except Exception:  # noqa: BLE001 —— 兜底：线程内异常不外泄、不卡状态
            lifecycle.settle_registration(
                reg, PostcardPhoto.REVIEW_MANUAL_PENDING,
                verdict={"reason": "ai_worker_error"},
            )


def _notify_manual(reg) -> None:
    from .notify import notify_reviewers

    notify_reviewers(reg)


def queue_registration_review(reg: PostcardRegistration) -> str:
    """登记建单后调度审核。返回初始 review_state（响应里带给前端）。

    - AI 未配置 / 未启用 → **同步**转人工复核（零延迟、不起线程）；
    - 启用 → 后台 daemon 线程（Semaphore 限并发），登记接口立即返回。
    """
    from . import lifecycle

    cfg = PostcardAIConfig.load()
    if cfg is None or not cfg.ready:
        lifecycle.settle_registration(
            reg, PostcardPhoto.REVIEW_MANUAL_PENDING, verdict={"reason": "ai_unavailable"},
        )
        _notify_manual(reg)
        return PostcardPhoto.REVIEW_MANUAL_PENDING
    thread = threading.Thread(
        target=_review_worker, args=(reg.pk,), daemon=True,
        name=f"postcard-ai-{reg.pk}",
    )
    thread.start()
    return PostcardPhoto.REVIEW_PENDING


# ---------------------------------------------------------------------------
# 连通性测试（管理端「测试连接」按钮）
# ---------------------------------------------------------------------------


def _http_error_text(code: int) -> str:
    """把厂商 HTTP 状态码收敛成一句可操作的中文（不回显响应体，防泄露）。"""
    if code in (401, 403):
        return "鉴权失败：API Key 无效或没有该模型的权限"
    if code == 404:
        return "接口不存在：请检查 Base URL 是否包含 /v1（如 https://api.example.com/v1）"
    if code == 429:
        return "被上游限流：请稍后重试或检查额度"
    if 500 <= code < 600:
        return f"上游服务错误（HTTP {code}），请稍后重试"
    return f"请求被拒绝（HTTP {code}）"


def test_connection(cfg: PostcardAIConfig) -> dict:
    """用已保存的配置发一次最小对话请求，验证 URL / Key / 模型是否可用。

    只发纯文本（不带图片），避免在 3M 带宽上测个连接就传几百 KB；
    返回 ``{ok, latency_ms, model, reply}`` 或 ``{ok: False, error}``。
    **绝不回显 api_key**，错误文案只给结论。
    """
    import time

    url = cfg.base_url.strip().rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model.strip(),
        "messages": [{"role": "user", "content": "只回复两个字：正常"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    for key, value in (cfg.extra_headers or {}).items():
        if isinstance(key, str) and isinstance(value, str) and key.strip():
            headers[key.strip()] = value

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=min(cfg.timeout_seconds or 20, 20)) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        text = body["choices"][0]["message"]["content"]
        latency = int((time.monotonic() - started) * 1000)
        return {
            "ok": True,
            "latency_ms": latency,
            "model": cfg.model,
            "reply": str(text or "").strip()[:120],
        }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": _http_error_text(exc.code)}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"ok": False, "error": "网络不可达或超时：请检查 Base URL 与服务器出网"}
    except (KeyError, IndexError, TypeError, ValueError):
        return {"ok": False, "error": "响应不是 OpenAI 兼容格式（缺 choices[0].message.content）"}
