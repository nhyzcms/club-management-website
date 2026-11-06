"""审计 #280：公开读接口必须有按 IP 的限流兜底。

覆盖两个此前「一个限流都没挂」的端点：`/about/`（完整名册 + 联系方式）
与 `/panorama/panoramas/`（`search_fields` 走 LIKE）。

做法是把 `PublicReadThrottle.RATE` patch 成极小值再打满，而不是真发 300 个
请求——`SimpleRateThrottle.__init__` 立刻读 `get_rate()` 算 `num_requests`，
所以按请求（DRF 每次 `initial()` 都新建实例）patch 类属性即可。

反证：把 `throttle_classes = [PublicReadThrottle]` 从任一视图删掉 →
对应的 `test_*_throttled` 立刻变红。
"""
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from common.throttles import PublicReadThrottle


class PublicReadThrottleTest(TestCase):
    def setUp(self):
        cache.clear()  # 限流计数进缓存，用例间必须隔离

    def tearDown(self):
        cache.clear()

    def test_about_is_throttled(self):
        """`/about/` 打满就必须 429。"""
        client = APIClient()
        PublicReadThrottle.RATE = "2/min"
        try:
            for _ in range(2):
                self.assertEqual(client.get("/about/").status_code, 200)
            resp = client.get("/about/")
        finally:
            PublicReadThrottle.RATE = "300/min"
        self.assertEqual(resp.status_code, 429)
        # DRF 标准 429 体；站点 locale 是 zh-hans，文案已被本地化。
        self.assertIn("限流", resp.json()["detail"])

    def test_about_subsidiary_reads_share_the_bucket(self):
        """`/about/blocks/`、`/about/overview/` 与 `/about/` 共用同一个读桶。

        限流键是 `scope + IP`，不区分具体 URL——否则把 `/about/` 换成
        `/about/overview/` 就能绕过。
        """
        client = APIClient()
        PublicReadThrottle.RATE = "2/min"
        try:
            codes = [
                client.get("/about/").status_code,
                client.get("/about/overview/").status_code,
                client.get("/about/").status_code,
            ]
        finally:
            PublicReadThrottle.RATE = "300/min"
        self.assertEqual(codes, [200, 200, 429])

    def test_panorama_list_is_throttled(self):
        """`/panorama/panoramas/` 同样有兜底。"""
        client = APIClient()
        PublicReadThrottle.RATE = "2/min"
        try:
            for _ in range(2):
                self.assertEqual(client.get("/panorama/panoramas/").status_code, 200)
            resp = client.get("/panorama/panoramas/")
        finally:
            PublicReadThrottle.RATE = "300/min"
        self.assertEqual(resp.status_code, 429)

    def test_unsafe_methods_do_not_consume_read_quota(self):
        """PUT /about/overview/ 是管理员保存，不该占访客的读额度。

        这条钉住 `allow_request` 里的安全方法过滤：去掉那三行，
        匿名的 PUT 会先被 403 拦下但仍计一次，后续 GET 就会提前 429。
        """
        client = APIClient()
        PublicReadThrottle.RATE = "2/min"
        try:
            for _ in range(5):
                client.put("/about/overview/", {}, format="json")  # 403，但不应计数
            codes = [client.get("/about/").status_code for _ in range(2)]
            blocked = client.get("/about/").status_code
        finally:
            PublicReadThrottle.RATE = "300/min"
        self.assertEqual(codes, [200, 200], "PUT 占用了读额度")
        self.assertEqual(blocked, 429)

    def test_separate_ips_have_separate_buckets(self):
        """限流键含 IP：一个客户端打满不影响另一个。"""
        PublicReadThrottle.RATE = "1/min"
        try:
            first = APIClient(REMOTE_ADDR="203.0.113.7")
            second = APIClient(REMOTE_ADDR="203.0.113.8")
            self.assertEqual(first.get("/about/").status_code, 200)
            self.assertEqual(first.get("/about/").status_code, 429)
            self.assertEqual(second.get("/about/").status_code, 200)
        finally:
            PublicReadThrottle.RATE = "300/min"

    def test_cache_isolation_guard(self):
        """默认速率是 300/min——生产值不能被上面几个用例的 patch 污染。"""
        self.assertEqual(PublicReadThrottle.RATE, "300/min")
        self.assertEqual(PublicReadThrottle().num_requests, 300)
