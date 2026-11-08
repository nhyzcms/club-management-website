"""明信片互寄 · 视图与业务流（方案 docs/plans/postcard-exchange.md）。

公开端点（AllowAny + phase 门禁 + 双轨限流 + Turnstile）：

- ``GET  portal/``：独立页一站式状态（阶段/公告/进度/表单元数据）；
- ``POST register/``：登记（multipart：表单 + photo_<i>_front/back）；
- ``GET  my/`` + ``PATCH my/<reg_code>/`` + ``POST my/<reg_code>/cancel/``：
  历史记录（ncdid/指纹/登录用户三轨识别；**改/取消必须命中登记码**）；
- ``POST suggestions/``：建议箱；
- ``GET  announcement-pdf/``：公告 PDF（CSP:sandbox + nosniff，PDF 内嵌 JS 不可能执行）；
- ``GET  photo/<pk>/``：照片鉴权下发（复核权限，或本人出示登记码）。

管理端点（命名权限 + 全量审计）：

- ``config/`` GET/PUT（首次 PUT 自动建 Event 壳）、``publish/``；
- ``barcodes/`` 生成与汇总、``barcodes/pdf/`` 整版导出；
- ``records/`` 搜索/筛选、``registrations/<reg_code>/`` 改/删、``export/``；
- ``stats/`` 总数据统计；``lookup/`` + ``confirm/`` + ``unreport/`` 签收三件套；
- ``suggestions/``、``audit/``。

安全要点（对照方案 §5）：登记码即能力凭证（绝不按自增 id 暴露写入口）；
非本人记录一律 404（不泄露存在性）；错误文案面向用户、不回显内部细节。
"""
from __future__ import annotations

import hashlib
import json
import re

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from accounts.turnstile import passes_turnstile, turnstile_error_response
from accounts.utils import device_id_from_request, get_client_ip
from common.rich_text import sanitize_html
from events import lifecycle
from events.models import Event

from . import barcode as barcode_mod
from . import lifecycle as photo_lifecycle
from . import state
from .models import (
    PostcardAIConfig,
    PostcardAISample,
    PostcardAuditLog,
    PostcardBarcode,
    PostcardConfig,
    PostcardItem,
    PostcardPhoto,
    PostcardRegistration,
    PostcardSuggestion,
)
from .permissions import CanManagePostcard, CanReviewPostcard
from .serializers import (
    AdminConfigInput,
    AdminRegistrationEditInput,
    AIConfigInput,
    MyRecordEditInput,
    RegisterInput,
    ReviewDecisionInput,
    SuggestionInput,
    registration_summary,
)
from .throttles import (
    CodeAccessDeviceThrottle,
    CodeAccessIPThrottle,
    LookupDeviceThrottle,
    LookupIPThrottle,
    RegisterDeviceThrottle,
    RegisterIPThrottle,
    SuggestionDeviceThrottle,
    SuggestionIPThrottle,
)

# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------


def _audit(event, request, action: str, target: str = "", detail=None):
    """管理员操作留痕。失败静默——审计不该拖垮业务（但正常不会失败）。"""
    try:
        PostcardAuditLog.objects.create(
            event=event,
            user=request.user if request.user.is_authenticated else None,
            action=action,
            target=target[:256],
            detail=detail,
            ip=get_client_ip(request),
        )
    except Exception:  # noqa: BLE001
        pass


def _fingerprint_hash(fp: str) -> str:
    return hashlib.sha256(fp.encode("utf-8")).hexdigest() if fp else ""


def _identity_filters(request, fp_hash: str):
    """归属三轨的 Q 过滤：ncdid / 指纹哈希 / 登录用户。"""
    from django.db.models import Q

    device = device_id_from_request(request)
    q = Q()
    if device:
        q |= Q(device_id=device)
    if fp_hash:
        q |= Q(fingerprint_hash=fp_hash)
    if request.user.is_authenticated:
        q |= Q(user=request.user)
    return q


def _new_reg_code(event) -> str:
    """6 位随机登记码（单活动唯一；碰撞重试，DB 约束兜底）。"""
    import secrets

    for _ in range(50):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if not PostcardRegistration.objects.filter(event=event, reg_code=code).exists():
            return code
    raise RuntimeError("登记码空间耗尽")  # 10^6 内 50 次全碰撞：不可能事件


_REGCODE_RE = re.compile(r"^\d{6}$")


def _phase_guard(*, admin: bool = False):
    """取 (event, config, phase)。活动不存在 → (None, None, 未开始)。

    ``admin=True`` 时草稿活动也纳入（配置页要能看到已建未发的活动）。
    phase 推导出「已结束」时惰性触发照片全清（方案 §7：状态翻转触发 +
    周期兜底双保险）——任何明信片请求都会过这道闸。
    """
    event = state.current_event(include_draft=admin)
    config = getattr(event, "postcard_config", None) if event else None
    phase = state.phase_of(event, config)
    photo_lifecycle.maybe_purge_ended_event(event, phase)
    return event, config, phase


# ---------------------------------------------------------------------------
# 公开端点
# ---------------------------------------------------------------------------


