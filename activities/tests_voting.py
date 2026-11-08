"""投票模块接口测试（次 seam：直接调用 cast_ballot 等，不经 HTTP）。

HTTP 黑盒仍在 activities/tests.py。此处钉选票、选项锁定、秘密票可见性、全员结算。
"""
from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase

from accounts.test_helpers import grant_verification

from .lifecycle import CLOSED, OPEN, SCHEDULED
from .models import Activity, Ballot, VoteOption
from .voting import (
    BallotError,
    ballots_visible_to,
    cast_ballot,
    maybe_close_deliberation_on_full_vote,
    options_locked,
    voting_active,
)


class CastBallotTest(TestCase):
    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.member = grant_verification(User.objects.create_user(username="member", password="x"))
        self.activity = Activity.objects.create(
            type="deliberation", status=OPEN, title="众议",
            creator=self.author, max_choices_per_voter=2,
        )
        self.oa = VoteOption.objects.create(activity=self.activity, text="A", order=0)
        self.ob = VoteOption.objects.create(activity=self.activity, text="B", order=1)
        self.oc = VoteOption.objects.create(activity=self.activity, text="C", order=2)

    def test_cast_ballot_records_selections(self):
        ballot = cast_ballot(
            activity=self.activity, user=self.member, option_ids=[self.oa.pk, self.ob.pk],
        )
        self.assertEqual(ballot.voter_id, self.member.pk)
        self.assertEqual(
            set(ballot.selections.values_list("option_id", flat=True)),
            {self.oa.pk, self.ob.pk},
        )
        self.assertEqual(Ballot.objects.filter(activity=self.activity).count(), 1)

    def test_cast_ballot_rejects_second_ballot(self):
        cast_ballot(activity=self.activity, user=self.member, option_ids=[self.oa.pk])
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=self.activity, user=self.member, option_ids=[self.ob.pk])
        self.assertEqual(ctx.exception.detail, "你已经投过票了，不能修改")

    def test_cast_ballot_rejects_empty(self):
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=self.activity, user=self.member, option_ids=[])
        self.assertEqual(ctx.exception.detail, "请至少选择一个选项")

    def test_cast_ballot_rejects_duplicate_option(self):
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(
                activity=self.activity, user=self.member,
                option_ids=[self.oa.pk, self.oa.pk],
            )
        self.assertEqual(ctx.exception.detail, "不能重复选择同一选项")

    def test_cast_ballot_rejects_over_k(self):
        self.activity.max_choices_per_voter = 1
        self.activity.save(update_fields=["max_choices_per_voter"])
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(
                activity=self.activity, user=self.member,
                option_ids=[self.oa.pk, self.ob.pk],
            )
        self.assertIn("最多选择", ctx.exception.detail)

    def test_cast_ballot_rejects_foreign_option(self):
        other = Activity.objects.create(
            type="deliberation", status=OPEN, title="另一场", max_choices_per_voter=1,
        )
        foreign = VoteOption.objects.create(activity=other, text="X", order=0)
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=self.activity, user=self.member, option_ids=[foreign.pk])
        self.assertEqual(ctx.exception.detail, "存在不属于本活动的选项")

    def test_cast_ballot_rejects_collection(self):
        collection = Activity.objects.create(
            type="collection", status="collecting", title="征集", creator=self.author,
        )
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=collection, user=self.member, option_ids=[1])
        self.assertEqual(ctx.exception.detail, "仅众议/展示可以投票")

    def test_cast_ballot_rejects_closed(self):
        self.activity.status = CLOSED
        self.activity.save(update_fields=["status"])
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=self.activity, user=self.member, option_ids=[self.oa.pk])
        self.assertEqual(ctx.exception.detail, "投票已结束")

    def test_cast_ballot_closes_when_all_verified_voted(self):
        # 本用例已认证成员恰好 2 人
        cast_ballot(activity=self.activity, user=self.member, option_ids=[self.oa.pk])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, OPEN)
        cast_ballot(activity=self.activity, user=self.author, option_ids=[self.ob.pk])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, CLOSED)


