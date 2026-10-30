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


class TargetBackfillMixin:
    """双写期兜底：旧列有值但 ``target`` 为空时，保存前自动补上。

    B1 引入，B9 删掉旧列后整体移除。

    为什么放在 ``save()`` 而不是四个调用点：写路径太多（视图、序列化器、admin、
    shell、管理命令、测试夹具），漏一个就会留下 target 为空的行，而 PR 2 切读
    之后这些行**直接查不到**——症状是「评论/附件凭空消失」，且只在特定入口复现。
    """

    #: 旧列名 → kind。子类按自己的多态列填。
    TARGET_LEGACY_FIELDS: dict[str, str] = {}

    def legacy_target_ref(self):
        """返回 ``(kind, object_id)``；没有旧列命中则 None。"""
        for field, kind in self.TARGET_LEGACY_FIELDS.items():
            object_id = getattr(self, f"{field}_id", None)
            if object_id is not None:
                return kind, object_id
        return None

    def save(self, *args, **kwargs):
        if getattr(self, "target_id", None) is None:
            ref = self.legacy_target_ref()
            if ref is not None:
                self.target = target_for(*ref)
        super().save(*args, **kwargs)


def host_ref(obj):
    """内容行（Attachment / Review / ReportCase / CommentThread）→ ``(kind, object_id)``。

    优先 ``target``，回落旧列。两者都没有返回 None。

    回落不是保险丝而是**必需品**：双写期仍可能存在 target 为空的存量行——
    回填迁移漏掉的、或绕过 ``save()`` 的裸 SQL 写入的。切读后这些行会「凭空消失」，
    所以读取路径必须两条路都走。
    """
    if getattr(obj, "target_id", None) is not None:
        target = obj.target
        return target.kind, target.object_id
    if hasattr(obj, "legacy_target_ref"):
        return obj.legacy_target_ref()
    return None


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


def _has_field(model, name):
    return any(f.name == name for f in model._meta.get_fields())


def related_to(model, host):
    """某宿主上挂的内容行 queryset（四张多态表通用）。

    切读期同时匹配 ``target`` 与旧列，覆盖「已回填」和「尚未回填」两种存量；
    B9 删掉旧列后这个 OR 可以退化成单个 ``target`` 条件。

    旧列名与 kind 名恰好一一对应（``news`` / ``activity`` / ``tutorial`` /
    ``task`` / ``comment`` / ``submission`` / ``exhibit`` / ``feedback``），
    所以不需要额外的映射表——但要判断该表**有没有**这一列（例如
    ``CommentThread`` 没有 ``comment`` 列）。
    """
    kind = kind_of(host)
    q = models.Q(target__kind=kind, target__object_id=host.pk)
    if _has_field(model, kind):
        q |= models.Q(**{kind: host})
    return model.objects.filter(q)


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
