"""展示布展：建/改/删展品、从征集导入。VoteOption 与展品同步。

视图 ``add_exhibit`` / ``update_exhibit`` / ``delete_exhibit`` / ``import_from_collection``
是 HTTP 适配器；附件写入走 ``create_attachment`` / ``copy_attachment``。
"""
from django.db import transaction

from attachments.create import AttachmentCreateError, copy_attachment, create_attachment
from attachments.queries import attachments_of
from attachments.validation import upload_error

from .lifecycle import can_curate, can_edit_exhibit
from .models import Activity, Exhibit, VoteOption


class ExhibitionError(Exception):
    """布展拒绝写入；``detail`` / ``http_status`` 给适配器当响应。"""

    def __init__(self, detail, http_status=400):
        super().__init__(detail)
        self.detail = detail
        self.http_status = http_status


def _validate_files(files):
    for f in files:
        err = upload_error(f)
        if err:
            raise ExhibitionError(err)


def _build_exhibit(activity, user, title, files):
    """建一个展品；启用投票时另建 VoteOption 并绑定。files 已校验。"""
    option = None
    if activity.voting_enabled:
        order = activity.options.count()
        option = VoteOption.objects.create(activity=activity, text=title or "", order=order)
    exhibit = Exhibit.objects.create(activity=activity, title=title, vote_option=option)
    for f in files:
        try:
            create_attachment(user=user, parent=exhibit, file=f)
        except AttachmentCreateError as exc:
            raise ExhibitionError(exc.detail) from exc
    return exhibit


def create_exhibit(*, activity, user, title, files):
    """策展人加展品。启用投票时同步 VoteOption。"""
    if not can_curate(activity, user):
        raise ExhibitionError("仅展示可在待开始/展示中加展品")
    if not files:
        raise ExhibitionError("展品至少需要 1 个文件")
    _validate_files(files)
    title = (title or "").strip()
    with transaction.atomic():
        return _build_exhibit(activity, user, title, files)


def delete_exhibit(*, activity, user, exhibit_id):
    """策展人删展品；连带删绑定的 VoteOption 与附件。"""
    if not can_curate(activity, user):
        raise ExhibitionError("仅展示可在待开始/展示中删展品")
    try:
        exhibit = activity.exhibits.get(pk=exhibit_id)
    except (Exhibit.DoesNotExist, ValueError, TypeError):
        raise ExhibitionError("展品不存在", http_status=404)
    with transaction.atomic():
        if exhibit.vote_option_id:
            VoteOption.objects.filter(pk=exhibit.vote_option_id).delete()
        exhibit.delete()


def update_exhibit(*, activity, user, exhibit_id, title=None, files=None):
    """待开始期改展品标题（同步 VoteOption）和/或替换文件。"""
    if not can_edit_exhibit(activity, user):
        raise ExhibitionError("仅展示可在待开始期改展品")
    try:
        exhibit = activity.exhibits.get(pk=exhibit_id)
    except (Exhibit.DoesNotExist, ValueError, TypeError):
        raise ExhibitionError("展品不存在", http_status=404)
    files = files or []
    _validate_files(files)
    with transaction.atomic():
        if title is not None:
            exhibit.title = title.strip()
            if exhibit.vote_option_id:
                VoteOption.objects.filter(pk=exhibit.vote_option_id).update(text=exhibit.title)
        if files:
            attachments_of(exhibit).delete()
            for f in files:
                try:
                    create_attachment(user=user, parent=exhibit, file=f)
                except AttachmentCreateError as exc:
                    raise ExhibitionError(exc.detail) from exc
        if title is not None:
            exhibit.save(update_fields=["title"])
    return exhibit


def import_submissions(*, activity, user, collection_id, submission_ids):
    """从一场征集勾选作品，复制成独立展品快照。"""
    if not can_curate(activity, user):
        raise ExhibitionError("仅展示可在待开始/展示中导入展品")
    try:
        source = Activity.objects.get(pk=collection_id, type="collection")
    except (Activity.DoesNotExist, ValueError, TypeError):
        raise ExhibitionError("征集不存在", http_status=404)
    submission_ids = submission_ids or []
    subs = source.submissions.filter(pk__in=submission_ids)
    if not subs:
        raise ExhibitionError("未选择任何作品")
    created = []
    with transaction.atomic():
        for sub in subs:
            exhibit = _build_exhibit(activity, user, "", [])
            for att in attachments_of(sub):
                try:
                    copy_attachment(user=user, parent=exhibit, source=att)
                except AttachmentCreateError as exc:
                    raise ExhibitionError(exc.detail) from exc
            created.append(exhibit)
    return created
