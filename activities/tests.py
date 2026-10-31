"""活动 HTTP 黑盒测试（主 seam：经 APIClient 打端点，断言状态码 + 响应形状 + DB 副作用）。

T1 范围：创建（已认证成员）+ 列表/详情（成员可读）+ 正文消毒 + 正文图片上传。
投票/投稿/复审在后续切片的测试类里增补。
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from reviews.test_helpers import approve_activity

from .models import Activity, QuestionnaireResponse, default_survey_schema


def _publish_created(resp):
    """既有活动测试默认走「已过审」夹具；待审可见性由 reviews/tests_activity.py 覆盖。"""
    if getattr(resp, "status_code", None) == 201:
        data = getattr(resp, "data", None) or {}
        pk = data.get("id")
        if pk:
            approve_activity(Activity.objects.get(pk=pk))
            if isinstance(data, dict):
                data["review_status"] = "approved"
    return resp


def _json(client, method, path, user, payload=None):
    client.force_authenticate(user)
    fn = getattr(client, method)
    if payload is None:
        return fn(path)
    resp = fn(path, data=json.dumps(payload), content_type="application/json")
    if method == "post" and path.rstrip("/") == "/activities/activities":
        _publish_created(resp)
    return resp


class ActivityCreateReadTest(TestCase):
    """T1：创建 + 读 + 消毒。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.visitor = User.objects.create_user(username="visitor", password="x")  # 未认证 = 访客
        self.other = grant_verification(User.objects.create_user(username="other", password="x"))
        self.client = APIClient()

    # ---- 创建 ----

    def test_verified_member_creates_deliberation(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "deliberation", "title": "去哪团建", "body": "<p>投票</p>",
                      "max_choices_per_voter": 1, "option_texts": ["去A地", "去B地"]})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["type"], "deliberation")
        self.assertEqual(resp.data["status"], "open")  # 众议创建即投票中
        self.assertEqual(resp.data["creator"]["id"], self.author.pk)
        self.assertEqual(resp.data["body"], "<p>投票</p>")

    def test_verified_member_creates_collection(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "collection", "title": "征社徽", "body": "<p>收件</p>"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "collecting")  # 征集创建即收件中

    def test_unverified_member_cannot_create(self):
        # 访客（未认证）发起 → IsVerified 门禁拒绝
        resp = _json(self.client, "post", "/activities/activities/", self.visitor,
                     {"type": "deliberation", "title": "x"})
        self.assertEqual(resp.status_code, 403)

    def test_invalid_type_rejected(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "bogus", "title": "x"})
        self.assertEqual(resp.status_code, 400)

    def test_body_is_sanitized_on_write(self):
        # script / 事件处理器须被剥（与新闻同级的消毒契约）
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "collection", "title": "x",
                      "body": "<p>ok</p><script>alert(1)</script><img onload=alert(1) src=x>"})
        self.assertEqual(resp.status_code, 201)
        self.assertNotIn("<script>", resp.data["body"])
        self.assertIn("<p>ok</p>", resp.data["body"])
        self.assertNotIn("onload", resp.data["body"])

    def test_https_iframe_kept_http_iframe_stripped(self):
        body = '<p><iframe src="https://example.com/a"></iframe><iframe src="http://evil.com"></iframe></p>'
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "collection", "title": "x", "body": body})
        self.assertEqual(resp.status_code, 201)
        self.assertIn("https://example.com/a", resp.data["body"])
        self.assertNotIn("evil.com", resp.data["body"])

    # ---- 长期活动（不设截止）----

    def test_permanent_activity_has_no_default_end(self):
        # 勾选「长期」→ 不填默认截止（征集默认 +7d 的兜底必须让路）
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "collection", "title": "长期征集", "is_permanent": True})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["is_permanent"])
        self.assertIsNone(resp.data["end_at"])

    def test_permanent_with_end_at_rejected(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "collection", "title": "x", "is_permanent": True,
                      "end_at": (timezone.now() + timedelta(days=3)).isoformat()})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("end_at", resp.data)

    def test_switching_to_permanent_clears_end_at(self):
        # 待开始期间可改：勾选长期即清空既有截止
        a = Activity.objects.create(
            type="collection", status="scheduled", title="s", creator=self.author,
            start_at=timezone.now() + timedelta(days=1),
            end_at=timezone.now() + timedelta(days=3),
        )
        self.client.force_authenticate(self.author)
        resp = self.client.patch(
            f"/activities/activities/{a.pk}/",
            data=json.dumps({"is_permanent": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["is_permanent"])
        self.assertIsNone(resp.data["end_at"])

    def test_unsetting_permanent_requires_end_at(self):
        # 由「长期」改回限期时必须补截止时间，否则会变成隐性永久
        a = Activity.objects.create(
            type="collection", status="scheduled", title="s", creator=self.author,
            is_permanent=True, start_at=timezone.now() + timedelta(days=1),
        )
        self.client.force_authenticate(self.author)
        resp = self.client.patch(
            f"/activities/activities/{a.pk}/",
            data=json.dumps({"is_permanent": False}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("end_at", resp.data)

    # ---- 读 ----

    def test_list_returns_activities(self):
        Activity.objects.create(type="deliberation", status="open", title="a", creator=self.author)
        Activity.objects.create(type="collection", status="collecting", title="b", creator=self.other)
        resp = _json(self.client, "get", "/activities/activities/", self.author)
        self.assertEqual(resp.status_code, 200)
        items = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
        self.assertEqual(len(items), 2)
        # 列表序列化不带 body（轻量）
        self.assertNotIn("body", items[0])

    def test_list_puts_ongoing_before_ended_then_newest(self):
        """进行中的活动排前面、已结束的沉底；同档按发布时间倒序（后发布的在上）。"""
        now = timezone.now()
        old_active = Activity.objects.create(
            type="deliberation", status="open", title="ongoing-old", creator=self.author,
        )
        ended_new = Activity.objects.create(
            type="deliberation", status="closed", title="ended-new", creator=self.other,
        )
        new_active = Activity.objects.create(
            type="collection", status="collecting", title="ongoing-new", creator=self.other,
        )
        Activity.objects.filter(pk=old_active.pk).update(created_at=now - timedelta(days=5))
        Activity.objects.filter(pk=ended_new.pk).update(created_at=now)
        Activity.objects.filter(pk=new_active.pk).update(created_at=now - timedelta(days=1))

        resp = _json(self.client, "get", "/activities/activities/", self.author)
        self.assertEqual(resp.status_code, 200)
        items = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
        self.assertEqual([i["title"] for i in items], ["ongoing-new", "ongoing-old", "ended-new"])

    def test_retrieve_returns_body(self):
        a = Activity.objects.create(type="collection", status="collecting", title="b",
                                    body="<p>hi</p>", creator=self.author)
        resp = _json(self.client, "get", f"/activities/activities/{a.pk}/", self.other)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["body"], "<p>hi</p>")
        self.assertEqual(resp.data["creator"]["id"], self.author.pk)

    def test_unauthenticated_list_only_public_surveys(self):
        Activity.objects.create(type="deliberation", status="open", title="hidden-delib", creator=self.author)
        approve_activity(Activity.objects.create(
            type="survey", status="open", title="public-survey",
            creator=self.author, audience="public",
        ))
        approve_activity(Activity.objects.create(
            type="survey", status="open", title="members-survey",
            creator=self.author, audience="members",
        ))
        self.client.force_authenticate(None)
        resp = self.client.get("/activities/activities/")
        self.assertEqual(resp.status_code, 200)
        items = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
        self.assertEqual({i["title"] for i in items}, {"public-survey"})

    # ---- 删除（发起人 / manage_activity）----

    def test_creator_can_delete_own(self):
        a = Activity.objects.create(type="deliberation", status="open", title="a", creator=self.author)
        self.client.force_authenticate(self.author)
        resp = self.client.delete(f"/activities/activities/{a.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Activity.objects.filter(pk=a.pk).exists())

    def test_other_cannot_delete(self):
        a = Activity.objects.create(type="deliberation", status="open", title="a", creator=self.author)
        self.client.force_authenticate(self.other)
        resp = self.client.delete(f"/activities/activities/{a.pk}/")
        self.assertEqual(resp.status_code, 403)


class ActivityUploadImageTest(TestCase):
    """正文图片上传端点（镜像新闻）。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.visitor = User.objects.create_user(username="visitor", password="x")
        self.client = APIClient()

    def _img(self, name="a.png", content_type="image/png", data=b"\x89PNG\r\n"):
        return SimpleUploadedFile(name, data, content_type=content_type)

    def test_verified_member_uploads_image(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post("/activities/activities/upload_image/", {"image": self._img()})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("url", resp.data)

    def test_unverified_cannot_upload(self):
        self.client.force_authenticate(self.visitor)
        resp = self.client.post("/activities/activities/upload_image/", {"image": self._img()})
        self.assertEqual(resp.status_code, 403)

    def test_rejects_non_image(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            "/activities/activities/upload_image/",
            {"image": SimpleUploadedFile("a.txt", b"hi", content_type="text/plain")},
        )
        self.assertEqual(resp.status_code, 400)


class SurveyUploadTest(TestCase):
    """问卷文件题上传端点：填答者（含游客）可传；类型限制。"""

    def _file(self, name="a.png", content_type="image/png", data=b"\x89PNG\r\n"):
        return SimpleUploadedFile(name, data, content_type=content_type)

    def test_guest_can_upload_image(self):
        resp = APIClient().post("/activities/activities/survey_upload/", {"file": self._file()})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("url", resp.data)

    def test_guest_can_upload_pdf(self):
        resp = APIClient().post(
            "/activities/activities/survey_upload/",
            {"file": self._file("a.pdf", "application/pdf", b"%PDF-1.4")},
        )
        self.assertEqual(resp.status_code, 200)

    def test_rejects_non_image_pdf(self):
        resp = APIClient().post(
            "/activities/activities/survey_upload/",
            {"file": self._file("a.txt", "text/plain", b"hi")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_missing_file(self):
        resp = APIClient().post("/activities/activities/survey_upload/", {})
        self.assertEqual(resp.status_code, 400)


class DeliberationVotingTest(TestCase):
    """T2：众议投票（自定义选项、K 选、不可改、惰性结算、公开计票）。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.m2 = grant_verification(User.objects.create_user(username="m2", password="x"))
        self.visitor = User.objects.create_user(username="visitor", password="x")  # 未认证
        self.client = APIClient()

    def _create(self, user, **payload):
        defaults = {"type": "deliberation", "title": "去哪团建", "body": "<p>x</p>",
                    "option_texts": ["A", "B", "C"]}
        defaults.update(payload)
        return _json(self.client, "post", "/activities/activities/", user, defaults)

    def _vote(self, user, activity_id, option_ids):
        return _json(self.client, "post", f"/activities/activities/{activity_id}/vote/", user,
                     {"option_ids": option_ids})

    def _opt(self, resp, idx):
        return resp.data["options"][idx]["id"]

    # ---- 创建（自定义选项 + K）----

    def test_create_with_options_and_default_end(self):
        resp = self._create(self.author, max_choices_per_voter=1)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "open")
        self.assertEqual([o["text"] for o in resp.data["options"]], ["A", "B", "C"])
        self.assertEqual(resp.data["max_choices_per_voter"], 1)
        self.assertIsNotNone(resp.data["end_at"])  # 默认 +3d

    def test_create_requires_at_least_two_options(self):
        resp = self._create(self.author, option_texts=["仅一个"])
        self.assertEqual(resp.status_code, 400)

    def test_create_rejects_k_above_option_count(self):
        resp = self._create(self.author, option_texts=["A", "B"], max_choices_per_voter=3)
        self.assertEqual(resp.status_code, 400)

    # ---- 投票（K=1 / K>1 / 不可改）----

    def test_k1_one_choice_only(self):
        a = self._create(self.author, max_choices_per_voter=1)
        aid, oa, ob = a.data["id"], self._opt(a, 0), self._opt(a, 1)
        # K=1 时选多项被拒
        self.assertEqual(self._vote(self.m1, aid, [oa, ob]).status_code, 400)
        # 选一项成功
        resp = self._vote(self.m1, aid, [oa])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["my_selections"], [oa])

    def test_k2_multi_choice(self):
        a = self._create(self.author, max_choices_per_voter=2)
        aid, oa, ob, oc = a.data["id"], self._opt(a, 0), self._opt(a, 1), self._opt(a, 2)
        resp = self._vote(self.m1, aid, [oa, ob])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.data["my_selections"]), {oa, ob})
        # 超过 K 被拒
        self.assertEqual(self._vote(self.m2, aid, [oa, ob, oc]).status_code, 400)

    def test_ballot_immutable(self):
        a = self._create(self.author)
        aid, oa = a.data["id"], self._opt(a, 0)
        self.assertEqual(self._vote(self.m1, aid, [oa]).status_code, 200)
        self.assertEqual(self._vote(self.m1, aid, [oa]).status_code, 400)  # 已投，不可改

    def test_visitor_cannot_vote(self):
        a = self._create(self.author)
        resp = self._vote(self.visitor, a.data["id"], [self._opt(a, 0)])
        self.assertEqual(resp.status_code, 403)

    def test_invalid_option_rejected(self):
        a = self._create(self.author)
        self.assertEqual(self._vote(self.m1, a.data["id"], [999999]).status_code, 400)

    def test_duplicate_option_rejected(self):
        a = self._create(self.author, max_choices_per_voter=2)
        oa = self._opt(a, 0)
        self.assertEqual(self._vote(self.m1, a.data["id"], [oa, oa]).status_code, 400)

    def test_cannot_vote_on_collection(self):
        c = _json(self.client, "post", "/activities/activities/", self.author,
                  {"type": "collection", "title": "征", "body": "<p>x</p>"})
        self.assertEqual(self._vote(self.m1, c.data["id"], [1]).status_code, 400)

    # ---- 公开计票 ----

    def test_public_tally_and_voters_visible(self):
        a = self._create(self.author, max_choices_per_voter=2)
        aid, oa, ob = a.data["id"], self._opt(a, 0), self._opt(a, 1)
        self._vote(self.m1, aid, [oa])
        self._vote(self.m2, aid, [oa, ob])
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.author)
        counts = {o["id"]: o["vote_count"] for o in resp.data["options"]}
        self.assertEqual(counts[oa], 2)
        self.assertEqual(counts[ob], 1)
        self.assertEqual(resp.data["total_ballots"], 2)
        # 公开：可见谁投了什么
        self.assertEqual(len(resp.data["ballots"]), 2)
        self.assertEqual({b["voter"]["id"] for b in resp.data["ballots"]}, {self.m1.pk, self.m2.pk})

    # ---- 惰性结算 ----

    def test_auto_close_on_end_at_blocks_voting(self):
        a = self._create(self.author)
        aid, oa = a.data["id"], self._opt(a, 0)
        Activity.objects.filter(pk=aid).update(end_at=timezone.now() - timedelta(minutes=1))
        _json(self.client, "get", f"/activities/activities/{aid}/", self.author)  # 触发惰性结算
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.author)
        self.assertEqual(resp.data["status"], "closed")
        self.assertEqual(self._vote(self.m1, aid, [oa]).status_code, 400)  # closed 后被拒


