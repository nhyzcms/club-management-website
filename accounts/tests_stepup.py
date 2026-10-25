"""安全验证（Step-up，ADR-0026）：方式 / 令牌 / 受保护端点 / Bootstrap。

覆盖：邮箱验证码（可用性 / 发送 / 冷却 / 节流 / 校验 / 一次性 / 限试 / 过期）、
安全问题（设置 / 首设密码确认 / 更换需 grant / 归一化 / 连错锁定）、
grant（有效 / 跨 scope / 篡改 / 过期）、受保护端点（改密码 / 换绑邮箱 / 问答管理的
403 契约与放行）、审计事件。
"""
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from accounts import stepup
from accounts.models import Profile, SecurityQuestion, StepUpEmailCode, StepUpEvent


def make_user(username="u1", email_ok=True):
    user = User.objects.create_user(username=username, password="StrongPass123!", email="")
    Profile.objects.create(user=user, real_name="测试用户")
    if email_ok:
        user.email = f"{username}@example.test"  # User.email 只装已认证邮箱
        user.save(update_fields=["email"])
    return user


def extract_code(body: str) -> str:
    return re.search(r"验证码是：(\d{6})", body).group(1)


class EmailCodeTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def test_send_requires_certified_email(self):
        u = make_user("nomail", email_ok=False)
        with self.assertRaises(stepup.StepUpError):
            stepup.send_email_code(u)

    def test_send_creates_code_mails_and_cooldown(self):
        row = stepup.send_email_code(self.user)
        self.assertEqual(row.sent_to, self.user.email)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("安全验证码", mail.outbox[0].subject)
        self.assertGreater(stepup.email_cooldown_remaining(self.user), 0)

    def test_new_send_invalidates_previous(self):
        row1 = stepup.send_email_code(self.user)
        stepup.send_email_code(self.user)
        row1.refresh_from_db()
        self.assertIsNotNone(row1.used_at)

    def test_send_then_verify_roundtrip(self):
        stepup.send_email_code(self.user)
        code = extract_code(mail.outbox[0].body)
        stepup.verify_email_code(self.user, code)
        row = StepUpEmailCode.objects.get(user=self.user)
        self.assertIsNotNone(row.used_at)

    def test_code_is_one_time(self):
        stepup.send_email_code(self.user)
        code = extract_code(mail.outbox[0].body)
        stepup.verify_email_code(self.user, code)
        with self.assertRaises(stepup.StepUpError):
            stepup.verify_email_code(self.user, code)

    def test_wrong_code_counts_attempts_and_blocks_after_five(self):
        stepup.send_email_code(self.user)
        for _ in range(5):
            with self.assertRaises(stepup.StepUpError):
                stepup.verify_email_code(self.user, "000000")
        row = StepUpEmailCode.objects.get(user=self.user)
        self.assertEqual(row.attempts, 5)
        with self.assertRaises(stepup.StepUpError):
            stepup.verify_email_code(self.user, "000000")

    def test_expired_code_rejected(self):
        StepUpEmailCode.objects.create(
            user=self.user, code_hash=make_password("123456"), sent_to=self.user.email,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(stepup.StepUpError):
            stepup.verify_email_code(self.user, "123456")


class QuestionTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def test_set_and_check_normalized_answer(self):
        stepup.set_security_questions(self.user, [
            {"key": "primary_school", "answer": "ＮａｎＨｕｉ　First  School"},
        ])
        q = self.user.security_questions.get()
        stepup.check_security_answer(self.user, q.id, "nanhui first school")

    def test_set_validation(self):
        with self.assertRaises(stepup.StepUpError):
            stepup.set_security_questions(self.user, [{"key": "nope", "answer": "x"}])
        with self.assertRaises(stepup.StepUpError):
            stepup.set_security_questions(self.user, [{"key": "primary_school", "answer": "  "}])
        with self.assertRaises(stepup.StepUpError):
            stepup.set_security_questions(self.user, [
                {"key": "primary_school", "answer": "a"},
                {"key": "favorite_book", "answer": "b"},
                {"key": "favorite_song", "answer": "c"},
                {"key": "birth_city", "answer": "d"},
            ])

    def test_replace_and_clear(self):
        stepup.set_security_questions(self.user, [{"key": "primary_school", "answer": "a"}])
        stepup.set_security_questions(self.user, [{"key": "favorite_book", "answer": "b"}])
        self.assertEqual(self.user.security_questions.count(), 1)
        stepup.set_security_questions(self.user, [])
        self.assertEqual(self.user.security_questions.count(), 0)

    def test_wrong_answer_locks_after_five(self):
        stepup.set_security_questions(self.user, [{"key": "primary_school", "answer": "right"}])
        q = self.user.security_questions.get()
        for _ in range(5):
            with self.assertRaises(stepup.StepUpError):
                stepup.check_security_answer(self.user, q.id, "wrong")
        with self.assertRaises(stepup.StepUpError):
            stepup.check_security_answer(self.user, q.id, "right")  # 已锁


class GrantTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def test_roundtrip_and_scope(self):
        token = stepup.issue_grant(self.user, "change_password")
        self.assertTrue(stepup.check_grant(self.user, "change_password", token))
        self.assertFalse(stepup.check_grant(self.user, "change_email", token))  # 跨 scope
        self.assertFalse(stepup.check_grant(self.user, "change_password", token + "x"))

    def test_other_user_token_rejected(self):
        other = make_user("u2")
        token = stepup.issue_grant(other, "change_password")
        self.assertFalse(stepup.check_grant(self.user, "change_password", token))

    def test_expired_token_rejected(self):
        token = stepup.issue_grant(self.user, "change_password")
        with mock.patch.object(stepup, "GRANT_TTL_SECONDS", -1):
            self.assertFalse(stepup.check_grant(self.user, "change_password", token))


class StepUpEndpointTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_status_overview(self):
        resp = self.client.get("/auth/stepup/")
        data = resp.json()
        self.assertTrue(data["email"]["available"])
        self.assertNotIn(self.user.email, data["email"]["address"])  # 打码
        self.assertFalse(data["questions"]["configured"])

    def test_email_send_cooldown_and_verify_flow(self):
        resp = self.client.post("/auth/stepup/email/send/")
        self.assertEqual(resp.status_code, 200, resp.content)
        resp2 = self.client.post("/auth/stepup/email/send/")
        self.assertEqual(resp2.status_code, 429)  # 冷却
        code = extract_code(mail.outbox[0].body)
        resp3 = self.client.post(
            "/auth/stepup/verify/",
            data={"method": "email", "scope": "change_password", "code": code},
            content_type="application/json",
        )
        self.assertEqual(resp3.status_code, 200, resp3.content)
        self.assertIn("grant", resp3.json())
        self.assertTrue(StepUpEvent.objects.filter(user=self.user, result="ok").exists())

    def test_email_unavailable_when_no_certified_email(self):
        u = make_user("nomail", email_ok=False)
        self.client.force_login(u)
        resp = self.client.post("/auth/stepup/email/send/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "email_unavailable")

    def test_verify_question_flow(self):
        stepup.set_security_questions(self.user, [{"key": "primary_school", "answer": "南汇"}])
        q = self.user.security_questions.get()
        bad = self.client.post(
            "/auth/stepup/verify/",
            data={"method": "question", "scope": "change_password", "question_id": q.id, "answer": "错"},
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(
            "/auth/stepup/verify/",
            data={"method": "question", "scope": "change_password", "question_id": q.id, "answer": " 南汇 "},
            content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200, ok.content)

    def test_verify_unknown_scope_and_method(self):
        resp = self.client.post(
            "/auth/stepup/verify/",
            data={"method": "email", "scope": "nope", "code": "1"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class ProtectedEndpointTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_change_password_requires_grant(self):
        resp = self.client.post(
            "/auth/profile/change-password/",
            data={"old_password": "StrongPass123!", "new_password": "NewPass12345!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "step_up_required")
        self.assertEqual(resp.json()["scope"], "change_password")

    def test_change_password_with_grant(self):
        grant = stepup.issue_grant(self.user, "change_password")
        resp = self.client.post(
            "/auth/profile/change-password/",
            data={"old_password": "StrongPass123!", "new_password": "NewPass12345!"},
            content_type="application/json",
            HTTP_X_STEPUP_GRANT=grant,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass12345!"))
        # 改密后会话保持（update_session_auth_hash）：当前会话仍可访问
        me = self.client.get("/auth/me/")
        self.assertEqual(me.status_code, 200, me.content)

    def test_change_password_wrong_grant_scope_rejected(self):
        grant = stepup.issue_grant(self.user, "change_email")
        resp = self.client.post(
            "/auth/profile/change-password/",
            data={"old_password": "StrongPass123!", "new_password": "NewPass12345!"},
            content_type="application/json",
            HTTP_X_STEPUP_GRANT=grant,
        )
        self.assertEqual(resp.status_code, 403)

    def test_first_email_bind_no_grant_ok(self):
        u = make_user("fresh", email_ok=False)
        self.client.force_login(u)
        resp = self.client.post(
            "/auth/verification/email/bind/",
            data={"email": "fresh@qq.com"},
            content_type="application/json",
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_rebind_email_requires_grant(self):
        resp = self.client.post(
            "/auth/verification/email/bind/",
            data={"email": "newaddr@qq.com"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["scope"], "change_email")

    def test_rebind_email_with_grant(self):
        grant = stepup.issue_grant(self.user, "change_email")
        resp = self.client.post(
            "/auth/verification/email/bind/",
            data={"email": "newaddr@qq.com"},
            content_type="application/json",
            HTTP_X_STEPUP_GRANT=grant,
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_questions_first_set_needs_password(self):
        resp = self.client.post(
            "/auth/stepup/questions/",
            data={"items": [{"key": "primary_school", "answer": "x"}]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "password_required")

    def test_questions_first_set_with_password_then_replace_needs_grant(self):
        resp = self.client.post(
            "/auth/stepup/questions/",
            data={"items": [{"key": "primary_school", "answer": "x"}], "password": "StrongPass123!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        # 更换需 grant
        resp2 = self.client.post(
            "/auth/stepup/questions/",
            data={"items": [{"key": "favorite_book", "answer": "y"}]},
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 403)
        self.assertEqual(resp2.json()["scope"], "manage_questions")
        grant = stepup.issue_grant(self.user, "manage_questions")
        resp3 = self.client.post(
            "/auth/stepup/questions/",
            data={"items": [{"key": "favorite_book", "answer": "y"}]},
            content_type="application/json",
            HTTP_X_STEPUP_GRANT=grant,
        )
        self.assertEqual(resp3.status_code, 200, resp3.content)

    def test_events_endpoint(self):
        stepup.record_event(self.user, "change_password", "email", "ok")
        resp = self.client.get("/auth/stepup/events/")
        results = resp.json()["results"]
        self.assertEqual(results[0]["scope_label"], "修改密码")
        self.assertEqual(results[0]["result"], "ok")


class ScopeRegistrationTest(TestCase):
    """安全中心用到的 stepup 作用域必须登记在 ``stepup.SCOPES``。

    2026-10-25 生产故障回归：security_center 引用了 manage_devices / manage_totp，
    但 SCOPES / 前端 labels 都没登记，POST /auth/stepup/verify/ 直接 400
    「未知的验证作用域」，撤销设备与解绑 TOTP 全部不可用。
    """

    def test_all_scopes_used_by_security_center_are_registered(self):
        import re
        from pathlib import Path

        src = (Path(__file__).parent / "security_center.py").read_text(encoding="utf-8")
        used = set(re.findall(r'grant_from_request\(request, "([a-z_]+)"\)', src))
        self.assertTrue(used, "应能从 security_center.py 解析出作用域")
        missing = used - set(stepup.SCOPES)
        self.assertEqual(missing, set(), f"未登记的作用域：{missing}")
