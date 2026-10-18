"""GET /auth/inbox/ —— 已认证成员的混合待办收件箱（#82）。

单一 HTTP seam：信封 {count, next: null, previous: null, results}；
条目 kind/reason/pinned；投票/投稿/已读/验收后下一 GET 不再出现该行。
活动列表 owed 与收件箱共用同一债谓词，测 GET /activities/activities/。
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from activities.models import Activity, VoteOption
from messaging.models import Conversation, Message
from reviews.test_helpers import approve_activity
from tasks.models import Task

INBOX = "/auth/inbox/"
ACTIVITIES = "/activities/activities/"


def _file(name="a.png"):
    return SimpleUploadedFile(name, b"x", content_type="image/png")


class InboxGateTest(TestCase):
    """门禁与 IsVerified 对齐：匿名/访客 403；已认证（含后台委任）放行。"""

    def setUp(self):
        self.client = APIClient()

    def test_anonymous_denied(self):
        resp = self.client.get(INBOX)
        self.assertIn(resp.status_code, (401, 403))

    def test_visitor_denied(self):
        visitor = User.objects.create_user(username="vis", password="x")
        self.client.force_authenticate(visitor)
        self.assertEqual(self.client.get(INBOX).status_code, 403)

    def test_staff_allowed_via_appointment(self):
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        self.client.force_authenticate(staff)
        self.assertEqual(self.client.get(INBOX).status_code, 200)

    def test_staff_without_appointment_row_denied(self):
        # 标志位不是认证逃生舱：无委任行仍 403（ADR-0013）
        from accounts.models import Verification
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        Verification.objects.filter(user=staff, channel=Verification.CHANNEL_APPOINTMENT).delete()
        self.client.force_authenticate(staff)
        self.assertEqual(self.client.get(INBOX).status_code, 403)

    def test_verified_member_empty_envelope(self):
        member = grant_verification(User.objects.create_user(username="m", password="x"))
        self.client.force_authenticate(member)
        resp = self.client.get(INBOX)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body.keys()), {"count", "next", "previous", "results"})
        self.assertIsNone(body["next"])
        self.assertIsNone(body["previous"])
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["results"], [])

    def test_superuser_allowed_via_appointment(self):
        root = User.objects.create_superuser(username="root", password="x")
        self.client.force_authenticate(root)
        resp = self.client.get(INBOX)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_superuser_without_appointment_row_denied(self):
        from accounts.models import Verification
        root = User.objects.create_superuser(username="root", password="x")
        Verification.objects.filter(user=root, channel=Verification.CHANNEL_APPOINTMENT).delete()
        self.client.force_authenticate(root)
        self.assertEqual(self.client.get(INBOX).status_code, 403)


class InboxActivityDebtTest(TestCase):
    """活动债：众议/征集/展示谓词，以及投票、投稿后从收件箱消失。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.member = grant_verification(User.objects.create_user(username="member", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.member)

    def _deliberation(self, **kwargs):
        now = timezone.now()
        defaults = dict(
            type="deliberation", status="open", title="众议",
            creator=self.author, end_at=now + timedelta(days=3),
        )
        defaults.update(kwargs)
        a = Activity.objects.create(**defaults)
        approve_activity(a)
        VoteOption.objects.create(activity=a, text="A", order=0)
        VoteOption.objects.create(activity=a, text="B", order=1)
        return a

    def _collection(self, **kwargs):
        defaults = dict(type="collection", status="collecting", title="征集", creator=self.author)
        defaults.update(kwargs)
        a = Activity.objects.create(**defaults)
        return approve_activity(a)

    def _exhibition(self, *, voting_enabled=True, **kwargs):
        defaults = dict(
            type="exhibition", status="open", title="展示",
            creator=self.author, voting_enabled=voting_enabled,
        )
        defaults.update(kwargs)
        a = Activity.objects.create(**defaults)
        return approve_activity(a)

    def _inbox(self):
        resp = self.client.get(INBOX)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _row_for(self, activity_id):
        for item in self._inbox()["results"]:
            if item["kind"] == "activity" and item["activity"]["id"] == activity_id:
                return item
        return None

    def test_open_deliberation_without_ballot_is_vote(self):
        a = self._deliberation(title="该投票")
        row = self._row_for(a.pk)
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "vote")
        self.assertEqual(row["kind"], "activity")
        self.assertFalse(row["pinned"])
        self.assertEqual(row["activity"]["title"], "该投票")
        self.assertIsNotNone(row["end_at"])
        self.assertIsNone(row["task"])
        self.assertIsNone(row["conversation"])

    def test_vote_removes_deliberation_row(self):
        a = self._deliberation()
        opt = a.options.order_by("order").first()
        vote = self.client.post(
            f"{ACTIVITIES}{a.pk}/vote/",
            {"option_ids": [opt.pk]},
            format="json",
        )
        self.assertEqual(vote.status_code, 200)
        self.assertIsNone(self._row_for(a.pk))

    def test_creator_still_owes_own_open_deliberation(self):
        a = self._deliberation()
        self.client.force_authenticate(self.author)
        self.assertIsNotNone(self._row_for(a.pk))
        self.assertEqual(self._row_for(a.pk)["reason"], "vote")

    def test_scheduled_and_closed_deliberation_absent(self):
        self._deliberation(status="scheduled", title="待开始")
        self._deliberation(status="closed", title="已结束")
        kinds = [r["activity"]["title"] for r in self._inbox()["results"] if r["kind"] == "activity"]
        self.assertEqual(kinds, [])

    def test_collecting_without_submission_is_submit(self):
        a = self._collection(title="该投稿")
        row = self._row_for(a.pk)
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "submit")

    def test_submit_removes_collection_row(self):
        a = self._collection()
        resp = self.client.post(f"{ACTIVITIES}{a.pk}/submit/", {"files": [_file()]})
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(self._row_for(a.pk))

    def test_collection_not_in_inbox_outside_collecting(self):
        for status in ("scheduled", "reviewing", "archived"):
            self._collection(status=status, title=status)
        self.assertEqual(self._inbox()["count"], 0)

    def test_exhibition_with_voting_is_vote(self):
        a = self._exhibition(voting_enabled=True, title="该投展")
        row = self._row_for(a.pk)
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "vote")

    def test_exhibition_ratings_only_absent(self):
        self._exhibition(voting_enabled=False, title="只赞踩")
        self.assertEqual(self._inbox()["count"], 0)

    def test_scheduled_exhibition_absent(self):
        self._exhibition(status="scheduled", voting_enabled=True)
        self.assertEqual(self._inbox()["count"], 0)


