"""活动生命周期模块的接口测试（次 seam：直接调用纯领域逻辑，不经 HTTP）。

与 activities/tests.py 的 HTTP 黑盒相对——本文件只测 lifecycle 对外契约。
T2：initial_status / can_vote / transition_overdue。
"""

from datetime import timedelta

from django.contrib.auth.models import AnonymousUser, Permission, User
from django.test import TestCase
from django.utils import timezone

from accounts.test_helpers import grant_verification

from .lifecycle import (
    ARCHIVED,
    CLOSED,
    COLLECTING,
    OPEN,
    REVIEWING,
    SCHEDULED,
    archive,
    can_archive,
    can_curate,
    can_edit_exhibit,
    can_edit_schema,
    can_respond,
    can_vote,
    initial_status,
    transition_overdue,
)
from .models import Activity, QuestionnaireResponse


class InitialStatusTest(TestCase):
    def test_deliberation_opens_open(self):
        self.assertEqual(initial_status("deliberation"), OPEN)

    def test_collection_opens_collecting(self):
        self.assertEqual(initial_status("collection"), COLLECTING)

    def test_exhibition_opens_open(self):
        self.assertEqual(initial_status("exhibition"), OPEN)

    def test_survey_opens_open(self):
        self.assertEqual(initial_status("survey"), OPEN)

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            initial_status("bogus")


class CanVoteTest(TestCase):
    def setUp(self):
        self.user = grant_verification(User.objects.create_user(username="u", password="x"))
        self.deliberation = Activity.objects.create(
            type="deliberation", status=OPEN, title="d", max_choices_per_voter=1,
        )
        self.collection = Activity.objects.create(type="collection", status=COLLECTING, title="c")
        self.closed = Activity.objects.create(
            type="deliberation", status=CLOSED, title="x", max_choices_per_voter=1,
        )
        # 展示：默认不启用投票（纯陈列）；启用投票时才可投。
        self.exhibit_pure = Activity.objects.create(
            type="exhibition", status=OPEN, title="e_pure", voting_enabled=False,
        )
        self.exhibit_voting = Activity.objects.create(
            type="exhibition", status=OPEN, title="e_voting", voting_enabled=True,
        )

    def test_open_deliberation_allows_vote(self):
        self.assertTrue(can_vote(self.deliberation, self.user))

    def test_closed_deliberation_blocks_vote(self):
        self.assertFalse(can_vote(self.closed, self.user))

    def test_collection_not_votable(self):
        self.assertFalse(can_vote(self.collection, self.user))

    def test_anonymous_cannot_vote(self):
        self.assertFalse(can_vote(self.deliberation, AnonymousUser()))

    def test_exhibition_voting_disabled_blocks_vote(self):
        # 展示纯陈列（未启用投票）不可投票
        self.assertFalse(can_vote(self.exhibit_pure, self.user))

    def test_exhibition_voting_enabled_allows_vote(self):
        # 展示启用投票时方可投
        self.assertTrue(can_vote(self.exhibit_voting, self.user))

    def test_public_deliberation_allows_guest(self):
        # 公开受众：游客（未登录）也可投
        self.deliberation.audience = "public"
        self.deliberation.save(update_fields=["audience"])
        self.assertTrue(can_vote(self.deliberation, AnonymousUser()))

    def test_public_closed_deliberation_blocks_guest(self):
        self.closed.audience = "public"
        self.closed.save(update_fields=["audience"])
        self.assertFalse(can_vote(self.closed, AnonymousUser()))


