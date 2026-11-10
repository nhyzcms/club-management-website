"""统一附件权限：单一抽象规则，父级差异收进 helper（见 ADR 0002）。

> 操作者须为该父级的**创建者**，或该父级的**活跃参与者**，或持有该父级
> **管理权限**者。

- 任务：活跃参与者 = 进行中（in_progress）时的负责人 / 协作者；管理权限 = tasks.manage_tasks。
- 意见反馈：活跃参与者 = 空（创建者即唯一参与者）；管理权限 = reviews.read_feedback（能删不能传）。
- 新闻：创建者 = ``author``；管理权限 = news.manage_news。
- 作品：策展/复审 = 活动发起人 / manage_activity / review_collection。
- 展品：策展人 = 活动发起人 / manage_activity。

父级身份读 ``attachments.create`` 注册表，不在本模块 ``isinstance`` 分叉。

**上传**走 ``can_upload_to_parent``：反馈父级在此之上做 carve-out——仅署名创建者 + 审结前，
社长被排除（不上传证据到别人反馈）。**删除**走 ``can_manage_parent_attachments``（通用规则），
并额外允许附件上传者删除自己上传的（用户故事 #12）。故社长对反馈「能删不能传」。
"""
from tasks.lifecycle import is_active_participant

from .create import spec_for


def is_parent_creator(user, parent):
    """父级创建者。任务/申报用 ``creator_id``；新闻用 ``author_id``（注册表 ``creator_attr``）。"""
    spec = spec_for(parent)
    if spec is None or not spec.creator_attr:
        return False
    creator_id = getattr(parent, spec.creator_attr, None)
    return creator_id is not None and creator_id == user.pk


# 「任务活跃参与者」谓词已收口到 tasks.lifecycle.is_active_participant
# （架构深化 #1），本模块按 (parent, user) 顺序引用之——对外规则不变。


def has_parent_manage_permission(user, parent):
    """父级管理权限：读注册表 ``key``，不 ``isinstance``。"""
    spec = spec_for(parent)
    if spec is None:
        return False
    if spec.key == "task":
        return user.has_perm("tasks.manage_tasks")
    if spec.key == "feedback":
        return user.has_perm("reviews.read_feedback")
    if spec.key == "news":
        return user.has_perm("news.manage_news")
    if spec.key == "submission":
        return (
            parent.activity.creator_id == user.pk
            or user.has_perm("activities.manage_activity")
            or user.has_perm("activities.review_collection")
        )
    if spec.key == "exhibit":
        return (
            parent.activity.creator_id == user.pk
            or user.has_perm("activities.manage_activity")
        )
    return False


def can_manage_parent_attachments(user, parent):
    """通用管理规则：创建者 / 活跃参与者 / 管理权限。**删除**附件沿用本函数。

    **上传**走 ``can_upload_to_parent``——反馈父级在此之上做了 carve-out（仅署名创建者
    + 审结前，排除社长）；其余父级上传与删除规则一致。故社长对反馈「能删不能传」。
    """
    if not user.is_authenticated or parent is None:
        return False
    if is_parent_creator(user, parent):
        return True
    spec = spec_for(parent)
    if spec is not None and spec.key == "task" and is_active_participant(parent, user):
        return True
    if has_parent_manage_permission(user, parent):
        return True
    return False


def can_upload_to_parent(user, parent):
    """上传附件到父级的权限（ADR 0002 单一规则的反馈 carve-out）。

    反馈特例：仅**署名创建者**、且仅 ``pending`` 期间可上传——持 read_feedback 者被排除
    （不上传证据到别人反馈），了结即锁死。其余父级沿用通用规则。
    """
    if not user.is_authenticated:
        return False
    spec = spec_for(parent)
    if spec is not None and spec.key == "feedback":
        return is_parent_creator(user, parent) and parent.status == "pending"
    return can_manage_parent_attachments(user, parent)
