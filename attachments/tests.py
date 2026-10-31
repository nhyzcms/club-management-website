"""统一附件端点测试。

单一接缝：HTTP API（``POST /attachments/``、``DELETE /attachments/{id}/``）。
只测外部行为（状态码、响应体、``refresh_from_db`` 后的模型状态、磁盘文件存在性），
不测信号/校验函数的内部实现。风格仿 ``tasks/tests.py`` / ``reviews/tests_feedback.py``。

所有用例经 ``_AttachmentTestCase`` 把 ``MEDIA_ROOT`` 重定向到临时目录，并在结束时兜底
清理真实 ``media/attachments/``（Django 可能缓存 FileField 存储、使 override 不生效）。
"""
import base64
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from common.policy import SitePolicy
from reviews.models import Feedback
from tasks.models import Task

from .models import Attachment, TusUpload


def make_president(user):
    """加入「社长」组：已含 manage_tasks / read_feedback 等管理权限。"""
    group, _ = Group.objects.get_or_create(name="社长")
    user.groups.add(group)
    return user


def upload(name="a.png", content=b"data", content_type="image/png"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def tus_meta(**kv):
    """构造 tus Upload-Metadata 头：``key base64(value),…``（值由 drf-tus 解码）。"""
    return ",".join(f"{k} {base64.b64encode(str(v).encode()).decode()}" for k, v in kv.items())


class _AttachmentTestCase(TestCase):
    """临时 MEDIA_ROOT + 兜底清理，确保测试不污染真实 media/。"""

    def setUp(self):
        self._real_media_root = Path(settings.MEDIA_ROOT)
        self.tmp_media = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self.tmp_media)
        self._override.enable()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._override.disable()
        # 兜底：若 FileField 存储未随 override 重定向，文件会落到真实 media/attachments/
        att_dir = self._real_media_root / "attachments"
        if att_dir.exists():
            for path in att_dir.glob("*"):
                path.unlink(missing_ok=True)
        shutil.rmtree(self.tmp_media, ignore_errors=True)


# ── 上传权限（任务父级）──
class UploadTaskPermissionTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.assignee = User.objects.create_user(username="assignee", password="x")
        self.collab = User.objects.create_user(username="collab", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.client = APIClient()
        # 进行中任务：creator + assignee + collaborator
        self.task = Task.objects.create(
            title="t", creator=self.creator, assignee=self.assignee, status="in_progress",
        )
        self.task.collaborators.add(self.collab)
        # 待处理任务：仅 creator 可上传
        self.pending = Task.objects.create(title="p", creator=self.creator, status="pending")

    def _post(self, user, task):
        self.client.force_authenticate(user) # pyright: ignore[reportAttributeAccessIssue]
        return self.client.post(
            "/attachments/", {"file": upload(), "task_id": task.pk}, format="multipart",
        )

    def test_creator_can_upload_to_in_progress_task(self):
        self.assertEqual(self._post(self.creator, self.task).status_code, 201)

    def test_creator_can_upload_to_own_pending_task(self):  # 故事 #6
        self.assertEqual(self._post(self.creator, self.pending).status_code, 201)

    def test_assignee_can_upload_to_in_progress_task(self):
        self.assertEqual(self._post(self.assignee, self.task).status_code, 201)

    def test_collaborator_can_upload_to_in_progress_task(self):
        self.assertEqual(self._post(self.collab, self.task).status_code, 201)

    def test_president_can_upload_to_any_task(self):  # 故事 #9
        self.assertEqual(self._post(self.president, self.task).status_code, 201)

    def test_outsider_cannot_upload_to_others_task(self):  # 故事 #7
        self.assertEqual(self._post(self.outsider, self.task).status_code, 403)

    def test_collaborator_cannot_upload_when_task_not_in_progress(self):
        # 协作者仅在进行中才是活跃参与者
        other = Task.objects.create(title="c", creator=self.creator, status="pending")
        other.collaborators.add(self.collab)
        self.assertEqual(self._post(self.collab, other).status_code, 403)

    def test_anonymous_cannot_upload(self):  # 故事 #11
        self.client.force_authenticate(None) # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.post(
            "/attachments/", {"file": upload(), "task_id": self.task.pk}, format="multipart",
        )
        self.assertEqual(resp.status_code, 403)


