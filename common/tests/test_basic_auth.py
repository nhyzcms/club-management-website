"""test 环境 HTTP Basic 闸门（common.middleware.BasicAuthGateMiddleware）。

这层闸门只在两个环境变量都配置时启用；它的失效模式必须两边都测到：
  - 该挡的没挡（test 环境 DEBUG 页面直接挂公网）；
  - 不该挡的挡了（生产漏配 / 半配置把整站锁在 401 后面）。
"""
import base64
import os
from contextlib import contextmanager

from django.conf import settings
from django.test import TestCase

USER = "tester"
PASSWORD = "s3cret-pass"


@contextmanager
def basic_auth_env(user=None, password=None):
    """临时设置（或清除）闸门的环境变量，退出时恢复原状。"""
    keys = ("TEST_BASIC_AUTH_USER", "TEST_BASIC_AUTH_PASSWORD")
    saved = {key: os.environ.get(key) for key in keys}
    for key in keys:
        os.environ.pop(key, None)
    if user is not None:
        os.environ["TEST_BASIC_AUTH_USER"] = user
    if password is not None:
        os.environ["TEST_BASIC_AUTH_PASSWORD"] = password
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def basic_header(user, password):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"HTTP_AUTHORIZATION": f"Basic {token}"}


class BasicAuthGateTest(TestCase):
    def test_disabled_by_default(self):
        """生产语义：不配变量 = 直通，不能因为中间件存在就把全站锁死。"""
        with basic_auth_env():
            response = self.client.get("/site-policy/")
        self.assertEqual(response.status_code, 200)

    def test_half_configured_is_disabled(self):
        """只配一半按未启用处理——半吊子配置不该把站点锁在一个没人知道的密码后。"""
        with basic_auth_env(user=USER):
            response = self.client.get("/site-policy/")
        self.assertEqual(response.status_code, 200)

    def test_missing_credentials_blocked(self):
        with basic_auth_env(USER, PASSWORD):
            response = self.client.get("/site-policy/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], 'Basic realm="club-test", charset="UTF-8"')
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_wrong_password_blocked(self):
        with basic_auth_env(USER, PASSWORD):
            response = self.client.get("/site-policy/", **basic_header(USER, "wrong"))
        self.assertEqual(response.status_code, 401)

    def test_correct_credentials_pass(self):
        with basic_auth_env(USER, PASSWORD):
            response = self.client.get("/site-policy/", **basic_header(USER, PASSWORD))
        self.assertEqual(response.status_code, 200)

    def test_healthz_is_exempt(self):
        """容器 healthcheck 拿不到用户密码，探活端点必须放行。"""
        with basic_auth_env(USER, PASSWORD):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_static_and_media_are_gated(self):
        """闸门在最前：静态 / 媒体 / 维护页也不能绕过（DEBUG 错误页会带 settings 片段）。"""
        with basic_auth_env(USER, PASSWORD):
            for path in ("/static/app.css", "/media/secret.png", "/admin/"):
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 401)

    def test_malformed_headers_are_rejected_not_500(self):
        bad_headers = [
            "Basic",
            "Basic !!!not-base64!!!",
            "Basic " + base64.b64encode(b"no-colon").decode(),
            "Bearer token",
            "Basic " + base64.b64encode("测试:密码".encode("utf-8")).decode(),
        ]
        with basic_auth_env(USER, PASSWORD):
            for header in bad_headers:
                with self.subTest(header=header):
                    response = self.client.get("/site-policy/", HTTP_AUTHORIZATION=header)
                    self.assertEqual(response.status_code, 401)

    def test_middleware_is_first(self):
        """闸门必须排在维护页 / session / csrf 之前，否则维护页与 debug 页会先漏出去。"""
        self.assertEqual(settings.MIDDLEWARE[0], "common.middleware.BasicAuthGateMiddleware")
