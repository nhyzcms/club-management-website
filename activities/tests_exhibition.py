"""展示布展模块接口测试（次 seam：直接调用 create_exhibit 等，不经 HTTP）。

HTTP 黑盒仍在 activities/tests.py。此处钉 VoteOption 同步与 create_attachment 落盘。
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from attachments.queries import attachments_of
from common.targets import target_of
from accounts.test_helpers import grant_verification
from attachments.models import Attachment

from .exhibition import ExhibitionError, create_exhibit
from .lifecycle import CLOSED, OPEN, SCHEDULED
from .models import Activity, Exhibit, VoteOption


def _img(name="a.png"):
    return SimpleUploadedFile(name, b"x", content_type="image/png")


class CreateExhibitTest(TestCase):
    def setUp(self):
        self.curator = grant_verification(User.objects.create_user(username="curator", password="x"))
        self.member = grant_verification(User.objects.create_user(username="member", password="x"))

    def _exhibition(self, *, voting_enabled=True, status=SCHEDULED):
        return Activity.objects.create(
            type="exhibition", status=status, title="展",
            creator=self.curator, voting_enabled=voting_enabled,
            max_choices_per_voter=1,
        )

    def test_create_exhibit_syncs_vote_option_when_voting_enabled(self):
        activity = self._exhibition(voting_enabled=True)
        exhibit = create_exhibit(
            activity=activity, user=self.curator, title="作品A", files=[_img(), _img("b.png")],
        )
        exhibit.refresh_from_db()
        self.assertEqual(exhibit.title, "作品A")
        self.assertIsNotNone(exhibit.vote_option_id)
        self.assertEqual(exhibit.vote_option.text, "作品A")
        self.assertEqual(attachments_of(exhibit).count(), 2)
        att = attachments_of(exhibit).first()
        self.assertEqual(att.uploaded_by_id, self.curator.pk)
        self.assertEqual(VoteOption.objects.filter(activity=activity).count(), 1)

    def test_create_exhibit_no_option_when_voting_disabled(self):
        activity = self._exhibition(voting_enabled=False)
        exhibit = create_exhibit(
            activity=activity, user=self.curator, title="陈列", files=[_img()],
        )
        self.assertIsNone(exhibit.vote_option_id)
        self.assertEqual(VoteOption.objects.filter(activity=activity).count(), 0)
        self.assertEqual(Attachment.objects.filter(target=target_of(exhibit)).count(), 1)

    def test_create_exhibit_allowed_when_open(self):
        activity = self._exhibition(status=OPEN, voting_enabled=True)
        exhibit = create_exhibit(
            activity=activity, user=self.curator, title="追加", files=[_img()],
        )
        self.assertIsNotNone(exhibit.vote_option_id)
        self.assertEqual(Exhibit.objects.filter(activity=activity).count(), 1)

    def test_create_exhibit_requires_file(self):
        activity = self._exhibition()
        with self.assertRaises(ExhibitionError) as ctx:
            create_exhibit(activity=activity, user=self.curator, title="空", files=[])
        self.assertEqual(ctx.exception.detail, "展品至少需要 1 个文件")
        self.assertEqual(ctx.exception.http_status, 400)

    def test_create_exhibit_blocked_when_closed(self):
        activity = self._exhibition(status=CLOSED)
        with self.assertRaises(ExhibitionError) as ctx:
            create_exhibit(activity=activity, user=self.curator, title="A", files=[_img()])
        self.assertEqual(ctx.exception.http_status, 400)

    def test_create_exhibit_rejects_non_exhibition(self):
        collection = Activity.objects.create(
            type="collection", status="collecting", title="征", creator=self.curator,
        )
        with self.assertRaises(ExhibitionError):
            create_exhibit(activity=collection, user=self.curator, title="A", files=[_img()])
