"""admin 全站冒烟：每个注册模型的三类页面都要能渲染出来。

为什么需要：2026-11-01 生产事故——用户详情页 500（``ProfileInline`` 引用了 B4
已删的列），而 CI 全绿、system check 全过、列表页也正常。**Django 的 admin
check 不验证 ``get_readonly_fields()`` 这类运行时返回的字段名**，任何「写了名字
但名字不存在」的 admin 定制都只能靠渲染一次发现。

本用例对 ``admin.site._registry`` 里每个模型各打三枪：列表 / 新增 / 修改
（取库里第一条）。允许 200（渲染成功）、302（无权限跳转）、403（无新增权限）；
其余状态码或抛异常都算失败，并在断言消息里列出具体路径。
"""
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase


class AdminPagesRenderTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser(
            "smoke-root", "smoke-root@example.com", "pw-smoke-123"
        )
        self.client.force_login(self.root)

    def test_every_registered_admin_page_renders(self):
        failures = []
        for model, _model_admin in admin.site._registry.items():
            opts = model._meta
            base = f"/admin/{opts.app_label}/{opts.model_name}/"
            targets = [base, base + "add/"]
            obj = model._default_manager.order_by("pk").first()
            if obj is not None:
                targets.append(f"{base}{obj.pk}/change/")

            for path in targets:
                try:
                    resp = self.client.get(path)
                except Exception as exc:  # raise_request_exception=True：未捕获异常就是线上 500
                    failures.append(f"{path} -> {type(exc).__name__}: {exc}")
                    continue
                if resp.status_code not in (200, 302, 403):
                    failures.append(f"{path} -> HTTP {resp.status_code}")

        self.assertEqual(
            failures,
            [],
            "以下 admin 页面渲染失败（新增模型时请一并补 fixture 或修正字段名）：\n"
            + "\n".join(failures),
        )
