"""明信片互寄 · 删活动时的物理文件兜底清理。

任何入口删除 ``module_key="postcard"`` 的 Event（Django admin、shell、清理脚本）
都必须在删行之前清私有存储里的照片 / 样例图 / 公告 PDF——级联删除不会碰文件。
显式路径见 ``lifecycle.delete_season``；本信号覆盖其余入口（幂等，重复清理无害）。

``pre_delete`` 而不是 ``post_delete``：级联删除先删子行，post_delete 时照片行
已经没了，找不回文件路径。
"""
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from events.models import Event

from . import lifecycle


@receiver(pre_delete, sender=Event, dispatch_uid="postcard.purge_files_on_event_delete")
def purge_postcard_files_on_delete(sender, instance, **kwargs):
    if instance.module_key != "postcard":
        return
    lifecycle.purge_event_files(instance)