class TransitionOverdueTest(TestCase):
    def test_overdue_open_flips_to_closed(self):
        a = Activity.objects.create(
            type="deliberation", status=OPEN, title="d", max_choices_per_voter=1,
            end_at=timezone.now() - timedelta(minutes=1),
        )
        closed = transition_overdue()
        self.assertIn(a.pk, closed)
        self.assertEqual(Activity.objects.get(pk=a.pk).status, CLOSED)

    def test_not_yet_due_stays_open(self):
        a = Activity.objects.create(
            type="deliberation", status=OPEN, title="d", max_choices_per_voter=1,
            end_at=timezone.now() + timedelta(days=1),
        )
        transition_overdue()
        self.assertEqual(Activity.objects.get(pk=a.pk).status, OPEN)

    def test_collection_not_affected(self):
        # 征集即便 end_at 过去也不被众议结算触碰
        c = Activity.objects.create(
            type="collection", status=COLLECTING, title="c",
            end_at=timezone.now() - timedelta(minutes=1),
        )
        transition_overdue()
        self.assertEqual(Activity.objects.get(pk=c.pk).status, COLLECTING)

    def test_permanent_activity_never_closes(self):
        # 长期活动（end_at 为空）不参与惰性结算，只能手动 close
        a = Activity.objects.create(
            type="deliberation", status=OPEN, title="p", max_choices_per_voter=1,
            is_permanent=True, end_at=None,
        )
        closed = transition_overdue()
        self.assertNotIn(a.pk, closed)
        self.assertEqual(Activity.objects.get(pk=a.pk).status, OPEN)

    def test_overdue_survey_flips_to_closed(self):
        a = Activity.objects.create(
            type="survey", status=OPEN, title="s",
            end_at=timezone.now() - timedelta(minutes=1),
        )
        closed = transition_overdue()
        self.assertIn(a.pk, closed)
        self.assertEqual(Activity.objects.get(pk=a.pk).status, CLOSED)


class CanCurateTest(TestCase):
    def setUp(self):
        self.user = grant_verification(User.objects.create_user(username="u", password="x"))
        self.exhibit_scheduled = Activity.objects.create(
            type="exhibition", status=SCHEDULED, title="e",
        )
        self.exhibit_open = Activity.objects.create(
            type="exhibition", status=OPEN, title="e2",
        )
        self.exhibit_closed = Activity.objects.create(
            type="exhibition", status=CLOSED, title="e3",
        )
        self.deliberation = Activity.objects.create(
            type="deliberation", status=SCHEDULED, title="d", max_choices_per_voter=1,
        )

    def test_scheduled_exhibition_allows_curate(self):
        self.assertTrue(can_curate(self.exhibit_scheduled, self.user))

    def test_open_exhibition_allows_curate(self):
        self.assertTrue(can_curate(self.exhibit_open, self.user))

    def test_closed_exhibition_blocks_curate(self):
        self.assertFalse(can_curate(self.exhibit_closed, self.user))

    def test_non_exhibition_blocks_curate(self):
        self.assertFalse(can_curate(self.deliberation, self.user))

    def test_anonymous_cannot_curate(self):
        self.assertFalse(can_curate(self.exhibit_scheduled, AnonymousUser()))

    def test_scheduled_exhibition_allows_edit_exhibit(self):
        self.assertTrue(can_edit_exhibit(self.exhibit_scheduled, self.user))

    def test_open_exhibition_blocks_edit_exhibit(self):
        self.assertFalse(can_edit_exhibit(self.exhibit_open, self.user))

    def test_closed_exhibition_blocks_edit_exhibit(self):
        self.assertFalse(can_edit_exhibit(self.exhibit_closed, self.user))

    def test_non_exhibition_blocks_edit_exhibit(self):
        self.assertFalse(can_edit_exhibit(self.deliberation, self.user))

    def test_anonymous_cannot_edit_exhibit(self):
        self.assertFalse(can_edit_exhibit(self.exhibit_scheduled, AnonymousUser()))