# ── 反馈附件上传权限（carve-out：仅署名创建者 + 仅审结前，社长被排除）──
class FeedbackUploadPermissionTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.client = APIClient()
        self.feedback = Feedback.objects.create(
            category="complaint", status="pending",
            title="f", creator=self.creator,
        )

    def _post(self, user, proposal=None):
        self.client.force_authenticate(user) # pyright: ignore[reportAttributeAccessIssue]
        return self.client.post(
            "/attachments/",
            {"file": upload(), "feedback_id": (proposal or self.feedback).pk},
            format="multipart",
        )

    def test_president_cannot_upload_to_feedback(self):  # carve-out：排除社长上传
        self.assertEqual(self._post(self.president).status_code, 403)

    def test_creator_can_upload_to_own_pending_feedback(self):
        self.assertEqual(self._post(self.creator).status_code, 201)

    def test_outsider_cannot_upload_to_feedback(self):
        self.assertEqual(self._post(self.outsider).status_code, 403)

    def test_upload_locked_after_feedback_closed(self):
        self.feedback.status = "closed"
        self.feedback.save()
        self.assertEqual(self._post(self.creator).status_code, 403)


# ── 反馈附件配额（每条 ≤9 个 / 总 ≤2GB）──
class FeedbackQuotaTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.creator)
        self.feedback = Feedback.objects.create(
            category="suggestion", status="pending",
            title="f", creator=self.creator,
        )

    def _post(self):
        return self.client.post(
            "/attachments/", {"file": upload(), "feedback_id": self.feedback.pk}, format="multipart",
        )

    def test_count_cap_rejects_extra(self):
        self.assertEqual(self._post().status_code, 201)  # 第一张 ok
        with mock.patch("attachments.validation.FEEDBACK_MAX_ATTACHMENTS", 1):
            self.assertEqual(self._post().status_code, 400)  # 超个数上限

    def test_total_size_cap_rejects_extra(self):
        self.assertEqual(self._post().status_code, 201)  # 第一张 ok
        with mock.patch("attachments.validation.FEEDBACK_MAX_TOTAL_BYTES", 1):
            self.assertEqual(self._post().status_code, 400)  # 超总大小上限


# ── 反馈附件删除：社长「能删不能传」（上传 carve-out 排除社长，删除沿用通用规则）──
class DeletePermissionFeedbackTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.client = APIClient()
        self.feedback = Feedback.objects.create(
            category="suggestion", status="pending",
            title="f", creator=self.creator,
        )
        # creator 在待审期上传一张
        self.client.force_authenticate(self.creator)
        resp = self.client.post(
            "/attachments/", {"file": upload(), "feedback_id": self.feedback.pk}, format="multipart",
        )
        self.attachment_id = resp.data["id"] # pyright: ignore[reportAttributeAccessIssue]

    def test_president_can_delete_feedback_attachment(self):  # 审核违规媒体
        self.client.force_authenticate(self.president) # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(self.client.delete(f"/attachments/{self.attachment_id}/").status_code, 204)

    def test_outsider_cannot_delete_feedback_attachment(self):
        self.client.force_authenticate(self.outsider) # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(self.client.delete(f"/attachments/{self.attachment_id}/").status_code, 403)


