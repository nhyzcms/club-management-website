"""Login brute-force throttle: portal /auth/login/ and Django admin login."""
import json

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from common.testing import set_policy





class _ThrottleTestCase(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        set_policy(login_per_ip_per_hour=2, login_per_username_per_hour=10)
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="secret123",
        )

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def login(self, **fields):
        return self.client.post(
            "/auth/login/",
            data=json.dumps(fields),
            content_type="application/json",
        )


class PortalLoginThrottleTest(_ThrottleTestCase):
    def test_third_failure_from_same_ip_is_429(self):
        for _ in range(2):
            resp = self.login(username="testuser", password="wrong")
            self.assertEqual(resp.status_code, 401)
        resp = self.login(username="testuser", password="wrong")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["reason"], "login_throttled")
        self.assertIn("retry_after", resp.json())

    def test_blocked_request_does_not_check_correct_password(self):
        for _ in range(2):
            self.assertEqual(self.login(username="testuser", password="wrong").status_code, 401)
        resp = self.login(username="testuser", password="secret123")
        self.assertEqual(resp.status_code, 429)

    def test_successful_login_is_not_counted(self):
        self.assertEqual(self.login(username="testuser", password="secret123").status_code, 200)
        self.assertEqual(self.login(username="testuser", password="wrong").status_code, 401)
        self.assertEqual(self.login(username="testuser", password="wrong").status_code, 401)
        self.assertEqual(self.login(username="testuser", password="wrong").status_code, 429)

    def test_unknown_email_still_counts_toward_ip_limit(self):
        for _ in range(2):
            self.assertEqual(
                self.login(email="nobody@example.com", password="wrong").status_code, 401,
            )
        self.assertEqual(
            self.login(email="nobody@example.com", password="wrong").status_code, 429,
        )


class UsernameLoginThrottleTest(_ThrottleTestCase):
    def setUp(self):
        super().setUp()
        set_policy(login_per_ip_per_hour=100, login_per_username_per_hour=2)

    def test_username_bucket_blocks_independently_of_high_ip_cap(self):
        for _ in range(2):
            self.assertEqual(self.login(username="testuser", password="wrong").status_code, 401)
        resp = self.login(username="testuser", password="wrong")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["reason"], "login_throttled")


class AdminLoginThrottleTest(_ThrottleTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("adm", "adm@example.com", "secret123")

    def test_third_admin_failure_is_429(self):
        for _ in range(2):
            resp = self.client.post(
                "/admin/login/", {"username": "adm", "password": "wrong"},
            )
            self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            "/admin/login/", {"username": "adm", "password": "wrong"},
        )
        self.assertEqual(resp.status_code, 429)

    def test_admin_success_after_one_failure_still_works(self):
        self.assertEqual(
            self.client.post(
                "/admin/login/", {"username": "adm", "password": "wrong"},
            ).status_code,
            200,
        )
        resp = self.client.post(
            "/admin/login/", {"username": "adm", "password": "secret123"},
        )
        self.assertEqual(resp.status_code, 302)
