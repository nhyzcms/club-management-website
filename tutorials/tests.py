from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from reviews.models import Review
from tutorials.models import Tutorial
from common.testing import set_policy


def _grant(user, app_label, *codenames):
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return user


def _member(name="mem"):
    return grant_verification(User.objects.create_user(username=name, password="x"))


def _moderator():
    return _grant(_member("mod"), "reviews", "moderate")


def _publisher():
    return _grant(_member("pub"), "reviews", "force_publish")


def _mp4():
    return SimpleUploadedFile("demo.mp4", b"\x00\x00fake-mp4", content_type="video/mp4")


def _ids(resp):
    return [row["id"] for row in resp.data["results"]]


class TutorialUploadTest(TestCase):
    def setUp(self):
        self.user = _member()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_verified_member_uploads_video(self):
        resp = self.client.post(
            "/tutorials/tutorials/",
            {"title": "Ps 入门", "description": "基础", "file": _mp4()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["title"], "Ps 入门")
        self.assertEqual(resp.data["file_type"], "video")
        self.assertEqual(resp.data["review_status"], "pending")
        self.assertNotIn("tags", resp.data)

    def test_unverified_cannot_upload(self):
        guest = User.objects.create_user(username="g", password="x")
        client = APIClient()
        client.force_authenticate(guest)
        resp = client.post(
            "/tutorials/tutorials/",
            {"title": "x", "file": _mp4()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 403)

    def test_rejects_plain_text(self):
        txt = SimpleUploadedFile("a.txt", b"hello", content_type="text/plain")
        resp = self.client.post(
            "/tutorials/tutorials/",
            {"title": "x", "file": txt},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)


class TutorialReviewVisibilityTest(TestCase):
    def setUp(self):
        self.author = _member("author")
        self.other = _member("other")
        self.mod = _moderator()
        writer = APIClient()
        writer.force_authenticate(self.author)
        created = writer.post(
            "/tutorials/tutorials/",
            {"title": "待审教程", "file": _mp4()},
            format="multipart",
        )
        self.tid = created.data["id"]
        self.review_id = Review.objects.get(target__kind="tutorial", target__object_id=self.tid).pk

    def test_public_list_hides_pending(self):
        listing = APIClient().get("/tutorials/tutorials/")
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn(self.tid, _ids(listing))

    def test_author_can_preview(self):
        client = APIClient()
        client.force_authenticate(self.author)
        self.assertEqual(client.get(f"/tutorials/tutorials/{self.tid}/").status_code, 200)

    def test_other_cannot_retrieve_pending(self):
        client = APIClient()
        client.force_authenticate(self.other)
        self.assertEqual(client.get(f"/tutorials/tutorials/{self.tid}/").status_code, 404)

    def test_force_publish_is_public(self):
        client = APIClient()
        client.force_authenticate(_publisher())
        resp = client.post(
            "/tutorials/tutorials/",
            {"title": "直发教程", "file": _mp4()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["review_status"], "approved")
        self.assertIn(resp.data["id"], _ids(APIClient().get("/tutorials/tutorials/")))

    def test_moderator_approve_makes_public(self):
        client = APIClient()
        client.force_authenticate(self.mod)
        resp = client.post(f"/reviews/reviews/{self.review_id}/approve/")
        self.assertEqual(resp.status_code, 200)
        listing = APIClient().get("/tutorials/tutorials/")
        self.assertIn(self.tid, _ids(listing))

    def test_queue_lists_tutorial(self):
        client = APIClient()
        client.force_authenticate(self.mod)
        rows = client.get("/reviews/reviews/?status=pending").data["results"]
        self.assertEqual(rows[0]["target_type"], "tutorial")
        self.assertEqual(rows[0]["title"], "待审教程")

    def test_author_preview_includes_reject_comment(self):
        client = APIClient()
        client.force_authenticate(self.mod)
        client.post(
            f"/reviews/reviews/{self.review_id}/reject/",
            {"comment": "画质不足"},
            format="json",
        )
        author = APIClient()
        author.force_authenticate(self.author)
        resp = author.get(f"/tutorials/tutorials/{self.tid}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["review_status"], "rejected")
        self.assertEqual(resp.data["review_comment"], "画质不足")


class TutorialContentReviewDisabledTest(TestCase):
    """content_review_enabled=False → 新建教程直接通过。"""

    def setUp(self):
        super().setUp()
        cache.clear()
        set_policy(content_review_enabled=False)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_create_without_force_publish_is_approved(self):
        client = APIClient()
        client.force_authenticate(_member("skip"))
        resp = client.post(
            "/tutorials/tutorials/",
            {"title": "免审教程", "file": _mp4()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["review_status"], "approved")


class TutorialFavoriteAndViewsTest(TestCase):
    def setUp(self):
        self.user = _member()
        pub = _publisher()
        writer = APIClient()
        writer.force_authenticate(pub)
        created = writer.post(
            "/tutorials/tutorials/",
            {"title": "公开教程", "file": _mp4()},
            format="multipart",
        )
        self.tid = created.data["id"]
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_favorite_toggle(self):
        r1 = self.client.post(f"/tutorials/tutorials/{self.tid}/favorite/")
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.data["favorited"])
        self.assertEqual(r1.data["favorite_count"], 1)
        r2 = self.client.post(f"/tutorials/tutorials/{self.tid}/favorite/")
        self.assertFalse(r2.data["favorited"])
        self.assertEqual(r2.data["favorite_count"], 0)

    def test_views_deduped_per_user(self):
        for _ in range(3):
            self.client.get(f"/tutorials/tutorials/{self.tid}/")
        t = Tutorial.objects.get(pk=self.tid)
        self.assertEqual(t.views, 1)


class TutorialMineAndOrphanVisibilityTest(TestCase):
    def test_mine_lists_pending_uploads(self):
        author = _member("me")
        client = APIClient()
        client.force_authenticate(author)
        created = client.post(
            "/tutorials/tutorials/",
            {"title": "我的待审", "file": _mp4()},
            format="multipart",
        )
        tid = created.data["id"]
        mine = client.get("/tutorials/tutorials/mine/")
        self.assertIn(tid, _ids(mine))
        self.assertNotIn(tid, _ids(APIClient().get("/tutorials/tutorials/")))

    def test_orphan_without_review_is_not_public(self):
        author = _member("orphan")
        t = Tutorial.objects.create(
            title="无审核行",
            file=SimpleUploadedFile("demo.mp4", b"x", content_type="video/mp4"),
            file_type="video",
            file_name="demo.mp4",
            file_size=1,
            uploader=author,
        )
        listing = APIClient().get("/tutorials/tutorials/")
        self.assertNotIn(t.pk, _ids(listing))

    def test_pending_preview_does_not_count_views(self):
        author = _member("prev")
        client = APIClient()
        client.force_authenticate(author)
        created = client.post(
            "/tutorials/tutorials/",
            {"title": "待审不计播放", "file": _mp4()},
            format="multipart",
        )
        tid = created.data["id"]
        for _ in range(3):
            self.assertEqual(client.get(f"/tutorials/tutorials/{tid}/").status_code, 200)
        self.assertEqual(Tutorial.objects.get(pk=tid).views, 0)