class OptionLockAndVisibilityTest(TestCase):
    def setUp(self):
        self.member = grant_verification(User.objects.create_user(username="m", password="x"))
        self.super = User.objects.create_superuser(username="root", password="x")
        self.open_delib = Activity.objects.create(
            type="deliberation", status=OPEN, title="开", max_choices_per_voter=1,
        )
        self.scheduled = Activity.objects.create(
            type="deliberation", status=SCHEDULED, title="待", max_choices_per_voter=1,
        )
        self.secret = Activity.objects.create(
            type="deliberation", status=OPEN, title="密",
            max_choices_per_voter=1, is_secret_ballot=True,
        )
        self.exhibition = Activity.objects.create(
            type="exhibition", status=OPEN, title="展", voting_enabled=True,
        )
        self.pure = Activity.objects.create(
            type="exhibition", status=OPEN, title="陈列", voting_enabled=False,
        )

    def test_options_locked_when_open(self):
        self.assertTrue(options_locked(self.open_delib))

    def test_options_unlocked_when_scheduled(self):
        self.assertFalse(options_locked(self.scheduled))

    def test_exhibition_options_not_locked_by_voting_module(self):
        # 展示选项随展品走 exhibition；展示中仍可加展品/选项
        self.assertFalse(options_locked(self.exhibition))

    def test_voting_active(self):
        self.assertTrue(voting_active(self.open_delib))
        self.assertTrue(voting_active(self.exhibition))
        self.assertFalse(voting_active(self.pure))

    def test_public_ballots_visible_to_member(self):
        self.assertTrue(ballots_visible_to(self.open_delib, self.member))

    def test_secret_hidden_from_member(self):
        self.assertFalse(ballots_visible_to(self.secret, self.member))

    def test_secret_hidden_from_anonymous(self):
        self.assertFalse(ballots_visible_to(self.secret, AnonymousUser()))

    def test_secret_visible_to_superuser(self):
        self.assertTrue(ballots_visible_to(self.secret, self.super))

    def test_pure_exhibition_ballots_not_visible(self):
        self.assertFalse(ballots_visible_to(self.pure, self.member))


class MaybeCloseDeliberationTest(TestCase):
    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="a", password="x"))
        self.member = grant_verification(User.objects.create_user(username="b", password="x"))
        self.activity = Activity.objects.create(
            type="deliberation", status=OPEN, title="结算", max_choices_per_voter=1,
        )
        self.opt = VoteOption.objects.create(activity=self.activity, text="A", order=0)

    def test_does_not_close_until_full(self):
        Ballot.objects.create(activity=self.activity, voter=self.member)
        self.assertFalse(maybe_close_deliberation_on_full_vote(self.activity))
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, OPEN)

    def test_closes_when_full(self):
        Ballot.objects.create(activity=self.activity, voter=self.member)
        Ballot.objects.create(activity=self.activity, voter=self.author)
        self.assertTrue(maybe_close_deliberation_on_full_vote(self.activity))
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, CLOSED)


class GuestBallotTest(TestCase):
    """公开受众：游客按设备标识判重（记录 IP 与设备），成员受众仍拦游客。"""

    DEVICE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="gauthor", password="x"))
        self.activity = Activity.objects.create(
            type="deliberation", status=OPEN, title="公开众议",
            creator=self.author, max_choices_per_voter=1, audience="public",
        )
        self.oa = VoteOption.objects.create(activity=self.activity, text="A", order=0)

    def test_guest_ballot_records_device_and_ip(self):
        ballot = cast_ballot(
            activity=self.activity, user=None, option_ids=[self.oa.pk],
            ip_address="203.0.113.5", device_id=self.DEVICE,
        )
        self.assertIsNone(ballot.voter_id)
        self.assertEqual(ballot.device_id, self.DEVICE)
        self.assertEqual(ballot.voter_ip, "203.0.113.5")

    def test_guest_ballot_requires_device(self):
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=self.activity, user=None, option_ids=[self.oa.pk])
        self.assertEqual(ctx.exception.detail, "缺少设备标识")

    def test_guest_ballot_device_dedup(self):
        cast_ballot(activity=self.activity, user=None, option_ids=[self.oa.pk],
                    device_id=self.DEVICE)
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=self.activity, user=None, option_ids=[self.oa.pk],
                        device_id=self.DEVICE)
        self.assertEqual(ctx.exception.detail, "该设备已投过票，不能重复投票")

    def test_members_audience_rejects_guest(self):
        members = Activity.objects.create(
            type="deliberation", status=OPEN, title="成员众议", max_choices_per_voter=1,
        )
        VoteOption.objects.create(activity=members, text="A", order=0)
        with self.assertRaises(BallotError) as ctx:
            cast_ballot(activity=members, user=None, option_ids=[1])
        self.assertEqual(ctx.exception.detail, "仅成员可投票，请先登录")
