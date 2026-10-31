"""集中一处上传校验（原 tasks / proposals 各有一份逐行重复的实现，T3 将删除）。

校验规则：
- 文件大小不超过站点策略的同步上限；
- 禁止上传可执行 / 脚本类扩展名；
- 按 content-type 把文件分类为 图片 / 视频 / 文档 / 压缩包 / 其他。
"""

from django.db.models import Count, Sum

from common.policy import format_byte_cap, get_policy
from common.uploads import RESTRICTED_EXTENSIONS, extension_of

# 反馈附件配额（同步 / tus 通路共用）：每条 ≤9 个 / 总 ≤2GB。
FEEDBACK_MAX_ATTACHMENTS = 9
FEEDBACK_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024

# 禁止上传的扩展名 = 站点自己的可执行清单 ∪ 浏览器会当文档执行的清单。
# 后者（html / svg / xml / js / php 系 …）尤其关键：公开媒体目录由 nginx 按扩展名
# 直出，落一个 .html 进去就是站点同源托管任意脚本（存储型 XSS）。
FORBIDDEN_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".sh", ".php", ".asp", ".jsp",
    ".py", ".rb", ".pl", ".cgi", ".com", ".scr", ".pif", ".msi",
}) | RESTRICTED_EXTENSIONS

_DOCUMENT_CONTENT_TYPES = frozenset({
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
})

_ARCHIVE_CONTENT_TYPES = frozenset({
    "application/zip",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
    "application/gzip",
})


def classify_file_type(content_type):
    """按 content-type 推断 file_type（与原 tasks/proposals 逻辑一致）。"""
    ct = content_type or ""
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct in _DOCUMENT_CONTENT_TYPES:
        return "document"
    if ct in _ARCHIVE_CONTENT_TYPES:
        return "archive"
    return "other"


def extension_error(filename: str) -> str | None:
    """只看扩展名：命中 ``FORBIDDEN_EXTENSIONS`` 则返回错误文案，否则 None。

    与 ``upload_error`` 拆开是为了给 tus 通路复用——tus 走的是大文件分档，
    不能套用「同步上限」那条尺寸检查（否则合法的大视频会被拒）。
    """
    ext = extension_of(filename or "")
    if ext in FORBIDDEN_EXTENSIONS:
        return "禁止上传此类型的文件"
    return None


def upload_error(file):
    """返回上传文件的错误消息（若合法则返回 None）。"""
    cap = get_policy().sync_upload_max_bytes
    if file.size > cap:
        return f"文件大小不能超过 {format_byte_cap(cap)}"
    return extension_error(getattr(file, "name", ""))


def feedback_quota_error(parent, incoming_size):
    """反馈父级的附件配额校验：超个数或总大小则返回错误消息，否则 None。

    同步与 tus 两条上传通路共用（#19）。``incoming_size`` 为本次即将新增的字节数。
    """
    from reviews.models import Feedback  # 延迟导入，避免 attachments↔reviews 循环

    if not isinstance(parent, Feedback):
        return None
    stats = parent.attachments.aggregate(n=Count("id"), total=Sum("file_size")) # pyright: ignore[reportAttributeAccessIssue]
    if (stats["n"] or 0) >= FEEDBACK_MAX_ATTACHMENTS:
        return f"单条反馈最多 {FEEDBACK_MAX_ATTACHMENTS} 个附件"
    if (stats["total"] or 0) + incoming_size > FEEDBACK_MAX_TOTAL_BYTES:
        return "超出单条反馈附件总大小上限"
    return None