class SecretBallotAndCloseTest(TestCase):
    """T3：秘密投票（个人明细仅超管可见）+ 提前关闭。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.super = User.objects.create_superuser(username="super", password="x", email="s@e.com")
        self.client = APIClient()

    def _make(self, user, secret=False):
        return _json(self.client, "post", "/activities/activities/", user, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"], "max_choices_per_voter": 1,
            "is_secret_ballot": secret,
        })

    def _vote(self, user, aid, oid):
        return _json(self.client, "post", f"/activities/activities/{aid}/vote/", user, {"option_ids": [oid]})

    def test_secret_hides_voters_from_member_but_keeps_aggregate(self):
        a = self._make(self.author, secret=True)
        aid, oa = a.data["id"], a.data["options"][0]["id"]
        self.assertEqual(self._vote(self.m1, aid, oa).status_code, 200)
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.m1)
        self.assertIsNone(resp.data["ballots"])          # 个人明细不可见
        self.assertEqual(resp.data["total_ballots"], 1)  # 聚合可见
        self.assertEqual(resp.data["options"][0]["vote_count"], 1)
        self.assertEqual(resp.data["my_selections"], [oa])  # 自己的选择仍可见

    def test_secret_hides_voters_from_creator(self):
        a = self._make(self.author, secret=True)
        aid, oa = a.data["id"], a.data["options"][0]["id"]
        self._vote(self.m1, aid, oa)
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.author)
        self.assertIsNone(resp.data["ballots"])  # 发起人也看不到个人明细

    def test_secret_visible_to_superuser(self):
        a = self._make(self.author, secret=True)
        aid, oa = a.data["id"], a.data["options"][0]["id"]
        self._vote(self.m1, aid, oa)
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.super)
        self.assertIsNotNone(resp.data["ballots"])
        self.assertEqual(len(resp.data["ballots"]), 1)

    def test_public_shows_voters(self):
        a = self._make(self.author, secret=False)
        aid, oa = a.data["id"], a.data["options"][0]["id"]
        self._vote(self.m1, aid, oa)
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.m1)
        self.assertIsNotNone(resp.data["ballots"])
        self.assertEqual(len(resp.data["ballots"]), 1)

    def test_creator_can_early_close(self):
        a = self._make(self.author)
        resp = _json(self.client, "post", f"/activities/activities/{a.data['id']}/close/", self.author)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "closed")

    def test_other_cannot_early_close(self):
        a = self._make(self.author)
        resp = _json(self.client, "post", f"/activities/activities/{a.data['id']}/close/", self.m1)
        self.assertEqual(resp.status_code, 403)

    def test_close_blocks_further_voting(self):
        a = self._make(self.author)
        aid, oa = a.data["id"], a.data["options"][0]["id"]
        _json(self.client, "post", f"/activities/activities/{aid}/close/", self.author)
        self.assertEqual(self._vote(self.m1, aid, oa).status_code, 400)


class CollectionSubmissionTest(TestCase):
    """T4：征集投稿（一人一作品、提交即锁定、上传配置校验、满额自动关闭）。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.m2 = grant_verification(User.objects.create_user(username="m2", password="x"))
        self.visitor = User.objects.create_user(username="visitor", password="x")  # 未认证
        self.client = APIClient()

    def _collection(self, user, **cfg):
        payload = {"type": "collection", "title": "征logo", "body": "<p>x</p>"}
        payload.update(cfg)
        return _json(self.client, "post", "/activities/activities/", user, payload)

    def _file(self, name="a.png", data=b"x", content_type="image/png"):
        return SimpleUploadedFile(name, data, content_type=content_type)

    def _submit(self, user, cid, files):
        self.client.force_authenticate(user)
        return self.client.post(f"/activities/activities/{cid}/submit/", {"files": files})

    def test_submit_one_work_multiple_files(self):
        c = self._collection(self.author, allowed_extensions=".png,.jpg", max_files_per_submission=3)
        resp = self._submit(self.m1, c.data["id"], [self._file("a.png"), self._file("b.png")])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.data["my_submission"]["files"]), 2)
        self.assertEqual(resp.data["my_submission"]["review_status"], "pending")

    def test_one_person_one_submission(self):
        cid = self._collection(self.author).data["id"]
        self.assertEqual(self._submit(self.m1, cid, [self._file()]).status_code, 201)
        self.assertEqual(self._submit(self.m1, cid, [self._file("c.png")]).status_code, 400)

    def test_too_many_files_rejected(self):
        cid = self._collection(self.author, max_files_per_submission=2).data["id"]
        resp = self._submit(self.m1, cid, [self._file("a.png"), self._file("b.png"), self._file("c.png")])
        self.assertEqual(resp.status_code, 400)

    def test_disallowed_extension_rejected(self):
        cid = self._collection(self.author, allowed_extensions=".png").data["id"]
        # 全局禁用后缀
        self.assertEqual(
            self._submit(self.m1, cid, [self._file("a.exe", b"MZ", "application/x-msdownload")]).status_code, 400
        )
        # 非允许后缀（.txt 不在 .png 白名单）
        self.assertEqual(
            self._submit(self.m1, cid, [self._file("a.txt", b"hi", "text/plain")]).status_code, 400
        )

    def test_file_size_limit_enforced(self):
        cid = self._collection(
            self.author, allowed_extensions=".bin", max_file_size=100
        ).data["id"]
        resp = self._submit(self.m1, cid, [self._file("big.bin", b"x" * 200, "application/octet-stream")])
        self.assertEqual(resp.status_code, 400)

    def test_visitor_cannot_submit(self):
        cid = self._collection(self.author).data["id"]
        self.assertEqual(self._submit(self.visitor, cid, [self._file()]).status_code, 403)

    def test_cap_auto_closes_collection(self):
        cid = self._collection(self.author, max_submissions=1).data["id"]
        resp = self._submit(self.m1, cid, [self._file()])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "reviewing")  # 满额自动 collecting→reviewing
        # 第二人投稿被拒（已 reviewing）
        self.assertEqual(self._submit(self.m2, cid, [self._file()]).status_code, 400)

    def test_reviewer_sees_all_others_see_only_accepted(self):
        cid = self._collection(self.author).data["id"]
        self._submit(self.m1, cid, [self._file()])  # m1 投了（pending）
        # 非复审者 m2：submissions 只见录用（暂无）→ 空
        self.assertEqual(_json(self.client, "get", f"/activities/activities/{cid}/", self.m2).data["submissions"], [])
        # 提交者 m1：submissions 同样只见录用（空），但 my_submission 有自己的
        resp = _json(self.client, "get", f"/activities/activities/{cid}/", self.m1)
        self.assertEqual(resp.data["submissions"], [])
        self.assertIsNotNone(resp.data["my_submission"])
        # 复审者（发起人）：submissions 见全部（含 m1 的 pending）
        resp = _json(self.client, "get", f"/activities/activities/{cid}/", self.author)
        self.assertEqual(len(resp.data["submissions"]), 1)

    def test_cannot_submit_to_deliberation(self):
        d = _json(self.client, "post", "/activities/activities/", self.author,
                  {"type": "deliberation", "title": "x", "body": "<p>x</p>", "option_texts": ["A", "B"]})
        self.assertEqual(self._submit(self.m1, d.data["id"], [self._file()]).status_code, 400)


