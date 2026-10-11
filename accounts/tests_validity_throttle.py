"""身份有效期惰性检查的会话级节流（性能回归，见 accounts/middleware.py）。

原行为：每个已登录请求都跑一次 ``enforce_account_validity``（普通用户 = 1 条 EXISTS
查询，未认证者还要再读 Profile）—— 实测每个已登录请求固定多 1~3 条 SQL。

现行为：同一会话 ``VALIDITY_CHECK_INTERVAL_SECONDS`` 内只跑一次。兜底不变：
登录流程直接调用一次、``manage.py enforce_validity`` 定时命令定期收敛，
故「过期管理员被撤销」最坏延迟一个间隔生效。
"""
import time
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from . import middleware


class ValidityThrottleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="throttle", password="pw-Str0ng!42")
        self.client.force_login(self.user)

    def _hit(self):
        """打一个最轻的已登录端点：/auth/me/（不触发任何业务写路径）。"""
        resp = self.client.get("/auth/me/")
        self.assertEqual(resp.status_code, 200)

    def test_repeated_requests_check_only_once(self):
        """同一会话连续 4 个请求 → 只执行 1 次检查。"""
        calls = []

        def _fake(user):
            calls.append(user.pk)
            return None

        with mock.patch.object(middleware, "enforce_account_validity", side_effect=_fake):
            for _ in range(4):
                self._hit()
        self.assertEqual(calls, [self.user.pk])

    def test_check_runs_again_after_interval(self):
        """时间戳推进超过间隔后，下一次请求会重新检查。"""
        with mock.patch.object(middleware, "enforce_account_validity") as mocked:
            self._hit()
            self.assertEqual(mocked.call_count, 1)

            session = self.client.session
            session[middleware._VALIDITY_CHECKED_AT_KEY] = (
                time.time() - middleware.VALIDITY_CHECK_INTERVAL_SECONDS - 1
            )
            session.save()

            self._hit()
        self.assertEqual(mocked.call_count, 2)

    def test_anonymous_request_is_never_checked(self):
        """未登录请求不执行检查（也不写 session）。"""
        self.client.logout()
        with mock.patch.object(middleware, "enforce_account_validity") as mocked:
            self.client.get("/auth/me/")
        mocked.assert_not_called()
