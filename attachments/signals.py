"""回收机制：删除附件行时同步删除磁盘文件。

父级（任务/申报）被删时，CASCADE 会逐行删除其附件，每行都触发本信号——故行与
文件一并清除。文件系统异常被吞掉并记日志：此时数据库行已删，不应因 FS 失败而向
用户抛 500。
"""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Attachment

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Attachment)
def delete_attachment_file(sender, instance, **kwargs):
    file = getattr(instance, "file", None)
    if not file:
        return
    try:
        file.delete(save=False)
    except Exception:  # noqa: BLE001 —— FS 故障不应冒泡成 500
        logger.warning(
            "删除附件磁盘文件失败: %s", getattr(file, "name", ""), exc_info=True,
        )
