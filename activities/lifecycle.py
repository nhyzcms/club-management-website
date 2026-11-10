"""活动生命周期模块（ADR 0007 / 0011 / 遵循 ADR 0003：状态机与访问控制分离）。

独占活动的状态机与守卫，对外暴露纯领域逻辑。

- 众议 / 调研：open → closed；到 ``end_at`` 惰性结算。
- 征集：collecting → reviewing → archived；满 ``max_submissions`` 自动 collecting→reviewing。
- 长期活动（``is_permanent``）：``end_at`` 为空，永不自动结算，仅能手动 close。

**判定一律走 :mod:`activities.state`**（B3）：落库的 ``status`` 只是最近一次结算的
快照，可能滞后（排期已到点但没读过列表、已过截止但结算没跑）。以前这里所有守卫都
直接读 ``activity.status``，等于把陈旧快照当真相——正确性全靠「所有入口都记得先调
transition」这条纪律兜着。现在时间窗判定全部改走 ``calc_state()``，transition 只
负责维护快照（供展示、筛选、排序）。

状态常量从 :mod:`activities.state` 再导出，保持 ``from .lifecycle import OPEN``
这类既有写法可用。
"""

from django.utils import timezone

from .state import (  # noqa: F401  （常量在此再导出，历史导入点仍有效）
    ARCHIVED,
    CLOSED,
    COLLECTING,
    ENDED_STATES,
    OPEN,
    REVIEWING,
    SCHEDULED,
    TIMED_TYPES,
    WORKFLOW_TYPES,
    accepting_submissions,
    calc_state,
    has_started,
    is_ended,
    past_end,
)



def initial_status(activity_type, start_at=None):
    """活动创建时的初始状态：``start_at`` 在未来 → scheduled（待开始）；否则众议/展示/调研=open、征集=collecting。

    供序列化器 create 共用的单一事实源。``start_at`` 为 None 表示不排期（创建即开放）。
    """
    if start_at is not None and start_at > timezone.now():
        return SCHEDULED
    if activity_type in ("deliberation", "exhibition", "survey"):
        return OPEN
    if activity_type == "collection":
        return COLLECTING
    raise ValueError(f"未知活动类型: {activity_type!r}")


def transition_due_starts():
    """惰性开放：把已到 ``start_at`` 的 scheduled 活动翻转为开放态
    （众议/展示/调研→open / 征集→collecting）。在 list/get/vote/submit/respond 入口调用。

    逐行条件更新（status=scheduled）保证并发安全——多个读者同时触达时只有一个请求真正翻转。
    """
    now = timezone.now()
    due = Activity.objects.filter(status=SCHEDULED, start_at__lte=now)
    opened = []
    for activity in due:
        # 征集 → collecting；众议/展示 → open
        target = COLLECTING if activity.type == "collection" else OPEN
        changed = Activity.objects.filter(pk=activity.pk, status=SCHEDULED).update(
            status=target, updated_at=now,
        )
        if changed:
            opened.append(activity.pk)
    if opened:
        _notify_opened(opened)
    return opened


def _notify_opened(activity_ids):
    """活动到点开放：向全体订阅者广播（订阅与静默规则照常生效）。"""
    from messaging.services import notify_all

    for activity in Activity.objects.filter(pk__in=activity_ids):
        notify_all(
            "activity",
            "opened",
            payload={
                "type": "activity",
                "id": activity.pk,
                "title": getattr(activity, "title", "") or "",
                "url": f"/activity/{activity.pk}",
            },
        )


def can_edit(activity):
    """是否可编辑（改 start_at/end_at/正文/选项/配置）：仅待开始期间。开放后锁定。

    调研 Schema 另见 ``can_edit_schema``（开放且零作答时仍可改问卷，标题/时间仍走本谓词）。
    """
    return calc_state(activity) == SCHEDULED


def can_edit_schema(activity):
    """调研问卷 Schema 可否改：类型=调研，且待开始，或开放中尚无作答。"""
    if activity.type != "survey":
        return False
    state = calc_state(activity)
    if state == SCHEDULED:
        return True
    if state == OPEN:
        qid = activity.questionnaire_id
        if not qid:
            return True
        return not QuestionnaireResponse.objects.filter(questionnaire_id=qid).exists()
    return False


def can_respond(activity, user):
    """调研作答守卫：类型=调研、此刻进行中。公开受众任何人；仅成员须登录。

    审核通过由视图另判；已登录重复提交由视图 + 部分唯一约束收口。
    """
    if activity.type != "survey" or calc_state(activity) != OPEN:
        return False
    if activity.audience == "public":
        return True
    return bool(getattr(user, "is_authenticated", False))


