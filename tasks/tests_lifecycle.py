"""任务生命周期模块的接口测试（主 seam：直接调用纯领域逻辑，不经 HTTP）。

覆盖「状态 × 角色 × 动作」矩阵。与 tasks/tests.py 里的 HTTP 冒烟相对——
本文件只测模块对外契约（谓词、available_actions、apply），不测视图内部。
"""

from django.contrib.auth.models import User
from django.test import TestCase

from .factories import make_president
from .lifecycle import (
    APPROVE_CLAIM,
    APPROVE_COMPLETION,
    ASSIGN,
    CANCEL,
    CLAIM,
    COMPLETE,
    KIND_BAD_REQUEST,
    KIND_FORBIDDEN,
    KIND_NOT_FOUND,
    REJECT_CLAIM,
    REJECT_COMPLETION,
    TransitionResult,
    apply,
    available_actions,
    can_assign,
    can_manage,
    is_active_participant,
    is_creator,
    status_for_assignee,
)
from .models import Task, TaskClaimRequest


class LifecyclePredicateTest(TestCase):
    """三段权限谓词：创建者 / 活跃参与者 / 管理权限（+ 指派权限）。"""

    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="x")
        self.assignee = User.objects.create_user(username="assignee", password="x")
        self.collaborator = User.objects.create_user(username="collab", password="x")
        self.outsider = User.objects.create_user(username="other", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))
        self.task = Task.objects.create(
            title="t", creator=self.creator, assignee=self.assignee, status="in_progress",
        )
        self.task.collaborators.add(self.collaborator)

    def test_is_creator(self):
        self.assertTrue(is_creator(self.task, self.creator))
        self.assertFalse(is_creator(self.task, self.assignee))

    def test_is_active_participant_in_progress(self):
        # in_progress：负责人与协作者都是活跃参与者；局外人不是。
        self.assertTrue(is_active_participant(self.task, self.assignee))
        self.assertTrue(is_active_participant(self.task, self.collaborator))
        self.assertFalse(is_active_participant(self.task, self.outsider))

    def test_is_active_participant_only_in_progress(self):
        # 流转出 in_progress 后，即便曾是负责人/协作者也不再活跃。
        self.task.status = "reviewing"
        self.assertFalse(is_active_participant(self.task, self.assignee))
        self.assertFalse(is_active_participant(self.task, self.collaborator))

    def test_can_manage_via_president_group(self):
        self.assertTrue(can_manage(self.president))
        self.assertFalse(can_manage(self.assignee))

    def test_can_assign_via_president_group(self):
        self.assertTrue(can_assign(self.president))
        self.assertFalse(can_assign(self.assignee))