class CollectionReviewTest(TestCase):
    """T5：征集复审（录用/退稿、对象级权限、滚动复审、公开展示、提交者见结果）。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.reviewer = grant_verification(User.objects.create_user(username="reviewer", password="x"))
        perm = Permission.objects.get(content_type__app_label="activities", codename="review_collection")
        self.reviewer.user_permissions.add(perm)
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.outsider = grant_verification(User.objects.create_user(username="out", password="x"))
        self.client = APIClient()

    def _setup(self):
        """发起人建征集 → m1 投一作品（pending），返回活动 id。"""
        c = _json(self.client, "post", "/activities/activities/", self.author,
                  {"type": "collection", "title": "征", "body": "<p>x</p>"})
        cid = c.data["id"]
        self.client.force_authenticate(self.m1)
        self.client.post(
            f"/activities/activities/{cid}/submit/",
            {"files": [SimpleUploadedFile("a.png", b"x", content_type="image/png")]},
        )
        return cid

    def _sub_id(self, cid):
        resp = _json(self.client, "get", f"/activities/activities/{cid}/", self.author)
        return resp.data["submissions"][0]["id"]

    def _review(self, user, cid, sub_id, decision, comment=""):
        return _json(self.client, "post", f"/activities/activities/{cid}/review_submission/", user,
                     {"submission_id": sub_id, "decision": decision, "comment": comment})

    def test_creator_can_accept(self):
        cid = self._setup()
        r = self._review(self.author, cid, self._sub_id(cid), "accepted", "好")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["submissions"][0]["review_status"], "accepted")
        self.assertEqual(r.data["submissions"][0]["review_comment"], "好")

    def test_perm_holder_can_review(self):
        cid = self._setup()
        r = self._review(self.reviewer, cid, self._sub_id(cid), "rejected", "不合")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["submissions"][0]["review_status"], "rejected")

    def test_outsider_cannot_review(self):
        cid = self._setup()
        self.assertEqual(self._review(self.outsider, cid, self._sub_id(cid), "accepted").status_code, 403)

    def test_rolling_review_during_collecting(self):
        # 未关闭（仍 collecting）即可复审（滚动复审）
        cid = self._setup()
        detail = _json(self.client, "get", f"/activities/activities/{cid}/", self.author).data
        self.assertEqual(detail["status"], "collecting")
        r = self._review(self.author, cid, detail["submissions"][0]["id"], "accepted")
        self.assertEqual(r.status_code, 200)

    def test_accepted_visible_in_public_showcase(self):
        cid = self._setup()
        self._review(self.author, cid, self._sub_id(cid), "accepted")
        resp = _json(self.client, "get", f"/activities/activities/{cid}/", self.outsider)
        self.assertEqual(len(resp.data["submissions"]), 1)  # 录用作品对非复审者可见
        self.assertEqual(resp.data["submissions"][0]["review_status"], "accepted")

    def test_submitter_sees_own_result(self):
        cid = self._setup()
        self._review(self.author, cid, self._sub_id(cid), "rejected", "重做")
        resp = _json(self.client, "get", f"/activities/activities/{cid}/", self.m1)
        self.assertEqual(resp.data["my_submission"]["review_status"], "rejected")
        self.assertEqual(resp.data["my_submission"]["review_comment"], "重做")

    def test_invalid_decision_rejected(self):
        cid = self._setup()
        self.assertEqual(self._review(self.author, cid, self._sub_id(cid), "maybe").status_code, 400)

    def test_cannot_review_deliberation(self):
        d = _json(self.client, "post", "/activities/activities/", self.author,
                  {"type": "deliberation", "title": "x", "body": "<p>x</p>", "option_texts": ["A", "B"]})
        r = _json(self.client, "post", f"/activities/activities/{d.data['id']}/review_submission/",
                  self.author, {"submission_id": 1, "decision": "accepted"})
        self.assertEqual(r.status_code, 400)


class CollectionReviewOptionalTest(TestCase):
    """#51：征集复审改为可选——关闭复审后跳过 reviewing，作品提交即公开、不接受复审。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.outsider = grant_verification(User.objects.create_user(username="out", password="x"))
        self.client = APIClient()

    def _collection(self, review_enabled, **cfg):
        payload = {"type": "collection", "title": "征", "body": "<p>x</p>",
                   "review_enabled": review_enabled}
        payload.update(cfg)
        return _json(self.client, "post", "/activities/activities/", self.author, payload)

    def _file(self, name="a.png"):
        return SimpleUploadedFile(name, b"x", content_type="image/png")

    def _submit(self, user, cid):
        self.client.force_authenticate(user)
        return self.client.post(f"/activities/activities/{cid}/submit/", {"files": [self._file()]})

    def test_default_review_enabled_true(self):
        c = self._collection(review_enabled=True)
        self.assertEqual(c.status_code, 201)
        self.assertTrue(c.data["review_enabled"])

    def test_submissions_public_without_review(self):
        # 关闭复审：成员一投稿，局外人立即可见（不必录用）
        cid = self._collection(review_enabled=False).data["id"]
        self._submit(self.m1, cid)
        resp = _json(self.client, "get", f"/activities/activities/{cid}/", self.outsider)
        self.assertEqual(len(resp.data["submissions"]), 1)  # pending 也对外可见
        self.assertEqual(resp.data["submissions"][0]["review_status"], "pending")

    def test_close_skips_reviewing_when_disabled(self):
        cid = self._collection(review_enabled=False).data["id"]
        r = _json(self.client, "post", f"/activities/activities/{cid}/close/", self.author)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "archived")  # 直接 collecting→archived

    def test_close_goes_reviewing_when_enabled(self):
        cid = self._collection(review_enabled=True).data["id"]
        r = _json(self.client, "post", f"/activities/activities/{cid}/close/", self.author)
        self.assertEqual(r.data["status"], "reviewing")

    def test_cap_skips_reviewing_when_disabled(self):
        cid = self._collection(review_enabled=False, max_submissions=1).data["id"]
        r = self._submit(self.m1, cid)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["status"], "archived")  # 满额 collecting→archived

    def test_review_rejected_when_disabled(self):
        cid = self._collection(review_enabled=False).data["id"]
        self._submit(self.m1, cid)
        sub_id = _json(self.client, "get", f"/activities/activities/{cid}/", self.author).data["submissions"][0]["id"]
        r = _json(self.client, "post", f"/activities/activities/{cid}/review_submission/", self.author,
                  {"submission_id": sub_id, "decision": "accepted"})
        self.assertEqual(r.status_code, 400)


