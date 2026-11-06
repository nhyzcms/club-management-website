"""限流基座与公开读限流（审计 #280）。

原 `_IPLimitThrottle` 只住在 `accounts/throttles.py` 里，而它其实是跨域的
基础设施——公开读接口（`/about/`、`/panorama/`）也要用它。放在 accounts 下
会让 `about` / `panorama` 反向依赖 accounts（accounts 已依赖 common.policy，
再反向就是循环的雏形），所以基类搬到 common；accounts 侧用 import 别名保留
原名，十几个子类一行都不用改。
"""
from rest_framework.throttling import SimpleRateThrottle

#: DRF 的 SAFE_METHODS，这里显式写死一份：本模块不 import rest_framework.views，
#: 免得为一个三元组把整个视图栈拉进导入图。
_READ_METHODS = ("GET", "HEAD", "OPTIONS")


class IPLimitThrottle(SimpleRateThrottle):
    """按 IP 计数的限流基类（函数式视图可手动实例化 + allow_request）。

    SimpleRateThrottle 的 get_cache_key 是抽象的，须覆写；这里固定用 self.scope +
    请求方 IP 作缓存键（与 DRF 内置 AnonRateThrottle 同形），不依赖 view 实例。
    """

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def is_blocked(self, request, view=None):
        """Peek: True if the next allow_request would deny. Does not increment."""
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return False
        self.history = list(self.cache.get(self.key, []))
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        return len(self.history) >= self.num_requests

    def retry_after(self, request, view=None):
        if not self.is_blocked(request, view):
            return 0
        wait = self.wait()
        return max(0, int(wait or 0))


class PublicReadThrottle(IPLimitThrottle):
    """公开读接口的按 IP 限流（审计 #280）。

    只覆盖此前**一个限流都没挂**的公开读端点：`/about/`（一次返回完整名册
    与联系方式，线上约 9KB）和 `/panorama/panoramas/`（`search_fields` 走
    `LIKE`）。写操作早就各自有限流，这里补的是「读也有兜底」。

    **只计安全方法**：同一个 throttle 会挂在同时允许写方法的视图上
    （`/about/overview/` 的 PUT），管理员的保存不该占用访客的读额度。

    速率取 300/min 而非审计建议的 120/min：学校网络整栋楼共用 NAT 出口，
    一个班同时刷名册就可能几十个请求；120/min 会在完全合法的场景误伤。
    300/min（5 req/s）对真人仍然宽松，对「单 worker 被并发读打满」已经够用。
    没有做成站点策略项：读限流是兜底能力，固定值即可，避免再开一次设置迁移。
    """

    scope = "public_read"

    #: 供测试 patch（`SimpleRateThrottle.__init__` 立刻读它算 num_requests）。
    RATE: str = "300/min"

    def get_rate(self):
        return self.RATE

    def allow_request(self, request, view):
        if request.method not in _READ_METHODS:
            return True
        return super().allow_request(request, view)

    # 没有 override throttled()：DRF 的 `APIView.check_throttles()` 调的是
    # **APIView.throttled()**，不是 throttle 实例上的方法——在实例上覆写是死代码。
    # 429 响应体因此是 DRF 的标准 `{"detail": ...}`（站点 locale 为 zh-hans，
    # 文案已是中文：「请求已被限流。预计 N 秒后可用。」）。
