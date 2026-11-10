from rest_framework import permissions


class CanViewTutorial(permissions.BasePermission):
    """公开读：list/retrieve 匿名可读。"""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)


class CanModifyTutorial(permissions.BasePermission):
    """改/删：上传者或持 tutorials.manage_tutorials。"""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return obj.uploader_id == request.user.pk or request.user.has_perm("tutorials.manage_tutorials")