# ---- 众议 --------------------------------------------------------------

def can_vote(activity, user):
    """投票守卫：类型与此刻状态（众议=进行中；展示=``voting_enabled`` 且进行中）+ 受众放行。

    受众 ``public``：任何人（含未登录游客——视图按设备标识判重、记录 IP）；
    受众 ``members``：须已登录（认证轴由 ``IsVerified`` 在视图层把关）。
    """
    if activity.audience != "public" and not (
        user and getattr(user, "is_authenticated", False)
    ):
        return False
    state = calc_state(activity)
    if activity.type == "deliberation":
        return state == OPEN
    if activity.type == "exhibition":
        return activity.voting_enabled and state == OPEN
    return False


def can_rate(activity, user):
    """展示评分守卫：类型=展示、此刻进行中、用户已认证。"""
    return (
        user.is_authenticated
        and activity.type == "exhibition"
        and calc_state(activity) == OPEN
    )


def can_curate(activity, user):
    """展示布展守卫：类型=展示、状态∈{待开始,展示中}、用户已认证。

    策展人(发起人 or manage_activity)的角色/归属判定由 CanModifyActivity 权限类
    在 get_object 时把关;此处只管「此刻能否布展」的状态机条件——加/删/导入展品
    在待开始与展示中都可进行,仅已结束禁止。改展品(标题)另见 can_edit_exhibit。
    """
    return (
        user.is_authenticated
        and activity.type == "exhibition"
        and calc_state(activity) in (SCHEDULED, OPEN)
    )


def can_edit_exhibit(activity, user):
    """展示展品改标题守卫：类型=展示、待开始、用户已认证。

    与 can_curate 的差异：展示中仍可加/删/导入展品，但**改**已上架展品
    （可能已有投票/赞踩）仅限待开始期，开放后锁定。
    """
    return (
        user.is_authenticated
        and activity.type == "exhibition"
        and calc_state(activity) == SCHEDULED
    )


def can_close(activity, user):
    """提前关闭守卫：发起人或持 activities.manage_activity，且此刻允许关。

    时间窗类须进行中；征集须收件中。归属与角色仍由 CanModifyActivity 把关；
    此处把视图曾内联的状态条件收口，供 close 动作调用。
    """
    if not user.is_authenticated:
        return False
    if not (activity.creator_id == user.pk or user.has_perm("activities.manage_activity")):
        return False
    state = calc_state(activity)
    if activity.type in TIMED_TYPES:
        return state == OPEN
    if activity.type == "collection":
        return state == COLLECTING
    return False


def can_archive(activity, user):
    """归档守卫：发起人或持 activities.manage_activity；仅征集 collecting / reviewing。

    众议 / 展示 / 调研没有归档态（截止走 closed）。后台批量归档走本谓词。
    """
    if not user.is_authenticated:
        return False
    if not (activity.creator_id == user.pk or user.has_perm("activities.manage_activity")):
        return False
    return activity.type == "collection" and calc_state(activity) in (COLLECTING, REVIEWING)


def archive(activity, user):
    """征集归档：collecting / reviewing → archived。非法则 False。

    收件中带复审的征集走本路径会跳过复审——后台批量归档的显式覆盖，不是 close 的别名。

    写路径的 ``status__in`` 含 ``SCHEDULED``：落库状态可能是「排期已到点但还没被
    翻转」的陈旧快照，此时 ``calc_state`` 已是 collecting 而库里仍是 scheduled。
    不加会被判定通过、实际 update 命中 0 行。
    """
    if not can_archive(activity, user):
        return False
    now = timezone.now()
    changed = Activity.objects.filter(
        pk=activity.pk, type="collection", status__in=(SCHEDULED, COLLECTING, REVIEWING),
    ).update(status=ARCHIVED, updated_at=now)
    if changed:
        activity.status = ARCHIVED
        activity.updated_at = now
    return bool(changed)


def transition_overdue():
    """惰性结算：把已到 ``end_at`` 的开放态众议/展示/调研从 open 流转到 closed。

    在 list/get/vote/rate/respond 入口调用。逐行条件更新保证每条活动只被一个请求流转（并发安全；
    Django 无内置调度，此惰性方式无需 cron）。征集另有满额流转（``maybe_close_collection_on_cap``）。

    长期活动（``is_permanent=True``，``end_at=None``）不参与结算——SQL 的 ``end_at__lte`` 本就
    不会命中 NULL，这里显式 ``end_at__isnull=False`` 把该契约写进查询，避免将来改用别的判定方式时误伤。
    长期活动只能由发起人 / 管理员通过 close（can_close）手动终结。
    """
    now = timezone.now()
    overdue = Activity.objects.filter(
        type__in=("deliberation", "exhibition", "survey"), status=OPEN,
        end_at__isnull=False, end_at__lte=now,
    )
    closed_pks = []
    for activity in overdue:
        changed = Activity.objects.filter(
            pk=activity.pk, status=OPEN,
        ).update(status=CLOSED, updated_at=now)
        if changed:
            closed_pks.append(activity.pk)
    return closed_pks


