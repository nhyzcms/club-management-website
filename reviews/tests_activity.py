"""活动接入统一审核（#80 / T11）。

Seams（HTTP 公共接口）：
- ``POST/GET /activities/activities/``：创建后的成员可见性、作者/审核员预览
- ``GET/POST /reviews/reviews/``：统一队列对活动 通过/驳回/下架
- 活动自身生命周期（scheduled → open）不因待审而停转
"""
from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from reviews.models import Review
from common.testing import set_policy


def _grant(user, app_label, *codenames):
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return user


def _author():
    return grant_verification(User.objects.create_user(username="author", password="x"))


def _moderator():
    user = grant_verification(User.objects.create_user(username="mod", password="x"))
    return _grant(user, "reviews", "moderate")


def _publisher():
    user = grant_verification(User.objects.create_user(username="pub", password="x"))
    return _grant(user, "reviews", "force_publish")


def _ids(resp):
    return [row["id"] for row in resp.data["results"]]


def _create(client, user, **extra):
    client.force_authenticate(user)
    payload = {
        "type": "deliberation",
        "title": extra.pop("title", "待审活动"),
        "body": "<p>x</p>",
        "option_texts": ["A", "B"],
        **extra,
    }
    return client.post("/activities/activities/", payload, format="json")


class ActivitySubmitEntersPendingTest(TestCase):
    """非免审发布者提交活动 → 待审；其他成员列表/详情读不到。"""

    def setUp(self):
        self.author = _author()
        self.other = grant_verification(User.objects.create_user(username="other", password="x"))
        self.client = APIClient()

    def test_create_without_force_publish_is_hidden_from_others(self):
        resp = _create(self.client, self.author)
        self.assertEqual(resp.status_code, 201)
        activity_id = resp.data["id"]
        self.assertEqual(resp.data.get("review_status"), "pending")

        other = APIClient()
        other.force_authenticate(self.other)
        listing = other.get("/activities/activities/")
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn(activity_id, _ids(listing))
        self.assertEqual(other.get(f"/activities/activities/{activity_id}/").status_code, 404)


class ActivityContentReviewDisabledTest(TestCase):
    """content_review_enabled=False → 新建活动直接通过。"""

    def setUp(self):
        super().setUp()
        cache.clear()
        set_policy(content_review_enabled=False)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_create_without_force_publish_is_approved(self):
        resp = _create(APIClient(), _author(), title="免审活动")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["review_status"], "approved")


class ActivityForcePublishSkipsReviewTest(TestCase):
    """持 force_publish 者新建活动直接公开。"""

    def test_create_with_force_publish_is_visible(self):
        client = APIClient()
        resp = _create(client, _publisher(), title="直发活动")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["review_status"], "approved")
        activity_id = resp.data["id"]

        other = grant_verification(User.objects.create_user(username="o", password="x"))
        reader = APIClient()
        reader.force_authenticate(other)
        self.assertIn(activity_id, _ids(reader.get("/activities/activities/")))
        self.assertEqual(reader.get(f"/activities/activities/{activity_id}/").status_code, 200)