class InboxPinAndSortTest(TestCase):
    """48h 内截止的活动债置顶（end_at 升序）；其余按 updated_at 降序。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.member = grant_verification(User.objects.create_user(username="member", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.member)
        self.now = timezone.now()

    def _open_delib(self, title, *, end_at, updated_at):
        a = Activity.objects.create(
            type="deliberation", status="open", title=title,
            creator=self.author, end_at=end_at,
        )
        approve_activity(a)
        VoteOption.objects.create(activity=a, text="A", order=0)
        VoteOption.objects.create(activity=a, text="B", order=1)
        Activity.objects.filter(pk=a.pk).update(updated_at=updated_at)
        a.refresh_from_db()
        return a

    def test_soonest_deadline_pinned_first_then_recency(self):
        soon = self._open_delib(
            "即将截止",
            end_at=self.now + timedelta(hours=2),
            updated_at=self.now - timedelta(days=5),
        )
        later_pin = self._open_delib(
            "明天截止",
            end_at=self.now + timedelta(hours=24),
            updated_at=self.now - timedelta(hours=1),
        )
        far = self._open_delib(
            "三天后",
            end_at=self.now + timedelta(hours=72),
            updated_at=self.now - timedelta(hours=3),
        )
        task = Task.objects.create(
            title="进行中的债", creator=self.author,
            assignee=self.member, status="in_progress",
        )
        Task.objects.filter(pk=task.pk).update(updated_at=self.now - timedelta(hours=2))

        body = self.client.get(INBOX).json()
        titles = []
        for item in body["results"]:
            if item["kind"] == "activity":
                titles.append(item["activity"]["title"])
            elif item["kind"] == "task":
                titles.append(item["task"]["title"])
        self.assertEqual(titles, ["即将截止", "明天截止", "进行中的债", "三天后"])
        self.assertTrue(body["results"][0]["pinned"])
        self.assertTrue(body["results"][1]["pinned"])
        self.assertFalse(body["results"][2]["pinned"])
        self.assertFalse(body["results"][3]["pinned"])
        self.assertEqual(body["results"][0]["activity"]["id"], soon.pk)
        self.assertEqual(body["results"][1]["activity"]["id"], later_pin.pk)
        self.assertEqual(body["results"][2]["task"]["id"], task.pk)
        self.assertEqual(body["results"][3]["activity"]["id"], far.pk)


class InboxTaskDebtTest(TestCase):
    """任务债：进行中的负责人/协作者、待验收/待批认领的创建人。不收录全社墙。"""

    def setUp(self):
        self.creator = grant_verification(User.objects.create_user(username="creator", password="x"))
        self.assignee = grant_verification(User.objects.create_user(username="assignee", password="x"))
        self.collab = grant_verification(User.objects.create_user(username="collab", password="x"))
        self.other = grant_verification(User.objects.create_user(username="other", password="x"))
        self.client = APIClient()

    def _inbox(self, user):
        self.client.force_authenticate(user)
        resp = self.client.get(INBOX)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _task_row(self, user, task_id):
        for item in self._inbox(user)["results"]:
            if item["kind"] == "task" and item["task"]["id"] == task_id:
                return item
        return None

    def test_assignee_in_progress_is_complete(self):
        t = Task.objects.create(
            title="做完", creator=self.creator, assignee=self.assignee, status="in_progress",
        )
        row = self._task_row(self.assignee, t.pk)
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "complete")
        self.assertEqual(row["task"]["title"], "做完")

    def test_collaborator_in_progress_is_complete(self):
        t = Task.objects.create(
            title="协作", creator=self.creator, assignee=self.assignee, status="in_progress",
        )
        t.collaborators.add(self.collab)
        row = self._task_row(self.collab, t.pk)
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "complete")

    def test_creator_of_in_progress_not_assignee_absent(self):
        t = Task.objects.create(
            title="别人的活", creator=self.creator, assignee=self.assignee, status="in_progress",
        )
        self.assertIsNone(self._task_row(self.creator, t.pk))
        self.assertIsNone(self._task_row(self.other, t.pk))

    def test_complete_removes_row(self):
        t = Task.objects.create(
            title="交验收", creator=self.creator, assignee=self.assignee, status="in_progress",
        )
        self.client.force_authenticate(self.assignee)
        resp = self.client.post(f"/tasks/tasks/{t.pk}/complete/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self._task_row(self.assignee, t.pk))

    def test_creator_reviewing_is_approve_completion(self):
        t = Task.objects.create(
            title="待验收", creator=self.creator, assignee=self.assignee, status="reviewing",
        )
        row = self._task_row(self.creator, t.pk)
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "approve_completion")
        self.assertIsNone(self._task_row(self.assignee, t.pk))

    def test_approve_completion_removes_row(self):
        t = Task.objects.create(
            title="验收掉", creator=self.creator, assignee=self.assignee, status="reviewing",
        )
        self.client.force_authenticate(self.creator)
        resp = self.client.post(f"/tasks/tasks/{t.pk}/approve_completion/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self._task_row(self.creator, t.pk))

    def test_creator_review_is_approve_claim(self):
        t = Task.objects.create(title="待批认领", creator=self.creator, status="review")
        row = self._task_row(self.creator, t.pk)
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "approve_claim")

    def test_pending_completed_cancelled_absent(self):
        Task.objects.create(title="待处理墙", creator=self.creator, status="pending")
        Task.objects.create(
            title="已完成", creator=self.creator, assignee=self.assignee, status="completed",
        )
        Task.objects.create(
            title="已取消", creator=self.creator, assignee=self.assignee, status="cancelled",
        )
        self.assertEqual(self._inbox(self.assignee)["count"], 0)
        self.assertEqual(self._inbox(self.other)["count"], 0)
        self.assertEqual(self._inbox(self.creator)["count"], 0)


class InboxOmitsConversationTest(TestCase):
    """私信未读不再进待办（私信有自己的未读计数）。"""

    def setUp(self):
        self.alice = grant_verification(User.objects.create_user(username="alice", password="x"))
        self.bob = grant_verification(User.objects.create_user(username="bob", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.alice)
        self.conv = Conversation.objects.create()
        self.conv.participants.set([self.alice, self.bob])

    def test_unread_dm_is_not_inbox_row(self):
        Message.objects.create(conversation=self.conv, sender=self.bob, content="在吗")
        body = self.client.get(INBOX).json()
        self.assertEqual(body["count"], 0)
        self.assertTrue(all(item["kind"] != "conversation" for item in body["results"]))

    def test_unread_dm_not_mixed_into_task_debt(self):
        Task.objects.create(
            title="进行中", creator=self.bob, assignee=self.alice, status="in_progress",
        )
        Message.objects.create(conversation=self.conv, sender=self.bob, content="在吗")
        body = self.client.get(INBOX).json()
        kinds = [item["kind"] for item in body["results"]]
        self.assertEqual(kinds, ["task"])
        self.assertTrue(all(item["conversation"] is None for item in body["results"]))

    def test_own_message_not_inbox_row(self):
        Message.objects.create(conversation=self.conv, sender=self.alice, content="我自己说的")
        self.assertEqual(self.client.get(INBOX).json()["count"], 0)

    def test_non_participant_conversation_absent(self):
        carol = grant_verification(User.objects.create_user(username="carol", password="x"))
        other = Conversation.objects.create()
        other.participants.set([self.bob, carol])
        Message.objects.create(conversation=other, sender=carol, content="与 alice 无关")
        self.assertEqual(self.client.get(INBOX).json()["count"], 0)


class ActivityListOwedTest(TestCase):
    """列表 owed 与收件箱同一谓词：已认证才有 vote/submit；访客/未债为 null。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.member = grant_verification(User.objects.create_user(username="member", password="x"))
        self.visitor = User.objects.create_user(username="visitor", password="x")
        self.client = APIClient()

    def _create_open_delib(self):
        a = Activity.objects.create(
            type="deliberation", status="open", title="列表众议", creator=self.author,
        )
        approve_activity(a)
        VoteOption.objects.create(activity=a, text="A", order=0)
        VoteOption.objects.create(activity=a, text="B", order=1)
        return a

    def _list_row(self, user, activity_id, **params):
        self.client.force_authenticate(user)
        resp = self.client.get(ACTIVITIES, params)
        self.assertEqual(resp.status_code, 200)
        for row in resp.json()["results"]:
            if row["id"] == activity_id:
                return row
        return None

    def test_verified_member_sees_owed_vote(self):
        a = self._create_open_delib()
        row = self._list_row(self.member, a.pk)
        self.assertEqual(row["owed"], "vote")

    def test_visitor_sees_owed_null(self):
        a = self._create_open_delib()
        row = self._list_row(self.visitor, a.pk)
        self.assertIsNone(row["owed"])

    def test_after_vote_owed_null(self):
        a = self._create_open_delib()
        self.client.force_authenticate(self.member)
        opt = a.options.order_by("order").first()
        self.assertEqual(
            self.client.post(
                f"{ACTIVITIES}{a.pk}/vote/", {"option_ids": [opt.pk]}, format="json",
            ).status_code,
            200,
        )
        row = self._list_row(self.member, a.pk)
        self.assertIsNone(row["owed"])

    def test_collection_owed_submit(self):
        a = approve_activity(Activity.objects.create(
            type="collection", status="collecting", title="列表征集", creator=self.author,
        ))
        row = self._list_row(self.member, a.pk)
        self.assertEqual(row["owed"], "submit")

    def test_exhibition_type_filter_includes_rows(self):
        a = approve_activity(Activity.objects.create(
            type="exhibition", status="open", title="列表展示",
            creator=self.author, voting_enabled=False,
        ))
        row = self._list_row(self.member, a.pk, type="exhibition")
        self.assertIsNotNone(row)
        self.assertEqual(row["type"], "exhibition")
        self.assertIsNone(row["owed"])

    def _detail(self, user, activity_id):
        self.client.force_authenticate(user)
        resp = self.client.get(f"{ACTIVITIES}{activity_id}/")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_detail_owed_matches_list_vote(self):
        a = self._create_open_delib()
        list_row = self._list_row(self.member, a.pk)
        detail = self._detail(self.member, a.pk)
        self.assertEqual(list_row["owed"], "vote")
        self.assertEqual(detail["owed"], list_row["owed"])

    def test_detail_owed_matches_list_after_vote(self):
        a = self._create_open_delib()
        self.client.force_authenticate(self.member)
        opt = a.options.order_by("order").first()
        self.assertEqual(
            self.client.post(
                f"{ACTIVITIES}{a.pk}/vote/", {"option_ids": [opt.pk]}, format="json",
            ).status_code,
            200,
        )
        list_row = self._list_row(self.member, a.pk)
        detail = self._detail(self.member, a.pk)
        self.assertIsNone(list_row["owed"])
        self.assertEqual(detail["owed"], list_row["owed"])

    def test_detail_owed_matches_list_submit(self):
        a = approve_activity(Activity.objects.create(
            type="collection", status="collecting", title="详情征集", creator=self.author,
        ))
        list_row = self._list_row(self.member, a.pk)
        detail = self._detail(self.member, a.pk)
        self.assertEqual(list_row["owed"], "submit")
        self.assertEqual(detail["owed"], list_row["owed"])

    def test_detail_visitor_owed_null_matches_list(self):
        a = self._create_open_delib()
        list_row = self._list_row(self.visitor, a.pk)
        detail = self._detail(self.visitor, a.pk)
        self.assertIsNone(list_row["owed"])
        self.assertEqual(detail["owed"], list_row["owed"])