# ---- 征集 --------------------------------------------------------------

def transition_overdue_collections():
    """惰性结束收件：把已过 ``end_at`` 的征集推进到复审 / 归档。

    目标态由 :func:`collection_close_target` 决定（启用复审 → ``reviewing``，
    否则 → ``archived``），与手动「结束收件」走同一条规则。

    **为什么单独一条**：征集的「结束」不是 ``closed``——那一档属于时间窗类。
    以前根本没有这一步，过期征集一直挂在 ``collecting``，于是形成
    「刊面写着收件中、实际投不进去」的不一致（``can_submit`` 曾不判时间窗，
    更早时是两边都错）。现在：判定由 ``accepting_submissions`` 立刻生效，
    落库由本函数跟上，两者口径一致。

    逐行条件更新保证并发安全；``end_at`` 为空的长期征集不参与。
    """
    now = timezone.now()
    overdue = Activity.objects.filter(
        type="collection", status=COLLECTING,
        end_at__isnull=False, end_at__lte=now,
    )
    moved = []
    for activity in overdue:
        changed = Activity.objects.filter(
            pk=activity.pk, status=COLLECTING,
        ).update(status=collection_close_target(activity), updated_at=now)
        if changed:
            moved.append(activity.pk)
    return moved


def can_submit(activity, user):
    """征集投稿守卫：类型=征集、此刻收件中、用户已认证。

    「已认证」由视图的 IsVerified 把关；满额由视图在投稿后用
    ``maybe_close_collection_on_cap`` 收口。

    **B3 修掉的已知偏差**：此前只看 ``status == collecting``，而
    ``transition_overdue`` 的 ``type__in`` 不含 collection——征集过了
    ``end_at`` 仍能投稿，直到有人手动「结束收件」。现在时间窗交给
    :func:`state.accepting_submissions`，过期即刻停止收件。
    """
    return user.is_authenticated and accepting_submissions(activity)


def collection_close_target(activity):
    """征集收件结束的目标态：启用复审 → reviewing；关闭复审 → archived（跳过复审）。

    单一事实源——``close`` 动作与 ``maybe_close_collection_on_cap`` 共用此规则。
    """
    return REVIEWING if activity.review_enabled else ARCHIVED


def maybe_close_collection_on_cap(activity):
    """满额自动关闭：作品数达 ``max_submissions`` 时 collecting→reviewing/archived。返回是否触发。

    逐行条件更新（status=collecting）保证并发安全——多个投稿者同时触达上限时只有一个
    请求真正翻转状态。``max_submissions`` 为 None（不限）时永不触发。
    """
    if activity.type != "collection" or activity.status != COLLECTING:
        return False
    if not activity.max_submissions:
        return False
    # 用直接模型查询计数，绕开视图预取缓存（submit 时 activity 携带空的预取 submissions，
    # 用 activity.submissions.count() 会读到缓存 0 而非真实 1）。
    count = Submission.objects.filter(activity_id=activity.pk).count()
    if count >= activity.max_submissions:
        changed = Activity.objects.filter(
            pk=activity.pk, status=COLLECTING,
        ).update(status=collection_close_target(activity), updated_at=timezone.now())
        return bool(changed)
    return False


# 延迟导入打破 activities 内部循环（lifecycle ↔ models 同 app，无环；保留供未来跨引用）。
from .models import Activity, QuestionnaireResponse, Submission  # noqa: E402

# 「已结束」的档位：closed（众议/调研截止、手动终结）/ archived（征集归档）。
# 列表与首页 feed 共用同一条规则：未结束的活动排前面，已结束的沉底；
# 同一档内按发布时间（created_at）倒序——后发布的在上面。
ENDED_STATUSES = frozenset({CLOSED, ARCHIVED})


def order_activities(qs):
    """活动列表默认顺序：未结束在前、已结束在后，同档按发布时间倒序。

    用 CASE 标注 ``_phase_rank`` 而不是改 ``Meta.ordering``：排序依赖 status 枚举的
    语义分组，塞进数据库默认排序会牵动迁移，且 `mine` / 详情等其它入口不需要它。
    """
    from django.db.models import Case, IntegerField, Value, When

    return qs.annotate(
        _phase_rank=Case(
            When(status__in=ENDED_STATUSES, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by("_phase_rank", "-created_at")