# ── 恰一父级 ──
class ParentValidationTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.creator)
        self.task = Task.objects.create(title="t", creator=self.creator, status="pending")
        self.prop = Feedback.objects.create(
            category="suggestion", status="pending", title="p", creator=self.creator,
        )

    def test_both_parents_rejected(self):  # 故事 #20
        resp = self.client.post(
            "/attachments/",
            {"file": upload(), "task_id": self.task.pk, "feedback_id": self.prop.pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_neither_parent_rejected(self):  # 故事 #20
        resp = self.client.post("/attachments/", {"file": upload()}, format="multipart")
        self.assertEqual(resp.status_code, 400)


# ── 文件校验 ──
class FileValidationTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.creator)
        self.task = Task.objects.create(title="t", creator=self.creator, status="pending")

    def _post(self, f):
        return self.client.post(
            "/attachments/", {"file": f, "task_id": self.task.pk}, format="multipart",
        )

    def test_oversize_rejected(self):  # 把同步上限降到 1B，4B 文件即超限
        policy = replace(SitePolicy.defaults(), sync_upload_max_bytes=1)
        with mock.patch("attachments.validation.get_policy", return_value=policy):
            resp = self._post(upload())
        self.assertEqual(resp.status_code, 400)

    def test_banned_extension_rejected(self):  # 故事 #18
        resp = self._post(upload("evil.py", b"x", "text/x-python"))
        self.assertEqual(resp.status_code, 400)

    def test_classifies_image(self):  # 故事 #19
        resp = self._post(upload("a.png", b"x", "image/png"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["file_type"], "image") # pyright: ignore[reportAttributeAccessIssue]

    def test_classifies_document(self):
        resp = self._post(upload("a.pdf", b"x", "application/pdf"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["file_type"], "document") # type: ignore

    def test_classifies_archive(self):
        resp = self._post(upload("a.zip", b"x", "application/zip"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["file_type"], "archive") # pyright: ignore[reportAttributeAccessIssue]

    def test_classifies_other(self):
        resp = self._post(upload("a.bin", b"x", "application/octet-stream"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["file_type"], "other") # pyright: ignore[reportAttributeAccessIssue]


# ── 删除权限 ──
class DeletePermissionTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user(username="owner", password="x")
        self.uploader = User.objects.create_user(username="uploader", password="x")
        self.collab = User.objects.create_user(username="collab", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.client = APIClient()
        # 进行中任务：owner 创建；uploader=assignee（活跃参与者）；collab=协作者
        self.task = Task.objects.create(
            title="t", creator=self.owner, assignee=self.uploader, status="in_progress",
        )
        self.task.collaborators.add(self.collab)
        # uploader（=负责人）上传一个附件
        self.client.force_authenticate(self.uploader)
        resp = self.client.post(
            "/attachments/", {"file": upload(), "task_id": self.task.pk}, format="multipart",
        )
        self.assertEqual(resp.status_code, 201) # pyright: ignore[reportAttributeAccessIssue]
        self.attachment_id = resp.data["id"] # pyright: ignore[reportAttributeAccessIssue]

    def _delete(self, user):
        self.client.force_authenticate(user) # pyright: ignore[reportAttributeAccessIssue]
        return self.client.delete(f"/attachments/{self.attachment_id}/")

    def test_uploader_can_delete_own(self):  # 故事 #12
        self.assertEqual(self._delete(self.uploader).status_code, 204)

    def test_parent_creator_can_delete(self):  # 故事 #13
        self.assertEqual(self._delete(self.owner).status_code, 204)

    def test_president_can_delete(self):  # 故事 #9 / #10
        self.assertEqual(self._delete(self.president).status_code, 204)

    def test_active_participant_can_delete(self):  # ADR：增、删同一套规则
        self.assertEqual(self._delete(self.collab).status_code, 204)

    def test_outsider_cannot_delete(self):  # 故事 #14
        self.assertEqual(self._delete(self.outsider).status_code, 403)


class DeleteOwnAfterTaskNotInProgressTest(_AttachmentTestCase):
    """故事 #12 健壮性：任务离开进行中后，上传者仍可删自己上传的附件。"""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user(username="owner", password="x")
        self.uploader = User.objects.create_user(username="uploader", password="x")
        self.client = APIClient()
        self.task = Task.objects.create(
            title="t", creator=self.owner, assignee=self.uploader, status="in_progress",
        )
        # uploader 在进行中上传（活跃参与者）
        self.client.force_authenticate(self.uploader)
        resp = self.client.post(
            "/attachments/", {"file": upload(), "task_id": self.task.pk}, format="multipart",
        )
        self.attachment_id = resp.data["id"] # pyright: ignore[reportAttributeAccessIssue]
        # 任务流转出进行中：uploader 不再是活跃参与者
        self.task.status = "completed"
        self.task.save()

    def test_uploader_can_delete_after_task_left_in_progress(self):
        self.client.force_authenticate(self.uploader) # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.delete(f"/attachments/{self.attachment_id}/")
        self.assertEqual(resp.status_code, 204)


# ── 级联回收（删父级 → 行 + 磁盘文件同步消失）──
class CascadeReclaimTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        # creator 会删 task（tasks destroy 受 IsVerified 门禁）→ 需已认证
        self.creator = grant_verification(User.objects.create_user(username="creator", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.creator)
        self.task = Task.objects.create(title="t", creator=self.creator, status="pending")
        self.prop = Feedback.objects.create(
            category="suggestion", status="pending", title="p", creator=self.creator,
        )

    def _upload_and_capture(self, parent_key, parent_pk):
        resp = self.client.post(
            "/attachments/",
            {"file": upload(), parent_key: parent_pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        att = Attachment.objects.get(pk=resp.data["id"]) # pyright: ignore[reportAttributeAccessIssue]
        return att.id, att.file.storage, att.file.name # pyright: ignore[reportAttributeAccessIssue]

    def test_deleting_task_removes_attachment_and_file(self):  # 故事 #15
        att_id, storage, name = self._upload_and_capture("task_id", self.task.pk)
        self.assertTrue(storage.exists(name))

        resp = self.client.delete(f"/tasks/tasks/{self.task.pk}/")  # creator 删 pending 任务
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Attachment.objects.filter(pk=att_id).exists())
        self.assertFalse(storage.exists(name))

    def test_deleting_feedback_removes_attachment_and_file(self):  # 故事 #16
        att_id, storage, name = self._upload_and_capture("feedback_id", self.prop.pk)
        self.assertTrue(storage.exists(name))

        self.prop.delete()
        self.assertFalse(Attachment.objects.filter(pk=att_id).exists())
        self.assertFalse(storage.exists(name))


# ── 详情内联渲染：附件随父级详情返回（统一序列化器 + 规范化后的 attachments 访问器）──
class ParentDetailRendersAttachmentsTest(_AttachmentTestCase):
    """统一附件不再有独立列表端点——列表随任务/申报详情的 ``attachments`` 字段返回。

    守护 T3 收尾后的渲染路径：访问器已从 ``unified_attachments`` 规范化为
    ``attachments``，且两个详情序列化器都复用统一 ``AttachmentSerializer``（其
    ``uploaded_by`` 经延迟导入打破 tasks↔attachments 序列化器循环）。
    """

    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.creator)
        self.task = Task.objects.create(title="t", creator=self.creator, status="pending")
        self.prop = Feedback.objects.create(
            category="suggestion", status="pending", title="p", creator=self.creator,
        )

    def test_task_detail_inlines_attachments(self):  # 故事 #23
        resp = self.client.post(
            "/attachments/",
            {"file": upload("a.png", b"x", "image/png"), "task_id": self.task.pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        att_id = resp.data["id"] # pyright: ignore[reportAttributeAccessIssue]

        resp = self.client.get(f"/tasks/tasks/{self.task.pk}/")
        self.assertEqual(resp.status_code, 200)
        attachments = resp.data["attachments"] # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["id"], att_id)
        self.assertEqual(attachments[0]["file_type"], "image")
        # 统一序列化器经延迟导入的 SimpleUserSerializer 渲染上传者
        self.assertEqual(attachments[0]["uploaded_by"]["username"], "creator")
        self.assertIn("file_url", attachments[0])

    def test_feedback_detail_inlines_attachments(self):  # 故事 #24
        resp = self.client.post(
            "/attachments/",
            {"file": upload("a.pdf", b"x", "application/pdf"), "feedback_id": self.prop.pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        att_id = resp.data["id"] # pyright: ignore[reportAttributeAccessIssue]

        resp = self.client.get(f"/reviews/feedbacks/{self.prop.pk}/")
        self.assertEqual(resp.status_code, 200)
        attachments = resp.data["attachments"] # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["id"], att_id)
        self.assertEqual(attachments[0]["file_type"], "document")
        self.assertEqual(attachments[0]["uploaded_by"]["username"], "creator")


# ── tus 可续传上传（#19）：大文件（>50MB 图/视频）经 drf-tus → 统一 Attachment ──
class TusUploadTest(_AttachmentTestCase):
    """单一接缝：HTTP（tus 协议 POST 创建 / PATCH 分片）。只断言外部结果——Attachment
    行是否正确创建/拒绝、tus 会话是否回收；不测 drf-tus 内部。
    """

    def setUp(self):
        super().setUp()
        self.creator = User.objects.create_user(username="creator", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.feedback = Feedback.objects.create(
            category="complaint", status="pending",
            title="f", creator=self.creator,
        )
        self.client = APIClient()

    def tearDown(self):
        TusUpload.objects.all().delete()  # 回收 temp + 落地文件，避免污染 BASE_DIR/tmp/uploads
        super().tearDown()

    def _create(self, user, *, length, filetype="image/png", filename="t.png",
                parent_type="feedback", parent_id=None):
        self.client.force_authenticate(user)  # pyright: ignore[reportAttributeAccessIssue]
        meta = tus_meta(
            filename=filename, filetype=filetype, parent_type=parent_type,
            parent_id=parent_id if parent_id is not None else self.feedback.pk,
        )
        return self.client.post(
            "/uploads/files/", content_type="application/octet-stream",
            HTTP_TUS_RESUMABLE="1.0.0", HTTP_UPLOAD_LENGTH=str(length), HTTP_UPLOAD_METADATA=meta,
        )

    def _patch(self, location, chunk):
        return self.client.patch(
            location, data=chunk, content_type="application/offset+octet-stream",
            HTTP_TUS_RESUMABLE="1.0.0", HTTP_UPLOAD_OFFSET="0",
        )

    def test_tus_upload_creates_attachment_bound_to_feedback(self):
        chunk = b"PNG-fake-bytes"
        resp = self._create(self.creator, length=len(chunk), filetype="image/png", filename="t.png")
        self.assertEqual(resp.status_code, 201)
        location = resp.get("Location") or resp["Location"]  # type: ignore[attr-defined]
        self.assertTrue(location)

        resp2 = self._patch(location, chunk)
        self.assertEqual(resp2.status_code, 204)

        att = Attachment.objects.get(feedback=self.feedback)
        self.assertEqual(att.uploaded_by, self.creator)
        self.assertEqual(att.file_type, "image")
        self.assertEqual(att.file_size, len(chunk))
        # 搬运后的附件文件落盘且有内容
        self.assertTrue(att.file.storage.exists(att.file.name))

    def test_outsider_cannot_tus_create(self):
        self.assertEqual(self._create(self.outsider, length=4).status_code, 403)

    def test_anonymous_cannot_tus_create(self):
        self.client.force_authenticate(None)  # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.post(
            "/uploads/files/", content_type="application/octet-stream",
            HTTP_TUS_RESUMABLE="1.0.0", HTTP_UPLOAD_LENGTH="4",
            HTTP_UPLOAD_METADATA=tus_meta(parent_type="feedback", parent_id=self.feedback.pk),
        )
        self.assertEqual(resp.status_code, 403)

    def test_president_cannot_tus_upload_to_feedback(self):  # 反馈 carve-out：排除社长
        self.assertEqual(self._create(self.president, length=4).status_code, 403)

    def test_missing_parent_rejected(self):
        self.client.force_authenticate(self.creator)  # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.post(
            "/uploads/files/", content_type="application/octet-stream",
            HTTP_TUS_RESUMABLE="1.0.0", HTTP_UPLOAD_LENGTH="4",
            HTTP_UPLOAD_METADATA=tus_meta(filename="t.png", filetype="image/png"),
        )
        self.assertEqual(resp.status_code, 400)

    def test_oversize_rejected_at_create(self):  # 超 tus 上限由 drf-tus 返 413（不传字节）
        policy = replace(SitePolicy.defaults(), tus_media_max_bytes=1024)
        with mock.patch("attachments.tus.get_policy", return_value=policy):
            resp = self._create(self.creator, length=2048, filetype="video/mp4")
        self.assertEqual(resp.status_code, 413)

    def test_non_media_above_50mb_rejected(self):  # >50MB 必须图/视频
        resp = self._create(self.creator, length=60 * 1024 * 1024, filetype="application/pdf")
        self.assertEqual(resp.status_code, 400)

    def test_completion_reverify_rejects_when_feedback_closed(self):
        # 创建时 pending（通过）；打补丁前反馈被了结 → 完成时复核失败，不建附件
        chunk = b"x" * 8
        resp = self._create(self.creator, length=len(chunk), filetype="image/png")
        self.assertEqual(resp.status_code, 201)
        self.feedback.status = "closed"
        self.feedback.save()
        resp2 = self._patch(resp.get("Location") or resp["Location"], chunk)  # type: ignore[attr-defined]
        self.assertEqual(resp2.status_code, 204)
        self.assertFalse(Attachment.objects.filter(feedback=self.feedback).exists())

    def test_tus_quota_enforced_at_create(self):
        with mock.patch("attachments.validation.FEEDBACK_MAX_ATTACHMENTS", 0):
            self.assertEqual(self._create(self.creator, length=4).status_code, 400)

    def test_tus_upload_to_task_creates_attachment(self):  # 非反馈父级路径
        task = Task.objects.create(title="t", creator=self.creator, status="pending")
        chunk = b"task-bytes"
        resp = self._create(
            self.creator, length=len(chunk), filetype="image/png",
            parent_type="task", parent_id=task.pk,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(self._patch(resp.get("Location") or resp["Location"], chunk).status_code, 204)  # type: ignore[attr-defined]
        att = Attachment.objects.get(task=task)
        self.assertEqual(att.uploaded_by, self.creator)
        self.assertEqual(att.file_type, "image")

    def test_tus_upload_to_feedback_creates_attachment(self):  # 反馈父级路径
        fb = Feedback.objects.create(
            category="suggestion", status="pending", title="p", creator=self.creator,
        )
        chunk = b"prop-bytes"
        resp = self._create(
            self.creator, length=len(chunk), filetype="image/png",
            parent_type="feedback", parent_id=fb.pk,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(self._patch(resp.get("Location") or resp["Location"], chunk).status_code, 204)  # type: ignore[attr-defined]
        att = Attachment.objects.get(feedback=fb)
        self.assertEqual(att.uploaded_by, self.creator)
        self.assertEqual(att.file_type, "image")

    def test_stale_tus_upload_swept_on_next_create(self):  # 放弃/过期的会话由惰性清理回收
        from datetime import timedelta
        from django.utils import timezone
        stale = TusUpload.objects.create(
            upload_length=4, upload_metadata={}, expires=timezone.now() - timedelta(hours=1),
        )
        self._create(self.creator, length=4)  # 触发 create → sweep
        self.assertFalse(TusUpload.objects.filter(pk=stale.pk).exists())

    def test_tus_upload_to_news_creates_attachment(self):  # 新闻视频父级路径
        from news.models import News
        news = News.objects.create(title="n", author=self.creator, is_published=True)
        chunk = b"news-video-bytes"
        resp = self._create(
            self.creator, length=len(chunk), filetype="video/mp4", filename="v.mp4",
            parent_type="news", parent_id=news.pk,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(self._patch(resp.get("Location") or resp["Location"], chunk).status_code, 204)  # type: ignore[attr-defined]
        att = Attachment.objects.get(news=news)
        self.assertEqual(att.uploaded_by, self.creator)
        self.assertEqual(att.file_type, "video")


# ── news 父级（#新闻视频）──
class AttachmentNewsParentTest(_AttachmentTestCase):
    """Attachment 可挂 news 父级；task/feedback/news 三选一。"""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User
        from news.models import News
        self.user = User.objects.create_user(username="author", password="x")
        self.news = News.objects.create(title="n", author=self.user, is_published=True)
        self.task = Task.objects.create(title="t", creator=self.user, status="pending")

    def test_news_only_attachment_valid(self):
        att = Attachment(
            uploaded_by=self.user, news=self.news,
            file=upload("v.mp4", b"x", "video/mp4"),
            file_type="video", file_name="v.mp4", file_size=1,
        )
        att.full_clean()  # 不抛
        att.save()
        self.assertEqual(Attachment.objects.get(pk=att.pk).news_id, self.news.pk)

    def test_news_and_task_rejected(self):
        from django.db import IntegrityError
        att = Attachment(
            uploaded_by=self.user, news=self.news, task=self.task,
            file=upload("v.mp4", b"x", "video/mp4"),
            file_type="video", file_name="v.mp4", file_size=1,
        )
        with self.assertRaises(IntegrityError):
            att.save()


# ── news 父级上传权限（#新闻视频）──
class UploadNewsPermissionTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        from news.models import News
        self.author = User.objects.create_user(username="author", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.news = News.objects.create(title="n", author=self.author, is_published=True)
        self.client = APIClient()

    def _post(self, user):
        self.client.force_authenticate(user)  # pyright: ignore[reportAttributeAccessIssue]
        return self.client.post(
            "/attachments/", {"file": upload("v.mp4", b"x", "video/mp4"), "news_id": self.news.pk},
            format="multipart",
        )

    def test_news_author_can_upload(self):
        self.assertEqual(self._post(self.author).status_code, 201)

    def test_outsider_cannot_upload_to_news(self):
        self.assertEqual(self._post(self.outsider).status_code, 403)


# ── 新闻详情内联视频附件（精简、不含 uploaded_by）──
class NewsDetailAttachmentsTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        from news.models import News
        self.author = User.objects.create_user(username="author", password="x")
        self.news = News.objects.create(title="n", author=self.author, is_published=True)
        self.client = APIClient()
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            "/attachments/",
            {"file": upload("v.mp4", b"x", "video/mp4"), "news_id": self.news.pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)

    def test_news_detail_inlines_attachments(self):
        resp = self.client.get(f"/news/news/{self.news.pk}/")
        self.assertEqual(resp.status_code, 200)
        atts = resp.data["attachments"]  # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts[0]["file_type"], "video")
        self.assertIn("file_url", atts[0])
        self.assertNotIn("uploaded_by", atts[0])


# ── 新闻作者即创建者（不依赖 manage_news；旧测试靠授权掩盖 author_id）──
class NewsAuthorIsCreatorTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        from news.models import News
        self.author = User.objects.create_user(username="author", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.news = News.objects.create(title="n", author=self.author, is_published=True)
        self.client = APIClient()

    def test_author_can_upload_without_manage_news(self):
        self.client.force_authenticate(self.author)  # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.post(
            "/attachments/",
            {"file": upload("v.mp4", b"x", "video/mp4"), "news_id": self.news.pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)

    def test_author_can_delete_without_manage_news(self):
        from attachments.create import create_attachment
        att = create_attachment(user=self.outsider, parent=self.news, file=upload("v.mp4", b"x", "video/mp4"))
        self.client.force_authenticate(self.author)  # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(self.client.delete(f"/attachments/{att.pk}/").status_code, 204)

    def test_outsider_cannot_delete_news_attachment(self):
        from attachments.create import create_attachment
        att = create_attachment(user=self.author, parent=self.news, file=upload("v.mp4", b"x", "video/mp4"))
        self.client.force_authenticate(self.outsider)  # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(self.client.delete(f"/attachments/{att.pk}/").status_code, 403)


# ── 展品父级：策展人可删（destroy 须含 exhibit；策展 = 活动发起人 / manage_activity）──
class ExhibitCuratorDeleteTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission

        from activities.models import Activity, Exhibit
        from attachments.create import create_attachment

        self.curator = User.objects.create_user(username="curator", password="x")
        self.uploader = User.objects.create_user(username="uploader", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.manager = User.objects.create_user(username="manager", password="x")
        self.manager.user_permissions.add(Permission.objects.get(codename="manage_activity"))
        self.activity = Activity.objects.create(
            type="exhibition", status="scheduled", title="影展", creator=self.curator,
        )
        self.exhibit = Exhibit.objects.create(activity=self.activity, title="作品A")
        att = create_attachment(user=self.uploader, parent=self.exhibit, file=upload())
        self.attachment_id = att.pk
        self.client = APIClient()

    def _delete(self, user):
        self.client.force_authenticate(user)  # pyright: ignore[reportAttributeAccessIssue]
        return self.client.delete(f"/attachments/{self.attachment_id}/")

    def test_curator_can_delete_exhibit_attachment(self):
        self.assertEqual(self._delete(self.curator).status_code, 204)

    def test_manage_activity_holder_can_delete_exhibit_attachment(self):
        self.assertEqual(self._delete(self.manager).status_code, 204)

    def test_outsider_cannot_delete_exhibit_attachment(self):
        self.assertEqual(self._delete(self.outsider).status_code, 403)

    def test_http_rejects_exhibit_id(self):
        self.client.force_authenticate(self.curator)  # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.post(
            "/attachments/",
            {"file": upload(), "exhibit_id": self.exhibit.pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)


# ── 作品父级：create 接缝 + 非 HTTP 父级 + 活动发起人可删──
class SubmissionParentTest(_AttachmentTestCase):
    def setUp(self):
        super().setUp()
        from activities.models import Activity, Submission
        from attachments.create import create_attachment, parent_of

        self.creator = User.objects.create_user(username="creator", password="x")
        self.submitter = User.objects.create_user(username="submitter", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.activity = Activity.objects.create(
            type="collection", status="collecting", title="征 logo", creator=self.creator,
        )
        self.submission = Submission.objects.create(
            activity=self.activity, submitter=self.submitter,
        )
        self.att = create_attachment(
            user=self.submitter, parent=self.submission, file=upload(),
        )
        self.parent_of = parent_of
        self.client = APIClient()

    def test_create_attachment_binds_submission(self):
        self.assertEqual(self.att.submission_id, self.submission.pk)
        self.assertEqual(self.parent_of(self.att).pk, self.submission.pk)

    def test_http_rejects_submission_id(self):
        self.client.force_authenticate(self.submitter)  # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.post(
            "/attachments/",
            {"file": upload(), "submission_id": self.submission.pk},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_activity_creator_can_delete_submission_attachment(self):
        self.client.force_authenticate(self.creator)  # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(self.client.delete(f"/attachments/{self.att.pk}/").status_code, 204)

    def test_outsider_cannot_delete_submission_attachment(self):
        self.client.force_authenticate(self.outsider)  # pyright: ignore[reportAttributeAccessIssue]
        self.assertEqual(self.client.delete(f"/attachments/{self.att.pk}/").status_code, 403)




class TusUploadHardeningTest(TusUploadTest):
    """M-1 回归：对象级授权 / 拒绝延迟长度 / 完成钩子扩展名校验。"""

    def test_other_user_cannot_head_or_patch(self):
        chunk = b"12345678"
        resp = self._create(self.creator, length=len(chunk))
        self.assertEqual(resp.status_code, 201)
        location = resp.get("Location") or resp["Location"]  # type: ignore[attr-defined]

        self.client.force_authenticate(self.outsider)  # pyright: ignore[reportAttributeAccessIssue]
        self.assertNotEqual(self.client.head(location).status_code, 200)
        self.assertNotEqual(self._patch(location, chunk).status_code, 204)

    def test_defer_length_rejected(self):
        self.client.force_authenticate(self.creator)  # pyright: ignore[reportAttributeAccessIssue]
        resp = self.client.post(
            "/uploads/files/", content_type="application/octet-stream",
            HTTP_TUS_RESUMABLE="1.0.0", HTTP_UPLOAD_DEFER_LENGTH="1",
            HTTP_UPLOAD_METADATA=tus_meta(
                filename="t.png", filetype="image/png",
                parent_type="feedback", parent_id=self.feedback.pk,
            ),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Upload-Length", resp.json()["detail"])

    def test_completion_rejects_forbidden_extension(self):
        chunk = b"<script>x</script>"
        resp = self._create(
            self.creator, length=len(chunk), filetype="image/png", filename="payload.html",
        )
        self.assertEqual(resp.status_code, 201)
        location = resp.get("Location") or resp["Location"]  # type: ignore[attr-defined]
        self.assertEqual(self._patch(location, chunk).status_code, 204)
        self.assertFalse(Attachment.objects.filter(feedback=self.feedback).exists())
