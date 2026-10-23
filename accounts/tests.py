import json
from datetime import timedelta
from django.test import TestCase, Client, RequestFactory, override_settings
from django.contrib.auth.models import Group, User
from django.utils import timezone
from .models import UserSession
from .utils import get_client_ip, parse_user_agent, record_user_session


class LoginViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="secret123",
        )

    def test_login_with_username_success(self):
        response = self.client.post(
            "/auth/login/",
            data=json.dumps({"username": "testuser", "password": "secret123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user"]["username"], "testuser")
        self.assertEqual(data["user"]["email"], "test@example.com")

    def test_login_with_email_success(self):
        response = self.client.post(
            "/auth/login/",
            data=json.dumps({"email": "test@example.com", "password": "secret123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user"]["username"], "testuser")

    def test_login_wrong_password(self):
        response = self.client.post(
            "/auth/login/",
            data=json.dumps({"username": "testuser", "password": "wrong"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    def test_login_missing_fields(self):
        response = self.client.post(
            "/auth/login/",
            data=json.dumps({"username": "testuser"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class CsrfCookieViewTest(TestCase):
    """GET /auth/csrf/ 显式下发 csrftoken cookie。

    生产环境由 Django 渲染 dist/index.html（含 {% csrf_token %}）下发 cookie；
    但开发态 webpack 直接服务模板，{% csrf_token %} 只是字面文本、不会下发 cookie，
    导致全新访客 POST /auth/login/ 收到 403。此端点把 cookie 下发与 HTML 渲染解耦。
    """

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="secret123")

    def test_csrf_endpoint_sets_cookie(self):
        c = Client(enforce_csrf_checks=True)
        response = c.get("/auth/csrf/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)

    def test_login_after_csrf_prime_does_not_403(self):
        # enforce_csrf_checks=True 复现真实浏览器：无 csrftoken cookie 时 POST 会被 403
        c = Client(enforce_csrf_checks=True)
        c.get("/auth/csrf/")  # 显式下发 cookie
        token_cookie = c.cookies.get("csrftoken")
        token = token_cookie.value if token_cookie else ""
        response = c.post(
            "/auth/login/",
            data=json.dumps({"username": "testuser", "password": "secret123"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 200)


class LogoutViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="secret123")

    def test_logout_success(self):
        self.client.login(username="testuser", password="secret123")
        response = self.client.post("/auth/logout/")
        self.assertEqual(response.status_code, 200)

    def test_logout_unauthenticated(self):
        response = self.client.post("/auth/logout/")
        self.assertEqual(response.status_code, 302)

    def test_logout_clears_current_session_row(self):
        self.client.login(username="testuser", password="secret123")
        self.assertTrue(UserSession.objects.filter(user=self.user, is_current=True).exists())
        self.client.post("/auth/logout/")
        self.assertFalse(UserSession.objects.filter(user=self.user, is_current=True).exists())


class MeViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="secret123",
        )

    def test_me_authenticated(self):
        self.client.login(username="testuser", password="secret123")
        response = self.client.get("/auth/me/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user"]["username"], "testuser")

    def test_me_unauthenticated(self):
        response = self.client.get("/auth/me/")
        self.assertEqual(response.status_code, 302)

    def test_me_permissions_all_false_for_normal_user(self):
        self.client.login(username="testuser", password="secret123")
        perms = self.client.get("/auth/me/").json()["user"]["permissions"]
        self.assertFalse(any(perms.values()))

    def test_me_permissions_for_info_group(self):
        from django.contrib.auth.models import Group
        grp, _ = Group.objects.get_or_create(name="信息组")
        self.user.groups.add(grp)
        self.client.login(username="testuser", password="secret123")
        perms = self.client.get("/auth/me/").json()["user"]["permissions"]
        self.assertTrue(perms["can_manage_news"])
        self.assertFalse(perms["can_manage_tasks"])
        self.assertTrue(perms["can_manage_announcement"])
        self.assertTrue(perms["can_manage_announcements"])
        self.assertFalse(perms["can_mute_user"])
        self.assertFalse(perms["can_manage_comment_thread"])

    def test_me_permissions_for_president(self):
        from django.contrib.auth.models import Group
        grp, _ = Group.objects.get_or_create(name="社长")
        self.user.groups.add(grp)
        self.client.login(username="testuser", password="secret123")
        perms = self.client.get("/auth/me/").json()["user"]["permissions"]
        self.assertTrue(perms["can_manage_tasks"])
        self.assertTrue(perms["can_view_feedback"])
        self.assertTrue(perms["can_handle_reports"])
        self.assertFalse(perms["can_manage_news"])
        self.assertTrue(perms["can_manage_comment_thread"])
        self.assertTrue(perms["can_mute_user"])
        self.assertFalse(perms["can_manage_announcement"])

    def test_can_change_activity_decoupled_from_president_seed(self):
        # 活动管理门禁与社长种子包解耦——社长无 manage_activity，故看不到他人活动编辑按钮。
        from django.contrib.auth.models import Group
        grp, _ = Group.objects.get_or_create(name="社长")
        self.user.groups.add(grp)
        self.client.login(username="testuser", password="secret123")
        perms = self.client.get("/auth/me/").json()["user"]["permissions"]
        self.assertIn("can_change_activity", perms)
        self.assertFalse(perms["can_change_activity"])

    def test_can_change_activity_true_when_perm_held(self):
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(content_type__app_label="activities", codename="manage_activity")
        self.user.user_permissions.add(perm)
        self.client.login(username="testuser", password="secret123")
        perms = self.client.get("/auth/me/").json()["user"]["permissions"]
        self.assertTrue(perms["can_change_activity"])


class PasswordResetViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldsecret123",
        )

    def test_password_reset_success(self):
        response = self.client.post(
            "/auth/password-reset/",
            data=json.dumps({"email": "test@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())

    def test_password_reset_unknown_email(self):
        response = self.client.post(
            "/auth/password-reset/",
            data=json.dumps({"email": "unknown@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())

    def test_password_reset_missing_email(self):
        response = self.client.post(
            "/auth/password-reset/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    def test_password_reset_rejected_without_turnstile_when_enabled(self):
        response = self.client.post(
            "/auth/password-reset/",
            data=json.dumps({"email": "test@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("人机校验", str(response.json()["error"]))


class PasswordResetConfirmViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldsecret123",
        )

    def _get_reset_token(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        return uid, token

    def test_password_reset_confirm_success(self):
        uid, token = self._get_reset_token()
        response = self.client.post(
            "/auth/password-reset/confirm/",
            data=json.dumps({
                "uid": uid,
                "token": token,
                "new_password": "newsecret456",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            self.client.login(username="testuser", password="newsecret456")
        )

    def test_password_reset_confirm_invalid_token(self):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.post(
            "/auth/password-reset/confirm/",
            data=json.dumps({
                "uid": uid,
                "token": "invalid-token",
                "new_password": "newsecret456",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_password_reset_confirm_missing_fields(self):
        response = self.client.post(
            "/auth/password-reset/confirm/",
            data=json.dumps({"uid": "MQ"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class UserSessionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")

    def test_create_session_defaults(self):
        s = UserSession.objects.create(user=self.user, session_key="abc")
        self.assertTrue(s.is_current)
        self.assertEqual(s.device_type, "Unknown")
        self.assertEqual(s.device_name, "")

    def test_str_contains_username(self):
        s = UserSession.objects.create(user=self.user, session_key="abcdef0123456789")
        self.assertIn("u", str(s))


class ParseUserAgentTest(TestCase):
    def test_desktop_chrome_windows(self):
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        dtype, dname = parse_user_agent(ua)
        self.assertEqual(dtype, "Desktop")
        self.assertIn("Chrome", dname)
        self.assertIn("Windows", dname)

    def test_mobile_iphone(self):
        ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1")
        dtype, dname = parse_user_agent(ua)
        self.assertEqual(dtype, "Mobile")
        self.assertIn("iOS", dname)

    def test_tablet_ipad(self):
        ua = ("Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
        dtype, _ = parse_user_agent(ua)
        self.assertEqual(dtype, "Tablet")

    def test_bot(self):
        dtype, _ = parse_user_agent("Mozilla/5.0 (compatible; Googlebot/2.1; +http://google.com/bot.html)")
        self.assertEqual(dtype, "Bot")

    def test_empty(self):
        self.assertEqual(parse_user_agent(""), ("Unknown", ""))


class GetClientIpTest(TestCase):
    def test_remote_addr(self):
        req = RequestFactory().get("/", REMOTE_ADDR="1.2.3.4")
        self.assertEqual(get_client_ip(req), "1.2.3.4")


class RecordUserSessionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="u", password="p")

    def _req(self):
        return self.factory.get(
            "/",
            REMOTE_ADDR="9.9.9.9",
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
        )

    def test_creates_current_row(self):
        record_user_session(self._req(), self.user, "keyA")
        s = UserSession.objects.get(session_key="keyA")
        self.assertTrue(s.is_current)
        self.assertEqual(s.ip_address, "9.9.9.9")
        self.assertEqual(s.device_type, "Desktop")

    def test_second_login_supersedes_first(self):
        record_user_session(self._req(), self.user, "keyA")
        record_user_session(self._req(), self.user, "keyB")
        # 历史保留：两行都在；is_current 仅 keyB
        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 2)
        current = UserSession.objects.get(user=self.user, is_current=True)
        self.assertEqual(current.session_key, "keyB")

    def test_same_key_updates_in_place(self):
        record_user_session(self._req(), self.user, "keyA")
        record_user_session(self._req(), self.user, "keyA")
        self.assertEqual(UserSession.objects.filter(session_key="keyA").count(), 1)
        self.assertTrue(UserSession.objects.get(session_key="keyA").is_current)

    def test_history_pruned_to_limit(self):
        # 制造 25 次登录：保留最近 20 条，最旧的被裁掉
        for i in range(25):
            record_user_session(self._req(), self.user, f"key{i:02d}")
        rows = list(UserSession.objects.filter(user=self.user).order_by("created_at", "id"))
        self.assertEqual(len(rows), 20, "应精确裁剪到 20 条")  # 改为精确断言确保失败
        # 当前会话（最后一次 key24）必在保留之列且为 current
        current = UserSession.objects.get(user=self.user, is_current=True)
        self.assertEqual(current.session_key, "key24")
        self.assertIn(current.id, [r.id for r in rows]) # type: ignore


class LoginSignalIntegrationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", email="u@e.com", password="secret123")

    def test_login_creates_user_session(self):
        c = Client()
        c.login(username="u", password="secret123")
        s = UserSession.objects.get(user=self.user)
        self.assertTrue(s.is_current)
        self.assertTrue(s.session_key)

    def test_login_records_device_info(self):
        c = Client()
        c.post(
            "/auth/login/",
            data=json.dumps({"username": "u", "password": "secret123"}),
            content_type="application/json",
            REMOTE_ADDR="1.2.3.4",
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
        )
        s = UserSession.objects.get(user=self.user)
        self.assertEqual(s.ip_address, "1.2.3.4")
        self.assertEqual(s.device_type, "Desktop")
        self.assertIn("Chrome", s.device_name)

    def test_second_device_login_leaves_single_current_row(self):
        a = Client()
        a.login(username="u", password="secret123")
        b = Client()
        b.login(username="u", password="secret123")
        self.assertEqual(UserSession.objects.filter(user=self.user, is_current=True).count(), 1)


class SingleSessionMiddlewareTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", email="u@e.com", password="secret123")

    def _login(self):
        c = Client()
        c.login(username="u", password="secret123")
        return c

    def test_first_device_can_access(self):
        a = self._login()
        self.assertEqual(a.get("/auth/me/").status_code, 200)

    def test_superseded_device_gets_401_with_takeover(self):
        a = self._login()
        # 老化 a 的当前会话到保护期外（≥10 分钟），b 才能挤号
        UserSession.objects.filter(user=self.user, is_current=True).update(
            created_at=timezone.now() - timedelta(minutes=11)
        )
        b = Client()
        b.post(
            "/auth/login/",
            data=json.dumps({"username": "u", "password": "secret123"}),
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari",
        )
        resp = a.get("/auth/me/")
        # 契约（#10）：被挤设备得到 401 + reason + takeover 四字段。前端适配器据此
        # 映射成类型化「会话被挤下线」结果，故此处把响应形状钉死。
        data = resp.json()
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(data["reason"], "session_superseded")
        takeover = data["takeover"]
        self.assertIsInstance(takeover, dict)
        # takeover 恰含四字段（前端 SessionSupersedeModal 直接消费）；ip 可为 null。
        self.assertEqual(set(takeover.keys()), {"device_name", "device_type", "ip", "time"})
        self.assertEqual(takeover["device_type"], "Mobile")
        self.assertIn("iOS", takeover["device_name"])
        self.assertIsInstance(takeover["time"], str)

    def test_superseded_browser_navigation_gets_html_page(self):
        # 浏览器导航（Accept 含 text/html）→ 渲染 HTML 下线页（而非裸 JSON）
        a = self._login()
        UserSession.objects.filter(user=self.user, is_current=True).update(
            created_at=timezone.now() - timedelta(minutes=11)
        )
        b = Client()
        b.post(
            "/auth/login/",
            data=json.dumps({"username": "u", "password": "secret123"}),
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari",
        )
        resp = a.get(
            "/auth/me/",
            HTTP_ACCEPT="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("text/html", resp["Content-Type"])
        html = resp.content.decode()
        self.assertIn("您已被迫下线", html)
        self.assertIn("Mobile", html)  # 接管设备信息展示在页面上（来自 b 的 UA）
        self.assertIn("重新登录", html)

    def test_superseded_api_request_keeps_json_contract(self):
        # Accept 不含 text/html（SPA fetch 默认 */*）→ 保持既有 JSON 契约（#10）
        a = self._login()
        UserSession.objects.filter(user=self.user, is_current=True).update(
            created_at=timezone.now() - timedelta(minutes=11)
        )
        b = Client()
        b.post(
            "/auth/login/",
            data=json.dumps({"username": "u", "password": "secret123"}),
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari",
        )
        resp = a.get("/auth/me/", HTTP_ACCEPT="*/*")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["reason"], "session_superseded")

    def test_new_device_can_access_after_takeover(self):
        a = self._login()
        b = self._login()
        self.assertEqual(b.get("/auth/me/").status_code, 200)

    def test_anonymous_request_passes_through(self):
        # /auth/me/ is login_required → anonymous gets 302, not a 500 from the middleware
        self.assertEqual(Client().get("/auth/me/").status_code, 302)

    def test_pre_feature_session_is_adopted(self):
        a = self._login()
        UserSession.objects.all().delete()  # simulate a session that predates this feature
        self.assertEqual(a.get("/auth/me/").status_code, 200)
        self.assertTrue(UserSession.objects.filter(user=self.user, is_current=True).exists())


class CrossUserReloginTest(TestCase):
    def test_second_user_login_on_same_session_records_row(self):
        # Same Client (same cookie jar) simulates one browser where user A didn't log out
        # before user B signs in. Django's login() takes the flush() branch here.
        User.objects.create_user(username="aaa", password="secret123")
        User.objects.create_user(username="bbb", password="secret123")
        c = Client()
        c.login(username="aaa", password="secret123")
        # Now sign in as bbb on the SAME client (no logout in between):
        c.login(username="bbb", password="secret123")
        bbb = User.objects.get(username="bbb")
        # B must have a current UserSession row:
        self.assertTrue(
            UserSession.objects.filter(user=bbb, is_current=True).exists(),
            "second-user login on a shared session did not record a UserSession row",
        )
        # And B must be able to access an authenticated view (not kicked):
        self.assertEqual(c.get("/auth/me/").status_code, 200)


class LoginProtectionTest(TestCase):
    """10 分钟登录保护：登录后 10 分钟内，他方新会话登录该账号被拒绝。"""
    def setUp(self):
        self.user = User.objects.create_user(username="u", email="u@e.com", password="secret123")

    def _post_login(self, client, **extra):
        return client.post(
            "/auth/login/",
            data=json.dumps({"username": "u", "password": "secret123"}),
            content_type="application/json",
            **extra,
        )

    def test_second_login_within_window_is_blocked(self):
        a = Client()
        a.login(username="u", password="secret123")  # 建立当前会话（age≈0）
        b = Client()
        resp = self._post_login(b)
        # 契约（#10）：保护期登录被拒 409 + reason + retry_after（数值，秒）。
        # 注：本契约为 409（Conflict），非 401——后端语义自始如此，此处钉死
        # （与挤号的 401 区分：挤号是「你已被顶下线」，保护期是「他方刚登录、暂拒」）。
        data = resp.json()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(data["reason"], "login_protection")
        self.assertIsInstance(data["retry_after"], int)
        self.assertGreater(data["retry_after"], 0)
        self.assertLessEqual(data["retry_after"], 600)
        # a 仍是当前会话、可继续访问
        self.assertEqual(UserSession.objects.filter(user=self.user, is_current=True).count(), 1)
        self.assertEqual(a.get("/auth/me/").status_code, 200)

    def test_second_login_after_window_is_allowed(self):
        a = Client()
        a.login(username="u", password="secret123")
        UserSession.objects.filter(user=self.user, is_current=True).update(
            created_at=timezone.now() - timedelta(minutes=11)
        )
        b = Client()
        resp = self._post_login(b)
        self.assertEqual(resp.status_code, 200)
        # a 现已被挤下线
        self.assertEqual(a.get("/auth/me/").status_code, 401)

    def test_logout_releases_protection(self):
        a = Client()
        a.login(username="u", password="secret123")
        a.post("/auth/logout/")  # 主动登出 → 清 is_current（依赖 Task 2）
        b = Client()
        resp = self._post_login(b)
        self.assertEqual(resp.status_code, 200)

    def test_same_session_reauth_is_exempt(self):
        c = Client()
        c.login(username="u", password="secret123")  # 当前会话 = c 的 session_key
        # 同一 client（同一 session_key）再次提交登录 → 不拦截
        resp = self._post_login(c)
        self.assertEqual(resp.status_code, 200)

    def test_wrong_password_not_treated_as_protection(self):
        a = Client()
        a.login(username="u", password="secret123")
        b = Client()
        resp = b.post(
            "/auth/login/",
            data=json.dumps({"username": "u", "password": "wrong"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertNotEqual(resp.json().get("reason"), "login_protection")


class SessionsViewTest(TestCase):
    """GET /auth/sessions/：返回本人最近 20 条登录记录（按时间倒序，含 is_current）。"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="secret123",
        )

    def _login(self):
        c = Client()
        c.post(
            "/auth/login/",
            data=json.dumps({"username": "testuser", "password": "secret123"}),
            content_type="application/json",
            REMOTE_ADDR="5.6.7.8",
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
        )
        return c

    def test_requires_login(self):
        resp = Client().get("/auth/sessions/")
        self.assertEqual(resp.status_code, 302)

    def test_response_shape_and_device_info(self):
        c = self._login()
        row = c.get("/auth/sessions/").json()["results"][0]
        for key in ("id", "device_name", "device_type", "ip_address", "created_at", "is_current"):
            self.assertIn(key, row)
        self.assertEqual(row["ip_address"], "5.6.7.8")
        self.assertEqual(row["device_type"], "Desktop")
        self.assertIn("Chrome", row["device_name"])
        self.assertTrue(row["is_current"])

    def test_ordered_desc_current_first(self):
        c = self._login()  # 当前会话：最新
        base = timezone.now() - timedelta(hours=2)
        # 先创建再 update created_at（auto_now_add 会覆盖 create 时的显式值）
        h1 = UserSession.objects.create(user=self.user, session_key="h1", is_current=False)
        h2 = UserSession.objects.create(user=self.user, session_key="h2", is_current=False)
        UserSession.objects.filter(pk=h1.pk).update(created_at=base)
        UserSession.objects.filter(pk=h2.pk).update(created_at=base + timedelta(minutes=30))
        results = c.get("/auth/sessions/").json()["results"]
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]["is_current"])  # 最新（当前会话）排第一
        times = [r["created_at"] for r in results]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_returns_only_own_sessions(self):
        other = User.objects.create_user(username="other", password="secret123")
        oc = Client()
        oc.login(username="other", password="secret123")  # 产生 other 的记录
        c = self._login()
        results = c.get("/auth/sessions/").json()["results"]
        expected = UserSession.objects.filter(user=self.user).count()
        self.assertEqual(len(results), expected)  # 只返回本人，不含 other

    def test_caps_at_history_limit(self):
        c = self._login()  # 1 条当前会话
        base = timezone.now() - timedelta(hours=1)
        # 直接造 21 条更早的历史（不经 record_user_session，不触发裁剪）
        for i in range(21):
            UserSession.objects.create(
                user=self.user,
                session_key=f"extra{i:02d}",
                is_current=False,
                created_at=base + timedelta(seconds=i),
            )
        results = c.get("/auth/sessions/").json()["results"]
        self.assertEqual(len(results), 20)  # 视图裁剪到 SESSION_HISTORY_LIMIT


class RoleForTest(TestCase):
    """_role_for 按身份态派生徽章（ADR-0005 决策 7 / ADR-0006）：超管 > 管理员 > 用户 > 访客。

    与组、权限解耦——纯 is_superuser / is_staff / is_verified 判定；「用户 / 访客」分界读
    is_verified（任一认证通道 approved 即用户，否则访客）。
    """

    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")

    def test_superadmin(self):
        self.user.is_superuser = True
        self.user.save()
        from .views import _role_for
        self.assertEqual(_role_for(self.user), {"label": "超级管理员", "variant": "superadmin"})

    def test_admin(self):
        self.user.is_staff = True
        self.user.save()
        from .views import _role_for
        self.assertEqual(_role_for(self.user), {"label": "管理员", "variant": "admin"})

    def test_superadmin_wins_over_staff(self):
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        from .views import _role_for
        self.assertEqual(_role_for(self.user), {"label": "超级管理员", "variant": "superadmin"})

    def test_verified_user(self):
        # 有 approved 通道 ⇒ 用户
        from .models import Verification
        from .views import _role_for
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_APPROVED
        )
        self.assertEqual(_role_for(self.user), {"label": "用户", "variant": "user"})

    def test_unverified_is_visitor(self):
        # 无 Verification 行 ⇒ 访客（不再有「无 profile 视为已审核」后备）
        from .views import _role_for
        self.assertEqual(_role_for(self.user), {"label": "访客", "variant": "visitor"})

    def test_anonymous_is_visitor(self):
        from django.contrib.auth.models import AnonymousUser
        from .views import _role_for
        self.assertEqual(_role_for(AnonymousUser()), {"label": "访客", "variant": "visitor"})


class PublicRoleMaskTest(TestCase):
    """对外徽章遮蔽超管（ADR-0042）：别人看不到「超级管理员」，本人与后台不受影响。"""

    def setUp(self):
        self.boss = User.objects.create_user(
            username="boss", password="p", is_staff=True, is_superuser=True,
        )
        self.member = User.objects.create_user(username="member", password="p")

    def test_public_role_masks_superadmin_for_others_and_guests(self):
        from .views import _public_role_for
        self.assertEqual(_public_role_for(self.boss, self.member),
                         {"label": "管理员", "variant": "admin"})
        self.assertEqual(_public_role_for(self.boss, None),
                         {"label": "管理员", "variant": "admin"})

    def test_public_role_keeps_superadmin_for_self(self):
        from .views import _public_role_for
        self.assertEqual(_public_role_for(self.boss, self.boss),
                         {"label": "超级管理员", "variant": "superadmin"})

    def test_profile_endpoint_does_not_leak_superadmin_badge(self):
        c = Client()
        c.force_login(self.member)
        data = c.get(f"/auth/users/{self.boss.id}/profile/").json()
        self.assertEqual(data["role"]["variant"], "admin")
        self.assertEqual(data["role"]["label"], "管理员")


class CapabilityKeysContractTest(TestCase):
    """前后端能力键集契约（ADR-0005 决策 4）：后端 _capabilities 键集必须与
    前端 PermissionsPanel.tsx 的 CAP_LABELS 键集一致，防漂移（后端加键、前端漏显）。
    """

    def test_frontend_cap_labels_match_backend_capabilities(self):
        import re
        from pathlib import Path
        from .views import _capabilities

        ts_path = (
            Path(__file__).resolve().parents[1]
            / "frontend" / "src" / "components" / "profile" / "PermissionsPanel.tsx"
        )
        src = ts_path.read_text(encoding="utf-8")
        match = re.search(r"CAP_LABELS[^{]*\{([^}]*)\}", src)
        self.assertIsNotNone(match, "未在前端找到 CAP_LABELS 块")
        fe_keys = set(re.findall(r"([A-Za-z_]+)\s*:", match.group(1)))

        user = User.objects.create_user(username="u", password="p")
        be_keys = set(_capabilities(user).keys())

        self.assertEqual(
            fe_keys, be_keys,
            f"能力键集漂移：后端={sorted(be_keys)} 前端={sorted(fe_keys)}",
        )

    def test_capability_key_set_unchanged_no_survey_can(self):
        """能力键集是冻结契约：新增能力键必须同时改后端投影、前端标签表与本清单。

        ADR 0011：调研不拆新 can_*（“survey” 字样的键永不出现）。
        ADR 0022：校园全景图新增 can_manage_panoramas（⇐ `panorama.manage_panoramas`）。
        """
        from .views import _capabilities

        expected = {
            "can_manage_news",
            "can_manage_tasks",
            "can_assign_task",
            "can_manage_tags",
            "can_change_activity",
            "can_view_feedback",
            "can_handle_reports",
            "can_review_collections",
            "can_edit_about",
            "can_manage_panoramas",
            "can_manage_exam",
            "can_review_content",
            "can_review_identity",
            "can_force_publish",
            "can_manage_comment_thread",
            "can_mute_user",
            "can_manage_announcement",
            "can_manage_announcements",
        }
        user = User.objects.create_user(username="cap", password="p")
        keys = set(_capabilities(user).keys())
        self.assertEqual(keys, expected)
        self.assertFalse(any("survey" in k for k in keys))


class UserProfileViewTest(TestCase):
    """薄冒烟：本人/管理员/他人各一条（字段可见集）+ 边界；可见性矩阵见 tests_visibility。"""
    def setUp(self):
        from django.contrib.auth.models import Group
        self.viewed = User.objects.create_user(username="viewed", email="v@e.com", password="p")
        self.viewer = User.objects.create_user(username="viewer", password="p")
        self.admin = User.objects.create_user(username="admin", password="p")
        self.admin.groups.add(Group.objects.get_or_create(name="信息组")[0])

    def _login(self, user):
        c = Client()
        c.force_login(user)
        return c

    def test_unauthenticated_redirects(self):
        self.assertEqual(Client().get(f"/auth/users/{self.viewed.id}/profile/").status_code, 302)

    def test_unknown_user_404(self):
        c = self._login(self.viewer)
        self.assertEqual(c.get("/auth/users/999999/profile/").status_code, 404)

    def test_public_viewer_does_not_see_private_fields(self):
        data = self._login(self.viewer).get(f"/auth/users/{self.viewed.id}/profile/").json()
        self.assertEqual(data["user"]["id"], self.viewed.id)
        self.assertEqual(data["user"]["username"], "viewed")
        self.assertIn("date_joined", data["user"])
        for k in ("avatar", "nickname", "bio"):
            self.assertIn(k, data["profile"])
        self.assertIn("role", data)
        self.assertEqual(data["viewer"], {"is_owner": False, "is_admin": False})
        self.assertNotIn("email", data["user"])
        self.assertNotIn("birthday", data["profile"])
        self.assertNotIn("gender", data["profile"])
        self.assertNotIn("permissions", data)
        self.assertNotIn("groups", data)

    def test_owner_sees_everything(self):
        data = self._login(self.viewed).get(f"/auth/users/{self.viewed.id}/profile/").json() # pyright: ignore[reportAttributeAccessIssue]
        self.assertTrue(data["viewer"]["is_owner"])
        self.assertEqual(data["user"]["email"], "v@e.com")
        self.assertIn("birthday", data["profile"])
        self.assertIn("gender", data["profile"])
        self.assertIn("permissions", data)
        self.assertIn("groups", data)

    def test_admin_sees_permissions_but_not_private_fields(self):
        data = self._login(self.admin).get(f"/auth/users/{self.viewed.id}/profile/").json() # pyright: ignore[reportAttributeAccessIssue]
        self.assertTrue(data["viewer"]["is_admin"])
        self.assertFalse(data["viewer"]["is_owner"])
        self.assertIn("permissions", data)
        self.assertIn("groups", data)
        self.assertNotIn("email", data["user"])
        self.assertNotIn("birthday", data["profile"])


class UserContentViewTest(TestCase):
    """薄冒烟：本人/他人两路 + 边界（404/400/403）；可见性矩阵见 tests_visibility。"""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="p")
        self.other = User.objects.create_user(username="other", password="p")
        from news.models import News
        from reviews.models import Feedback
        from tasks.models import Task
        from reviews.test_helpers import approve_news, approve_activity, approve_tutorial
        approve_news(News.objects.create(title="published", author=self.owner, is_published=True))
        News.objects.create(title="draft", author=self.owner, is_published=False)
        Feedback.objects.create(title="closed", category="suggestion", status="closed", creator=self.owner)
        Feedback.objects.create(title="pending", category="suggestion", status="pending", creator=self.owner)
        Task.objects.create(title="t", creator=self.owner, assignee=self.owner)
        from activities.models import Activity
        from tutorials.models import Tutorial
        from django.core.files.uploadedfile import SimpleUploadedFile
        from reviews.models import Review
        pending_act = Activity.objects.create(
            type="deliberation", status="open", title="pending-act", creator=self.owner,
        )
        Review.objects.create(activity=pending_act, status=Review.STATUS_PENDING)
        approved_act = Activity.objects.create(
            type="deliberation", status="open", title="approved-act", creator=self.owner,
        )
        approve_activity(approved_act)
        pending_tut = Tutorial.objects.create(
            title="pending-tut",
            file=SimpleUploadedFile("a.mp4", b"x", content_type="video/mp4"),
            file_type="video",
            file_name="a.mp4",
            file_size=1,
            uploader=self.owner,
        )
        approved_tut = Tutorial.objects.create(
            title="approved-tut",
            file=SimpleUploadedFile("b.mp4", b"x", content_type="video/mp4"),
            file_type="video",
            file_name="b.mp4",
            file_size=1,
            uploader=self.owner,
        )
        approve_tutorial(approved_tut)
        self.pending_act = pending_act
        self.pending_tut = pending_tut

    def _login(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _get(self, client, type_):
        return client.get(f"/auth/users/{self.owner.id}/content/?type={type_}") # pyright: ignore[reportAttributeAccessIssue]

    def test_unauthenticated_redirects(self):
        self.assertEqual(Client().get(f"/auth/users/{self.owner.id}/content/?type=news").status_code, 302) # pyright: ignore[reportAttributeAccessIssue]

    def test_unknown_user_404(self):
        c = self._login(self.other)
        self.assertEqual(c.get("/auth/users/999999/content/?type=news").status_code, 404)

    def test_invalid_type_400(self):
        c = self._login(self.other)
        self.assertEqual(self._get(c, "bogus").status_code, 400)

    def test_owner_smoke_reaches_all_types(self):
        # 本人冒烟：三类内容都可达，本人可见未发布项（可见性矩阵见模块测试）
        c = self._login(self.owner)
        news = {r["title"] for r in self._get(c, "news").json()["results"]}
        self.assertIn("draft", news)
        self.assertEqual(len(self._get(c, "feedback").json()["results"]), 2)
        self.assertEqual(len(self._get(c, "tasks").json()["results"]), 1)
        acts = {r["title"] for r in self._get(c, "activities").json()["results"]}
        self.assertIn("pending-act", acts)
        self.assertIn("approved-act", acts)
        tuts = {r["title"] for r in self._get(c, "tutorials").json()["results"]}
        self.assertIn("pending-tut", tuts)
        self.assertIn("approved-tut", tuts)

    def test_other_smoke_filtered_and_tasks_forbidden(self):
        # 他人冒烟：news 草稿不可见、feedback 邮箱对他人不可见、tasks 403（边界）
        c = self._login(self.other)
        news = {r["title"] for r in self._get(c, "news").json()["results"]}
        self.assertNotIn("draft", news)
        feedback = {r["title"] for r in self._get(c, "feedback").json()["results"]}
        self.assertEqual(feedback, set())
        self.assertEqual(self._get(c, "tasks").status_code, 403)
        acts = {r["title"] for r in self._get(c, "activities").json()["results"]}
        self.assertNotIn("pending-act", acts)
        self.assertIn("approved-act", acts)
        tuts = {r["title"] for r in self._get(c, "tutorials").json()["results"]}
        self.assertNotIn("pending-tut", tuts)
        self.assertIn("approved-tut", tuts)


class UsersViewTest(TestCase):
    """GET /auth/users/ —— DRF 分页信封 + ?search=（用户名/昵称模糊）。

    任务表单指派/协作者搜索式下拉的数据源；无 search 时返回全量激活用户第一页。
    """

    URL = "/auth/users/"

    def setUp(self):
        self.client = Client()
        self.client.force_login(User.objects.create_user(username="login", password="p"))
        from accounts.models import Profile
        self.bob = User.objects.create_user(username="bob", password="p")
        Profile.objects.create(user=self.bob, nickname="")
        self.alice = User.objects.create_user(username="alice", password="p")
        Profile.objects.create(user=self.alice, nickname="爱丽丝")

    def test_requires_auth(self):
        self.assertIn(Client().get(self.URL).status_code, (401, 403, 302))

    def test_returns_paginated_envelope(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(set(data), {"count", "next", "previous", "results"})
        self.assertEqual(data["count"], 3)  # login + bob + alice
        self.assertEqual(len(data["results"]), 3)
        self.assertIn("id", data["results"][0])
        self.assertIn("username", data["results"][0])
        self.assertIn("nickname", data["results"][0])
        self.assertIn("avatar", data["results"][0])

    def test_search_by_username(self):
        data = self.client.get(self.URL, {"search": "alice"}).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["username"], "alice")

    def test_search_by_nickname(self):
        data = self.client.get(self.URL, {"search": "爱丽丝"}).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["username"], "alice")

    def test_search_no_match_empty_results(self):
        data = self.client.get(self.URL, {"search": "zzznomatch"}).json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_page_size_20_and_pagination(self):
        # 造 25 个用户 → 分两页；第二页 next=null
        for i in range(25):
            User.objects.create_user(username=f"user{i}", password="p")
        first = self.client.get(self.URL).json()
        self.assertEqual(len(first["results"]), 20)
        self.assertIsNotNone(first["next"])
        second = self.client.get(self.URL, {"page": 2}).json()
        self.assertEqual(len(second["results"]), 8)  # 3 + 25 = 28，第二页 8 条
        self.assertIsNone(second["next"])

    def test_out_of_range_page_returns_empty_results(self):
        data = self.client.get(self.URL, {"page": 999}).json()
        self.assertEqual(data["results"], [])



class SessionsEnvelopeTest(TestCase):
    """GET /auth/sessions/ —— 信封补全：count/next/previous/results 齐备（数据本身单页）。"""

    def setUp(self):
        self.user = User.objects.create_user(username="sess-env", password="secret123")

    def test_full_envelope_single_page(self):
        c = Client()
        c.post(
            "/auth/login/",
            data=json.dumps({"username": "sess-env", "password": "secret123"}),
            content_type="application/json",
            REMOTE_ADDR="1.2.3.4",
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
        )
        data = c.get("/auth/sessions/").json()
        self.assertEqual(set(data.keys()), {"count", "next", "previous", "results"})
        self.assertEqual(data["count"], len(data["results"]))
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])


class UserContentPaginationTest(TestCase):
    """GET /auth/users/{id}/content/ —— 分页信封 + 逐页翻。

    面板「加载更多」消费信封：page=1 为最新 CONTENT_LIMIT 条，next 非空即还有更多。
    """

    URL_TMPL = "/auth/users/{}/content/?type=tasks"

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="p")
        from tasks.models import Task
        for i in range(17):
            Task.objects.create(title=f"t{i:02d}", creator=self.owner, assignee=self.owner)

    def test_envelope_and_two_pages(self):
        c = Client()
        c.force_login(self.owner)
        url = self.URL_TMPL.format(self.owner.pk)
        page1 = c.get(url).json()
        self.assertEqual(set(page1.keys()), {"count", "next", "previous", "results"})
        self.assertEqual(page1["count"], 17)
        self.assertEqual(len(page1["results"]), 15)
        self.assertIsNotNone(page1["next"])
        self.assertIsNone(page1["previous"])
        self.assertEqual(page1["results"][0]["title"], "t16")  # 最新在前

        page2 = c.get(f"{url}&page=2").json()
        self.assertEqual(len(page2["results"]), 2)
        self.assertIsNone(page2["next"])
        self.assertIsNotNone(page2["previous"])
        self.assertEqual(page2["results"][-1]["title"], "t00")  # 最早的兜底

    def test_out_of_range_page_empty_envelope(self):
        c = Client()
        c.force_login(self.owner)
        data = c.get(f"{self.URL_TMPL.format(self.owner.pk)}&page=99").json()
        self.assertEqual(data["count"], 17)
        self.assertEqual(data["results"], [])
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])


class PermissionNormalizationTest(TestCase):
    """权限规范化数据迁移（accounts/0009）：持有旧 CRUD 权限的组自动获得新语义权限。"""

    def _codenames(self, group_name):
        group = Group.objects.get(name=group_name)
        return set(group.permissions.values_list("codename", flat=True))

    def test_info_group_gets_manage_news(self):
        # accounts/0002 给信息组 news add/change/delete_news → 0009 补 manage_news
        self.assertIn("manage_news", self._codenames("信息组"))

    def test_info_group_gets_manage_aboutpage(self):
        # about/0005 给信息组 change_aboutpage → 0009 补 manage_aboutpage
        self.assertIn("manage_aboutpage", self._codenames("信息组"))

    def test_info_group_gets_manage_exams(self):
        # exam_board/0004 给信息组 add_exam → 0009 补 manage_exams
        self.assertIn("manage_exams", self._codenames("信息组"))

    def test_president_gets_read_feedback(self):
        # reviews/0007 给社长 view_feedback → 0009 补 read_feedback
        self.assertIn("read_feedback", self._codenames("社长"))
