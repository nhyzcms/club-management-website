"""任务生命周期模块（架构深化 #1，见 #6 / #9 / #12）。

独占任务的状态机、权限规则与「活跃参与者」判定。对外暴露：

- 三段权限谓词：``is_creator`` / ``is_active_participant`` / ``can_manage``
  （外加指派权限 ``can_assign``）；
- ``available_actions(task, user)`` —— 此刻该用户可执行的动作集合；
- ``apply(action, task, user, *, payload)`` —— 执行一次状态转移，返回
  :class:`TransitionResult`（含拒绝类别 ``kind``，供 HTTP 层映射状态码）；
- ``status_for_assignee(assignee)`` —— 负责人↔状态联动，供任务创建与指派共用。

状态机与权限规则为进程内纯领域逻辑，集中在 ``_REQUIRED_STATES`` 与
``_permitted`` 一处，``available_actions`` 与 ``apply`` 共用、不再五处复制。
``apply`` 在此之上产生副作用并写库（创建/审批认领申请、置负责人、记完成时间）。
"""

from dataclasses import dataclass

from django.contrib.auth.models import User
from django.utils import timezone

from .models import Task, TaskClaimRequest


# ---- 权限谓词 -----------------------------------------------------------

def is_creator(task, user):
    """任务的创建者。"""
    return task.creator_id is not None and task.creator_id == user.pk


def is_active_participant(task, user):
    """活跃参与者：任务处于进行中（``in_progress``）时的负责人或协作者。

    供提交验收（complete）判定；附件子系统亦复用本谓词（ADR-0002）。
    """
    return task.status == "in_progress" and (
        task.assignee_id == user.pk
        or task.collaborators.filter(pk=user.pk).exists()
    )


def can_manage(user):
    """持任务管理权限者（社长组授予 ``tasks.manage_tasks``）。"""
    return user.has_perm("tasks.manage_tasks")


def can_assign(user):
    """持任务指派权限者（社长组授予 ``tasks.assign_task``）。"""
    return user.has_perm("tasks.assign_task")


def status_for_assignee(assignee):
    """负责人↔状态联动：有负责人则进行中，否则待处理。

    任务创建（序列化器）与指派动作（``apply(ASSIGN)``）共用此判定，
    删除两处各自直接改状态的做法（见 #12）。
    """
    return "in_progress" if assignee else "pending"


# ---- 动作标识 -----------------------------------------------------------
# 与 tasks 视图的 @action 名一一对应，HTTP 路由即以此映射。
CLAIM = "claim"
APPROVE_CLAIM = "approve_claim"
REJECT_CLAIM = "reject_claim"
COMPLETE = "complete"
APPROVE_COMPLETION = "approve_completion"
REJECT_COMPLETION = "reject_completion"
CANCEL = "cancel"
ASSIGN = "assign"

# 稳定输出顺序：供前端按既定次序渲染按钮（顺序本身不是契约，仅为一致）。
_ACTION_ORDER = (
    CLAIM, APPROVE_CLAIM, REJECT_CLAIM,
    COMPLETE, APPROVE_COMPLETION, REJECT_COMPLETION,
    CANCEL, ASSIGN,
)

# 各动作的合法源状态。空元组表示「任意状态」（指派）。
_REQUIRED_STATES = {
    CLAIM: ("pending", "review"),
    APPROVE_CLAIM: ("review",),
    REJECT_CLAIM: ("review",),
    COMPLETE: ("in_progress",),
    APPROVE_COMPLETION: ("reviewing",),
    REJECT_COMPLETION: ("reviewing",),
    CANCEL: ("pending", "in_progress", "reviewing", "review"),  # 非终态
    ASSIGN: (),
}

# 闸口失败时的中文原因（载荷级校验另给具体原因）。
_UNAVAILABLE_REASON = {
    COMPLETE: "当前无法提交验收",
    APPROVE_COMPLETION: "当前无法通过验收",
    REJECT_COMPLETION: "当前无法打回验收",
    CANCEL: "当前无法取消任务",
    CLAIM: "当前无法申请认领",
    APPROVE_CLAIM: "当前无法审批认领",
    REJECT_CLAIM: "当前无法审批认领",
    ASSIGN: "无指派权限",
}


def _permitted(action, task, user):
    """动作的权限判定（假定状态已满足）。

    审批类动作（批准/拒绝认领、通过/打回验收、取消）统一「创建者 或 管理权限」；
    提交验收为「活跃参与者 或 管理权限」；认领为「非创建者 且 无负责人」。
    """
    if action == COMPLETE:
        return is_active_participant(task, user) or can_manage(user)
    if action in (APPROVE_CLAIM, REJECT_CLAIM, APPROVE_COMPLETION, REJECT_COMPLETION, CANCEL):
        return is_creator(task, user) or can_manage(user)
    if action == CLAIM:
        return not is_creator(task, user) and not task.assignee_id
    if action == ASSIGN:
        return can_assign(user)
    return False


def available_actions(task, user):
    """此刻 ``user`` 可对 ``task`` 执行的动作（有序、唯一）。

    纯领域逻辑：仅依据任务字段 + 用户权限，不查认领申请、不触 HTTP。
    故「认领」类动作按「状态 + 角色」给出，至于此刻是否真有待审认领、
    是否已重复申请，留待 ``apply`` / HTTP 层在执行时校验。
    """
    if not user.is_authenticated:
        return ()
    out = []
    for action in _ACTION_ORDER:
        states = _REQUIRED_STATES[action]
        if states and task.status not in states:
            continue
        if not _permitted(action, task, user):
            continue
        out.append(action)
    return tuple(out)


