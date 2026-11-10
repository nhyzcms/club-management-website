import json

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory

from accounts.test_helpers import grant_verification
from .factories import make_president
from .models import Task, TaskClaimRequest
from .serializers import SimpleUserSerializer


class TaskActionSmokeTest(TestCase):
    """八个流转动作的薄冒烟：每动作一条，断言状态码 + 响应形状 + 详情 available_actions。

    重规则矩阵（状态 × 角色 × 动作）由 ``tasks.tests_lifecycle`` 在模块接口层承担，
    此处只验「HTTP 委托是否接对」——成功路径、行为变更，以及 ``kind``→状态码映射。
    """

    def setUp(self):
        self.creator = grant_verification(User.objects.create_user(username="creator", password="x"))
        self.member = grant_verification(User.objects.create_user(username="member", password="x"))
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.client = APIClient()

    def _post(self, path, user, payload=None):
        self.client.force_authenticate(user)
        if payload is None:
            return self.client.post(path)
        return self.client.post(path, data=json.dumps(payload), content_type="application/json")

    def test_claim_creates_request_and_returns_201(self):
        task = Task.objects.create(title="t", creator=self.creator, status="pending")
        resp = self._post(f"/tasks/tasks/{task.pk}/claim/", self.member, {"reason": "我能做"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["claimant"]["id"], self.member.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, "review")  # 首个认领 → 认领审核

    def test_approve_claim_assigns_claimant(self):
        task = Task.objects.create(title="t", creator=self.creator, status="review")
        claim = TaskClaimRequest.objects.create(task=task, claimant=self.member)
        resp = self._post(f"/tasks/tasks/{task.pk}/approve_claim/", self.creator, {"claim_id": claim.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["assignee"]["id"], self.member.pk)
        self.assertIn("available_actions", resp.data)

    def test_reject_claim_reverts_to_pending(self):
        task = Task.objects.create(title="t", creator=self.creator, status="review")
        claim = TaskClaimRequest.objects.create(task=task, claimant=self.member)
        resp = self._post(f"/tasks/tasks/{task.pk}/reject_claim/", self.creator, {"claim_id": claim.pk})
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, "pending")

    def test_complete_by_assignee_moves_to_reviewing(self):
        task = Task.objects.create(title="t", creator=self.creator, status="in_progress", assignee=self.member)
        resp = self._post(f"/tasks/tasks/{task.pk}/complete/", self.member)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("available_actions", resp.data)
        task.refresh_from_db()
        self.assertEqual(task.status, "reviewing")

    def test_complete_by_collaborator(self):
        # 行为变更（已签字）：协作者（活跃参与者）也能提交验收，此前被静默排除。
        task = Task.objects.create(title="t", creator=self.creator, status="in_progress")
        task.collaborators.add(self.member)
        resp = self._post(f"/tasks/tasks/{task.pk}/complete/", self.member)
        self.assertEqual(resp.status_code, 200)

    def test_approve_completion_completes_task(self):
        task = Task.objects.create(title="t", creator=self.creator, status="reviewing")
        resp = self._post(f"/tasks/tasks/{task.pk}/approve_completion/", self.creator)
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNotNone(task.completed_at)

    def test_reject_completion_returns_to_in_progress_with_reason(self):
        task = Task.objects.create(title="t", creator=self.creator, status="reviewing", assignee=self.member)
        resp = self._post(f"/tasks/tasks/{task.pk}/reject_completion/", self.creator, {"reason": "返工"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["reject_reason"], "返工")
        task.refresh_from_db()
        self.assertEqual(task.status, "in_progress")
        self.assertEqual(task.assignee_id, self.member.pk)  # 负责人不变

    def test_reject_completion_without_reason_is_bad_request(self):
        # 载荷校验失败 → bad_request → 400（kind→状态码映射的冒烟）。
        task = Task.objects.create(title="t", creator=self.creator, status="reviewing")
        resp = self._post(f"/tasks/tasks/{task.pk}/reject_completion/", self.creator, {"reason": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_cancel_cancels_task(self):
        task = Task.objects.create(title="t", creator=self.creator, status="in_progress")
        resp = self._post(f"/tasks/tasks/{task.pk}/cancel/", self.creator)
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, "cancelled")

    def test_assign_sets_assignee_and_in_progress(self):
        task = Task.objects.create(title="t", creator=self.creator, status="pending")
        resp = self._post(f"/tasks/tasks/{task.pk}/assign/", self.president, {"assignee_id": self.member.pk})
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.assignee_id, self.member.pk)
        self.assertEqual(task.status, "in_progress")

    def test_non_creator_approval_is_forbidden(self):
        # 权限不足 → forbidden → 403（kind→状态码映射的冒烟）。
        task = Task.objects.create(title="t", creator=self.creator, status="reviewing")
        resp = self._post(f"/tasks/tasks/{task.pk}/approve_completion/", self.member)
        self.assertEqual(resp.status_code, 403)


class TaskEditLockTest(TestCase):
    def setUp(self):
        self.creator = grant_verification(User.objects.create_user(username="creator", password="x"))
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.client = APIClient()
        self.task = Task.objects.create(
            title="t", creator=self.creator, status="in_progress",
        )

    def _patch(self):
        return self.client.patch(
            f"/tasks/tasks/{self.task.pk}/",
            data=json.dumps({"title": "changed"}),
            content_type="application/json",
        )

    def test_creator_cannot_edit_in_progress(self):
        self.client.force_authenticate(self.creator)
        self.assertEqual(self._patch().status_code, 403)

    def test_president_cannot_edit_in_progress(self):
        self.client.force_authenticate(self.president)
        self.assertEqual(self._patch().status_code, 403)

    def test_creator_cannot_delete_in_progress(self):
        self.client.force_authenticate(self.creator)
        resp = self.client.delete(f"/tasks/tasks/{self.task.pk}/")
        self.assertEqual(resp.status_code, 403)

    def test_creator_can_edit_pending(self):
        self.task.status = "pending"
        self.task.save()
        self.client.force_authenticate(self.creator)
        self.assertEqual(self._patch().status_code, 200)


class TaskAvailableActionsTest(TestCase):
    """详情序列化带 available_actions（来自生命周期模块）；列表不带。"""

    def setUp(self):
        self.creator = grant_verification(User.objects.create_user(username="creator", password="x"))
        self.assignee = grant_verification(User.objects.create_user(username="assignee", password="x"))
        self.client = APIClient()

    def test_detail_includes_available_actions(self):
        task = Task.objects.create(title="t", creator=self.creator, status="in_progress", assignee=self.assignee)
        self.client.force_authenticate(self.creator)
        resp = self.client.get(f"/tasks/tasks/{task.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("available_actions", resp.data)
        # 创建者看进行中任务：可取消（非终态 + 创建者）；不可完成（非活跃参与者）。
        self.assertIn("cancel", resp.data["available_actions"])
        self.assertNotIn("complete", resp.data["available_actions"])

    def test_detail_available_actions_for_active_participant(self):
        # 负责人是活跃参与者 → complete 出现在可用动作里。
        task = Task.objects.create(title="t", creator=self.creator, status="in_progress", assignee=self.assignee)
        self.client.force_authenticate(self.assignee)
        resp = self.client.get(f"/tasks/tasks/{task.pk}/")
        self.assertIn("complete", resp.data["available_actions"])

    def test_list_excludes_available_actions(self):
        Task.objects.create(title="t", creator=self.creator, status="pending")
        self.client.force_authenticate(self.creator)
        resp = self.client.get("/tasks/tasks/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        items = data["results"] if isinstance(data, dict) and "results" in data else data
        self.assertNotIn("available_actions", items[0])


class TaskListPaginationTest(TestCase):
    """任务列表分页 + ?all=1 逃生口 + 标签关分页。

    - 默认返回分页信封（20/页）；?all=1 返回全量裸数组（时间线/甘特用），并尊重筛选。
    - /tasks/tags/ 关分页：一次返回全部标签（表单下拉需要全量）。
    """

    def setUp(self):
        self.user = User.objects.create_user(username="plain", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        for i in range(25):
            Task.objects.create(title=f"任务{i:02d}", creator=self.user, status="pending")

    def test_default_paginated_envelope(self):
        resp = self.client.get("/tasks/tasks/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.data.keys()), {"count", "next", "previous", "results"})
        self.assertEqual(resp.data["count"], 25)
        self.assertEqual(len(resp.data["results"]), 20)
        self.assertIsNotNone(resp.data["next"])

    def test_all_returns_bare_full_array(self):
        resp = self.client.get("/tasks/tasks/?all=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)
        self.assertEqual(len(resp.data), 25)

    def test_all_respects_filters(self):
        Task.objects.filter(title="任务01").update(status="completed")
        resp = self.client.get("/tasks/tasks/?all=1&status=completed")
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["title"], "任务01")

    def test_tags_unpaginated(self):
        from .models import Tag
        for i in range(5):
            Tag.objects.create(name=f"标签{i}")
        resp = self.client.get("/tasks/tags/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)
        self.assertEqual(len(resp.data), 5)


# ---- 用户引用的 email 可见性：仅本人（回归：公开读接口曾随内容泄露邮箱）----


class SimpleUserSerializerEmailVisibilityTest(TestCase):
    """``SimpleUserSerializer`` 的 email 仅对本人输出。

    与 ``accounts.visibility`` 的 ``can_see_private = owner`` 对齐：新闻 / 教程 /
    活动等公开读接口均复用本序列化器渲染他人用户引用，此前 email 无条件输出，
    未认证访客即可批量收集成员邮箱（字段级越权）。
    """

    def setUp(self):
        self.me = User.objects.create_user(username="me", password="x", email="me@example.com")
        self.other = User.objects.create_user(username="other", password="x", email="other@example.com")

    def _render(self, viewer, obj):
        request = APIRequestFactory().get("/")
        request.user = viewer
        return SimpleUserSerializer(obj, context={"request": request}).data

    def test_email_visible_to_self(self):
        self.assertEqual(self._render(self.me, self.me)["email"], "me@example.com")

    def test_email_hidden_from_authenticated_other(self):
        self.assertNotIn("email", self._render(self.other, self.me))

    def test_email_hidden_from_anonymous(self):
        self.assertNotIn("email", self._render(AnonymousUser(), self.me))

    def test_email_hidden_without_request_context(self):
        # 无 request（内部调用 / 缺省 context）→ 安全默认：不输出 email
        self.assertNotIn("email", SimpleUserSerializer(self.me).data)

    def test_public_fields_intact(self):
        data = self._render(self.other, self.me)
        self.assertEqual(data["id"], self.me.pk)
        self.assertEqual(data["username"], "me")
        self.assertIn("nickname", data)
        self.assertIn("avatar", data)
