"""内容目标的注册表与生命周期（B1）。

``common.ContentTarget`` 是「可被评论 / 审核 / 举报 / 挂附件的对象」的锚点。
本模块负责两件事：

1. **登记表**：``kind`` ↔ 宿主模型。新增一种宿主只改这里，不改任何表结构。
2. **生命周期**：宿主删除时，删掉它的 target；与之关联的附件 / 审核 / 举报 /
   评论区由 ``CASCADE`` 一起带走。

## 孤儿风险与兜底

``object_id`` 没有数据库外键（见模型 docstring 的取舍）。所以「宿主删了但 target
还在」是可能的，触发条件是**绕过信号**的删除——``raw=True`` 的 SQL、手工改库、
或某个宿主忘了注册。

两道兜底：
- ``connect_host()`` 由 ``common.apps.CommonConfig.ready()`` 统一调用，漏注册会在
  启动时就暴露（``audit_registry()`` 可查）。
- B9 的 ``prune_orphan_targets`` 管理命令定期清理。
"""

from django.apps import apps
from django.db import models
from django.db.models.signals import post_delete

# kind → (app_label, ModelName)
# **新增宿主只改这一张表 + ContentTarget.KIND_CHOICES。零 DDL。**
KIND_TO_MODEL = {
    "news": ("news", "News"),
    "activity": ("activities", "Activity"),
    "tutorial": ("tutorials", "Tutorial"),
    "task": ("tasks", "Task"),
    "comment": ("messaging", "Comment"),
    "submission": ("activities", "Submission"),
    "exhibit": ("activities", "Exhibit"),
    "feedback": ("reviews", "Feedback"),
}

_MODEL_TO_KIND = {
    (app_label, model_name): kind
    for kind, (app_label, model_name) in KIND_TO_MODEL.items()
}


def model_for(kind):
    """kind → 模型类（懒解析，避免 app 加载期的循环导入）。"""
    try:
        app_label, model_name = KIND_TO_MODEL[kind]
    except KeyError:
        raise LookupError(f"未知的内容目标类型: {kind!r}") from None
    return apps.get_model(app_label, model_name)


def kind_of(obj):
    """模型实例 → kind。**不在登记表里就是编程错误**，直接抛，不要静默返回 None。"""
    key = (obj._meta.app_label, obj._meta.object_name)
    try:
        return _MODEL_TO_KIND[key]
    except KeyError:
        raise LookupError(
            f"{obj._meta.label} 不在 ContentTarget 登记表中；"
            f"新增宿主请在 common/targets.py 的 KIND_TO_MODEL 里注册"
        ) from None


def target_for(kind, object_id):
    """取（或建）某个对象的 target。幂等，可安全地在每次写路径调用。"""
    from .models import ContentTarget

    if object_id is None:
        raise ValueError("object_id 不能为空——target 只属于已落库的对象")
    target, _ = ContentTarget.objects.get_or_create(kind=kind, object_id=object_id)
    return target


def target_of(obj):
    """取（或建）某个模型实例的 target。"""
    return target_for(kind_of(obj), obj.pk)


def _on_host_deleted(sender, instance, **kwargs):  # noqa: ARG001
    """宿主删除 → 删 target → CASCADE 带走附件/审核/举报/评论区。

    逐条按 ``(kind, object_id)`` 删，而不是走 ``instance.content_target``：
    宿主侧没有反向字段（那要再改 8 张表），查一次带索引的等值条件足够。
    """
    from .models import ContentTarget

    kind = _MODEL_TO_KIND.get((sender._meta.app_label, sender._meta.object_name))
    if kind is None:  # pragma: no cover - ready() 只连注册过的模型
        return
    ContentTarget.objects.filter(kind=kind, object_id=instance.pk).delete()


def host_ref(obj):
    """内容行（Attachment / Review / ReportCase / CommentThread）→ ``(kind, object_id)``。

    B9 删掉 5 个旧父级列之后，``target`` 是唯一来源。target 为空说明这行是在
    删列之前就漏了回填的——返回 None，调用方按「没有宿主」处理。
    """
    if getattr(obj, "target_id", None) is None:
        return None
    target = obj.target
    return target.kind, target.object_id


def content_host(obj):
    """内容行 → 宿主模型实例；定位不到返回 None。

    注意：每次调用都会查一次宿主表。批量场景（审核台列表）不要逐行调用，
    用 ``related_to`` 做反向查询，或按 kind 分组预取。
    """
    ref = host_ref(obj)
    if ref is None:
        return None
    kind, object_id = ref
    return model_for(kind).objects.filter(pk=object_id).first()


def related_to(model, host):
    """某宿主上挂的内容行 queryset（四张多态表通用）。

    ``target`` 的 ``(kind, object_id)`` 唯一标识一个宿主，所以一条等值条件就够。
    B9 之前这里还有一个 ``Q(**{kind: host})`` 的旧列分支，删列后去掉。
    """
    return model.objects.filter(target__kind=kind_of(host), target__object_id=host.pk)


def connect_host(kind):
    """给一个宿主模型挂 post_delete。重复调用无副作用（dispatch_uid 去重）。"""
    model = model_for(kind)
    post_delete.connect(
        _on_host_deleted,
        sender=model,
        dispatch_uid=f"common.content_target.host_deleted.{kind}",
        weak=False,
    )


def connect_all():
    """把所有已登记的宿主接上信号。由 ``CommonConfig.ready()`` 调用。"""
    for kind in KIND_TO_MODEL:
        try:
            connect_host(kind)
        except LookupError:
            # 模型尚未就绪（app 加载顺序 / 被裁剪的部署）——ready() 里不该发生，
            # 但也不该让整站起不来。
            continue


def audit_registry():
    """自检：登记表里的每个 kind 都能解析到模型，且 KIND_CHOICES 完全对齐。

    返回问题列表（空 = 健康）。给测试和 ``manage.py check`` 用。
    """
    from .models import ContentTarget

    problems = []
    declared = {value for value, _label in ContentTarget.KIND_CHOICES}
    registered = set(KIND_TO_MODEL)
    if declared != registered:
        problems.append(
            f"KIND_CHOICES 与 KIND_TO_MODEL 不一致："
            f"只在 choices={sorted(declared - registered)}，"
            f"只在登记表={sorted(registered - declared)}"
        )
    for kind in sorted(registered):
        try:
            model_for(kind)
        except LookupError:
            problems.append(f"{kind}: 模型不存在（{KIND_TO_MODEL[kind]}）")
    return problems
