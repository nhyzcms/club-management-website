from rest_framework import permissions


class CanEditAbout(permissions.BasePermission):
    """关于区块 / 社团概览写：复用 about.manage_aboutpage，不按块拆权限。"""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("about.manage_aboutpage"))
