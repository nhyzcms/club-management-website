"""公开的站点策略快照（审计 #274）。

原先这里直接 ``asdict(get_policy())`` —— 把 36 个字段全量倒给匿名访问者，
包括自动更新窗口、`tus` 上限、各条 per-IP 限流阈值、Turnstile 开关。
单看每个字段都不敏感，合起来是一张侦察地图；而 `asdict` 是「全量导出」，
以后 `SitePolicy` 再加任何内部字段都会自动公开——结构性问题，不是一次性泄漏。

现在改成**显式 allowlist**：只下发 SPA 真正消费的字段。新增字段必须同时改这里
和 ``common/tests/test_public_policy.py`` 的冻结清单，否则测试红——「不小心公开」
比「不小心不公开」严重得多。
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.turnstile import public_turnstile_fields

from .policy import get_policy

#: 公开字段的唯一真源。每一项都必须有前端消费端（grep 得到），
#: 不做「以后可能有用」的预留——预留一个键就是永久多暴露一个键。
PUBLIC_POLICY_FIELDS = (
    # 认证 / 注册门禁与有效期提示文案
    "verification_enabled",
    "verification_valid_days",
    "admin_valid_days",
    "registration_verify_days",
    "registration_enabled",
    # 评论区 / 私信开关与嵌套深度
    "comments_enabled",
    "comment_max_depth",
    "dms_enabled",
    # 前端按大小选同步 / tus 通路
    "sync_upload_max_bytes",
)


def public_policy_snapshot(policy=None) -> dict:
    """把策略快照裁成公开子集。"""
    policy = policy or get_policy()
    return {name: getattr(policy, name) for name in PUBLIC_POLICY_FIELDS}


class SitePolicyView(APIView):
    """SPA 用的公开策略快照。无写路径。"""

    permission_classes = [AllowAny]
    authentication_classes = []  # anonymous GET; skip session/CSRF dance

    def get(self, request):
        # Turnstile sitekey 来自 .env，不是 SiteSettings；叠到公开快照给 SPA。
        return Response({**public_policy_snapshot(), **public_turnstile_fields()})