class SchedulingTest(TestCase):
    """开始时间 + 待开始状态：排期、惰性自动开放、待开始可改/开放后锁、start<end 校验。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.client = APIClient()

    def _future(self, days=2):
        return (timezone.now() + timedelta(days=days)).isoformat()

    def _past(self, days=1):
        return (timezone.now() - timedelta(days=days)).isoformat()

    def test_future_start_creates_scheduled(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"], "start_at": self._future(),
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "scheduled")

    def test_no_start_opens_immediately(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "collection", "title": "x", "body": "<p>x</p>"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "collecting")  # 创建即开

    def test_past_start_opens_immediately(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"], "start_at": self._past(),
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "open")

    def test_auto_open_on_start_at(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"], "start_at": self._future(),
        })
        aid = resp.data["id"]
        Activity.objects.filter(pk=aid).update(start_at=timezone.now() - timedelta(minutes=1))
        _json(self.client, "get", f"/activities/activities/{aid}/", self.author)  # 触发惰性开放
        self.assertEqual(
            _json(self.client, "get", f"/activities/activities/{aid}/", self.author).data["status"], "open"
        )

    def test_scheduled_blocks_vote_and_submit(self):
        # 众议 scheduled → 投票被拒
        d = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"], "start_at": self._future(),
        })
        opt = d.data["options"][0]["id"]
        self.assertEqual(
            _json(self.client, "post", f"/activities/activities/{d.data['id']}/vote/", self.m1,
                  {"option_ids": [opt]}).status_code,
            400,
        )
        # 征集 scheduled → 投稿被拒
        c = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "collection", "title": "x", "body": "<p>x</p>", "start_at": self._future(),
        })
        self.client.force_authenticate(self.m1)
        r = self.client.post(
            f"/activities/activities/{c.data['id']}/submit/",
            {"files": [SimpleUploadedFile("a.png", b"x", content_type="image/png")]},
        )
        self.assertEqual(r.status_code, 400)

    def test_edit_allowed_while_scheduled(self):
        d = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"], "start_at": self._future(),
        })
        r = _json(self.client, "patch", f"/activities/activities/{d.data['id']}/", self.author,
                  {"title": "改标题", "option_texts": ["A", "B", "C"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["title"], "改标题")
        self.assertEqual(len(r.data["options"]), 3)  # 选项替换

    def test_edit_locked_after_open(self):
        # 创建即开 → open；开放后改 → 403
        d = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>", "option_texts": ["A", "B"],
        })
        r = _json(self.client, "patch", f"/activities/activities/{d.data['id']}/", self.author, {"title": "改"})
        self.assertEqual(r.status_code, 403)

    def test_start_after_end_rejected(self):
        r = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"],
            "start_at": self._future(days=5), "end_at": self._future(days=1),
        })
        self.assertEqual(r.status_code, 400)


class AutoCloseOnFullVoteTest(TestCase):
    """全员投完即提前结算：众议票数达已认证成员数时自动 closed。"""

    def setUp(self):
        # 本测试下已认证成员恰好 = author + m1 = 2 人（TestCase 隔离，无其他用户）
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.client = APIClient()

    def _make(self):
        return _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>",
            "option_texts": ["A", "B"], "max_choices_per_voter": 1,
        })

    def _vote(self, user, aid, oid):
        return _json(self.client, "post", f"/activities/activities/{aid}/vote/", user, {"option_ids": [oid]})

    def test_not_closed_until_all_voted(self):
        a = self._make()
        aid, oa = a.data["id"], a.data["options"][0]["id"]
        r = self._vote(self.m1, aid, oa)  # 1/2 投票
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "open")  # 仍未全员

    def test_closed_when_all_voted(self):
        a = self._make()
        aid, oa = a.data["id"], a.data["options"][0]["id"]
        self._vote(self.m1, aid, oa)
        r = self._vote(self.author, aid, oa)  # 2/2 全员投完
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "closed")  # 自动结算
        # closed 后再投被拒
        self.assertEqual(self._vote(self.m1, aid, a.data["options"][1]["id"]).status_code, 400)


class ExhibitionTest(TestCase):
    """展示：创建时录入并冻结展品（每展品一投票选项）+ 展品投票（1..K）+ 三态赞踩 + 生命周期。"""

    def setUp(self):
        self.curator = grant_verification(User.objects.create_user(username="curator", password="x"))
        self.member = grant_verification(User.objects.create_user(username="member", password="x"))
        self.m2 = grant_verification(User.objects.create_user(username="m2", password="x"))
        self.visitor = User.objects.create_user(username="visitor", password="x")  # 未认证
        self.client = APIClient()

    def _img(self, name="a.png", data=b"x", ct="image/png"):
        return SimpleUploadedFile(name, data, content_type=ct)

    def _create(self, user, exhibits, **scalar):
        """建展示 + 待开始期布展 + 翻 open。exhibits: [(title, [SimpleUploadedFile...]), ...]

        新流程:排期到未来(→scheduled)→ add_exhibit 逐个加展品 → 把 start_at 改到
        过去并 GET 触发 transition_due_starts(→open)。对外契约不变:返回带 exhibits
        的 open 态 response(投票/赞踩测试可直接用)。默认 voting_enabled=True。
        """
        from datetime import datetime, timedelta, timezone as dtz
        from .models import Activity
        start_future = (datetime.now(dtz.utc) + timedelta(days=1)).isoformat()
        body = {"type": "exhibition", "title": "影展", "body": "<p>x</p>",
                "voting_enabled": True, "start_at": start_future}
        # scalar 可能带 voting_enabled="false" 等(#55 的纯陈列测试)——原样合并
        body.update(scalar)
        self.client.force_authenticate(user)
        r = self.client.post("/activities/activities/", data=body, content_type="application/json")
        assert r.status_code == 201, r.data
        _publish_created(r)
        aid = r.data["id"]
        assert r.data["status"] == "scheduled", r.data
        for title, files in exhibits:
            ar = self._add_exhibit(user, aid, title=title, files=files)
            assert ar.status_code == 200, ar.data
        Activity.objects.filter(pk=aid).update(
            start_at=datetime.now(dtz.utc) - timedelta(hours=1))
        r2 = self.client.get(f"/activities/activities/{aid}/")
        assert r2.data["status"] == "open", r2.data
        return r2

    def _create_empty(self, user, voting_enabled=False, scheduled=False, **scalar):
        """通过 HTTP JSON 建一个 0 展品的展示。返回 response。

        scheduled=True → 给未来 start_at(status=scheduled,可布展);否则不排期(status=open)。
        """
        from datetime import datetime, timedelta, timezone as dtz
        body = {"type": "exhibition", "title": scalar.get("title", "影展"),
                "body": scalar.get("body", "<p>x</p>"),
                "voting_enabled": voting_enabled,
                "max_choices_per_voter": scalar.get("max_choices_per_voter", 1)}
        if scheduled:
            body["start_at"] = (datetime.now(dtz.utc) + timedelta(days=1)).isoformat()
        self.client.force_authenticate(user)
        return _publish_created(
            self.client.post("/activities/activities/", data=body, content_type="application/json")
        )

    def _add_exhibit(self, user, aid, title="", files=None):
        files = files if files is not None else [self._img()]
        fd = {}
        if title:
            fd["title"] = title
        for f in files:
            fd.setdefault("files", []).append(f)
        self.client.force_authenticate(user)
        return self.client.post(f"/activities/activities/{aid}/add_exhibit/", data=fd)

    def _vote(self, user, aid, option_ids):
        return _json(self.client, "post", f"/activities/activities/{aid}/vote/", user,
                     {"option_ids": option_ids})

    def _rate(self, user, aid, eid, choice):
        return _json(self.client, "post", f"/activities/activities/{aid}/rate/", user,
                     {"exhibit_id": eid, "choice": choice})

    def _make_collection_with_submissions(self, owner, n=2):
        """建一个征集并提交 n 个作品(含文件),返回 (activity_id, [submission_id])。"""
        self.client.force_authenticate(owner)
        c = self.client.post("/activities/activities/", data={
            "type": "collection", "title": "征", "body": "<p>x</p>",
            "review_enabled": "false",  # 跳过复审,作品直接公开可见
        }, content_type="application/json")
        _publish_created(c)
        cid = c.data["id"]
        sub_ids = []
        submitters = [self.member, self.m2]
        for i in range(n):
            fd = {"files": [self._img(f"s{i}.png")]}
            self.client.force_authenticate(submitters[i % len(submitters)])
            r = self.client.post(f"/activities/activities/{cid}/submit/", data=fd)
            sub_ids.append(r.data["my_submission"]["id"])
        return cid, sub_ids

    @staticmethod
    def _ex(resp, idx=0):
        return resp.data["exhibits"][idx]

    # ---- 创建（JSON 标量,0 展品可建;展品在详情页布展）----

    def test_create_voting_enabled_k_at_least_1(self):
        self.client.force_authenticate(self.curator)
        r = self.client.post("/activities/activities/", data={
            "type": "exhibition", "title": "t", "body": "",
            "voting_enabled": True, "max_choices_per_voter": 0,
        }, content_type="application/json")
        self.assertEqual(r.status_code, 400)

    # ---- 详情页布展:add_exhibit(待开始期手动加展品)----

    def test_add_exhibit_creates_exhibit_with_files(self):
        aid = self._create_empty(self.curator, voting_enabled=False, scheduled=True).data["id"]
        r = self._add_exhibit(self.curator, aid, title="作品A",
                               files=[self._img(), self._img("b.png")])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["exhibits"]), 1)
        e = r.data["exhibits"][0]
        self.assertEqual(e["title"], "作品A")
        self.assertEqual(len(e["files"]), 2)
        self.assertIsNone(e["vote_option_id"])  # 未启用投票:无选项

    def test_add_exhibit_voting_enabled_builds_option(self):
        aid = self._create_empty(self.curator, voting_enabled=True,
                                 max_choices_per_voter=1, scheduled=True).data["id"]
        r = self._add_exhibit(self.curator, aid, title="X")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.data["exhibits"][0]["vote_option_id"])

    def test_add_exhibit_requires_file(self):
        aid = self._create_empty(self.curator, scheduled=True).data["id"]
        r = self._add_exhibit(self.curator, aid, files=[])
        self.assertEqual(r.status_code, 400)

    def test_add_exhibit_allowed_when_open(self):
        # 未排期 → open → 展示中仍可加展品
        aid = self._create_empty(self.curator, scheduled=False).data["id"]
        r = self._add_exhibit(self.curator, aid, title="A")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["exhibits"]), 1)

    def test_add_exhibit_open_builds_option_and_files(self):
        # 展示中加展品保留副作用:启用投票建选项 + 文件落盘
        aid = self._create_empty(self.curator, voting_enabled=True,
                                 max_choices_per_voter=1, scheduled=False).data["id"]
        r = self._add_exhibit(self.curator, aid, title="X",
                               files=[self._img("a.png"), self._img("b.png")])
        self.assertEqual(r.status_code, 200)
        e = r.data["exhibits"][0]
        self.assertIsNotNone(e["vote_option_id"])
        self.assertEqual(len(e["files"]), 2)

    def test_add_exhibit_blocked_when_closed(self):
        # 已结束 → 不可加展品
        aid = self._create_empty(self.curator, scheduled=False).data["id"]
        _json(self.client, "post", f"/activities/activities/{aid}/close/", self.curator)
        r = self._add_exhibit(self.curator, aid, title="A")
        self.assertEqual(r.status_code, 400)

    def test_add_exhibit_non_curator_forbidden(self):
        aid = self._create_empty(self.curator, scheduled=True).data["id"]
        r = self._add_exhibit(self.member, aid, title="A")
        self.assertEqual(r.status_code, 403)

    def test_add_exhibit_scheduled_allowed(self):
        aid = self._create_empty(self.curator, scheduled=True).data["id"]
        r = self._add_exhibit(self.curator, aid, title="A")
        self.assertEqual(r.status_code, 200)

    # ---- 展品删除（delete_exhibit）----

    def _delete_exhibit(self, user, aid, eid):
        self.client.force_authenticate(user)
        return self.client.post(f"/activities/activities/{aid}/delete_exhibit/",
                                data={"exhibit_id": eid})

    def test_delete_exhibit_removes_it_and_option(self):
        aid = self._create_empty(self.curator, voting_enabled=True,
                                 max_choices_per_voter=1, scheduled=True).data["id"]
        self._add_exhibit(self.curator, aid, title="A")
        eid = self.client.get(f"/activities/activities/{aid}/").data["exhibits"][0]["id"]
        r = self._delete_exhibit(self.curator, aid, eid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["exhibits"]), 0)
        from .models import VoteOption
        self.assertEqual(VoteOption.objects.filter(activity_id=aid).count(), 0)

    def test_delete_exhibit_open_allowed(self):
        # open 态(未排期)放行——展示中可删展品
        aid = self._create_empty(self.curator, voting_enabled=True,
                                 max_choices_per_voter=1, scheduled=False).data["id"]
        self._add_exhibit(self.curator, aid, title="A")
        eid = self.client.get(f"/activities/activities/{aid}/").data["exhibits"][0]["id"]
        r = self._delete_exhibit(self.curator, aid, eid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["exhibits"]), 0)

    def test_delete_exhibit_blocked_when_closed(self):
        aid = self._create_empty(self.curator, scheduled=False).data["id"]
        _json(self.client, "post", f"/activities/activities/{aid}/close/", self.curator)
        r = self._delete_exhibit(self.curator, aid, 999)
        self.assertEqual(r.status_code, 400)

    # ---- 展品修改（update_exhibit）----

    def _update_exhibit(self, user, aid, eid, title=None, files=None):
        fd = {"exhibit_id": str(eid)}
        if title is not None:
            fd["title"] = title
        if files:
            for f in files:
                fd.setdefault("files", []).append(f)
        self.client.force_authenticate(user)
        return self.client.post(f"/activities/activities/{aid}/update_exhibit/",
                                data=fd, format="multipart")

    def test_update_exhibit_renames_and_syncs_option(self):
        aid = self._create_empty(self.curator, voting_enabled=True,
                                 max_choices_per_voter=1, scheduled=True).data["id"]
        self._add_exhibit(self.curator, aid, title="旧名")
        eid = self.client.get(f"/activities/activities/{aid}/").data["exhibits"][0]["id"]
        r = self._update_exhibit(self.curator, aid, eid, title="新名")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["exhibits"][0]["title"], "新名")
        from .models import VoteOption
        self.assertEqual(VoteOption.objects.get(activity_id=aid).text, "新名")

    def test_update_exhibit_replaces_files(self):
        aid = self._create_empty(self.curator, scheduled=True).data["id"]
        self._add_exhibit(self.curator, aid, files=[self._img("a.png"), self._img("b.png")])
        eid = self.client.get(f"/activities/activities/{aid}/").data["exhibits"][0]["id"]
        r = self._update_exhibit(self.curator, aid, eid, files=[self._img("c.png")])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["exhibits"][0]["files"]), 1)
        self.assertEqual(r.data["exhibits"][0]["files"][0]["file_name"], "c.png")

    def test_update_exhibit_blocked_when_open(self):
        # 展示中可加/删/导入,但改标题仍限待开始
        aid = self._create_empty(self.curator, scheduled=False).data["id"]
        self._add_exhibit(self.curator, aid, title="A")
        eid = self.client.get(f"/activities/activities/{aid}/").data["exhibits"][0]["id"]
        r = self._update_exhibit(self.curator, aid, eid, title="新名")
        self.assertEqual(r.status_code, 400)

    def test_update_exhibit_blocked_when_closed(self):
        aid = self._create_empty(self.curator, scheduled=True).data["id"]
        self._add_exhibit(self.curator, aid, title="A")
        eid = self.client.get(f"/activities/activities/{aid}/").data["exhibits"][0]["id"]
        Activity.objects.filter(pk=aid).update(status="closed")
        r = self._update_exhibit(self.curator, aid, eid, title="新名")
        self.assertEqual(r.status_code, 400)

    # ---- 展品投票（每展品一选项）----

    def test_vote_k1_single_exhibit(self):
        ex = self._create(self.curator, [("A", [self._img()]), ("B", [self._img()])],
                          max_choices_per_voter=1)
        aid = ex.data["id"]
        oa, ob = self._ex(ex, 0)["vote_option_id"], self._ex(ex, 1)["vote_option_id"]
        # K=1：选两个展品被拒
        self.assertEqual(self._vote(self.member, aid, [oa, ob]).status_code, 400)
        # 选一个 → 成功
        r = self._vote(self.member, aid, [oa])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["my_selections"], [oa])
        self.assertEqual(self._ex(r, 0)["vote_count"], 1)  # 展品 A 得 1 票

    def test_vote_k2_multi_exhibits(self):
        ex = self._create(self.curator, [("A", [self._img()]), ("B", [self._img()]), ("C", [self._img()])],
                          max_choices_per_voter=2)
        aid = ex.data["id"]
        oa, ob, oc = (self._ex(ex, i)["vote_option_id"] for i in range(3))
        r = self._vote(self.member, aid, [oa, ob])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data["my_selections"]), {oa, ob})
        # 超过 K 被拒
        self.assertEqual(self._vote(self.m2, aid, [oa, ob, oc]).status_code, 400)

    def test_ballot_immutable(self):
        ex = self._create(self.curator, [("A", [self._img()]), ("B", [self._img()])])
        aid, oa = ex.data["id"], self._ex(ex)["vote_option_id"]
        self.assertEqual(self._vote(self.member, aid, [oa]).status_code, 200)
        self.assertEqual(self._vote(self.member, aid, [oa]).status_code, 400)  # 已投，不可改

    def test_visitor_cannot_vote(self):
        ex = self._create(self.curator, [("A", [self._img()]), ("B", [self._img()])])
        self.assertEqual(self._vote(self.visitor, ex.data["id"], [self._ex(ex)["vote_option_id"]]).status_code, 403)

    def test_public_tally_per_exhibit(self):
        ex = self._create(self.curator, [("A", [self._img()]), ("B", [self._img()])], max_choices_per_voter=2)
        aid = ex.data["id"]
        oa, ob = self._ex(ex, 0)["vote_option_id"], self._ex(ex, 1)["vote_option_id"]
        self._vote(self.member, aid, [oa])
        self._vote(self.m2, aid, [oa, ob])
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.curator)
        counts = {e["vote_option_id"]: e["vote_count"] for e in resp.data["exhibits"]}
        self.assertEqual(counts[oa], 2)
        self.assertEqual(counts[ob], 1)
        self.assertEqual(resp.data["total_ballots"], 2)

    def test_secret_exhibition_hides_ballots(self):
        ex = self._create(self.curator, [("A", [self._img()]), ("B", [self._img()])],
                          max_choices_per_voter=1, is_secret_ballot="true")
        aid, oa = ex.data["id"], self._ex(ex)["vote_option_id"]
        self.assertEqual(self._vote(self.member, aid, [oa]).status_code, 200)
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.member)
        self.assertIsNone(resp.data["ballots"])  # 秘密：个人明细不可见
        self.assertEqual(resp.data["total_ballots"], 1)  # 聚合可见
        self.assertEqual(self._ex(resp)["vote_count"], 1)

    # ---- 三态赞踩（与投票并存）----

    def test_rate_three_state(self):
        ex = self._create(self.curator, [("A", [self._img()])])
        aid, eid = ex.data["id"], self._ex(ex)["id"]
        r = self._rate(self.member, aid, eid, "like")
        self.assertEqual(self._ex(r)["my_rating"], "like")
        self.assertEqual(self._ex(r)["like_count"], 1)
        # like 再点 → none
        r = self._rate(self.member, aid, eid, "like")
        self.assertIsNone(self._ex(r)["my_rating"])
        self.assertEqual(self._ex(r)["like_count"], 0)
        # dislike
        r = self._rate(self.member, aid, eid, "dislike")
        self.assertEqual(self._ex(r)["my_rating"], "dislike")
        self.assertEqual(self._ex(r)["dislike_count"], 1)

    def test_rate_mutually_exclusive(self):
        ex = self._create(self.curator, [("A", [self._img()])])
        aid, eid = ex.data["id"], self._ex(ex)["id"]
        self._rate(self.member, aid, eid, "like")
        r = self._rate(self.member, aid, eid, "dislike")
        self.assertEqual(self._ex(r)["my_rating"], "dislike")
        self.assertEqual(self._ex(r)["like_count"], 0)
        self.assertEqual(self._ex(r)["dislike_count"], 1)

    def test_visitor_cannot_rate(self):
        ex = self._create(self.curator, [("A", [self._img()])])
        self.assertEqual(self._rate(self.visitor, ex.data["id"], self._ex(ex)["id"], "like").status_code, 403)

    def test_invalid_rating_choice(self):
        ex = self._create(self.curator, [("A", [self._img()])])
        aid, eid = ex.data["id"], self._ex(ex)["id"]
        self.assertEqual(self._rate(self.member, aid, eid, "meh").status_code, 400)

    # ---- 纯陈列：投票被拒、赞踩照常 ----

    def _create_pure(self):
        return self._create(
            self.curator, [("A", [self._img()]), ("B", [self._img()])],
            voting_enabled="false",
        )

    def test_vote_rejected_when_voting_disabled(self):
        ex = self._create_pure()
        aid = ex.data["id"]
        # 纯陈列展示无选项；即便提交任意选项，投票动作本身就被拒（防御性双保险）
        r = self._vote(self.member, aid, [999999])
        self.assertEqual(r.status_code, 400)
        self.assertIn("投票", r.data["detail"])

    def test_rate_works_when_voting_disabled(self):
        ex = self._create_pure()
        aid, eid = ex.data["id"], self._ex(ex)["id"]
        r = self._rate(self.member, aid, eid, "like")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._ex(r)["my_rating"], "like")
        self.assertEqual(self._ex(r)["like_count"], 1)
        self.assertIsNone(self._ex(r)["vote_option_id"])  # 仍未绑定选项

    def test_detail_omits_vote_data_when_voting_disabled(self):
        ex = self._create_pure()
        aid = ex.data["id"]
        # 给展品点赞，确认赞踩数据存在、但投票相关数据全部缺席
        self._rate(self.member, aid, self._ex(ex)["id"], "like")
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.member)
        self.assertEqual(resp.data["voting_enabled"], False)
        self.assertIsNone(resp.data["ballots"])
        self.assertIsNone(resp.data["my_selections"])
        self.assertIsNone(resp.data["total_ballots"])
        self.assertIsNone(resp.data["options"])
        # 展品画廊照常：含赞踩计数与我的评分
        self.assertEqual(len(resp.data["exhibits"]), 2)
        self.assertEqual(self._ex(resp)["like_count"], 1)
        self.assertEqual(self._ex(resp)["my_rating"], "like")

    # ---- 生命周期 ----

    def test_closed_blocks_vote_and_rate(self):
        ex = self._create(self.curator, [("A", [self._img()])])
        aid, eid = ex.data["id"], self._ex(ex)["id"]
        oa = self._ex(ex)["vote_option_id"]
        Activity.objects.filter(pk=aid).update(end_at=timezone.now() - timedelta(minutes=1))
        _json(self.client, "get", f"/activities/activities/{aid}/", self.curator)  # 触发惰性结算
        self.assertEqual(self._vote(self.member, aid, [oa]).status_code, 400)
        self.assertEqual(self._rate(self.member, aid, eid, "like").status_code, 400)

    def test_early_close_exhibition(self):
        ex = self._create(self.curator, [("A", [self._img()])])
        r = _json(self.client, "post", f"/activities/activities/{ex.data['id']}/close/", self.curator)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "closed")

    # ---- 征集导入（从征集勾选任意作品，复制独立副本）----

    def test_import_from_collection_copies_selected(self):
        cid, sub_ids = self._make_collection_with_submissions(self.curator, n=2)
        aid = self._create_empty(self.curator, voting_enabled=False, scheduled=True).data["id"]
        self.client.force_authenticate(self.curator)
        r = self.client.post(f"/activities/activities/{aid}/import_from_collection/",
                             data={"collection_id": cid, "submission_ids": sub_ids},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["exhibits"]), 2)
        files = [f for e in r.data["exhibits"] for f in e["files"]]
        self.assertEqual(len(files), 2)

    def test_import_from_collection_allowed_when_open(self):
        # 展示中(未排期)仍可导入
        cid, sub_ids = self._make_collection_with_submissions(self.curator, n=1)
        aid = self._create_empty(self.curator, voting_enabled=False, scheduled=False).data["id"]
        self.client.force_authenticate(self.curator)
        r = self.client.post(f"/activities/activities/{aid}/import_from_collection/",
                             data={"collection_id": cid, "submission_ids": sub_ids},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["exhibits"]), 1)

    def test_import_from_collection_blocked_when_closed(self):
        cid, sub_ids = self._make_collection_with_submissions(self.curator, n=1)
        aid = self._create_empty(self.curator, voting_enabled=False, scheduled=False).data["id"]
        _json(self.client, "post", f"/activities/activities/{aid}/close/", self.curator)
        self.client.force_authenticate(self.curator)
        r = self.client.post(f"/activities/activities/{aid}/import_from_collection/",
                             data={"collection_id": cid, "submission_ids": sub_ids},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_import_invalid_collection(self):
        aid = self._create_empty(self.curator, scheduled=True).data["id"]
        self.client.force_authenticate(self.curator)
        r = self.client.post(f"/activities/activities/{aid}/import_from_collection/",
                             data={"collection_id": 999999, "submission_ids": []},
                             content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_import_is_independent_snapshot(self):
        # 复制成独立副本:原作品附件删了,展品文件仍在
        cid, sub_ids = self._make_collection_with_submissions(self.curator, n=1)
        aid = self._create_empty(self.curator, scheduled=True).data["id"]
        self.client.force_authenticate(self.curator)
        self.client.post(f"/activities/activities/{aid}/import_from_collection/",
                         data={"collection_id": cid, "submission_ids": sub_ids},
                         content_type="application/json")
        from .models import Submission
        Submission.objects.get(pk=sub_ids[0]).attachments.all().delete()
        detail = self.client.get(f"/activities/activities/{aid}/").data
        self.assertEqual(len(detail["exhibits"][0]["files"]), 1)


class SurveyActivityTest(TestCase):
    """调研：创建默认 / 访客公开可见性 / 一人一答 / 问卷可改窗口 / 惰性关闭。"""

    _SCHEMA = {
        "title": "满意度",
        "pages": [{"name": "page1", "elements": [{"type": "text", "name": "q1", "title": "意见"}]}],
    }

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="m1", password="x"))
        self.client = APIClient()

    def _create(self, user, **payload):
        defaults = {"type": "survey", "title": "问卷", "body": "<p>x</p>"}
        defaults.update(payload)
        return _json(self.client, "post", "/activities/activities/", user, defaults)

    def _respond(self, user, aid, answers=None):
        return _json(
            self.client, "post", f"/activities/activities/{aid}/respond/", user,
            {"answers": answers if answers is not None else {"q1": "ok"}},
        )

    def _guest_get(self, path):
        self.client.force_authenticate(None)
        return self.client.get(path)

    def _guest_respond(self, aid, answers=None, device_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"):
        self.client.force_authenticate(None)
        extra = {}
        if device_id:
            extra["HTTP_X_DEVICE_ID"] = device_id
        return self.client.post(
            f"/activities/activities/{aid}/respond/",
            data=json.dumps({"answers": answers if answers is not None else {"q1": "ok"}}),
            content_type="application/json",
            **extra,
        )

    # ---- 创建 ----

    def test_create_survey_defaults_schema_and_members_audience(self):
        resp = self._create(self.author)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["type"], "survey")
        self.assertEqual(resp.data["status"], "open")
        self.assertEqual(resp.data["audience"], "members")
        self.assertEqual(resp.data["schema"], default_survey_schema())
        self.assertEqual(resp.data["response_count"], 0)
        self.assertIsNone(resp.data["my_response"])
        self.assertTrue(resp.data["schema_editable"])
        self.assertIsNotNone(resp.data["end_at"])  # 默认 +7d

    def test_create_survey_with_public_audience(self):
        resp = self._create(self.author, audience="public")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["audience"], "public")

    def test_list_includes_audience(self):
        self._create(self.author, audience="public")
        resp = _json(self.client, "get", "/activities/activities/", self.m1)
        items = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
        self.assertIn("audience", items[0])

    def test_audience_immutable_after_create(self):
        aid = self._create(self.author).data["id"]
        r = _json(self.client, "patch", f"/activities/activities/{aid}/", self.author,
                  {"audience": "public"})
        self.assertEqual(r.status_code, 400)

    # ---- 访客：公开过审调研可列/开/交；仅成员与其他类型 404 ----

    def test_guest_list_retrieve_respond_public_approved_open(self):
        a = self._create(self.author, audience="public", schema=self._SCHEMA)
        aid = a.data["id"]
        listing = self._guest_get("/activities/activities/")
        items = listing.data["results"] if isinstance(listing.data, dict) and "results" in listing.data else listing.data
        self.assertEqual({i["title"] for i in items}, {"问卷"})
        retrieve = self._guest_get(f"/activities/activities/{aid}/")
        self.assertEqual(retrieve.status_code, 200)
        self.assertEqual(retrieve.data["schema"], self._SCHEMA)
        self.assertIsNone(retrieve.data["my_response"])
        r = self._guest_respond(aid, {"q1": "访客"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["response_count"], 1)

    def test_guest_404_on_members_only_and_other_types(self):
        members = self._create(self.author)  # 默认 audience=members
        delib = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "众议", "body": "<p>x</p>", "option_texts": ["A", "B"],
        })
        collection = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "collection", "title": "征集", "body": "<p>x</p>",
        })
        for aid in (members.data["id"], delib.data["id"], collection.data["id"]):
            self.assertEqual(self._guest_get(f"/activities/activities/{aid}/").status_code, 404)
            self.assertEqual(self._guest_respond(aid).status_code, 404)

    def test_guest_cannot_see_unapproved_public_survey(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            "/activities/activities/",
            data=json.dumps({"type": "survey", "title": "待审公开", "audience": "public"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data.get("review_status"), "pending")
        aid = resp.data["id"]
        self.assertEqual(self._guest_get(f"/activities/activities/{aid}/").status_code, 404)
        listing = self._guest_get("/activities/activities/")
        items = listing.data["results"] if isinstance(listing.data, dict) and "results" in listing.data else listing.data
        self.assertEqual({i["title"] for i in items}, set())

    # ---- 作答唯一性 ----

    def test_member_one_response_second_post_400(self):
        aid = self._create(self.author).data["id"]
        first = self._respond(self.m1, aid, {"q1": "一次"})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["my_response"], {"q1": "一次"})
        self.assertEqual(first.data["response_count"], 1)
        self.assertEqual(self._respond(self.m1, aid, {"q1": "二次"}).status_code, 400)
        q = Activity.objects.get(pk=aid).questionnaire
        self.assertEqual(QuestionnaireResponse.objects.filter(questionnaire=q, user=self.m1).count(), 1)

    def test_guest_same_device_second_post_400(self):
        aid = self._create(self.author, audience="public").data["id"]
        device = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        self.assertEqual(self._guest_respond(aid, {"q1": "a"}, device).status_code, 201)
        again = self._guest_respond(aid, {"q1": "b"}, device)
        self.assertEqual(again.status_code, 400)
        q = Activity.objects.get(pk=aid).questionnaire
        self.assertEqual(QuestionnaireResponse.objects.filter(questionnaire=q, user__isnull=True).count(), 1)

    def test_guest_different_devices_each_once(self):
        aid = self._create(self.author, audience="public").data["id"]
        self.assertEqual(self._guest_respond(aid, {"q1": "a"}, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee").status_code, 201)
        self.assertEqual(self._guest_respond(aid, {"q1": "b"}, "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff").status_code, 201)
        q = Activity.objects.get(pk=aid).questionnaire
        self.assertEqual(QuestionnaireResponse.objects.filter(questionnaire=q, user__isnull=True).count(), 2)

    def test_guest_respond_requires_device_id(self):
        aid = self._create(self.author, audience="public").data["id"]
        r = self._guest_respond(aid, {"q1": "a"}, device_id="")
        self.assertEqual(r.status_code, 400)

    def test_guest_my_response_follows_device(self):
        aid = self._create(self.author, audience="public").data["id"]
        device = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        self.assertEqual(self._guest_respond(aid, {"q1": "访客"}, device).status_code, 201)
        self.client.force_authenticate(None)
        retrieve = self.client.get(
            f"/activities/activities/{aid}/",
            HTTP_X_DEVICE_ID=device,
        )
        self.assertEqual(retrieve.data["my_response"], {"q1": "访客"})

    def test_member_can_respond_to_members_survey(self):
        aid = self._create(self.author).data["id"]
        r = self._respond(self.m1, aid)
        self.assertEqual(r.status_code, 201)

    def test_cannot_respond_to_deliberation(self):
        d = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "x", "body": "<p>x</p>", "option_texts": ["A", "B"],
        })
        self.assertEqual(self._respond(self.m1, d.data["id"]).status_code, 400)

    def test_respond_requires_answers_object(self):
        aid = self._create(self.author, audience="public").data["id"]
        r = _json(self.client, "post", f"/activities/activities/{aid}/respond/", self.m1, {"answers": "nope"})
        self.assertEqual(r.status_code, 400)

    # ---- Schema 可改窗口 ----

    def test_schema_patch_allowed_while_open_with_zero_responses(self):
        aid = self._create(self.author).data["id"]
        r = _json(self.client, "patch", f"/activities/activities/{aid}/", self.author,
                  {"schema": self._SCHEMA})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["schema"], self._SCHEMA)

    def test_schema_patch_refused_after_first_response(self):
        aid = self._create(self.author).data["id"]
        self.assertEqual(self._respond(self.m1, aid).status_code, 201)
        r = _json(self.client, "patch", f"/activities/activities/{aid}/", self.author,
                  {"schema": self._SCHEMA})
        self.assertEqual(r.status_code, 403)

    def test_title_still_locked_while_open(self):
        aid = self._create(self.author).data["id"]
        r = _json(self.client, "patch", f"/activities/activities/{aid}/", self.author, {"title": "改"})
        self.assertEqual(r.status_code, 403)

    def test_invalid_schema_rejected(self):
        aid = self._create(self.author).data["id"]
        r = _json(self.client, "patch", f"/activities/activities/{aid}/", self.author,
                  {"schema": {"title": "无 pages"}})
        self.assertEqual(r.status_code, 400)

    def test_detail_schema_editable_tracks_lifecycle(self):
        aid = self._create(self.author).data["id"]
        open_ok = _json(self.client, "get", f"/activities/activities/{aid}/", self.author)
        self.assertTrue(open_ok.data["schema_editable"])
        listing = _json(self.client, "get", "/activities/activities/", self.m1)
        items = listing.data["results"] if isinstance(listing.data, dict) and "results" in listing.data else listing.data
        self.assertNotIn("schema_editable", items[0])
        self.assertEqual(self._respond(self.m1, aid).status_code, 201)
        locked = _json(self.client, "get", f"/activities/activities/{aid}/", self.author)
        self.assertFalse(locked.data["schema_editable"])

    def test_scheduled_survey_schema_editable(self):
        start = (timezone.now() + timedelta(days=1)).isoformat()
        resp = self._create(self.author, start_at=start)
        self.assertEqual(resp.data["status"], "scheduled")
        self.assertTrue(resp.data["schema_editable"])

    def test_non_survey_detail_schema_editable_false(self):
        d = _json(self.client, "post", "/activities/activities/", self.author, {
            "type": "deliberation", "title": "众议", "body": "<p>x</p>", "option_texts": ["A", "B"],
        })
        r = _json(self.client, "get", f"/activities/activities/{d.data['id']}/", self.author)
        self.assertFalse(r.data["schema_editable"])

    # ---- 惰性关闭 ----

    def test_end_at_auto_closes_survey_and_blocks_respond(self):
        aid = self._create(self.author, audience="public").data["id"]
        Activity.objects.filter(pk=aid).update(end_at=timezone.now() - timedelta(minutes=1))
        _json(self.client, "get", f"/activities/activities/{aid}/", self.author)  # 触发惰性结算
        resp = _json(self.client, "get", f"/activities/activities/{aid}/", self.author)
        self.assertEqual(resp.data["status"], "closed")
        self.assertFalse(resp.data["schema_editable"])
        self.assertEqual(self._respond(self.m1, aid).status_code, 400)
        self.assertEqual(self._guest_respond(aid).status_code, 400)


class SurveyResponsesViewTest(TestCase):
    """问卷作答查看（GET .../responses/）：发起人/管理看全部；其他登录用户看自己。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="rauthor", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="rm1", password="x"))
        self.m2 = grant_verification(User.objects.create_user(username="rm2", password="x"))
        self.client = APIClient()
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "survey", "title": "作答查看", "body": "<p>x</p>"})
        self.aid = resp.data["id"]
        self.q = Activity.objects.get(pk=self.aid).questionnaire

    def _respond(self, user, answers):
        return _json(self.client, "post", f"/activities/activities/{self.aid}/respond/", user,
                     {"answers": answers})

    def _responses(self, user=None):
        self.client.force_authenticate(user)
        return self.client.get(f"/activities/activities/{self.aid}/responses/")

    def test_creator_sees_all(self):
        self._respond(self.m1, {"q1": "a"})
        self._respond(self.m2, {"q1": "b"})
        resp = self._responses(self.author)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["is_manager"])
        self.assertEqual(len(resp.data["results"]), 2)
        self.assertIsInstance(resp.data["schema"], dict)

    def test_manage_activity_holder_sees_all(self):
        holder = User.objects.create_user(username="rholder", password="x")
        holder.user_permissions.add(Permission.objects.get(
            content_type__app_label="activities", codename="manage_activity"))
        holder = User.objects.get(pk=holder.pk)
        self._respond(self.m1, {"q1": "a"})
        resp = self._responses(holder)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["is_manager"])
        self.assertEqual(len(resp.data["results"]), 1)

    def test_member_sees_only_own(self):
        self._respond(self.m1, {"q1": "mine"})
        self._respond(self.m2, {"q1": "other"})
        resp = self._responses(self.m1)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_manager"])
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["answers"], {"q1": "mine"})

    def test_anonymous_403(self):
        self.assertEqual(self._responses(None).status_code, 403)

    def test_non_survey_400(self):
        resp = _json(self.client, "post", "/activities/activities/", self.author,
                     {"type": "collection", "title": "征集R", "body": "<p>x</p>"})
        did = resp.data["id"]
        self.client.force_authenticate(self.author)
        self.assertEqual(
            self.client.get(f"/activities/activities/{did}/responses/").status_code, 400)


