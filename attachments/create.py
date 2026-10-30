"""附件创建接缝：create_attachment / copy_attachment / parent_of。

HTTP 与 tus 是增量父级（task / feedback / news）适配器；活动投稿 / 布展是批量
适配器。作品与展品不走 ``POST /attachments/``（提交 / 布展是原子批量）。见 ADR 0012。
"""
import os
from dataclasses import dataclass

from django.core.files.base import ContentFile

from activities.models import Exhibit, Submission
from news.models import News
from reviews.models import Feedback
from tasks.models import Task

from common.targets import content_host
from .models import Attachment
from .validation import classify_file_type


class AttachmentCreateError(Exception):
    """create_attachment / copy_attachment 拒绝写入；``detail`` 给适配器当 400 文案。"""

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ParentSpec:
    """父级注册表一行：谁能挂、HTTP 是否暴露、创建者字段名。"""

    key: str
    fk: str
    model: type
    endpoint: bool
    creator_attr: str | None = None


PARENTS = {
    "task": ParentSpec("task", "task", Task, True, "creator_id"),
    "feedback": ParentSpec("feedback", "feedback", Feedback, True, "creator_id"),
    "news": ParentSpec("news", "news", News, True, "author_id"),
    "submission": ParentSpec("submission", "submission", Submission, False),
    "exhibit": ParentSpec("exhibit", "exhibit", Exhibit, False),
}


def spec_for(parent):
    """按实例类型取注册表行；未知父级返回 None。"""
    if parent is None:
        return None
    for spec in PARENTS.values():
        if isinstance(parent, spec.model):
            return spec
    return None


def parent_of(attachment):
    """附件的父级对象；无父级返回 None。

    切读期：走 target，回落旧列。仍用 ``PARENTS`` 过滤一次——target 是「可评论
    对象」的通用锚点，比附件的父级集合更宽（例如评论也有 target，但附件不能挂在
    评论上）。
    """
    host = content_host(attachment)
    if host is None or spec_for(host) is None:
        return None
    return host


def create_attachment(*, user, parent, file, extra_validate=None):
    """把 ``file`` 挂到 ``parent`` 上，返回新 ``Attachment``。

    ``extra_validate(file) -> str | None``：适配器注入的额外校验（如征集后缀 / 单文件上限）。
    返回错误文案则拒绝写入。全局 ``upload_error`` 仍由 HTTP / 活动适配器在调用前执行
    （tus 有自己的尺寸分档，不走同步上限）。
    """
    spec = spec_for(parent)
    if spec is None:
        raise AttachmentCreateError("不支持的父级")
    if extra_validate is not None:
        err = extra_validate(file)
        if err:
            raise AttachmentCreateError(err)
    content_type = getattr(file, "content_type", None) or ""
    file_name = os.path.basename(getattr(file, "name", "") or "") or "file"
    return Attachment.objects.create(
        **{spec.fk: parent},
        uploaded_by=user,
        file=file,
        file_type=classify_file_type(content_type),
        file_name=file_name,
        file_size=file.size,
    )


def copy_attachment(*, user, parent, source):
    """把已有附件的文件副本挂到 ``parent``（征集导入展品）。"""
    spec = spec_for(parent)
    if spec is None:
        raise AttachmentCreateError("不支持的父级")
    new_att = Attachment(
        **{spec.fk: parent},
        uploaded_by=user,
        file_type=source.file_type,
        file_name=source.file_name,
        file_size=source.file_size,
    )
    with source.file.open("rb") as content:
        new_att.file.save(source.file_name, ContentFile(content.read()))
    return new_att