class PortalView(APIView):
    """独立页一站式状态。未开始时对普通用户不泄露表单元数据（年级/学校清单）。"""

    permission_classes = [AllowAny]

    def get(self, request):
        event, config, phase = _phase_guard()
        is_admin = bool(
            request.user.is_authenticated and (
                request.user.is_superuser
                or request.user.has_perm("events.manage_postcard")
                or request.user.has_perm("events.review_postcard")
            )
        )
        payload = {
            "phase": phase,
            "phase_label": state.PHASE_LABELS.get(phase, phase),
            "can_register": state.can_register(phase),
            "is_admin": is_admin,
            # PR2：样例门禁——活动开始前管理员必须上传填写样例，否则登记不开放。
            "sample_ready": (
                PostcardAISample.objects.filter(event=event).exists() if event else False
            ),
            "event": None,
            "progress": [],
            "grades": [],
            "classes": list(range(1, 9)),
            "regions": [],
            "schools": [],
            "announcement_pdf": False,
            # 公告正文：入库前已 bleach 白名单净化（AdminConfigView PUT），
            # 这里原样下发，前端直接渲染。
            "announcement_body": "",
        }
        if event is not None:
            payload["event"] = {
                "id": event.pk,
                "title": event.title,
                "summary": event.summary,
                "start_at": event.start_at.isoformat(),
                "end_at": event.end_at.isoformat() if event.end_at else None,
            }
            payload["progress"] = state.progress_nodes(event, config)
        if config is not None:
            payload["announcement_pdf"] = bool(config.announcement_pdf)
            payload["announcement_body"] = config.announcement_body or ""
            # 表单元数据只在「登记中」对普通用户开放；管理员任何阶段都要（配置预览）。
            if state.can_register(phase) or is_admin:
                payload["grades"] = config.grade_options()
                payload["regions"] = config.regions()
                payload["schools"] = config.destination_schools or []
        return Response(payload)


class RegisterView(APIView):
    """登记提交：phase 门禁 → Turnstile → 双轨限流 → 校验 → 原子建单。

    multipart 契约：``items`` 为 JSON 字符串（[{barcode}]），照片文件键
    ``photo_<i>_front`` / ``photo_<i>_back``（i = items 下标，两面必填）。
    照片先全部重编码校验通过才建单——失败零残留（无孤儿行/孤儿文件）。
    """

    permission_classes = [AllowAny]
    throttle_classes = [RegisterIPThrottle, RegisterDeviceThrottle]

    def post(self, request):
        event, config, phase = _phase_guard()
        if event is None or config is None or not state.can_register(phase):
            return Response({"detail": "当前不在登记期内"}, status=400)
        # —— 样例门禁（PR2）：活动开始前管理员必须上传「填写样例」——
        if not PostcardAISample.objects.filter(event=event).exists():
            return Response(
                {"detail": "活动填写样例尚未配置，暂不能登记；请联系管理员"},
                status=400,
            )
        if not passes_turnstile(request, request.data.get("turnstile_token") or ""):
            return turnstile_error_response(drf=True)

        try:
            items_raw = json.loads(request.data.get("items") or "[]")
        except (TypeError, ValueError):
            return Response({"detail": "登记数据格式错误"}, status=400)

        serializer = RegisterInput(data={
            "sender_name": request.data.get("sender_name"),
            "grade": request.data.get("grade"),
            "class_no": request.data.get("class_no"),
            "dest_region": request.data.get("dest_region"),
            "dest_school": request.data.get("dest_school"),
            "items": items_raw,
            "fingerprint": request.data.get("fingerprint") or "",
        })
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # —— 业务校验（不通过给用户可读的具体原因）——
        if data["grade"] not in (config.allowed_grades or [k for k, _ in PostcardConfig.GRADE_CHOICES]):
            return Response({"detail": "你的年级不在本次活动可参与范围内"}, status=400)
        if data["dest_region"] not in PostcardConfig.REGION_CHOICES:
            return Response({"detail": "寄达区不在支持范围内"}, status=400)
        school_pairs = {
            ((s.get("region") or "").strip(), (s.get("name") or "").strip())
            for s in (config.destination_schools or [])
        }
        if (data["dest_region"], data["dest_school"]) not in school_pairs:
            return Response({"detail": "寄达校不在本次活动支持的学校清单内"}, status=400)

        barcode_codes = [it["barcode"] for it in data["items"]]
        barcodes = {
            b.code: b for b in PostcardBarcode.objects.filter(event=event, code__in=barcode_codes)
        }
        missing = [c for c in barcode_codes if c not in barcodes]
        if missing:
            return Response(
                {"detail": f"条码 {missing[0]} 不存在，请核对明信片上的条码"},
                status=400,
            )
        claimed = set(
            PostcardItem.objects.filter(
                barcode_id__in=[b.pk for b in barcodes.values()]
            ).values_list("barcode_id", flat=True)
        )
        if claimed:
            bad = next(b.code for b in barcodes.values() if b.pk in claimed)
            return Response({"detail": f"条码 {bad} 已被登记过，一条码对应一份明信片"}, status=400)

        # —— 照片：先全部重编码（任何一张失败 → 整单拒绝，零残留）——
        from .photos import PhotoRejected, validate_and_reencode

        photo_files: dict[int, dict[str, object]] = {}
        try:
            for i in range(len(barcode_codes)):
                pair = {}
                for side in ("front", "back"):
                    f = request.FILES.get(f"photo_{i}_{side}")
                    if f is None:
                        raise PhotoRejected(f"第 {i + 1} 张明信片缺少{'正' if side == 'front' else '反'}面照片")
                    pair[side] = validate_and_reencode(f)
                photo_files[i] = pair
        except PhotoRejected as exc:
            return Response({"detail": exc.reason}, status=400)

        # —— 原子建单 ——
        fp_hash = _fingerprint_hash(data.get("fingerprint") or "")
        with transaction.atomic():
            reg = PostcardRegistration.objects.create(
                event=event,
                reg_code=_new_reg_code(event),
                sender_name=data["sender_name"],
                grade=data["grade"],
                class_no=data["class_no"],
                dest_region=data["dest_region"],
                dest_school=data["dest_school"],
                device_id=device_id_from_request(request),
                fingerprint_hash=fp_hash,
                user=request.user if request.user.is_authenticated else None,
            )
            for i, code in enumerate(barcode_codes):
                item = PostcardItem.objects.create(registration=reg, barcode=barcodes[code])
                for side, content in photo_files[i].items():
                    photo = PostcardPhoto(item=item, side=side)
                    photo.file.save(f"{item.pk}-{side}.jpg", content, save=True)

        # —— AI 审核调度（PR2）：未启用 → 同步转人工；启用 → 后台线程，
        # 登记接口立即返回（绝不挂起 worker，方案 §9）。前端轮询 my/<code>/ 拿结果。
        from . import ai

        review_state = ai.queue_registration_review(reg)

        return Response({
            "reg_code": reg.reg_code,
            "message": "登记成功！请保存好您的登记码，凭它可查看和修改自己的登记记录",
            "registration": registration_summary(reg),
            "review": {
                "state": review_state,
                "hint": (
                    "照片正在 AI 审核，结果稍后可在「历史登记记录」查看"
                    if review_state == PostcardPhoto.REVIEW_PENDING
                    else "AI 审核暂不可用，已转人工复核"
                ),
            },
        }, status=201)