class CanEditSchemaTest(TestCase):
    def setUp(self):
        self.user = grant_verification(User.objects.create_user(username="u", password="x"))
        self.scheduled = Activity.objects.create(type="survey", status=SCHEDULED, title="s")
        self.open = Activity.objects.create(type="survey", status=OPEN, title="o")
        self.closed = Activity.objects.create(type="survey", status=CLOSED, title="c")
        self.deliberation = Activity.objects.create(
            type="deliberation", status=OPEN, title="d", max_choices_per_voter=1,
        )

    def test_scheduled_survey_allows_schema_edit(self):
        self.assertTrue(can_edit_schema(self.scheduled))

    def test_open_survey_with_zero_responses_allows_schema_edit(self):
        self.assertTrue(can_edit_schema(self.open))

    def test_open_survey_with_response_blocks_schema_edit(self):
        QuestionnaireResponse.objects.create(
            questionnaire=self.open.questionnaire, user=self.user, answers={"q": "a"},
        )
        self.assertFalse(can_edit_schema(self.open))

    def test_closed_survey_blocks_schema_edit(self):
        self.assertFalse(can_edit_schema(self.closed))

    def test_non_survey_blocks_schema_edit(self):
        self.assertFalse(can_edit_schema(self.deliberation))


class CanRespondTest(TestCase):
    def setUp(self):
        self.user = grant_verification(User.objects.create_user(username="u", password="x"))
        self.public_open = Activity.objects.create(
            type="survey", status=OPEN, title="p", audience="public",
        )
        self.members_open = Activity.objects.create(
            type="survey", status=OPEN, title="m", audience="members",
        )
        self.public_closed = Activity.objects.create(
            type="survey", status=CLOSED, title="c", audience="public",
        )
        self.scheduled = Activity.objects.create(
            type="survey", status=SCHEDULED, title="s", audience="public",
        )
        self.deliberation = Activity.objects.create(
            type="deliberation", status=OPEN, title="d", max_choices_per_voter=1,
        )

    def test_public_open_allows_anonymous(self):
        self.assertTrue(can_respond(self.public_open, AnonymousUser()))

    def test_members_open_blocks_anonymous(self):
        self.assertFalse(can_respond(self.members_open, AnonymousUser()))

    def test_members_open_allows_authenticated(self):
        self.assertTrue(can_respond(self.members_open, self.user))

    def test_closed_blocks_respond(self):
        self.assertFalse(can_respond(self.public_closed, AnonymousUser()))

    def test_scheduled_blocks_respond(self):
        self.assertFalse(can_respond(self.scheduled, self.user))

    def test_non_survey_blocks_respond(self):
        self.assertFalse(can_respond(self.deliberation, self.user))


class ArchiveTest(TestCase):
    def setUp(self):
        self.owner = grant_verification(User.objects.create_user(username="owner", password="x"))
        self.other = grant_verification(User.objects.create_user(username="other", password="x"))
        self.staff = grant_verification(User.objects.create_user(username="staff", password="x"))
        self.staff.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="activities", codename="manage_activity",
            )
        )
        self.staff = User.objects.get(pk=self.staff.pk)

    def test_collecting_archives(self):
        activity = Activity.objects.create(
            type="collection", status=COLLECTING, title="c", creator=self.owner,
        )
        self.assertTrue(archive(activity, self.owner))
        activity.refresh_from_db()
        self.assertEqual(activity.status, ARCHIVED)

    def test_reviewing_archives(self):
        activity = Activity.objects.create(
            type="collection", status=REVIEWING, title="r", creator=self.owner,
        )
        self.assertTrue(can_archive(activity, self.owner))
        self.assertTrue(archive(activity, self.owner))
        activity.refresh_from_db()
        self.assertEqual(activity.status, ARCHIVED)

    def test_staff_with_manage_activity_can_archive(self):
        activity = Activity.objects.create(
            type="collection", status=COLLECTING, title="c", creator=self.owner,
        )
        self.assertTrue(archive(activity, self.staff))

    def test_outsider_cannot_archive(self):
        activity = Activity.objects.create(
            type="collection", status=COLLECTING, title="c", creator=self.owner,
        )
        self.assertFalse(archive(activity, self.other))
        activity.refresh_from_db()
        self.assertEqual(activity.status, COLLECTING)

    def test_deliberation_cannot_archive(self):
        activity = Activity.objects.create(
            type="deliberation", status=OPEN, title="d", creator=self.owner,
        )
        self.assertFalse(can_archive(activity, self.owner))
        self.assertFalse(archive(activity, self.owner))
