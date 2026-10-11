"""活动债谓词（#82）：收件箱活动行与列表/详情 ``owed`` 的单一事实源。

``activity_debts_for`` 的 queryset 由调用方先过滤身份；序列化 ``owed_for``
在此判定已验证（访客与未验证得到 None；超管经后台委任通道计入）。

性能：``owed_for`` 会被**逐行**调用，而它要判「当前用户是否已验证」。若不预取，
N 行就是 N 条完全相同的通道查询（实测 20 行 = 20 条 SQL）——故 ``annotate_activity_debt``
在返回前先把该用户的验证通道读进内存（见 ``accounts.models.prefetch_verifications_for``）。
"""
from django.db.models import Exists, OuterRef, Q

from accounts.models import is_verified, prefetch_verifications_for
from reviews.visibility import public_q

from .lifecycle import COLLECTING, OPEN, transition_due_starts, transition_overdue
from .models import Activity, Ballot, Submission

REASON_VOTE = "vote"
REASON_SUBMIT = "submit"


def activity_debt_reason(activity, *, has_ballot, has_submission):
    """返回 ``vote`` / ``submit`` / None。"""
    if activity.type == "deliberation" and activity.status == OPEN and not has_ballot:
        return REASON_VOTE
    if activity.type == "collection" and activity.status == COLLECTING and not has_submission:
        return REASON_SUBMIT
    if (
        activity.type == "exhibition"
        and activity.status == OPEN
        and activity.voting_enabled
        and not has_ballot
    ):
        return REASON_VOTE
    return None  # 调研等其余类型不算社团义务，不进债


def owed_for(activity, user):
    """序列化 ``owed``：``vote`` / ``submit`` / None。优先用 annotate 的 Exists。"""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    # 已预取过通道行时这次判定零 SQL（见模块 docstring）
    if not is_verified(user):
        return None
    has_ballot = getattr(activity, "_has_ballot", None)
    if has_ballot is None:
        has_ballot = any(b.voter_id == user.pk for b in activity.ballots.all())
    has_submission = getattr(activity, "_has_submission", None)
    if has_submission is None:
        has_submission = any(s.submitter_id == user.pk for s in activity.submissions.all())
    return activity_debt_reason(
        activity, has_ballot=bool(has_ballot), has_submission=bool(has_submission),
    )


def annotate_activity_debt(qs, user):
    """给活动 queryset 标 ``_has_ballot`` / ``_has_submission``（Exists，避免 N+1）。

    同时把当前用户的验证通道预取进内存：序列化每行的 ``owed`` 都要判「已验证」，
    预取后这些判定不再各查一次库（写路径不受影响，见 accounts.models 的说明）。
    """
    if not user or not user.is_authenticated:
        return qs
    prefetch_verifications_for(user)
    return qs.annotate(
        _has_ballot=Exists(
            Ballot.objects.filter(activity_id=OuterRef("pk"), voter=user),
        ),
        _has_submission=Exists(
            Submission.objects.filter(activity_id=OuterRef("pk"), submitter=user),
        ),
    )


def activity_debts_for(user):
    """当前用户仍欠行动的公开活动（已跑惰性状态机）。"""
    transition_due_starts()
    transition_overdue()
    qs = annotate_activity_debt(
        Activity.objects.filter(public_q("activity")).select_related(
            "creator", "creator__profile", "publication_review",
        ),
        user,
    )
    return qs.filter(
        Q(type="deliberation", status=OPEN, _has_ballot=False)
        | Q(type="collection", status=COLLECTING, _has_submission=False)
        | Q(type="exhibition", status=OPEN, voting_enabled=True, _has_ballot=False)
    )
