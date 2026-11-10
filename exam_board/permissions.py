from rest_framework import permissions


class CanManageExam(permissions.BasePermission):
    """考试看板写：持 exam_board.manage_exams。读匿名开放。"""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("exam_board.manage_exams"))
