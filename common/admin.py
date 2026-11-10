from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import (
    AuthPolicy,
    ContentPolicy,
    RateLimitPolicy,
    Tag,
    UpdaterPolicy,
    UploadPolicy,
)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """标签（跨模块公共概念，2026-10 从 tasks 移来）。"""

    list_display = ["name", "color"]
    search_fields = ["name"]


# ── B5：SiteSettings 拆五之后的管理入口 ──────────────────────────────
#
# 五张表各一个 admin，只放本领域的字段。旧 SiteSettings **不再注册**——它已经
# 没人读了（get_policy() 只读新表），留着可编辑只会让管理员改了没效果。


class _SingletonPolicyAdmin(admin.ModelAdmin):
    """策略表只有一行：不能新增、不能删除，进 changelist 直接跳编辑页。"""

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = self.model.objects.get_or_create(pk=1)
        opts = self.model._meta
        return HttpResponseRedirect(
            reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
        )


@admin.register(AuthPolicy)
class AuthPolicyAdmin(_SingletonPolicyAdmin):
    """认证与身份：谁能注册、认证多久有效。"""


@admin.register(RateLimitPolicy)
class RateLimitPolicyAdmin(_SingletonPolicyAdmin):
    """频控额度。13 个参数放在一起才看得出松紧。"""


@admin.register(UploadPolicy)
class UploadPolicyAdmin(_SingletonPolicyAdmin):
    """上传体积上限。"""


@admin.register(UpdaterPolicy)
class UpdaterPolicyAdmin(_SingletonPolicyAdmin):
    """自动更新守护进程参数。改错会导致线上不更新。"""


@admin.register(ContentPolicy)
class ContentPolicyAdmin(_SingletonPolicyAdmin):
    """内容侧开关：审核、评论区、私信。"""