class PublicVotingGuestTest(TestCase):
    """公开受众投票：游客按设备标识判重（记录 IP），成员行为不变。"""

    DEV1 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    DEV2 = "11111111-2222-4333-8444-555555555555"

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="pauthor", password="x"))
        self.member = grant_verification(User.objects.create_user(username="pmember", password="x"))
        self.visitor = User.objects.create_user(username="pvisitor", password="x")  # 未认证
        self.client = APIClient()

    def _create(self, **extra):
        payload = {
            "type": "deliberation", "title": "公开众议", "body": "<p>x</p>",
            "max_choices_per_voter": 1, "audience": "public",
            "option_texts": ["A", "B"],
        }
        payload.update(extra)
        self.client.force_authenticate(self.author)
        return _publish_created(
            self.client.post("/activities/activities/",
                             data=json.dumps(payload), content_type="application/json")
        )

    def _guest_vote(self, aid, option_ids, device=None, xff=None):
        self.client.force_authenticate(None)
        extra = {}
        if device is not None:
            extra["HTTP_X_DEVICE_ID"] = device
        if xff is not None:
            extra["HTTP_X_FORWARDED_FOR"] = xff
        return self.client.post(
            f"/activities/activities/{aid}/vote/",
            data=json.dumps({"option_ids": option_ids}),
            content_type="application/json", **extra,
        )

    def _vote(self, user, aid, option_ids):
        return _json(self.client, "post", f"/activities/activities/{aid}/vote/", user,
                     {"option_ids": option_ids})

    # ---- 创建：受众对众议/展示生效 ----

    def test_create_public_deliberation_keeps_audience(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["audience"], "public")

    def test_create_collection_drops_audience(self):
        self.client.force_authenticate(self.author)
        resp = _publish_created(self.client.post(
            "/activities/activities/",
            data=json.dumps({"type": "collection", "title": "征集",
                             "body": "<p>x</p>", "audience": "public"}),
            content_type="application/json",
        ))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["audience"], "members")  # 征集无受众语义，回落默认

    def test_deliberation_audience_immutable(self):
        a = self._create()
        resp = _json(self.client, "patch", f"/activities/activities/{a.data['id']}/",
                     self.author, {"audience": "members"})
        self.assertEqual(resp.status_code, 400)

    # ---- 游客投票 ----

    def test_guest_votes_public_deliberation_with_device(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        resp = self._guest_vote(aid, [oid], device=self.DEV1, xff="203.0.113.9")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["my_selections"], [oid])
        self.assertEqual(resp.data["total_ballots"], 1)
        ballot = Activity.objects.get(pk=aid).ballots.get()
        self.assertIsNone(ballot.voter_id)
        self.assertEqual(ballot.device_id, self.DEV1)
        self.assertEqual(ballot.voter_ip, "203.0.113.9")

    def test_guest_without_device_rejected(self):
        a = self._create()
        resp = self._guest_vote(a.data["id"], [a.data["options"][0]["id"]])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["detail"], "缺少设备标识")

    def test_same_device_cannot_vote_twice(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self.assertEqual(self._guest_vote(aid, [oid], device=self.DEV1).status_code, 200)
        resp = self._guest_vote(aid, [oid], device=self.DEV1)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["detail"], "该设备已投过票，不能重复投票")

    def test_different_devices_can_vote(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self.assertEqual(self._guest_vote(aid, [oid], device=self.DEV1).status_code, 200)
        self.assertEqual(self._guest_vote(aid, [oid], device=self.DEV2).status_code, 200)
        self.assertEqual(Activity.objects.get(pk=aid).ballots.count(), 2)

    def test_guest_ip_from_xff_last_segment(self):
        # 最左可伪造（客户端自带）；真实 IP 由 Nginx 追加在末段 → 取末段
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self._guest_vote(aid, [oid], device=self.DEV1, xff="1.2.3.4, 198.51.100.7")
        ballot = Activity.objects.get(pk=aid).ballots.get()
        self.assertEqual(ballot.voter_ip, "198.51.100.7")

    def test_guest_ip_fallback_remote_addr(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self._guest_vote(aid, [oid], device=self.DEV1)
        ballot = Activity.objects.get(pk=aid).ballots.get()
        self.assertEqual(ballot.voter_ip, "127.0.0.1")  # 测试客户端默认 REMOTE_ADDR

    def test_guest_selection_roundtrip_by_device(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self._guest_vote(aid, [oid], device=self.DEV1)
        self.client.force_authenticate(None)
        r1 = self.client.get(f"/activities/activities/{aid}/", HTTP_X_DEVICE_ID=self.DEV1)
        self.assertEqual(r1.data["my_selections"], [oid])
        r2 = self.client.get(f"/activities/activities/{aid}/", HTTP_X_DEVICE_ID=self.DEV2)
        self.assertIsNone(r2.data["my_selections"])

    def test_guest_ballot_listed_with_null_voter(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self._guest_vote(aid, [oid], device=self.DEV1)
        self.client.force_authenticate(self.author)
        resp = self.client.get(f"/activities/activities/{aid}/")
        self.assertEqual(resp.data["total_ballots"], 1)
        self.assertEqual(len(resp.data["ballots"]), 1)
        self.assertIsNone(resp.data["ballots"][0]["voter"])

    # ---- 成员行为不变 ----

    def test_members_activity_404_for_guest(self):
        a = self._create(audience="members")
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"/activities/activities/{aid}/").status_code, 404)
        self.assertEqual(self._guest_vote(aid, [oid], device=self.DEV1).status_code, 404)

    def test_unverified_user_403_on_members_activity(self):
        a = self._create(audience="members")
        resp = self._vote(self.visitor, a.data["id"], [a.data["options"][0]["id"]])
        self.assertEqual(resp.status_code, 403)

    def test_verified_member_votes_public_without_device(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        resp = self._vote(self.member, aid, [oid])
        self.assertEqual(resp.status_code, 200)
        ballot = Activity.objects.get(pk=aid).ballots.get()
        self.assertEqual(ballot.voter_id, self.member.pk)
        self.assertEqual(ballot.device_id, "")
        self.assertIsNone(ballot.voter_ip)

    def test_public_activity_visible_to_guest(self):
        a = self._create()
        self.client.force_authenticate(None)
        resp = self.client.get(f"/activities/activities/{a.data['id']}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["audience"], "public")

    # ---- 提前结算只数已认证成员的票 ----

    def test_guest_votes_do_not_trigger_early_close(self):
        # 2 名已认证成员（author/member）；游客票不参与提前结算
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        self.assertEqual(self._guest_vote(aid, [oid], device=self.DEV1).status_code, 200)
        self.assertEqual(self._guest_vote(aid, [oid], device=self.DEV2).status_code, 200)
        self.assertEqual(Activity.objects.get(pk=aid).status, "open")  # 游客票不触发
        self.assertEqual(self._vote(self.member, aid, [oid]).status_code, 200)
        self.assertEqual(Activity.objects.get(pk=aid).status, "open")
        self.assertEqual(self._vote(self.author, aid, [oid]).status_code, 200)
        self.assertEqual(Activity.objects.get(pk=aid).status, "closed")  # 成员全投完才结算

    def test_guest_vote_closed_public_rejected(self):
        a = self._create()
        aid, oid = a.data["id"], a.data["options"][0]["id"]
        Activity.objects.filter(pk=aid).update(status="closed")
        resp = self._guest_vote(aid, [oid], device=self.DEV1)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["detail"], "投票已结束")


class PublicExhibitionGuestVoteTest(TestCase):
    """公开展示（启用投票）：游客可对展品投票。"""

    DEV1 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    def setUp(self):
        self.curator = grant_verification(User.objects.create_user(username="xcurator", password="x"))
        self.client = APIClient()

    def _img(self, name="a.png"):
        return SimpleUploadedFile(name, b"x", content_type="image/png")

    def test_guest_votes_public_exhibition(self):
        self.client.force_authenticate(self.curator)
        r = _publish_created(self.client.post("/activities/activities/", data=json.dumps({
            "type": "exhibition", "title": "公开影展", "body": "<p>x</p>",
            "voting_enabled": True, "max_choices_per_voter": 1, "audience": "public",
        }), content_type="application/json"))
        aid = r.data["id"]
        self.client.force_authenticate(self.curator)
        self.client.post(f"/activities/activities/{aid}/add_exhibit/",
                         data={"files": [self._img()]})
        self.client.force_authenticate(self.curator)
        detail = self.client.get(f"/activities/activities/{aid}/")
        oid = detail.data["exhibits"][0]["vote_option_id"]

        self.client.force_authenticate(None)
        resp = self.client.post(
            f"/activities/activities/{aid}/vote/",
            data=json.dumps({"option_ids": [oid]}),
            content_type="application/json", HTTP_X_DEVICE_ID=self.DEV1,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["my_selections"], [oid])


class SurveySchemaReopenTest(TestCase):
    """S-4 回归：已过审的调研改 schema → 必须退回待审。

    反证：删掉 ``perform_update`` 里的 ``reopen(...)`` 调用，本条变红（仍是 approved）。
    """

    def setUp(self):
        self.user = grant_verification(User.objects.create_user(username="survey_author", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.activity = Activity.objects.create(
            type="survey", title="调研", audience="public",
            creator=self.user, status="in_progress",
            start_at=timezone.now() - timedelta(hours=1),
            end_at=timezone.now() + timedelta(days=1),
            schema={"pages": [{"name": "p1", "elements": [{"type": "text", "name": "q1"}]}]},
        )
        approve_activity(self.activity)

    def _patch_schema(self, schema):
        return self.client.patch(
            f"/activities/activities/{self.activity.pk}/",
            data=json.dumps({"schema": schema}),
            content_type="application/json",
        )

    def test_schema_change_resets_review(self):
        resp = self._patch_schema(
            {"pages": [{"name": "p1", "elements": [{"type": "text", "name": "q2"}]}]},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        from reviews.models import Review

        self.activity.refresh_from_db()
        review = Review.objects.get(activity=self.activity)
        self.assertEqual(review.status, "pending")

    def test_html_question_rejected_by_api(self):
        resp = self._patch_schema(
            {"pages": [{"elements": [{"type": "html", "html": "<img src=x onerror=alert(1)>"}]}]},
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_unchanged_review_when_patching_other_fields(self):
        """只改标题不该触发重新审核（待开始期）。"""
        self.activity.start_at = timezone.now() + timedelta(hours=2)
        self.activity.save(update_fields=["start_at"])
        resp = self.client.patch(
            f"/activities/activities/{self.activity.pk}/",
            data=json.dumps({"title": "改个标题"}),
            content_type="application/json",
        )
        from reviews.models import Review

        self.assertEqual(resp.status_code, 200, resp.content)
        review = Review.objects.get(activity=self.activity)
        self.assertEqual(review.status, "approved")
