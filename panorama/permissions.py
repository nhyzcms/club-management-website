from rest_framework import permissions


class CanViewPanorama(permissions.BasePermission):
    """公开读：列表 / 详情匿名可读。

    可见性（未发布 / 切片未就绪的条目）由视图 ``get_queryset`` 收窄，
    不在这里判权——读走「身份 + 可见性」（ADR-0005 决策 8）。
    """

    def has_permission(self, request, view):
        return True


class CanManagePanorama(permissions.BasePermission):
    """增 / 删 / 改 / 重切片：须持 ``panorama.manage_panoramas``。"""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.has_perm("panorama.manage_panoramas")
        )
