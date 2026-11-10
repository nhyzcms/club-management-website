"""用户资料可见性模块（架构深化 #3，见 #8 / #11 / #14）。

独占「谁能看到某个用户的哪些资料 / 内容」判定。对外暴露：

- :func:`is_admin_viewer` —— 管理员视角（权限判定，替换硬编码「信息组」组名）；
- :func:`profile_view_for` —— 资料字段可见性裁定；
- :func:`content_visibility` —— 某类内容的查询过滤 / 无权信号。

进程内纯领域逻辑，仅依赖查看者与被查看者的字段和权限；资料视图与内容视图
退化为薄调用方，``is_owner`` / ``is_admin`` 与各类内容的过滤不再各自内联重推。
"""

from dataclasses import dataclass

from django.db.models import Q

from reviews.visibility import public_q


# 「信息组即管理员」在此单点定义：信息组（持 news.manage_news）可窥他人能力清单 / 所属组。
# 与 2026-07-19「角色→权限」迁移一致——此前两处视图内联 ``groups.filter(name="信息组")``
# 是该迁移漏出的硬编码遗留。超级用户隐式持全部权限，故 has_perm 已覆盖。
ADMIN_VIEW_PERMISSION = "news.manage_news"


def is_admin_viewer(viewer):
    """查看者是否为管理员视角（信息组 / 超级用户）。

    以权限判定为准，而非组名字面量：持 ``ADMIN_VIEW_PERMISSION`` 即管理员。
    """
    return viewer.is_superuser or viewer.has_perm(ADMIN_VIEW_PERMISSION)


def _is_owner(viewer, viewed):
    """查看者是否为被查看者本人。"""
    return viewer.pk is not None and viewer.pk == viewed.pk


@dataclass(frozen=True)
class ProfileVisibility:
    """资料字段可见性裁定：三档字段 + 本人/管理员标记。

    - 私密字段（email / birthday / gender）：仅本人（``can_see_private``）；
    - 敏感字段（能力清单 permissions / 所属组 groups）：本人或管理员（``can_see_sensitive``）；
    - 公开字段（role / 基础资料）：所有人（视图始终输出，不在本裁定里）。
    """

    is_owner: bool
    is_admin: bool
    can_see_private: bool
    can_see_sensitive: bool


def profile_view_for(viewer, viewed):
    """查看者对被查看者资料的可见性裁定（:class:`ProfileVisibility`）。

    视图据此条件挂载私密/敏感字段，并取 ``is_owner`` / ``is_admin`` 作为响应里的
    ``viewer`` 标记（契约不变，#8 故事 6）。
    """
    owner = _is_owner(viewer, viewed)
    admin = is_admin_viewer(viewer)
    return ProfileVisibility(
        is_owner=owner,
        is_admin=admin,
        can_see_private=owner,
        can_see_sensitive=owner or admin,
    )


@dataclass(frozen=True)
class ContentVisibility:
    """内容可见性裁定：是否无权（403）+ 额外查询 ``Q``。

    ``denied`` 为 True 时视图直接返回 403（任务对他人）；否则视图把
    ``extra_q`` 套到该类内容的查询集上（本人为空 ``Q()`` = 不过滤）。
    可审核种类的他人过滤与 :func:`reviews.visibility.public_q` 对齐（活动含夹具例外）；
    新闻另相交 ``is_published``（生命周期轴，非审核轴）。
    """

    denied: bool
    extra_q: Q


def content_visibility(viewer, viewed, content_type):
    """某类内容对查看者的可见性裁定（:class:`ContentVisibility`）。

    - news：他人仅已发布且过审；本人全部。
    - feedback：仅本人（署名投递箱）；他人不可见。
    - activities：他人仅公开审核轴（含无审核行夹具例外）；本人全部。
    - tutorials：他人仅已过审；本人全部。
    - tasks：仅本人；他人无权（denied）。

    未知 ``content_type`` 抛 :class:`ValueError`（视图层先做 type 校验返回 400，
    故正常不会抵达此分支；保留为派发完备性断言）。
    """
    owner = _is_owner(viewer, viewed)
    if content_type == "news":
        extra = Q() if owner else public_q("news") & Q(is_published=True)
        return ContentVisibility(denied=False, extra_q=extra)
    if content_type == "feedback":
        extra = Q() if owner else Q(pk__in=[])
        return ContentVisibility(denied=False, extra_q=extra)
    if content_type == "activities":
        extra = Q() if owner else public_q("activity")
        return ContentVisibility(denied=False, extra_q=extra)
    if content_type == "tutorials":
        extra = Q() if owner else public_q("tutorial")
        return ContentVisibility(denied=False, extra_q=extra)
    if content_type == "tasks":
        return ContentVisibility(denied=not owner, extra_q=Q())
    raise ValueError(f"未知内容类型: {content_type!r}")
