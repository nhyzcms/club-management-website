"""附件的读查询。

## 为什么单独一个模块

B9 删掉 5 个旧父级外键后，``news.attachments`` / ``task.attachments`` 这些反向
访问器不存在了，调用方统一走 ``attachments_of(obj)``。

放在 ``create.py`` 里会成环：``validation.py`` 需要它，而 ``create.py`` 反过来
依赖 ``validation.py``。这里只依赖 ``models`` 和 ``common.targets``，没有下行依赖。
"""
from common.targets import target_of

from .models import Attachment


def attachments_of(obj):
    """某个内容对象挂的附件（旧 ``obj.attachments`` 反向访问器的替代）。"""
    return Attachment.objects.filter(target=target_of(obj))