class MyRegistrationsView(APIView):
    """历史登记记录：按 ncdid / 指纹 / 登录用户三轨匹配。"""

    permission_classes = [AllowAny]

    def get(self, request):
        event, _, _ = _phase_guard()
        if event is None:
            return Response({"results": []})
        fp_hash = _fingerprint_hash(request.query_params.get("fingerprint") or "")
        qs = (
            PostcardRegistration.objects.filter(event=event)
            .filter(_identity_filters(request, fp_hash))
            .prefetch_related("items__barcode", "items__photos")
            .order_by("-created_at")
        )
        return Response({"results": [registration_summary(r) for r in qs]})


def _get_own_registration(request, reg_code: str) -> PostcardRegistration:
    """按登记码（能力凭证）取登记单；码不命中一律 404（不泄露存在性）。

    2026-11-08 起（用户要求「换设备也能凭码查/改」）：登记码本身就是唯一
    能力凭证——不再强制三轨命中（`/my/` 列表仍按 ncdid/指纹/登录用户归集）。
    6 位数字的枚举风险由视图层双轨限流兜底（30/min 设备 + 120/h IP）。
    MyRegistrationDetailView / 复核申请 / sendBeacon 清理三个用户侧入口共用。
    """
    event, _, _ = _phase_guard()
    if event is None:
        raise Http404
    reg = (
        PostcardRegistration.objects.filter(event=event, reg_code=reg_code)
        .prefetch_related("items__barcode", "items__photos")
        .first()
    )
    if reg is None:
        raise Http404
    return reg


class LookupView(APIView):
    """用户侧查询入口（2026-11-08 用户要求）：按登记码或寄出人姓名查登记单。

    - **q = 6 位数字** → 登记码即能力凭证：返回**完整**摘要（含 reg_code），
      前端据此直接改 / 取消 / 申请复核（`/my/<code>/` 同为凭证通道）；
    - **q = 姓名（2~64 字，精确匹配）** → 只返回**掩码**摘要（reg_code →
      ``82****``、照片列表清空）：用于确认「登记是否成功 / 什么状态」，
      修改必须出示完整登记码——否则任何人凭姓名就能改别人记录。

    双轨限流（设备 20/min + IP 300/h）防枚举；姓名不命中返回空列表，
    不区分「无此人」与「无记录」（不泄露他人是否存在登记）。
    """

    permission_classes = [AllowAny]
    throttle_classes = [LookupIPThrottle, LookupDeviceThrottle]

    def post(self, request):
        q = (request.data.get("q") or "").strip()
        if not q:
            return Response({"detail": "请输入 6 位登记码或寄出人姓名"}, status=400)
        event, _, _ = _phase_guard()
        if event is None:
            return Response({"kind": "code" if _REGCODE_RE.fullmatch(q) else "name", "results": []})
        if _REGCODE_RE.fullmatch(q):
            reg = (
                PostcardRegistration.objects.filter(event=event, reg_code=q)
                .prefetch_related("items__barcode", "items__photos")
                .first()
            )
            return Response(
                {"kind": "code", "results": [registration_summary(reg)] if reg else []}
            )
        if len(q) < 2:
            return Response({"detail": "姓名至少 2 个字"}, status=400)
        if len(q) > 64:
            return Response({"detail": "姓名过长，请核对后重试"}, status=400)
        qs = (
            PostcardRegistration.objects.filter(event=event, sender_name=q)
            .prefetch_related("items__barcode", "items__photos")
            .order_by("-created_at")[:20]
        )
        return Response({"kind": "name", "results": [_masked_summary(r) for r in qs]})


def _masked_summary(reg: PostcardRegistration) -> dict:
    """姓名查询结果的掩码摘要：登记码只留前 2 位，照片需要完整码才能取。"""
    data = registration_summary(reg)
    data["reg_code"] = f"{reg.reg_code[:2]}****"
    for item in data.get("items", []):
        item["photos"] = []
    return data


class MyRegistrationDetailView(APIView):
    """查看/修改/取消自己的一条登记：URL 携带登记码（能力凭证）。

    任何设备凭码可操作（2026-11-08 用户要求）；码不命中一律 404——
    不泄露记录存在性（IDOR 防护），枚举由双轨限流兜底。
    """

    permission_classes = [AllowAny]
    throttle_classes = [CodeAccessIPThrottle, CodeAccessDeviceThrottle]

    def _get_own(self, request, reg_code: str):
        return _get_own_registration(request, reg_code)

    def get(self, request, reg_code: str):
        return Response(registration_summary(self._get_own(request, reg_code)))

    def patch(self, request, reg_code: str):
        reg = self._get_own(request, reg_code)
        if reg.status == PostcardRegistration.STATUS_CANCELLED:
            return Response({"detail": "已取消的登记不能修改"}, status=400)
        serializer = MyRecordEditInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(reg, field, value)
        reg.save()
        return Response(registration_summary(reg))

    def post(self, request, reg_code: str):
        """取消自己的登记（整单 + 全部条目）。"""
        reg = self._get_own(request, reg_code)
        if reg.status == PostcardRegistration.STATUS_CANCELLED:
            return Response({"detail": "该登记已是取消状态"}, status=400)
        now = timezone.now()
        PostcardRegistration.objects.filter(pk=reg.pk).update(
            status=PostcardRegistration.STATUS_CANCELLED, updated_at=now,
        )
        reg.items.update(
            status=PostcardItem.STATUS_CANCELLED, updated_at=now,
        )
        reg.status = PostcardRegistration.STATUS_CANCELLED
        return Response(registration_summary(reg))


