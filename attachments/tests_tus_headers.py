"""审计 #273：tus 数字头的畸形值必须是 400，不能 500。

`rest_framework_tus` 2.0.3 的 ``TusMiddleware`` 直接 ``int()`` 头值且没有
try/except，而它早于 DRF 权限执行——匿名请求带 ``Upload-Length: abc`` 就能
稳定打出 500。这个文件钉住「畸形 = 客户端错误」这条契约。

反证：把 ``TusHeaderValidationMiddleware`` 从 ``MIDDLEWARE`` 里删掉 →
前五条会变成 500（最后两条抓住 Python 3.11+ 的 int 位数上限）。
"""
from django.test import TestCase
from rest_framework.test import APIClient

URL = "/uploads/files/"


class TusMalformedHeaderTest(TestCase):
    def _post(self, **headers):
        return APIClient().post(URL, **headers)

    def test_non_numeric_upload_length_is_400(self):
        resp = self._post(HTTP_UPLOAD_LENGTH="abc")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("Upload-Length", resp.json()["detail"])

    def test_scientific_notation_is_400(self):
        resp = self._post(HTTP_UPLOAD_LENGTH="1e9")
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_negative_upload_length_is_400(self):
        resp = self._post(HTTP_UPLOAD_LENGTH="-5")
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_non_numeric_upload_offset_is_400(self):
        resp = self._post(HTTP_UPLOAD_OFFSET="abc")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("Upload-Offset", resp.json()["detail"])

    def test_over_long_digit_string_is_400(self):
        """5000 位数字串：isdigit 为真，但 int() 会撞 Python 的位数上限。"""
        resp = self._post(HTTP_UPLOAD_LENGTH="9" * 5000)
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_valid_length_reaches_auth(self):
        """合法值不该被这层拦：匿名的正常终点是 403（权限），不是 400。"""
        resp = self._post(HTTP_UPLOAD_LENGTH="10")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_error_response_carries_tus_version(self):
        resp = self._post(HTTP_UPLOAD_LENGTH="abc")
        self.assertEqual(resp["Tus-Resumable"], "1.0.0")

    def test_any_path_with_malformed_header_is_400(self):
        """第三方中间件不判路径：打在 /site-policy/ 上也是同一个 500。

        这条钉住「闸门必须全局」——按 /uploads/ 前缀过滤会漏掉这个更宽的触发面。
        """
        resp = APIClient().get("/site-policy/", HTTP_UPLOAD_LENGTH="abc")
        self.assertEqual(resp.status_code, 400, resp.content)
