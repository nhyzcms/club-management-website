"""活动状态的唯一真源（B3，ADR 0007 / 0011 的状态语义收口）。

## 为什么要这个模块

``Activity.status`` 是**最近一次结算的快照**——它只在写路径上被推进
（``transition_due_starts`` / ``transition_overdue`` / ``close`` / ``archive`` /
``maybe_close_collection_on_cap``）。任何时刻它都可能滞后：

* 排期已到点，但还没人读过列表 → 库里仍是 ``scheduled``；
* 已过截止，但结算没跑 → 库里仍是 ``open``。

以前所有守卫（``can_vote`` / ``can_submit`` / ``can_edit`` …）都直接读
``activity.status``，等于**把陈旧快照当真相**，只靠「所有入口都记得先调
transition」这条纪律兜着。漏一个入口，判定就错。

本模块把「此刻真实状态」变成一次纯计算：读 ``type`` / ``status`` /
``start_at`` / ``end_at``，不写库、不发通知、不碰缓存。**所有判断走这里；
落库的 ``status`` 只用于展示、筛选、排序。**

## 两种状态维度

* **时间窗驱动**（众议 / 展示 / 调研）：``start_at`` 与 ``end_at`` 决定一切。
  落库 status 只是它的一次快照。
* **工作流驱动**（征集）：``collecting → reviewing → archived`` 由人工或满额推进，
  时钟不改变阶段。但 :func:`accepting_submissions` 会额外判截止——
  征集过了 ``end_at`` 就不再收件，哪怕阶段仍是 ``collecting``。
"""

from django.utils import timezone

# 状态常量（与 models.STATUS_CHOICES 逐字对齐）
SCHEDULED = "scheduled"    # 排期：start_at 之前，待开始
OPEN = "open"              # 众议 / 展示 / 调研：进行中
CLOSED = "closed"          # 众议 / 展示 / 调研：已截止或已手动终结
COLLECTING = "collecting"  # 征集：收件中
REVIEWING = "reviewing"    # 征集：复审中
ARCHIVED = "archived"      # 征集：已归档

# 时间窗驱动的类型：状态完全由 start_at / end_at 决定。
TIMED_TYPES = frozenset({"deliberation", "exhibition", "survey"})
# 工作流驱动的类型：状态由人工 / 满额推进，时钟只决定「还要不要收件」。
WORKFLOW_TYPES = frozenset({"collection"})

# 征集的工作流档位（只有这三个对 collection 有意义）
COLLECTION_STATES = frozenset({COLLECTING, REVIEWING, ARCHIVED})

# 已结束的档位：closed（时间窗类截止 / 手动终结）与 archived（征集归档）。
ENDED_STATES = frozenset({CLOSED, ARCHIVED})


def calc_state(activity, now=None) -> str:
    """此刻的真实状态。纯函数，不写库。

    优先级：

    1. 落库 ``status == closed`` → 终态，不回退（手动 close / 提前结算的意图优先）；
    2. ``start_at`` 在未来 → ``scheduled``（时钟说还没开始，无论落库状态）；
    3. 落库 ``status == scheduled`` 且没有 ``start_at`` → ``scheduled``
       （无排期时间却标记待开始：库里的历史/夹具数据形态，保持旧行为）；
    4. 征集 → 落库工作流态（``collecting`` / ``reviewing`` / ``archived``）；
    5. ``end_at`` 已过 → ``closed``（``end_at`` 为空 = 长期活动，永不到期）；
    6. 否则 ``open``。

    第 2、3 步的差别是有意的：第 2 步让「排期已到点但快照没翻转」正确落到开放态，
    第 3 步让「没有排期时间」的存量行不被误判为已开放。
    """
    now = now or timezone.now()

    if activity.status == CLOSED:
        return CLOSED

    if activity.start_at is not None and activity.start_at > now:
        return SCHEDULED

    if activity.status == SCHEDULED and activity.start_at is None:
        return SCHEDULED

    # 脏数据防御：时间窗类不会进入征集档位。库里若真有这种行（历史脚本 / 手工改库），
    # 一律按「已结束」处理——这是唯一安全的方向：宁可多拦一次写，也不能因为
    # status 不认识就回落成 open 而放宽守卫（旧逻辑读 status 时这类行是 False）。
    if activity.type in TIMED_TYPES and activity.status in COLLECTION_STATES:
        return CLOSED

    if activity.type in WORKFLOW_TYPES:
        # 落库态若是排期（start_at 已过但还没翻转），惰性结果就是「收件中」。
        if activity.status in COLLECTION_STATES:
            return activity.status
        return COLLECTING

    if activity.end_at is not None and activity.end_at <= now:
        return CLOSED

    return OPEN


def has_started(activity, now=None) -> bool:
    """是否已开始（已过排期或被手动终结）。

    众议选项锁定、编辑锁定都用它——比 ``status != scheduled`` 可靠：
    后者在排期到点但未翻转时会误判「已开始」。
    """
    return calc_state(activity, now) != SCHEDULED


def past_end(activity, now=None) -> bool:
    """是否已过截止时间。只看 ``end_at``，不看落库 status。

    ``end_at`` 为空（长期活动）恒为 False。
    """
    now = now or timezone.now()
    return activity.end_at is not None and activity.end_at <= now


def is_ended(activity, now=None) -> bool:
    """是否已进入结束档位（closed / archived）——列表沉底与 feed 过滤共用。"""
    return calc_state(activity, now) in ENDED_STATES


def accepting_submissions(activity, now=None) -> bool:
    """征集此刻是否收件：阶段 = ``collecting`` **且** 未过截止。

    这是 B3 修掉的已知偏差。此前 ``can_submit`` 只看 ``status == collecting``，
    而 ``transition_overdue`` 的 ``type__in`` 不含 ``collection``——结果是
    **征集过了 ``end_at`` 仍然收稿**，直到有人手动「结束收件」。
    判定搬到这里之后，过期即刻停止收件；落库阶段由
    ``lifecycle.transition_overdue_collections`` 跟上（展示一致）。
    """
    if activity.type not in WORKFLOW_TYPES:
        return False
    if calc_state(activity, now) != COLLECTING:
        return False
    return not past_end(activity, now)


def can_respond_now(activity, now=None) -> bool:
    """时间窗层面是否可以作答/投票（不含受众与权限判定）。"""
    return calc_state(activity, now) == OPEN
