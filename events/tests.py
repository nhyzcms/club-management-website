"""活动骨架测试（主 seam：HTTP 黑盒；生命周期另有纯领域用例）。

覆盖：状态流转（scheduled→active→ended）、到点后不可编辑、可见性（游客/成员/
草稿）、创建与发布权限、归档。
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification

from . import lifecycle
from .models import Event


def _user(name, verified=True):
    user = User.objects.create_user(username=name, password="test-pass-123")
    if verified:
        grant_verification(user)
    return user


def _event(organizer, **overrides):
    now = timezone.now()
    data = {
        "title": "明信片互寄送",
        "start_at": now - timedelta(hours=1),
        "end_at": now + timedelta(days=7),
        "status": Event.STATUS_ACTIVE,
        "organizer": organizer,
    }
    data.update(overrides)
    return Event.objects.create(**data)


class EventLifecycleTest(TestCase):
    def test_initial_status_follows_start_at(self):
        now = timezone.now()
        self.assertEqual(
            lifecycle.initial_status(now + timedelta(hours=1)), Event.STATUS_SCHEDULED,
        )
        self.assertEqual(
            lifecycle.initial_status(now - timedelta(hours=1)), Event.STATUS_ACTIVE,
        )

    def test_touch_opens_scheduled_and_closes_overdue(self):
        now = timezone.now()
        organizer = _user("org")
        due = _event(
            organizer, status=Event.STATUS_SCHEDULED,
            start_at=now - timedelta(minutes=1), end_at=now + timedelta(days=1),
        )
        over = _event(
            organizer, status=Event.STATUS_ACTIVE,
            start_at=now - timedelta(days=2), end_at=now - timedelta(minutes=1),
        )

        opened, closed = lifecycle.touch()

        self.assertEqual(opened, [due.pk])
        self.assertEqual(closed, [over.pk])
        due.refresh_from_db()
        over.refresh_from_db()
        self.assertEqual(due.status, Event.STATUS_ACTIVE)
        self.assertEqual(over.status, Event.STATUS_ENDED)

    def test_touch_ignores_events_without_end(self):
        now = timezone.now()
        organizer = _user("org")
        running = _event(
            organizer, end_at=None,
            start_at=now - timedelta(days=30), status=Event.STATUS_ACTIVE,
        )

        lifecycle.touch()

        running.refresh_from_db()
        self.assertEqual(running.status, Event.STATUS_ACTIVE)

    def test_edit_and_participate_guards(self):
        organizer = _user("org")
        draft = _event(organizer, status=Event.STATUS_DRAFT)
        active = _event(organizer, status=Event.STATUS_ACTIVE)
        ended = _event(organizer, status=Event.STATUS_ENDED)

        self.assertTrue(lifecycle.can_edit(draft, organizer))
        # active 起锁定：进行中改时间会让已报名的参与者困惑
        self.assertFalse(lifecycle.can_edit(active, organizer))
        self.assertFalse(lifecycle.can_edit(ended, organizer))

        self.assertFalse(lifecycle.can_participate(draft, organizer))
        self.assertTrue(lifecycle.can_participate(active, organizer))
        self.assertFalse(lifecycle.can_participate(ended, organizer))


class EventApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.organizer = _user("organizer")
        self.member = _user("member")
        self.now = timezone.now()

    def _post(self, path, user=None, payload=None):
        if user is not None:
            self.client.force_authenticate(user)
        return self.client.post(path, data=payload or {}, format="json")

    def test_guest_sees_only_public_non_draft(self):
        _event(self.organizer, title="公开进行中", visibility=Event.VISIBILITY_PUBLIC)
        _event(self.organizer, title="仅成员", visibility=Event.VISIBILITY_MEMBERS)
        _event(
            self.organizer, title="公开草稿", visibility=Event.VISIBILITY_PUBLIC,
            status=Event.STATUS_DRAFT,
        )

        resp = self.client.get("/events/")

        self.assertEqual(resp.status_code, 200)
        titles = [row["title"] for row in resp.data["results"]] if "results" in resp.data else [
            row["title"] for row in resp.data
        ]
        self.assertIn("公开进行中", titles)
        self.assertNotIn("仅成员", titles)
        self.assertNotIn("公开草稿", titles)

    def test_member_sees_members_only_event(self):
        _event(self.organizer, title="仅成员", visibility=Event.VISIBILITY_MEMBERS)
        self.client.force_authenticate(self.member)

        resp = self.client.get("/events/")

        self.assertEqual(resp.status_code, 200)
        titles = [row["title"] for row in resp.data["results"]] if "results" in resp.data else [
            row["title"] for row in resp.data
        ]
        self.assertIn("仅成员", titles)

    def test_draft_visible_to_organizer_only(self):
        draft = _event(
            self.organizer, title="我的草稿",
            visibility=Event.VISIBILITY_PUBLIC, status=Event.STATUS_DRAFT,
        )
        self.client.force_authenticate(self.member)
        self.assertEqual(
            self.client.get(f"/events/{draft.pk}/").status_code, 404,
        )
        self.client.force_authenticate(self.organizer)
        self.assertEqual(
            self.client.get(f"/events/{draft.pk}/").status_code, 200,
        )

    def test_create_requires_login(self):
        # 本站用 SessionAuthentication（无 WWW-Authenticate 头），未登录一律 403
        resp = self._post("/events/", payload={"title": "x", "start_at": self.now.isoformat()})
        self.assertEqual(resp.status_code, 403)

    def test_create_requires_verified(self):
        plain = _user("plain", verified=False)
        resp = self._post(
            "/events/", plain,
            {"title": "x", "start_at": self.now.isoformat()},
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_starts_as_draft(self):
        resp = self._post(
            "/events/", self.organizer,
            {"title": "新活动", "start_at": (self.now + timedelta(days=1)).isoformat()},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], Event.STATUS_DRAFT)
        self.assertEqual(resp.data["organizer"]["username"], "organizer")

    def test_publish_scheduled_or_active(self):
        future = _event(
            self.organizer, status=Event.STATUS_DRAFT,
            start_at=self.now + timedelta(days=1), end_at=self.now + timedelta(days=2),
        )
        now_event = _event(
            self.organizer, status=Event.STATUS_DRAFT,
            start_at=self.now - timedelta(hours=1), end_at=self.now + timedelta(days=1),
        )

        r1 = self._post(f"/events/{future.pk}/publish/", self.organizer)
        r2 = self._post(f"/events/{now_event.pk}/publish/", self.organizer)

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.data["status"], Event.STATUS_SCHEDULED)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["status"], Event.STATUS_ACTIVE)

    def test_publish_twice_rejected(self):
        event = _event(self.organizer, status=Event.STATUS_DRAFT)
        self._post(f"/events/{event.pk}/publish/", self.organizer)
        resp = self._post(f"/events/{event.pk}/publish/", self.organizer)
        self.assertEqual(resp.status_code, 400)

    def test_ended_event_cannot_be_edited(self):
        event = _event(
            self.organizer, status=Event.STATUS_ACTIVE,
            start_at=self.now - timedelta(days=2), end_at=self.now - timedelta(minutes=1),
        )
        self.client.force_authenticate(self.organizer)

        resp = self.client.patch(
            f"/events/{event.pk}/", data={"title": "改不动"}, format="json",
        )

        self.assertEqual(resp.status_code, 403)
        event.refresh_from_db()
        self.assertEqual(event.status, Event.STATUS_ENDED)

    def test_archive_only_after_ended(self):
        active = _event(self.organizer, status=Event.STATUS_ACTIVE)
        ended = _event(
            self.organizer, status=Event.STATUS_ENDED,
            start_at=self.now - timedelta(days=2), end_at=self.now - timedelta(days=1),
        )

        self.assertEqual(
            self._post(f"/events/{active.pk}/archive/", self.organizer).status_code, 400,
        )
        resp = self._post(f"/events/{ended.pk}/archive/", self.organizer)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], Event.STATUS_ARCHIVED)

    def test_delete_only_draft(self):
        draft = _event(self.organizer, status=Event.STATUS_DRAFT)
        active = _event(self.organizer, status=Event.STATUS_ACTIVE)
        self.client.force_authenticate(self.organizer)

        self.assertEqual(self.client.delete(f"/events/{active.pk}/").status_code, 403)
        self.assertEqual(self.client.delete(f"/events/{draft.pk}/").status_code, 204)

    def test_non_organizer_cannot_edit(self):
        # 草稿对非组织者不可见 → 404（不暴露存在性）
        draft = _event(self.organizer, status=Event.STATUS_DRAFT)
        # 已公开的活动可见但不可改 → 403
        public = _event(
            self.organizer, status=Event.STATUS_SCHEDULED,
            start_at=self.now + timedelta(days=1), end_at=self.now + timedelta(days=2),
        )
        self.client.force_authenticate(self.member)

        self.assertEqual(
            self.client.patch(
                f"/events/{draft.pk}/", data={"title": "越权"}, format="json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/events/{public.pk}/", data={"title": "越权"}, format="json",
            ).status_code,
            403,
        )

    def test_rejects_end_before_start(self):
        resp = self._post(
            "/events/", self.organizer,
            {
                "title": "时间倒挂",
                "start_at": (self.now + timedelta(days=2)).isoformat(),
                "end_at": (self.now + timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("end_at", resp.data)