class MyReviewRequestView(APIView):
    """申请人工复核（AI 判不匹配后）：ai_failed 的条目 → manual_pending。

    凭证 = URL 里的登记码（同 MyRegistrationDetailView）；码不对 404。
    """

    permission_classes = [AllowAny]
    throttle_classes = [CodeAccessIPThrottle, CodeAccessDeviceThrottle]

    def post(self, request, reg_code: str):
        reg = _get_own_registration(request, reg_code)
        moved = 0
        for item in reg.items.prefetch_related("photos"):
            if item.photos.filter(review_state=PostcardPhoto.REVIEW_AI_FAILED).exists():
                # 保留 ai_verdict——复核员要看 AI 判了什么，只翻状态。
                old_verdict = next(
                    (p.ai_verdict for p in item.photos.all() if p.ai_verdict), None,
                )
                photo_lifecycle.settle_item_photos(
                    item, PostcardPhoto.REVIEW_MANUAL_PENDING, verdict=old_verdict,
                )
                moved += 1
        if moved == 0:
            return Response(
                {"detail": "当前没有 AI 判定不匹配、需要人工复核的明信片"}, status=400,
            )
        return Response({"message": "已提交人工复核，请耐心等待复核结果", "count": moved})


class MyPhotoPurgeView(APIView):
    """关标签页清理（sendBeacon）：删除自己登记单下**终态失败**照片的文件。

    sendBeacon 无法带自定义 header（无 CSRF token）→ 豁免 SessionAuthentication
    （``authentication_classes = []``，DRF 便不做 CSRF 强制）。安全依据：能力
    凭证 = body 里的 6 位登记码（跨站攻击者不可知，CSRF 所防的「借 cookie
    伪造操作」在此不成立），且操作仅删自己失败照片（低危、幂等）；ncdid /
    指纹两轨归属校验照做。前端须以 ``application/json`` Blob 发送。
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [CodeAccessIPThrottle, CodeAccessDeviceThrottle]

    def post(self, request, reg_code: str):
        reg = _get_own_registration(request, reg_code)
        purged = photo_lifecycle.purge_registration_failed_photos(reg)
        return Response({"purged": purged})


class SuggestionsView(APIView):
    """建议箱：Turnstile + 双轨限流。"""

    permission_classes = [AllowAny]
    throttle_classes = [SuggestionIPThrottle, SuggestionDeviceThrottle]

    def post(self, request):
        event, _, _ = _phase_guard()
        if event is None:
            return Response({"detail": "活动尚未配置"}, status=400)
        if not passes_turnstile(request, request.data.get("turnstile_token") or ""):
            return turnstile_error_response(drf=True)
        serializer = SuggestionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        PostcardSuggestion.objects.create(
            event=event,
            content=serializer.validated_data["content"],
            contact=serializer.validated_data.get("contact", ""),
            device_id=device_id_from_request(request),
        )
        return Response({"message": "感谢你的建议！"}, status=201)


class AnnouncementPdfView(APIView):
    """公告 PDF 下发：CSP:sandbox + nosniff + inline。

    浏览器 PDF 查看器在 ``sandbox`` 下无脚本执行能力；``nosniff`` 杜绝
    Content-Type 猜测。上传侧（管理端）已限 .pdf 扩展 + %PDF 魔数。
    """

    permission_classes = [AllowAny]

    def get(self, request):
        _, config, _ = _phase_guard()
        if config is None or not config.announcement_pdf:
            raise Http404
        if not config.announcement_pdf.storage.exists(config.announcement_pdf.name):
            raise Http404
        resp = FileResponse(
            config.announcement_pdf.open("rb"), content_type="application/pdf",
        )
        resp["Content-Disposition"] = 'inline; filename="announcement.pdf"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Security-Policy"] = "sandbox"
        return resp


class PhotoView(APIView):
    """照片鉴权下发：复核权限，或「出示登记码」（登记码即能力凭证，2026-11-08）。

    重编码后一律 JPEG，Content-Type 固定 image/jpeg（无用户可控面）。
    """

    permission_classes = [AllowAny]

    def get(self, request, pk: int):
        photo = PostcardPhoto.objects.select_related(
            "item__registration", "item__barcode",
        ).filter(pk=pk).first()
        if photo is None or not photo.file or not photo.file.storage.exists(photo.file.name):
            raise Http404
        user = request.user
        if not (
            user.is_authenticated and (
                user.is_superuser
                or user.has_perm("events.review_postcard")
                or user.has_perm("events.manage_postcard")
            )
        ):
            reg = photo.item.registration
            code = (request.query_params.get("reg_code") or "").strip()
            if not _REGCODE_RE.fullmatch(code) or code != reg.reg_code:
                return HttpResponseForbidden("无权访问该照片")
        resp = FileResponse(photo.file.open("rb"), content_type="image/jpeg")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "private, max-age=60"
        return resp


# ---------------------------------------------------------------------------
# 管理端点
# ---------------------------------------------------------------------------


class AdminConfigView(APIView):
    """活动配置：GET 读（未配置返回 configured:false），PUT 写（首次自动建 Event 壳）。

    Event 壳字段（标题/简介/起止时间）在活动开始后锁定（沿用壳层生命周期
    契约）；模块字段（节点/清单/公告）活动期间随时可改——进度与公告更新是刚需。
    """

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, config, phase = _phase_guard(admin=True)
        if event is None or config is None:
            return Response({"configured": False, "phase": state.PHASE_NOT_STARTED})
        return Response(self._payload(event, config, phase))

    def _payload(self, event, config, phase) -> dict:
        return {
            "configured": True,
            "phase": phase,
            "phase_label": state.PHASE_LABELS.get(phase, phase),
            "event": {
                "id": event.pk,
                "title": event.title,
                "summary": event.summary,
                "status": event.status,
                "start_at": event.start_at.isoformat(),
                "end_at": event.end_at.isoformat() if event.end_at else None,
            },
            "announcement_body": config.announcement_body,
            "has_announcement_pdf": bool(config.announcement_pdf),
            "allowed_grades": config.allowed_grades or [],
            "destination_schools": config.destination_schools or [],
            "ship_at": config.ship_at.isoformat() if config.ship_at else None,
            "distribute_at": config.distribute_at.isoformat() if config.distribute_at else None,
            "barcode_count": PostcardBarcode.objects.filter(event=event).count(),
            "registration_count": PostcardRegistration.objects.filter(event=event).count(),
        }

    def put(self, request):
        serializer = AdminConfigInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        event, config, _ = _phase_guard(admin=True)
        pdf = request.FILES.get("announcement_pdf")
        if pdf is not None:
            head = pdf.read(5)
            pdf.seek(0)
            if head != b"%PDF-":
                return Response({"detail": "公告附件必须是 PDF 文件"}, status=400)
            if pdf.size > 10 * 1024 * 1024:
                return Response({"detail": "公告 PDF 超过 10MB 上限"}, status=400)

        with transaction.atomic():
            if event is None:
                event = Event.objects.create(
                    title=data["title"],
                    summary=data.get("summary", ""),
                    module_key="postcard",
                    visibility=Event.VISIBILITY_PUBLIC,
                    organizer=request.user if request.user.is_authenticated else None,
                    start_at=data["start_at"],
                    end_at=data["end_at"],
                    status=Event.STATUS_DRAFT,
                )
            else:
                # 壳字段锁定：active 后只接受模块字段（节点/清单/公告随时可改）。
                if event.status not in (Event.STATUS_DRAFT, Event.STATUS_SCHEDULED):
                    shell_changed = any([
                        data["title"] != event.title,
                        (data.get("summary") or "") != event.summary,
                        data["start_at"] != event.start_at,
                        data["end_at"] != event.end_at,
                    ])
                    if shell_changed:
                        return Response(
                            {"detail": "活动已开始，标题/简介/起止时间已锁定；节点、学校清单与公告仍可修改"},
                            status=400,
                        )
                event.title = data["title"]
                event.summary = data.get("summary", "")
                event.start_at = data["start_at"]
                event.end_at = data["end_at"]
                event.save()
            if config is None:
                config = PostcardConfig.objects.create(event=event)

            config.ship_at = data.get("ship_at")
            config.distribute_at = data.get("distribute_at")
            config.allowed_grades = data.get("allowed_grades") or []
            config.destination_schools = data.get("destination_schools") or []
            config.announcement_body = sanitize_html(data.get("body") or "")
            if request.data.get("clear_announcement_pdf") in ("1", "true", True):
                if config.announcement_pdf:
                    config.announcement_pdf.delete(save=False)
                config.announcement_pdf = None
            config.save()
            if pdf is not None:
                config.announcement_pdf.save("announcement.pdf", pdf, save=True)

        _audit(event, request, "config_update", f"event#{event.pk}", {
            "title": data["title"],
            "start_at": data["start_at"].isoformat(),
            "end_at": data["end_at"].isoformat(),
            "pdf_updated": pdf is not None,
        })
        config.refresh_from_db()
        phase = state.phase_of(event, config)
        return Response(self._payload(event, config, phase))


class AdminPublishView(APIView):
    """发布活动（draft → scheduled/active）。结束由 end_at 到点自动翻转。"""

    permission_classes = [CanManagePostcard]

    def post(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        if event.status != Event.STATUS_DRAFT:
            return Response({"detail": "只有草稿可以发布"}, status=400)
        lifecycle.publish(event)
        _audit(event, request, "publish", f"event#{event.pk}", {"status": event.status})
        return Response({"status": event.status})


class AdminBarcodesView(APIView):
    """条码：GET 汇总，POST 生成（1500~10000、步进 500；增量式、单活动累计 ≤10000）。"""

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"configured": False})
        qs = PostcardBarcode.objects.filter(event=event)
        return Response({
            "total": qs.count(),
            "min": barcode_mod.COUNT_MIN,
            "max": barcode_mod.COUNT_MAX,
            "step": barcode_mod.COUNT_STEP,
            "default": barcode_mod.COUNT_DEFAULT,
        })

    def post(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        try:
            rows = barcode_mod.generate_barcodes(event, request.data.get("count"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        _audit(event, request, "barcode_generate", f"event#{event.pk}", {"count": len(rows)})
        return Response({
            "generated": len(rows),
            "total": PostcardBarcode.objects.filter(event=event).count(),
        }, status=201)


class AdminBarcodesPdfView(APIView):
    """整版条码 PDF 导出（A4、40×20mm、2mm 间隙、每页 65 枚）。"""

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        _audit(event, request, "barcode_export_pdf", f"event#{event.pk}")
        return barcode_mod.export_pdf(event, title=event.title)


def _admin_items_queryset(event, params):
    """管理端条目查询（记录列表与导出共用）：搜索 + 筛选。"""
    from django.db.models import Q

    qs = PostcardItem.objects.filter(registration__event=event).select_related(
        "registration", "barcode",
    ).order_by("-registration__created_at", "-id")

    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(registration__sender_name__icontains=q)
            | Q(registration__reg_code__icontains=q)
            | Q(barcode__code__icontains=q)
        )
    status = (params.get("status") or "").strip()
    if status:
        qs = qs.filter(registration__status=status)
    item_status = (params.get("item_status") or "").strip()
    if item_status:
        qs = qs.filter(status=item_status)
    grade = (params.get("grade") or "").strip()
    if grade:
        qs = qs.filter(registration__grade=grade)
    class_no = (params.get("class_no") or "").strip()
    if class_no.isdigit():
        qs = qs.filter(registration__class_no=int(class_no))
    school = (params.get("school") or "").strip()
    if school:
        qs = qs.filter(registration__dest_school__icontains=school)
    region = (params.get("region") or "").strip()
    if region:
        qs = qs.filter(registration__dest_region__icontains=region)
    return qs


class AdminRecordsView(APIView):
    """登记记录列表：按条目平铺（登记单信息随行），搜索/筛选 + 分页。"""

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        qs = _admin_items_queryset(event, request.query_params)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        status_labels = dict(PostcardRegistration.STATUS_CHOICES)
        rows = []
        for item in page:
            reg = item.registration
            rows.append({
                "item_id": item.pk,
                "barcode": item.barcode.code,
                "item_status": item.status,
                "item_status_label": status_labels.get(item.status, item.status),
                "registration": {
                    "reg_code": reg.reg_code,
                    "sender_name": reg.sender_name,
                    "grade": reg.grade,
                    "grade_label": reg.grade_label,
                    "class_no": reg.class_no,
                    "dest_region": reg.dest_region,
                    "dest_school": reg.dest_school,
                    "status": reg.status,
                    "status_label": reg.get_status_display(),
                    "created_at": reg.created_at.isoformat(),
                },
            })
        return paginator.get_paginated_response(rows)


class AdminRegistrationDetailView(APIView):
    """改/删登记单（按登记码定位）。取消联动全部条目；删除连带照片文件。"""

    permission_classes = [CanManagePostcard]

    def patch(self, request, reg_code: str):
        event, _, _ = _phase_guard(admin=True)
        reg = PostcardRegistration.objects.filter(
            event=event, reg_code=reg_code,
        ).prefetch_related("items__barcode").first() if event else None
        if reg is None:
            raise Http404
        serializer = AdminRegistrationEditInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        for field in ("sender_name", "grade", "class_no", "dest_region", "dest_school"):
            if field in data:
                setattr(reg, field, data[field])
        reg.save()
        if data.get("status") == PostcardRegistration.STATUS_CANCELLED:
            now = timezone.now()
            reg.items.update(status=PostcardItem.STATUS_CANCELLED, updated_at=now)
            reg.status = PostcardRegistration.STATUS_CANCELLED
            reg.save(update_fields=["status", "updated_at"])
        _audit(event, request, "registration_update", reg.reg_code, {
            "fields": list(data.keys()),
        })
        return Response(registration_summary(reg))

    def delete(self, request, reg_code: str):
        event, _, _ = _phase_guard(admin=True)
        reg = PostcardRegistration.objects.filter(
            event=event, reg_code=reg_code,
        ).first() if event else None
        if reg is None:
            raise Http404
        for photo in PostcardPhoto.objects.filter(item__registration=reg):
            photo.delete_file()
        reg.delete()
        _audit(event, request, "registration_delete", reg_code)
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class AdminExportView(APIView):
    """导出：?fmt=xlsx|pdf，搜索参数与记录列表一致。

    注意参数名用 ``fmt`` 而不是 ``format``：DRF 内容协商把 ``?format=```
    当渲染器格式覆盖（找 xlsx 渲染器 → 404），实测踩坑。
    """

    permission_classes = [CanManagePostcard]

    def get(self, request):
        from . import exports

        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        fmt = (request.query_params.get("fmt") or "xlsx").lower()
        _audit(event, request, "export", fmt, {
            "q": request.query_params.get("q") or "",
            "status": request.query_params.get("status") or "",
        })
        if fmt == "pdf":
            return exports.export_pdf(event, request.query_params, title=event.title)
        return exports.export_xlsx(event, request.query_params, title=event.title)


class AdminStatsView(APIView):
    """总数据统计：寄达校数、寄出量、状态分布、年级/学校/时间线。"""

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        regs = PostcardRegistration.objects.filter(event=event)
        items = PostcardItem.objects.filter(registration__event=event)
        reported_q = Q(status=PostcardItem.STATUS_REPORTED)

        by_school = list(
            items.values("registration__dest_school")
            .annotate(total=Count("id"), reported=Count("id", filter=reported_q))
            .order_by("-total")
        )
        by_day = list(
            items.annotate(day=TruncDate("registration__created_at"))
            .values("day").annotate(total=Count("id")).order_by("day")
        )
        return Response({
            "registrations": {
                "total": regs.count(),
                "registered": regs.filter(status=PostcardRegistration.STATUS_REGISTERED).count(),
                "reported": regs.filter(status=PostcardRegistration.STATUS_REPORTED).count(),
                "cancelled": regs.filter(status=PostcardRegistration.STATUS_CANCELLED).count(),
            },
            "items": {
                "total": items.count(),
                "registered": items.filter(status=PostcardItem.STATUS_REGISTERED).count(),
                "reported": items.filter(reported_q).count(),
                "cancelled": items.filter(status=PostcardItem.STATUS_CANCELLED).count(),
            },
            "destination_schools": len({
                r["registration__dest_school"] for r in by_school if r["registration__dest_school"]
            }),
            "by_school": [
                {"school": r["registration__dest_school"], "total": r["total"], "reported": r["reported"]}
                for r in by_school
            ],
            "by_grade": [
                {"grade": g["registration__grade"], "total": g["total"]}
                for g in items.values("registration__grade").annotate(total=Count("id"))
            ],
            "by_day": [
                {"day": d["day"].isoformat() if d["day"] else None, "total": d["total"]}
                for d in by_day
            ],
        })


class AdminLookupView(APIView):
    """签收查询：?barcode=7位。命中返回登记信息；未命中 404 + 固定文案。"""

    permission_classes = [CanReviewPostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        barcode = (request.query_params.get("barcode") or "").strip()
        if not barcode.isdigit() or len(barcode) != 7:
            return Response({"detail": "请输入 7 位条码号"}, status=400)
        item = (
            PostcardItem.objects.select_related("registration", "barcode")
            .filter(registration__event=event, barcode__code=barcode)
            .first()
        ) if event else None
        if item is None:
            return Response(
                {"detail": "明信片未登记，请先登记！"}, status=404,
            )
        return Response({
            "barcode": barcode,
            "item_status": item.status,
            "item_status_label": item.get_status_display(),
            "registration": registration_summary(item.registration),
        })


class AdminConfirmView(APIView):
    """签收确认：{barcode} → 该张置「已报寄」并联动登记单。幂等。"""

    permission_classes = [CanReviewPostcard]

    def post(self, request):
        event, _, _ = _phase_guard(admin=True)
        barcode = (request.data.get("barcode") or "").strip()
        if not barcode.isdigit() or len(barcode) != 7:
            return Response({"detail": "请输入 7 位条码号"}, status=400)
        item = (
            PostcardItem.objects.select_related("registration", "barcode")
            .filter(registration__event=event, barcode__code=barcode)
            .first()
        ) if event else None
        if item is None:
            return Response({"detail": "明信片未登记，请先登记！"}, status=404)
        if item.status == PostcardItem.STATUS_CANCELLED:
            return Response({"detail": "该明信片所属登记已取消，无法签收"}, status=400)
        already = item.status == PostcardItem.STATUS_REPORTED
        if not already:
            now = timezone.now()
            PostcardItem.objects.filter(pk=item.pk).update(
                status=PostcardItem.STATUS_REPORTED, updated_at=now,
            )
            item.status = PostcardItem.STATUS_REPORTED
            item.registration.sync_status_from_items()
            _audit(event, request, "confirm_receipt", barcode, {
                "reg_code": item.registration.reg_code,
            })
        return Response({
            "barcode": barcode,
            "already_reported": already,
            "item_status": item.status,
            "registration": registration_summary(item.registration),
        })


class AdminUnreportView(APIView):
    """误签回退：{barcode} → 已报寄回已登记，联动登记单。"""

    permission_classes = [CanReviewPostcard]

    def post(self, request):
        event, _, _ = _phase_guard(admin=True)
        barcode = (request.data.get("barcode") or "").strip()
        item = (
            PostcardItem.objects.select_related("registration", "barcode")
            .filter(registration__event=event, barcode__code=barcode)
            .first()
        ) if event else None
        if item is None or item.status != PostcardItem.STATUS_REPORTED:
            return Response({"detail": "该条码不是已报寄状态"}, status=400)
        now = timezone.now()
        PostcardItem.objects.filter(pk=item.pk).update(
            status=PostcardItem.STATUS_REGISTERED, updated_at=now,
        )
        item.status = PostcardItem.STATUS_REGISTERED
        item.registration.sync_status_from_items()
        _audit(event, request, "unreport", barcode, {"reg_code": item.registration.reg_code})
        return Response({
            "barcode": barcode,
            "item_status": item.status,
            "registration": registration_summary(item.registration),
        })


class AdminSuggestionsView(APIView):
    """建议列表（分页）。"""

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"results": []})
        paginator = PageNumberPagination()
        qs = PostcardSuggestion.objects.filter(event=event).order_by("-created_at")
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response([
            {
                "id": s.pk,
                "content": s.content,
                "contact": s.contact,
                "created_at": s.created_at.isoformat(),
            }
            for s in page
        ])


class AdminAuditView(APIView):
    """审计日志（分页，只读）。"""

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"results": []})
        paginator = PageNumberPagination()
        qs = PostcardAuditLog.objects.filter(event=event).select_related("user").order_by("-created_at")
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response([
            {
                "id": log.pk,
                "action": log.action,
                "target": log.target,
                "detail": log.detail,
                "user": log.user.username if log.user else None,
                "ip": log.ip,
                "created_at": log.created_at.isoformat(),
            }
            for log in page
        ])


class AdminAIConfigView(APIView):
    """AI 审核配置（全局单例）：GET 只回掩码（api_key 绝不回显），PUT 写入。

    审计挂当前活动（PostcardAuditLog.event 必填）；活动未建时跳过审计行——
    配置变更有 updated_at 可查，活动建立后的任何变更都会留痕。
    """

    permission_classes = [CanManagePostcard]

    def get(self, request):
        cfg = PostcardAIConfig.load()
        if cfg is None:
            return Response({"configured": False})
        return Response({
            "configured": True,
            "enabled": cfg.enabled,
            "ready": cfg.ready,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "extra_headers": cfg.extra_headers or {},
            "timeout_seconds": cfg.timeout_seconds,
            "ip_blacklist": cfg.ip_blacklist or [],
            "api_key_set": bool(cfg.api_key),
        })

    def put(self, request):
        serializer = AIConfigInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cfg = PostcardAIConfig.load() or PostcardAIConfig()
        cfg.base_url = data.get("base_url", cfg.base_url)
        cfg.model = data.get("model", cfg.model)
        cfg.extra_headers = data.get("extra_headers", cfg.extra_headers)
        cfg.timeout_seconds = data.get("timeout_seconds", cfg.timeout_seconds)
        cfg.ip_blacklist = data.get("ip_blacklist", cfg.ip_blacklist)
        cfg.enabled = data.get("enabled", cfg.enabled)
        if data.get("api_key"):
            cfg.api_key = data["api_key"]  # 留空 = 保持原值（写后不可读）
        cfg.save()
        event, _, _ = _phase_guard(admin=True)
        if event is not None:
            _audit(event, request, "ai_config_update", "ai-config", {
                "enabled": cfg.enabled,
                "base_url": cfg.base_url,
                "model": cfg.model,
                "api_key_changed": bool(data.get("api_key")),
                "blacklist_count": len(cfg.ip_blacklist or []),
            })
        return Response({
            "configured": True,
            "enabled": cfg.enabled,
            "ready": cfg.ready,
            "api_key_set": bool(cfg.api_key),
        })


class AdminAISamplesView(APIView):
    """填写样例管理：GET 列表（含 sample_ready 门禁状态），POST 上传。

    样例照片走与用户照片同一道安全管线（魔数 + 重编码 + 私有存储）——
    管理员账号同样不可信（可能被盗），上传面一律收口。
    """

    permission_classes = [CanManagePostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"results": [], "sample_ready": False})
        samples = list(event.postcard_ai_samples.all())
        return Response({
            "results": [
                {
                    "id": s.pk,
                    "caption": s.caption,
                    "has_image": bool(s.image),
                    "created_at": s.created_at.isoformat(),
                }
                for s in samples
            ],
            "sample_ready": bool(samples),
        })

    def post(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        image = request.FILES.get("image")
        if image is None:
            return Response({"detail": "缺少样例照片"}, status=400)
        from .photos import PhotoRejected, validate_and_reencode

        try:
            content = validate_and_reencode(image)
        except PhotoRejected as exc:
            return Response({"detail": exc.reason}, status=400)
        caption = str(request.data.get("caption") or "").strip()[:500]
        sample = PostcardAISample(event=event, caption=caption)
        sample.image.save("sample.jpg", content, save=True)
        _audit(event, request, "ai_sample_upload", f"sample#{sample.pk}", {"caption": caption})
        return Response({
            "id": sample.pk,
            "caption": sample.caption,
            "sample_ready": True,
        }, status=201)


class AdminAISampleDetailView(APIView):
    """单条样例：DELETE 删（行 + 文件）。"""

    permission_classes = [CanManagePostcard]

    def delete(self, request, pk: int):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        sample = event.postcard_ai_samples.filter(pk=pk).first()
        if sample is None:
            raise Http404
        sample.delete_file()
        sample.delete()
        _audit(event, request, "ai_sample_delete", f"sample#{pk}")
        return Response({
            "deleted": pk,
            "sample_ready": event.postcard_ai_samples.exists(),
        })


class AdminAISampleImageView(APIView):
    """样例照片下发（manage / review 权限；重编码后一律 JPEG）。"""

    permission_classes = [CanReviewPostcard]

    def get(self, request, pk: int):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            raise Http404
        sample = event.postcard_ai_samples.filter(pk=pk).first()
        if sample is None or not sample.image or not sample.image.storage.exists(sample.image.name):
            raise Http404
        resp = FileResponse(sample.image.open("rb"), content_type="image/jpeg")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "private, max-age=300"
        return resp


class AdminReviewQueueView(APIView):
    """人工复核台队列：待人工（manual_pending）+ AI 不匹配（ai_failed）。

    按条目（一张明信片）聚合：登记信息 + 照片 id（前端经 photo/<pk>/ 取图，
    复核权限直达）+ AI 判定详情（复核员要看 AI 判了什么）。
    """

    permission_classes = [CanReviewPostcard]

    def get(self, request):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"results": []})
        qs = (
            PostcardItem.objects.filter(
                registration__event=event,
                photos__review_state__in=[
                    PostcardPhoto.REVIEW_MANUAL_PENDING, PostcardPhoto.REVIEW_AI_FAILED,
                ],
            )
            .select_related("barcode", "registration")
            .prefetch_related("photos")
            .distinct()
            .order_by("-pk")
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        results = []
        for item in page:
            reg = item.registration
            photos = list(item.photos.all())
            verdict = next((p.ai_verdict for p in photos if p.ai_verdict), None)
            results.append({
                "item_id": item.pk,
                "barcode": item.barcode.code,
                "review_state": photos[0].review_state if photos else None,
                "photo_ids": [p.pk for p in photos if p.file],
                "ai_verdict": verdict,
                "registration": {
                    "reg_code": reg.reg_code,
                    "sender_name": reg.sender_name,
                    "grade_label": reg.grade_label,
                    "class_no": reg.class_no,
                    "dest_region": reg.dest_region,
                    "dest_school": reg.dest_school,
                    "created_at": reg.created_at.isoformat(),
                },
            })
        return paginator.get_paginated_response(results)


class AdminReviewDecisionView(APIView):
    """人工复核判定：pass = 通过（照片文件即删）/ fail = 不通过（24h TTL 删）。

    只接受待复核状态（manual_pending / ai_failed）；其余 400。全量审计。
    """

    permission_classes = [CanReviewPostcard]

    def post(self, request, item_pk: int):
        event, _, _ = _phase_guard(admin=True)
        if event is None:
            return Response({"detail": "请先保存活动配置"}, status=400)
        item = (
            PostcardItem.objects.select_related("registration")
            .filter(pk=item_pk, registration__event=event)
            .first()
        )
        if item is None:
            raise Http404
        serializer = ReviewDecisionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        note = serializer.validated_data.get("note", "")
        current = set(item.photos.values_list("review_state", flat=True))
        if not current & {PostcardPhoto.REVIEW_MANUAL_PENDING, PostcardPhoto.REVIEW_AI_FAILED}:
            return Response({"detail": "该明信片不在待复核状态"}, status=400)
        new_state = (
            PostcardPhoto.REVIEW_MANUAL_PASSED if decision == "pass"
            else PostcardPhoto.REVIEW_MANUAL_FAILED
        )
        # 人工判定覆盖 ai_verdict（保留 AI 原判定于 manual.ai_verdict 供追溯）。
        old_verdict = next(
            (p.ai_verdict for p in item.photos.all() if p.ai_verdict), None,
        )
        verdict = {
            "manual": {
                "decision": decision,
                "note": note,
                "by": request.user.username if request.user.is_authenticated else None,
            },
            "ai_verdict": old_verdict,
        }
        photo_lifecycle.settle_item_photos(
            item, new_state, verdict=verdict, purge_files=(decision == "pass"),
        )
        _audit(event, request, "review_decision", f"item#{item.pk}", {
            "decision": decision,
            "note": note,
            "barcode": item.barcode.code,
        })
        return Response({
            "item_id": item.pk,
            "review_state": new_state,
            "review_label": dict(PostcardPhoto.REVIEW_CHOICES).get(new_state, new_state),
        })