class ActivityCreatorAndModeratorPreviewTest(TestCase):
    """待审活动对创建者/审核员可见，对其他成员隐藏。"""

    def setUp(self):
        self.author = _author()
        self.mod = _moderator()
        self.other = grant_verification(User.objects.create_user(username="other", password="x"))
        writer = APIClient()
        created = _create(writer, self.author, title="预览活动")
        self.activity_id = created.data["id"]

    def test_author_can_retrieve_pending(self):
        client = APIClient()
        client.force_authenticate(self.author)
        resp = client.get(f"/activities/activities/{self.activity_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["review_status"], "pending")

    def test_moderator_can_retrieve_pending(self):
        client = APIClient()
        client.force_authenticate(self.mod)
        self.assertEqual(client.get(f"/activities/activities/{self.activity_id}/").status_code, 200)

    def test_other_member_cannot_retrieve_pending(self):
        client = APIClient()
        client.force_authenticate(self.other)
        self.assertEqual(client.get(f"/activities/activities/{self.activity_id}/").status_code, 404)


class ActivityReviewQueueActionsTest(TestCase):
    """审核员从统一队列对活动 通过 / 驳回 / 下架。"""

    def setUp(self):
        self.author = _author()
        self.mod = _moderator()
        self.other = grant_verification(User.objects.create_user(username="other", password="x"))
        created = _create(APIClient(), self.author, title="队列活动")
        self.activity_id = created.data["id"]
        self.review_id = Review.objects.get(activity_id=self.activity_id).pk
        self.client = APIClient()
        self.client.force_authenticate(self.mod)

    def test_queue_lists_pending_activity(self):
        resp = self.client.get("/reviews/reviews/?status=pending")
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_type"], "activity")
        self.assertEqual(rows[0]["target_id"], self.activity_id)
        self.assertEqual(rows[0]["title"], "队列活动")

    def test_approve_makes_activity_visible(self):
        resp = self.client.post(f"/reviews/reviews/{self.review_id}/approve/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "approved")

        reader = APIClient()
        reader.force_authenticate(self.other)
        self.assertIn(self.activity_id, _ids(reader.get("/activities/activities/")))

    def test_reject_keeps_activity_hidden(self):
        resp = self.client.post(
            f"/reviews/reviews/{self.review_id}/reject/",
            {"comment": "主题不符"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "rejected")

        reader = APIClient()
        reader.force_authenticate(self.other)
        self.assertNotIn(self.activity_id, _ids(reader.get("/activities/activities/")))

    def test_remove_hides_approved_activity(self):
        self.client.post(f"/reviews/reviews/{self.review_id}/approve/")
        resp = self.client.post(f"/reviews/reviews/{self.review_id}/remove/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "removed")

        reader = APIClient()
        reader.force_authenticate(self.other)
        self.assertNotIn(self.activity_id, _ids(reader.get("/activities/activities/")))

    def test_author_preview_includes_reject_comment(self):
        self.client.post(
            f"/reviews/reviews/{self.review_id}/reject/",
            {"comment": "主题不符"},
            format="json",
        )
        author = APIClient()
        author.force_authenticate(self.author)
        resp = author.get(f"/activities/activities/{self.activity_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["review_status"], "rejected")
        self.assertEqual(resp.data["review_comment"], "主题不符")


class ActivityMineListTest(TestCase):
    """作者预览列表含待审活动；成员公开列表不含。"""

    def test_mine_includes_pending_and_public_list_does_not(self):
        author = _author()
        other = grant_verification(User.objects.create_user(username="peer", password="x"))
        client = APIClient()
        created = _create(client, author, title="我的待审活动")
        activity_id = created.data["id"]
        mine = client.get("/activities/activities/mine/")
        self.assertEqual(mine.status_code, 200)
        self.assertIn(activity_id, _ids(mine))

        peer = APIClient()
        peer.force_authenticate(other)
        self.assertNotIn(activity_id, _ids(peer.get("/activities/activities/")))

    def test_anonymous_mine_is_denied(self):
        self.assertIn(APIClient().get("/activities/activities/mine/").status_code, (401, 403))


class ActivityLifecycleNotBlockedByReviewTest(TestCase):
    """待审期间活动自身生命周期仍推进（scheduled → open），只是对公众不可见。"""

    def test_scheduled_opens_while_pending_but_stays_hidden(self):
        author = _author()
        other = grant_verification(User.objects.create_user(username="o", password="x"))
        start_at = (timezone.now() - timedelta(hours=1)).isoformat()
        client = APIClient()
        resp = _create(client, author, title="排期众议", start_at=start_at)
        self.assertEqual(resp.status_code, 201)
        activity_id = resp.data["id"]
        self.assertEqual(resp.data["review_status"], "pending")

        # 创建者预览：到点后应变为 open
        author_client = APIClient()
        author_client.force_authenticate(author)
        detail = author_client.get(f"/activities/activities/{activity_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], "open")
        self.assertEqual(detail.data["review_status"], "pending")

        other_client = APIClient()
        other_client.force_authenticate(other)
        self.assertEqual(other_client.get(f"/activities/activities/{activity_id}/").status_code, 404)