class AvailableActionsTest(TestCase):
    """``available_actions`` 的「状态 × 角色 × 动作」矩阵。"""

    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="x")
        self.assignee = User.objects.create_user(username="assignee", password="x")
        self.collaborator = User.objects.create_user(username="collab", password="x")
        self.outsider = User.objects.create_user(username="other", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))

    def _task(self, *, status="pending", assignee=None):
        task = Task.objects.create(title="t", creator=self.creator, status=status, assignee=assignee)
        return task

    # ---- complete（提交验收）—— 本切片的核心行为变更 ----

    def test_complete_available_to_assignee_in_progress(self):
        task = self._task(status="in_progress", assignee=self.assignee)
        self.assertIn(COMPLETE, available_actions(task, self.assignee))

    def test_complete_available_to_collaborator_in_progress(self):
        # 行为变更：协作者属于活跃参与者，也能提交验收（此前被静默排除）。
        task = self._task(status="in_progress")
        task.collaborators.add(self.collaborator)
        self.assertIn(COMPLETE, available_actions(task, self.collaborator))

    def test_complete_unavailable_to_non_active_participant(self):
        task = self._task(status="in_progress", assignee=self.assignee)
        self.assertNotIn(COMPLETE, available_actions(task, self.outsider))

    def test_complete_available_to_manager_even_when_not_participant(self):
        task = self._task(status="in_progress", assignee=self.assignee)
        self.assertIn(COMPLETE, available_actions(task, self.president))

    def test_complete_only_in_progress(self):
        task = self._task(status="reviewing", assignee=self.assignee)
        self.assertNotIn(COMPLETE, available_actions(task, self.assignee))

    # ---- approve / reject completion（通过 / 打回验收）----

    def test_completion_review_available_to_creator_in_reviewing(self):
        task = self._task(status="reviewing")
        actions = available_actions(task, self.creator)
        self.assertIn(APPROVE_COMPLETION, actions)
        self.assertIn(REJECT_COMPLETION, actions)

    def test_completion_review_unavailable_to_assignee(self):
        task = self._task(status="reviewing", assignee=self.assignee)
        actions = available_actions(task, self.assignee)
        self.assertNotIn(APPROVE_COMPLETION, actions)
        self.assertNotIn(REJECT_COMPLETION, actions)

    def test_completion_review_only_in_reviewing(self):
        task = self._task(status="in_progress")
        self.assertNotIn(APPROVE_COMPLETION, available_actions(task, self.creator))

    # ---- cancel（取消）----

    def test_cancel_available_to_creator_when_open(self):
        task = self._task(status="in_progress")
        self.assertIn(CANCEL, available_actions(task, self.creator))

    def test_cancel_unavailable_in_terminal_states(self):
        for terminal in ("completed", "cancelled"):
            task = self._task(status=terminal)
            self.assertNotIn(CANCEL, available_actions(task, self.creator), terminal)

    def test_cancel_unavailable_to_outsider(self):
        task = self._task(status="in_progress")
        self.assertNotIn(CANCEL, available_actions(task, self.outsider))

    # ---- assign（指派，独立于状态）----

    def test_assign_available_to_assigner_in_any_state(self):
        for state in ("pending", "in_progress", "reviewing", "completed"):
            task = self._task(status=state)
            self.assertIn(ASSIGN, available_actions(task, self.president), state)

    def test_assign_unavailable_to_non_assigner(self):
        task = self._task(status="pending")
        self.assertNotIn(ASSIGN, available_actions(task, self.creator))

    # ---- claim（申请认领）+ approve / reject claim（审批认领）----

    def test_claim_available_to_non_creator_when_open(self):
        task = self._task(status="pending")  # 无负责人
        self.assertIn(CLAIM, available_actions(task, self.outsider))

    def test_claim_unavailable_to_creator(self):
        # 创建者不认领自己的任务。
        task = self._task(status="pending")
        self.assertNotIn(CLAIM, available_actions(task, self.creator))

    def test_claim_unavailable_when_task_has_assignee(self):
        task = self._task(status="pending", assignee=self.assignee)
        self.assertNotIn(CLAIM, available_actions(task, self.outsider))

    def test_claim_available_in_review_for_latecomers(self):
        # 认领审核中，其他成员仍可追加申请。
        task = self._task(status="review")
        self.assertIn(CLAIM, available_actions(task, self.outsider))

    def test_claim_only_in_pending_or_review(self):
        for state in ("in_progress", "reviewing", "completed"):
            task = self._task(status=state)
            self.assertNotIn(CLAIM, available_actions(task, self.outsider), state)

    def test_claim_review_available_to_creator_in_review(self):
        task = self._task(status="review")
        actions = available_actions(task, self.creator)
        self.assertIn(APPROVE_CLAIM, actions)
        self.assertIn(REJECT_CLAIM, actions)

    def test_claim_review_unavailable_to_outsider(self):
        task = self._task(status="review")
        actions = available_actions(task, self.outsider)
        self.assertNotIn(APPROVE_CLAIM, actions)
        self.assertNotIn(REJECT_CLAIM, actions)

    def test_claim_review_only_in_review(self):
        task = self._task(status="pending")
        self.assertNotIn(APPROVE_CLAIM, available_actions(task, self.creator))


