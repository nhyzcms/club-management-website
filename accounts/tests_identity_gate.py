"""账号认证写门槛（ADR-0006）：桶写操作需账号已认证（任一通道 approved）；只读不受影响。

未认证 = 无 approved Verification 行（访客）；已认证 = 有一条 approved 通道（用户）。

URL 前缀注意：config 把各 app 挂在 `tasks/` `reviews/` `messaging/` 下，各 app 路由器又
注册同名 resource，故为 `/tasks/tasks/`、`/reviews/feedbacks/`、`/messaging/conversations/`。
用 APIClient.force_authenticate（与既有 tests 一致，绕过 CSRF，仍走 DRF 权限链）。
"""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from messaging.models import Conversation
from tasks.models import Task

TASKS = "/tasks/tasks/"
FEEDBACK_SUBMIT = "/reviews/feedbacks/submit/"
REPORTS = "/reviews/reports/"
CONV = "/messaging/conversations/"


def make_unverified(username):
    # 无 Verification 行 ⇒ 未认证（访客）
    return User.objects.create_user(username=username, password="p")


def make_verified(username):
    # approved manual 通道 ⇒ 已认证（用户）
    return grant_verification(User.objects.create_user(username=username, password="p"))


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _post(client, url, payload=None):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json")


class TasksGateTest(TestCase):
    def setUp(self):
        self.tier2 = make_unverified("tier2")
        self.tier3 = make_verified("tier3")
        self.creator = make_verified("creator")
        self.task = Task.objects.create(title="gate-task", creator=self.creator, status="pending")

    def test_tier2_create_task_blocked(self):
        self.assertEqual(_post(_client(self.tier2), TASKS, {"title": "x"}).status_code, 403)

    def test_tier3_create_task_allowed(self):
        # 门槛通过即可（具体校验由序列化器；非 403 即说明 gate 放行）
        self.assertNotEqual(_post(_client(self.tier3), TASKS, {"title": "x"}).status_code, 403)

    def test_tier2_claim_blocked(self):
        self.assertEqual(_post(_client(self.tier2), f"{TASKS}{self.task.id}/claim/").status_code, 403)

    def test_tier3_claim_allowed(self):
        self.assertEqual(_post(_client(self.tier3), f"{TASKS}{self.task.id}/claim/", {"reason": "我能做"}).status_code, 201)

    def test_tier2_cancel_blocked(self):
        self.assertEqual(_post(_client(self.tier2), f"{TASKS}{self.task.id}/cancel/").status_code, 403)

    def test_tier2_read_tasks_unaffected(self):
        self.assertEqual(_client(self.tier2).get(TASKS).status_code, 200)


class MessagingGateTest(TestCase):
    def setUp(self):
        self.tier2 = make_unverified("tier2")
        self.tier3 = make_verified("tier3")
        self.target = make_verified("target")
        # tier3 参与的会话（供 send_message）
        self.conv = Conversation.objects.create()
        self.conv.participants.set([self.tier3, self.target])
        # tier2 参与的会话（验证 send_message 被 gate 挡、mark_read 不被挡）
        self.conv2 = Conversation.objects.create()
        self.conv2.participants.set([self.tier2, self.target])

    def test_tier2_send_message_blocked(self):
        # 即便 tier2 是参与者，身份门槛仍在 has_permission 阶段先于 participant 校验放 403
        resp = _post(_client(self.tier2), f"{CONV}{self.conv2.id}/send_message/", {"content": "hi"})
        self.assertEqual(resp.status_code, 403)

    def test_tier3_send_message_allowed(self):
        resp = _post(_client(self.tier3), f"{CONV}{self.conv.id}/send_message/", {"content": "hi"})
        self.assertEqual(resp.status_code, 201)

    def test_tier2_start_private_blocked(self):
        resp = _post(_client(self.tier2), f"{CONV}start_private/", {"user_id": self.target.id})
        self.assertEqual(resp.status_code, 403)

    def test_tier3_start_private_allowed(self):
        # 已有会话则 200、新建则 201；两者均说明门槛放行
        resp = _post(_client(self.tier3), f"{CONV}start_private/", {"user_id": self.target.id})
        self.assertIn(resp.status_code, (200, 201))

    def test_tier2_mark_read_not_gated(self):
        # mark_read 继承父动作权限，不单独加身份门槛 → tier2（参与者）可标记
        from messaging.models import Message
        Message.objects.create(conversation=self.conv2, sender=self.target, content="hey")
        resp = _post(_client(self.tier2), f"{CONV}{self.conv2.id}/mark_read/")
        self.assertEqual(resp.status_code, 200)

    def test_tier2_list_conversations_unaffected(self):
        self.assertEqual(_client(self.tier2).get(CONV).status_code, 200)

    def test_legacy_task_and_proposal_conversation_actions_gone(self):
        # 任务/申报讨论已拆出会话；身份门槛测试不得再打 get_task_conversation。
        # 动作已从路由器删除：POST 落到 detail pk → 405，GET 则 404。
        c = _client(self.tier3)
        for action in ("get_task_conversation", "get_proposal_conversation"):
            self.assertIn(_post(c, f"{CONV}{action}/", {"task_id": 1}).status_code, (404, 405))
            self.assertEqual(c.get(f"{CONV}{action}/").status_code, 404)


class FeedbackAndReportGateTest(TestCase):
    def setUp(self):
        self.tier2 = make_unverified("tier2")
        self.tier3 = make_verified("tier3")

    def test_submit_feedback_still_anonymous(self):
        c = APIClient()
        resp = _post(c, FEEDBACK_SUBMIT, {"title": "匿名", "description": "...", "category": "suggestion"})
        self.assertEqual(resp.status_code, 201)

    def test_unverified_cannot_file_report(self):
        resp = _post(_client(self.tier2), REPORTS, {
            "target_type": "user", "target_id": self.tier3.id, "reason": "x",
        })
        self.assertEqual(resp.status_code, 403)
