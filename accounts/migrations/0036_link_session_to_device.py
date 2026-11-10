"""把 ``UserSession`` 的设备展示信息归到 ``AccountDevice``（B6）。

## 为什么归

``UserSession`` 上有 `ip_address` / `user_agent` / `device_type` / `device_name`，
``AccountDevice`` 上有 `last_ip` / `browser` / `platform` / `label` —— 同一批信息的
两份，靠 ``record_user_session`` 各自写一遍。两边一旦不一致（比如一处更新了 IP、
另一处没跟上），「安全中心里显示的设备」和「被顶下线提示里的设备」就会说两件事。

归完之后会话只引用设备，展示信息只有一处。

## 为什么 ``device_id`` 不删

它是字符串形式的设备标识，用于「同一台设备重新登录不额外占名额」的匹配。设备
记录可能不存在（脚本直连 API 没有 ``club_device`` cookie），那时 FK 为空但
``device_id`` 仍能表达「这是同一台设备」。

## 操作顺序

**必须** AddField → 回填 → RemoveField。Django 生成的迁移是「先删后加」，
那样回填时旧字段已经没了——迁移能跑通，数据全丢，而且不会报错。

## 反向

`RemoveField` 的反向是 `AddField`（空默认值），所以自己写回填，从 ``AccountDevice``
把能还原的抄回去。

**``user_agent`` 还原不了**——UA 原文没存在任何地方（`AccountDevice` 只存解析后的
browser / platform）。回滚后该字段为空，不影响功能（它只用于展示）。
"""
from django.db import migrations, models
import django.db.models.deletion


def backfill(apps, schema_editor):
    """按 ``(user_id, device_id)`` 把会话关联到设备；设备行不存在时补建。"""
    UserSession = apps.get_model("accounts", "UserSession")
    AccountDevice = apps.get_model("accounts", "AccountDevice")

    linked = created = 0
    for session in UserSession.objects.exclude(device_id="").iterator():
        device = AccountDevice.objects.filter(
            user_id=session.user_id, device_id=session.device_id,
        ).first()
        if device is None:
            device = AccountDevice.objects.create(
                user_id=session.user_id,
                device_id=session.device_id,
                device_type=(session.device_type or "Unknown")[:16],
                label=(session.device_name or "")[:128],
                last_ip=session.ip_address,
            )
            created += 1
        UserSession.objects.filter(pk=session.pk).update(account_device_id=device.pk)
        linked += 1

    if linked:
        print(f"[accounts.0036] {linked} 条会话已关联设备（新建 {created} 台）")


def restore(apps, schema_editor):
    """反向：从设备把能还原的展示信息抄回会话旧字段。"""
    UserSession = apps.get_model("accounts", "UserSession")

    restored = 0
    for session in UserSession.objects.exclude(account_device__isnull=True).select_related(
        "account_device"
    ).iterator():
        device = session.account_device
        UserSession.objects.filter(pk=session.pk).update(
            ip_address=device.last_ip,
            device_type=(device.device_type or "Unknown")[:16],
            device_name=(device.label or "")[:128],
        )
        restored += 1

    if restored:
        print(f"[accounts.0036] 回滚：{restored} 条会话的展示信息已抄回")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0035_drop_profile_legacy_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountdevice",
            name="device_type",
            field=models.CharField(
                default="Unknown", max_length=16, verbose_name="设备类型",
            ),
        ),
        migrations.AddField(
            model_name="usersession",
            name="account_device",
            field=models.ForeignKey(
                blank=True,
                help_text="无 club_device cookie 的会话（脚本直连 API）为空。",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sessions",
                to="accounts.accountdevice",
                verbose_name="设备",
            ),
        ),
        # 必须夹在 AddField 和 RemoveField 之间
        migrations.RunPython(backfill, restore),
        migrations.RemoveField(model_name="usersession", name="device_name"),
        migrations.RemoveField(model_name="usersession", name="device_type"),
        migrations.RemoveField(model_name="usersession", name="ip_address"),
        migrations.RemoveField(model_name="usersession", name="user_agent"),
    ]
