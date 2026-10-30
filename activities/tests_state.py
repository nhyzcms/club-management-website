"""活动状态收口测试（B3）。

这组测试的核心不是「新逻辑对不对」，而是**「重写了，但没偷偷改行为」**：

``activities.state`` 把「此刻真实状态」从落库的 ``status`` 快照里分离出来。
风险在于——重构一个被全站依赖的守卫层时，很容易顺手放宽某个判定，
而那不会让测试变红，只会让某个写入口悄悄放行。

所以这里做**差分证明**：把旧实现（读 ``status``）原样复刻到本文件，
在 216 种 ``(type, status, start_at, end_at)`` 组合上逐一比对：
**新结果只允许比旧结果更严格（True→False），绝不允许更宽松（False→True）**，
且每一处差异都必须能归因到「时钟」或「快照滞后」。

顺带钉住一个修掉的真实缺陷：征集过了 ``end_at`` 仍可投稿。
"""
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification

from . import lifecycle as L
from . import state as S
from .models import Activity, Submission
from .voting import options_locked

PAST = timedelta(days=-1)
FUTURE = timedelta(days=1)


def _activity(**overrides):
    """构造一个「够用就够」的活动替身：calc_state 只读这几个属性。"""
    base = dict(
        type="deliberation",
        status="open",
        start_at=None,
        end_at=None,
        is_permanent=False,
        audience="members",
        voting_enabled=True,
        creator_id=1,
        questionnaire_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _User:
    """建站权限的替身：只让 creator 分支命中（has_perm 恒 False）。"""

    pk = 1
    is_authenticated = True

    def has_perm(self, perm):  # noqa: ARG002
        return False


ANON = SimpleNamespace(pk=None, is_authenticated=False, has_perm=lambda p: False)


# ---------------------------------------------------------------------------
# 旧实现复刻（B3 之前的 lifecycle / voting 原文逻辑）
# 改动这里等于改「基线」，会让差分失去意义——只在确认需求变化时才动。
# ---------------------------------------------------------------------------

def _legacy_can_edit(a):
    return a.status == "scheduled"


def _legacy_can_edit_schema(a):
    if a.type != "survey":
        return False
    if a.status == "scheduled":
        return True
    if a.status == "open":
        qid = a.questionnaire_id
        if not qid:
            return True
        return False  # 本文件不造作答行，等价于「无作答」
    return False


def _legacy_can_respond(a, u):
    if a.type != "survey" or a.status != "open":
        return False
    if a.audience == "public":
        return True
    return bool(getattr(u, "is_authenticated", False))


def _legacy_can_vote(a, u):
    if a.audience != "public" and not (u and getattr(u, "is_authenticated", False)):
        return False
    if a.type == "deliberation":
        return a.status == "open"
    if a.type == "exhibition":
        return a.voting_enabled and a.status == "open"
    return False


def _legacy_can_rate(a, u):
    return u.is_authenticated and a.type == "exhibition" and a.status == "open"


def _legacy_can_curate(a, u):
    return u.is_authenticated and a.type == "exhibition" and a.status in ("scheduled", "open")


def _legacy_can_edit_exhibit(a, u):
    return u.is_authenticated and a.type == "exhibition" and a.status == "scheduled"


def _legacy_can_close(a, u):
    if not u.is_authenticated:
        return False
    if not (a.creator_id == u.pk or u.has_perm("activities.manage_activity")):
        return False
    if a.type in ("deliberation", "exhibition", "survey"):
        return a.status == "open"
    if a.type == "collection":
        return a.status == "collecting"
    return False


def _legacy_can_archive(a, u):
    if not u.is_authenticated:
        return False
    if not (a.creator_id == u.pk or u.has_perm("activities.manage_activity")):
        return False
    return a.type == "collection" and a.status in ("collecting", "reviewing")


def _legacy_can_submit(a, u):
    return u.is_authenticated and a.type == "collection" and a.status == "collecting"


def _legacy_options_locked(a):
    return a.type == "deliberation" and a.status != "scheduled"


def _not_past_end(a, now):
    """``can_submit`` 相对旧实现的唯一增量：额外判了「征集是否已过截止」。"""
    return not S.past_end(a, now)


# 被测的成对谓词：
# (名字, 旧实现, 新实现, 是否需要 user, 旧的应然结果之外还多加的条件)
# 最后一列只有 can_submit 非空——它是 B3 真正修掉的那条缺陷，单独暴露出来让差异可见。
PAIRS = [
    ("can_edit", _legacy_can_edit, L.can_edit, False, None),
    ("can_edit_schema", _legacy_can_edit_schema, L.can_edit_schema, False, None),
    ("can_respond", _legacy_can_respond, L.can_respond, True, None),
    ("can_vote", _legacy_can_vote, L.can_vote, True, None),
    ("can_rate", _legacy_can_rate, L.can_rate, True, None),
    ("can_curate", _legacy_can_curate, L.can_curate, True, None),
    ("can_edit_exhibit", _legacy_can_edit_exhibit, L.can_edit_exhibit, True, None),
    ("can_close", _legacy_can_close, L.can_close, True, None),
    ("can_archive", _legacy_can_archive, L.can_archive, True, None),
    ("can_submit", _legacy_can_submit, L.can_submit, True, _not_past_end),
    ("options_locked", _legacy_options_locked, options_locked, False, None),
]


class CalcStateTableTest(TestCase):
    """``calc_state`` 的期望值表——把每一种语义一次钉死。"""

    def _state(self, **kw):
        return S.calc_state(_activity(**kw))

    def test_long_running_is_open_forever(self):
        self.assertEqual(self._state(type="deliberation", status="open", end_at=None), S.OPEN)

    def test_past_end_closes_even_if_status_open(self):
        self.assertEqual(
            self._state(type="deliberation", status="open", end_at=timezone.now() + PAST),
            S.CLOSED,
        )

    def test_future_start_is_scheduled_even_if_status_open(self):
        """时钟说还没开始——这是旧逻辑做不到的（它只看 status）。"""
        self.assertEqual(
            self._state(type="deliberation", status="open", start_at=timezone.now() + FUTURE),
            S.SCHEDULED,
        )

    def test_due_start_corrects_stale_scheduled(self):
        """排期已到点但快照没翻转 → 惰性结果就是 open。"""
        self.assertEqual(
            self._state(type="deliberation", status="scheduled", start_at=timezone.now() + PAST),
            S.OPEN,
        )

    def test_scheduled_without_start_at_stays_scheduled(self):
        """存量/夹具形态：无排期时间但标记待开始。保持旧行为，不误判为已开放。"""
        self.assertEqual(
            self._state(type="deliberation", status="scheduled", start_at=None), S.SCHEDULED,
        )

    def test_closed_is_terminal_even_with_future_end(self):
        """手动 close / 提前结算之后，end_at 再远也不能退回 open。"""
        self.assertEqual(
            self._state(type="deliberation", status="closed", end_at=timezone.now() + FUTURE),
            S.CLOSED,
        )

    def test_collection_keeps_workflow_stage_regardless_of_clock(self):
        """征集的阶段由工作流推进，时钟不改变它（截止由 accepting_submissions 判）。"""
        for stage in (S.COLLECTING, S.REVIEWING, S.ARCHIVED):
            with self.subTest(stage=stage):
                self.assertEqual(
                    self._state(
                        type="collection", status=stage, end_at=timezone.now() + PAST,
                    ),
                    stage,
                )

    def test_due_collection_start_becomes_collecting(self):
        self.assertEqual(
            self._state(type="collection", status="scheduled", start_at=timezone.now() + PAST),
            S.COLLECTING,
        )

    def test_timed_type_in_collection_stage_is_treated_as_ended(self):
        """脏数据防御：众议不该有 collecting/reviewing/archived。宁可多拦，不能放宽。"""
        for stage in (S.COLLECTING, S.REVIEWING, S.ARCHIVED):
            with self.subTest(stage=stage):
                self.assertEqual(
                    self._state(type="deliberation", status=stage, end_at=None), S.CLOSED,
                )


class GuardDifferentialTest(TestCase):
    """差分证明：新逻辑 ≡ 旧逻辑 + 一次惰性结算。

    这个表述比「新逻辑更严格」精确得多，也更本质：

    旧流程靠「每个入口先调 ``transition_*`` 把 status 刷新，再让守卫读 status」维持正确。
    新流程把这一步内化进 ``calc_state``，守卫直接读「刷新后应该是什么」。

    所以对任意一行数据，**把落库 status 替换成 ``calc_state`` 之后喂给旧实现，
    必须与新实现逐字相同**。若某个谓词多做了事（``can_submit`` 额外判了截止），
    就把那件事显式写进 ``extra`` 列，让差异可见、可审。

    任何在这一条之外的差异 = 重构顺手改了行为，测试会失败。
    """

    TYPES = ("deliberation", "exhibition", "survey", "collection")
    STATUSES = ("scheduled", "open", "closed", "collecting", "reviewing", "archived")
    CLOCKS = {None: None, "past": PAST, "future": FUTURE}

    def _corrected(self, a, now):
        """把落库 status 换成「此刻应然状态」的替身。"""
        return SimpleNamespace(**{**vars(a), "status": S.calc_state(a, now)})

    def test_new_guards_equal_legacy_after_lazy_settlement(self):
        now = timezone.now()
        user = _User()
        mismatches = []
        checked = 0
        differed = 0

        for activity_type in self.TYPES:
            for status in self.STATUSES:
                for start_key, start_delta in self.CLOCKS.items():
                    for end_key, end_delta in self.CLOCKS.items():
                        a = _activity(
                            type=activity_type,
                            status=status,
                            start_at=(now + start_delta) if start_delta else None,
                            end_at=(now + end_delta) if end_delta else None,
                        )
                        label = f"{activity_type}/{status}/start={start_key}/end={end_key}"
                        corrected = self._corrected(a, now)
                        if corrected.status != status:
                            differed += 1

                        for name, legacy, current, needs_user, extra in PAIRS:
                            old = legacy(corrected, user) if needs_user else legacy(corrected)
                            if extra is not None:
                                old = old and extra(a, now)
                            new = current(a, user) if needs_user else current(a)
                            checked += 1
                            if old != new:
                                mismatches.append(f"{label} · {name}: 应然={old} 实际={new}")

        self.assertEqual(
            mismatches, [],
            "新守卫与「旧守卫 + 惰性结算」不等价——说明重构改变了行为，而不只是换了判定来源",
        )
        self.assertGreater(checked, 0)
        self.assertGreater(differed, 0, "没有一行的 status 需要纠正，说明组合枚举或 calc_state 有问题")

    def test_no_diff_when_snapshot_already_fresh(self):
        """快照已经新鲜的行，新旧必须逐字等价（无歧义情形零行为变化）。"""
        now = timezone.now()
        user = _User()
        rows = [
            _activity(type="deliberation", status="open"),
            _activity(type="survey", status="open"),
            _activity(type="exhibition", status="open"),
            _activity(type="deliberation", status="scheduled", start_at=now + FUTURE),
            _activity(type="collection", status="scheduled", start_at=now + FUTURE),
            _activity(type="deliberation", status="closed"),
            _activity(type="survey", status="closed"),
            _activity(type="collection", status="collecting", end_at=now + FUTURE),
            _activity(type="collection", status="reviewing"),
            _activity(type="collection", status="archived"),
        ]
        for a in rows:
            self.assertEqual(S.calc_state(a, now), a.status, "这组数据的前提是快照新鲜")
            for name, legacy, current, needs_user, _extra in PAIRS:
                with self.subTest(activity=(a.type, a.status), guard=name):
                    old = legacy(a, user) if needs_user else legacy(a)
                    new = current(a, user) if needs_user else current(a)
                    self.assertEqual(old, new)


class AcceptingSubmissionsTest(TestCase):
    """征集「此刻是否收件」——B3 修掉的那个缺陷的正身。"""

    def test_collecting_without_deadline_accepts(self):
        self.assertTrue(S.accepting_submissions(_activity(type="collection", status="collecting")))

    def test_collecting_with_future_deadline_accepts(self):
        self.assertTrue(
            S.accepting_submissions(
                _activity(type="collection", status="collecting", end_at=timezone.now() + FUTURE)
            )
        )

    def test_collecting_past_deadline_rejects(self):
        """❌ 旧行为：True（过期仍收稿，直到有人手动「结束收件」）。"""
        self.assertFalse(
            S.accepting_submissions(
                _activity(type="collection", status="collecting", end_at=timezone.now() + PAST)
            )
        )

    def test_due_start_collection_accepts(self):
        """排期已到点、快照还是 scheduled：惰性结果就是收件中。"""
        self.assertTrue(
            S.accepting_submissions(
                _activity(type="collection", status="scheduled", start_at=timezone.now() + PAST)
            )
        )

    def test_future_start_collection_rejects(self):
        self.assertFalse(
            S.accepting_submissions(
                _activity(type="collection", status="scheduled", start_at=timezone.now() + FUTURE)
            )
        )

    def test_reviewing_and_archived_reject(self):
        for stage in (S.REVIEWING, S.ARCHIVED):
            with self.subTest(stage=stage):
                self.assertFalse(
                    S.accepting_submissions(_activity(type="collection", status=stage))
                )

    def test_non_collection_rejects(self):
        self.assertFalse(S.accepting_submissions(_activity(type="deliberation", status="open")))


class CollectionOverdueTransitionTest(TestCase):
    """过期征集要落库推进到 reviewing / archived，不能一直挂在 collecting。"""

    def _collection(self, **kw):
        base = dict(type="collection", status=S.COLLECTING, title="征集")
        base.update(kw)
        return Activity.objects.create(**base)

    def test_overdue_with_review_goes_to_reviewing(self):
        c = self._collection(end_at=timezone.now() + PAST, review_enabled=True)
        moved = L.transition_overdue_collections()
        self.assertIn(c.pk, moved)
        self.assertEqual(Activity.objects.get(pk=c.pk).status, S.REVIEWING)

    def test_overdue_without_review_goes_to_archived(self):
        c = self._collection(end_at=timezone.now() + PAST, review_enabled=False)
        L.transition_overdue_collections()
        self.assertEqual(Activity.objects.get(pk=c.pk).status, S.ARCHIVED)

    def test_not_yet_due_stays_collecting(self):
        c = self._collection(end_at=timezone.now() + FUTURE)
        L.transition_overdue_collections()
        self.assertEqual(Activity.objects.get(pk=c.pk).status, S.COLLECTING)

    def test_permanent_collection_untouched(self):
        c = self._collection(end_at=None)
        L.transition_overdue_collections()
        self.assertEqual(Activity.objects.get(pk=c.pk).status, S.COLLECTING)

    def test_reviewing_not_reverted(self):
        c = self._collection(status=S.REVIEWING, end_at=timezone.now() + PAST)
        L.transition_overdue_collections()
        self.assertEqual(Activity.objects.get(pk=c.pk).status, S.REVIEWING)

    def test_deliberation_untouched(self):
        a = Activity.objects.create(
            type="deliberation", status=S.OPEN, title="众议", max_choices_per_voter=1,
            end_at=timezone.now() + PAST,
        )
        L.transition_overdue_collections()
        self.assertEqual(Activity.objects.get(pk=a.pk).status, S.OPEN)


class ExpiredCollectionSubmitTest(TestCase):
    """端到端回归：征集过期后真的投不进去。

    这是 skill 里记了很久的那条偏差——``transition_overdue`` 的 ``type__in``
    不含 collection，而 ``can_submit`` 只看 status，于是过了截止还能收稿。
    """

    def setUp(self):
        self.user = grant_verification(User.objects.create_user(username="artist", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _collection(self, **kw):
        base = dict(type="collection", status=S.COLLECTING, title="摄影征集")
        base.update(kw)
        return Activity.objects.create(**base)

    def _post(self, pk):
        f = SimpleUploadedFile("photo.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")
        return self.client.post(
            f"/activities/activities/{pk}/submit/", {"files": [f]}, format="multipart",
        )

    def test_submit_blocked_when_past_deadline(self):
        c = self._collection(end_at=timezone.now() + PAST)
        resp = self._post(c.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("征集已结束收件", str(resp.data))
        self.assertEqual(Submission.objects.filter(activity=c).count(), 0)

    def test_can_submit_rejects_without_running_transition(self):
        """即使惰性流转没跑（直接调守卫），也必须拦住。"""
        c = self._collection(end_at=timezone.now() + PAST)
        self.assertFalse(L.can_submit(c, self.user))
        # 落库状态此刻仍是 collecting——这正是「快照滞后」的形态
        self.assertEqual(Activity.objects.get(pk=c.pk).status, S.COLLECTING)

    def test_submit_allowed_before_deadline(self):
        c = self._collection(end_at=timezone.now() + FUTURE)
        resp = self._post(c.pk)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Submission.objects.filter(activity=c).count(), 1)

    def test_submit_allowed_for_permanent_collection(self):
        c = self._collection(end_at=None)
        resp = self._post(c.pk)
        self.assertEqual(resp.status_code, 201, resp.data)