class ApplyTransitionTest(TestCase):
    """``apply`` 执行状态转移 + 副作用；非法调用被拒并带原因。"""

    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="x")
        self.assignee = User.objects.create_user(username="assignee", password="x")
        self.collaborator = User.objects.create_user(username="collab", password="x")
        self.outsider = User.objects.create_user(username="other", password="x")
        self.president = make_president(User.objects.create_user(username="pres", password="x"))

    def _task(self, **kwargs):
        defaults = dict(title="t", creator=self.creator)
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    # ---- complete（提交验收）----

    def test_complete_by_assignee_moves_to_reviewing_and_clears_reason(self):
        task = self._task(status="in_progress", assignee=self.assignee, reject_reason="旧理由")
        result = apply(COMPLETE, task, self.assignee)
        self.assertTrue(result.ok)
        self.assertIsInstance(result, TransitionResult)
        task.refresh_from_db()
        self.assertEqual(task.status, "reviewing")
        self.assertEqual(task.reject_reason, "")

    def test_complete_by_collaborator(self):
        # 行为变更：协作者（活跃参与者）也能提交验收。
        task = self._task(status="in_progress")
        task.collaborators.add(self.collaborator)
        result = apply(COMPLETE, task, self.collaborator)
        self.assertTrue(result.ok)
        self.assertEqual(Task.objects.get(pk=task.pk).status, "reviewing")

    def test_complete_rejected_for_non_active_participant(self):
        # 反向用例：非活跃参与者被拒，状态不变。
        task = self._task(status="in_progress", assignee=self.assignee)
        result = apply(COMPLETE, task, self.outsider)
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.reason)
        self.assertEqual(Task.objects.get(pk=task.pk).status, "in_progress")

    # ---- approve / reject completion（通过 / 打回验收）----

    def test_approve_completion_by_creator(self):
        task = self._task(status="reviewing")
        result = apply(APPROVE_COMPLETION, task, self.creator)
        self.assertTrue(result.ok)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNotNone(task.completed_at)

    def test_reject_completion_requires_reason(self):
        task = self._task(status="reviewing")
        result = apply(REJECT_COMPLETION, task, self.creator, payload={})
        self.assertFalse(result.ok)
        self.assertIn("理由", result.reason)
        self.assertEqual(Task.objects.get(pk=task.pk).status, "reviewing")

    def test_reject_completion_with_reason_keeps_assignee(self):
        task = self._task(status="reviewing", assignee=self.assignee)
        result = apply(REJECT_COMPLETION, task, self.creator, payload={"reason": "返工"})
        self.assertTrue(result.ok)
        task.refresh_from_db()
        self.assertEqual(task.status, "in_progress")
        self.assertEqual(task.assignee_id, self.assignee.pk)
        self.assertEqual(task.reject_reason, "返工")

    # ---- cancel（取消）----

    def test_cancel_by_creator(self):
        task = self._task(status="in_progress")
        result = apply(CANCEL, task, self.creator)
        self.assertTrue(result.ok)
        self.assertEqual(Task.objects.get(pk=task.pk).status, "cancelled")

    def test_cancel_rejected_in_terminal_state(self):
        task = self._task(status="completed")
        result = apply(CANCEL, task, self.creator)
        self.assertFalse(result.ok)

    # ---- assign（指派，社长）----

    def test_assign_sets_assignee_and_in_progress(self):
        task = self._task(status="pending")
        result = apply(ASSIGN, task, self.president, payload={"assignee_id": self.assignee.pk})
        self.assertTrue(result.ok)
        task.refresh_from_db()
        self.assertEqual(task.assignee_id, self.assignee.pk)
        self.assertEqual(task.status, "in_progress")

    def test_assign_clears_assignee_back_to_pending(self):
        task = self._task(status="in_progress", assignee=self.assignee)
        result = apply(ASSIGN, task, self.president, payload={"assignee_id": None})
        self.assertTrue(result.ok)
        task.refresh_from_db()
        self.assertIsNone(task.assignee_id)
        self.assertEqual(task.status, "pending")

    def test_assign_rejected_without_permission(self):
        task = self._task(status="pending")
        result = apply(ASSIGN, task, self.creator, payload={"assignee_id": self.assignee.pk})
        self.assertFalse(result.ok)

    # ---- claim（申请认领）+ approve / reject claim（审批认领）----

    def test_claim_first_creates_request_and_moves_to_review(self):
        task = self._task(status="pending")
        result = apply(CLAIM, task, self.outsider, payload={"reason": "我能做"})
        self.assertTrue(result.ok)
        self.assertEqual(result.claim.claimant_id, self.outsider.pk)  # 结果携带新建的认领申请
        task.refresh_from_db()
        self.assertEqual(task.status, "review")
        self.assertTrue(
            TaskClaimRequest.objects.filter(task=task, claimant=self.outsider, status="pending").exists()
        )

    def test_claim_in_review_stays_review(self):
        # 已在认领审核中：后来者仍可追加，状态不变。
        task = self._task(status="review")
        result = apply(CLAIM, task, self.outsider)
        self.assertTrue(result.ok)
        self.assertEqual(Task.objects.get(pk=task.pk).status, "review")

    def test_claim_duplicate_rejected(self):
        task = self._task(status="review")
        apply(CLAIM, task, self.outsider)
        result = apply(CLAIM, task, self.outsider)
        self.assertFalse(result.ok)
        self.assertIn("申请过", result.reason)

    def test_approve_claim_assigns_and_moves_to_in_progress(self):
        task = self._task(status="review")
        claim = TaskClaimRequest.objects.create(task=task, claimant=self.outsider)
        result = apply(APPROVE_CLAIM, task, self.creator, payload={"claim_id": claim.pk})
        self.assertTrue(result.ok)
        task.refresh_from_db()
        self.assertEqual(task.assignee_id, self.outsider.pk)
        self.assertEqual(task.status, "in_progress")
        claim.refresh_from_db()
        self.assertEqual(claim.status, "approved")
        self.assertEqual(claim.moderated_by_id, self.creator.pk)

    def test_approve_claim_unknown_claim_rejected(self):
        task = self._task(status="review")
        result = apply(APPROVE_CLAIM, task, self.creator, payload={"claim_id": 999999})
        self.assertFalse(result.ok)
        self.assertIn("不存在", result.reason)

    def test_reject_claim_reverts_to_pending_when_no_pending_left(self):
        task = self._task(status="review")
        claim = TaskClaimRequest.objects.create(task=task, claimant=self.outsider)
        result = apply(REJECT_CLAIM, task, self.creator, payload={"claim_id": claim.pk})
        self.assertTrue(result.ok)
        task.refresh_from_db()
        self.assertEqual(task.status, "pending")
        claim.refresh_from_db()
        self.assertEqual(claim.status, "rejected")

    def test_reject_claim_keeps_review_when_other_pending_remains(self):
        task = self._task(status="review")
        claim_a = TaskClaimRequest.objects.create(task=task, claimant=self.outsider)
        TaskClaimRequest.objects.create(task=task, claimant=self.collaborator)
        result = apply(REJECT_CLAIM, task, self.creator, payload={"claim_id": claim_a.pk})
        self.assertTrue(result.ok)
        self.assertEqual(Task.objects.get(pk=task.pk).status, "review")  # 仍有待审认领，不回退

    # ---- 拒绝类别 kind（供 HTTP 层映射 403/400/404）----

    def test_complete_by_non_participant_is_forbidden(self):
        task = self._task(status="in_progress", assignee=self.assignee)
        self.assertEqual(apply(COMPLETE, task, self.outsider).kind, KIND_FORBIDDEN)

    def test_complete_in_wrong_state_is_bad_request(self):
        # 状态不对（非进行中）优先于权限判定 → bad_request。
        task = self._task(status="reviewing", assignee=self.assignee)
        self.assertEqual(apply(COMPLETE, task, self.assignee).kind, KIND_BAD_REQUEST)

    def test_approve_completion_by_assignee_is_forbidden(self):
        task = self._task(status="reviewing", assignee=self.assignee)
        self.assertEqual(apply(APPROVE_COMPLETION, task, self.assignee).kind, KIND_FORBIDDEN)

    def test_approve_claim_missing_claim_is_not_found(self):
        task = self._task(status="review")
        result = apply(APPROVE_CLAIM, task, self.creator, payload={"claim_id": 999999})
        self.assertEqual(result.kind, KIND_NOT_FOUND)

    def test_reject_completion_without_reason_is_bad_request(self):
        task = self._task(status="reviewing")
        result = apply(REJECT_COMPLETION, task, self.creator, payload={})
        self.assertEqual(result.kind, KIND_BAD_REQUEST)


class AssigneeLinkageTest(TestCase):
    """负责人↔状态联动：任务创建与指派共用的单一判定。"""

    def test_status_for_assignee(self):
        user = User.objects.create_user(username="u", password="x")
        self.assertEqual(status_for_assignee(user), "in_progress")
        self.assertEqual(status_for_assignee(None), "pending")
