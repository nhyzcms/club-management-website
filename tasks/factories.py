"""测试共享夹具：供 tasks 的各测试模块（HTTP 冒烟、生命周期接口等）复用。

抽出此处以免 ``make_president`` 之类的助手在多个测试文件里各自复制、渐行渐远。
"""

from django.contrib.auth.models import Group

from accounts.test_helpers import grant_verification


def make_president(user):
    """把用户加入「社长」组（默认组已由迁移授予 manage_tasks / assign_task 等权限）。

    社长亦是已认证成员（通过 IsVerified 写门禁需 approved 通道）——测试夹具一并满足。
    """
    group, _ = Group.objects.get_or_create(name="社长")
    user.groups.add(group)
    grant_verification(user)
    return user