# ---- 转移执行 -----------------------------------------------------------

# 拒绝类别：HTTP 层据此映射状态码（403 / 400 / 404）。成功时为 None。
KIND_FORBIDDEN = "forbidden"
KIND_BAD_REQUEST = "bad_request"
KIND_NOT_FOUND = "not_found"


@dataclass(frozen=True)
class TransitionResult:
    """``apply`` 的返回：是否成功、所执行动作、转移后的任务、拒绝原因与类别。

    ``kind`` 为 ``None`` 表示成功；否则为 ``KIND_*`` 之一，供 HTTP 层映射
    状态码（403 / 400 / 404）。``claim`` 仅 ``claim`` 动作成功时携带新建的
    认领申请，供视图直接序列化、免去二次查询。
    """

    ok: bool
    action: str
    task: Task
    reason: str | None = None
    kind: str | None = None
    claim: TaskClaimRequest | None = None


def _reject(action, task, reason, kind):
    return TransitionResult(False, action, task, reason, kind=kind)


def apply(action, task, user, *, payload=None):
    """执行一次状态转移，返回 :class:`TransitionResult`。

    先按 ``_REQUIRED_STATES`` 把状态闸口（不满足 → ``bad_request``），再按
    ``_permitted`` 把权限闸口（不满足 → ``forbidden``），最后做载荷级校验
    （打回理由、认领 id、指派 id、重复认领 → ``bad_request`` / ``not_found``）
    并落地副作用、写库。
    """
    payload = payload or {}

    if action not in _REQUIRED_STATES:
        return _reject(action, task, "当前不可执行此操作", KIND_BAD_REQUEST)
    states = _REQUIRED_STATES[action]
    if states and task.status not in states:
        return _reject(action, task, _UNAVAILABLE_REASON[action], KIND_BAD_REQUEST)
    if not _permitted(action, task, user):
        return _reject(action, task, _UNAVAILABLE_REASON[action], KIND_FORBIDDEN)

    if action == COMPLETE:
        task.status = "reviewing"
        task.reject_reason = ""
        task.save(update_fields=["status", "reject_reason", "updated_at"])
        return TransitionResult(True, action, task)

    if action == APPROVE_COMPLETION:
        task.status = "completed"
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        return TransitionResult(True, action, task)

    if action == REJECT_COMPLETION:
        reason = str(payload.get("reason", "")).strip()
        if not reason:
            return _reject(action, task, "请填写打回理由", KIND_BAD_REQUEST)
        task.status = "in_progress"
        task.reject_reason = reason
        task.save(update_fields=["status", "reject_reason", "updated_at"])
        return TransitionResult(True, action, task)

    if action == CANCEL:
        task.status = "cancelled"
        task.save(update_fields=["status", "updated_at"])
        return TransitionResult(True, action, task)

    if action == ASSIGN:
        assignee_id = payload.get("assignee_id")
        if assignee_id:
            try:
                assignee = User.objects.get(pk=assignee_id)
            except User.DoesNotExist:
                return _reject(action, task, "用户不存在", KIND_NOT_FOUND)
            task.assignee = assignee
        else:
            task.assignee = None
        task.status = status_for_assignee(task.assignee)
        task.save(update_fields=["assignee", "status", "updated_at"])
        return TransitionResult(True, action, task)

    if action == CLAIM:
        reason = str(payload.get("reason", "")).strip()
        claim, created = TaskClaimRequest.objects.get_or_create(
            task=task, claimant=user, defaults={"reason": reason},
        )
        if not created:
            return _reject(action, task, "你已经申请过认领此任务", KIND_BAD_REQUEST)
        # 首个认领申请把待处理任务流转到认领审核；审核中追加则状态不变。
        if task.status == "pending":
            task.status = "review"
            task.save(update_fields=["status", "updated_at"])
        return TransitionResult(True, action, task, claim=claim)

    if action == APPROVE_CLAIM:
        try:
            claim = TaskClaimRequest.objects.get(pk=payload.get("claim_id"), task=task, status="pending")
        except TaskClaimRequest.DoesNotExist:
            return _reject(action, task, "认领请求不存在或已处理", KIND_NOT_FOUND)
        claim.status = "approved"
        claim.moderated_by = user
        claim.moderated_at = timezone.now()
        claim.save(update_fields=["status", "moderated_by", "moderated_at"])
        task.assignee = claim.claimant
        task.status = "in_progress"
        task.save(update_fields=["assignee", "status", "updated_at"])
        return TransitionResult(True, action, task)

    if action == REJECT_CLAIM:
        try:
            claim = TaskClaimRequest.objects.get(pk=payload.get("claim_id"), task=task, status="pending")
        except TaskClaimRequest.DoesNotExist:
            return _reject(action, task, "认领请求不存在或已处理", KIND_NOT_FOUND)
        claim.status = "rejected"
        claim.moderated_by = user
        claim.moderated_at = timezone.now()
        claim.save(update_fields=["status", "moderated_by", "moderated_at"])
        # 已无其它待处理申请时，把任务从认领审核回退到待处理。
        if task.status == "review" and not TaskClaimRequest.objects.filter(task=task, status="pending").exists():
            task.status = "pending"
            task.save(update_fields=["status", "updated_at"])
        return TransitionResult(True, action, task)

    # 不可达：上方 _REQUIRED_STATES 已拦下未知动作，已知动作均在上方分支处理。
    # 保留此句作为派发完备性的断言，防新增动作时漏写分支。
    raise AssertionError(f"lifecycle.apply: 未处理的动作 {action!r}")
