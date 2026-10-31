from datetime import timedelta
import json

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from messaging.models import Banner, Conversation, Message, MessageReadStatus, NotificationSubscription
from messaging.services import mute_user, post_comment, thread_for
from news.models import News
from reviews.test_helpers import approve_news


class UnreadCountTest(TestCase):
    """GET /messaging/conversations/unread_count/ —— 驱动顶栏铃铛红点。

    红点应当只在「确实有别人发来、且自己未读的消息」时出现；自己发出的消息
    不计（发送者不会为自己生成 MessageReadStatus）。
    """

    URL = "/messaging/conversations/unread_count/"

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="secret123")
        self.bob = User.objects.create_user(username="bob", password="secret123")
        self.conv = Conversation.objects.create()
        self.conv.participants.set([self.alice, self.bob])
        self.client.login(username="alice", password="secret123")

    def _total(self):
        return self.client.get(self.URL).json()["total"]

    def test_requires_auth(self):
        resp = Client().get(self.URL)
        self.assertIn(resp.status_code, (401, 403))

    def test_zero_when_no_messages(self):
        self.assertEqual(self._total(), 0)

    def test_counts_messages_from_others(self):
        Message.objects.create(conversation=self.conv, sender=self.bob, content="在吗")
        Message.objects.create(conversation=self.conv, sender=self.bob, content="还有个事")
        self.assertEqual(self._total(), 2)

    def test_ignores_own_messages(self):
        # alice 给自己发的不算未读，否则发过消息的人红点永远亮着
        Message.objects.create(conversation=self.conv, sender=self.alice, content="我自己说的")
        Message.objects.create(conversation=self.conv, sender=self.bob, content="回你")
        self.assertEqual(self._total(), 1)

    def test_clears_once_read(self):
        msg = Message.objects.create(conversation=self.conv, sender=self.bob, content="看一下")
        MessageReadStatus.objects.create(message=msg, user=self.alice)
        self.assertEqual(self._total(), 0)

    def test_mark_read_clears_unread_via_http(self):
        Message.objects.create(conversation=self.conv, sender=self.bob, content="在吗")
        Message.objects.create(conversation=self.conv, sender=self.bob, content="还有个事")
        self.assertEqual(self._total(), 2)
        resp = self.client.post(f"/messaging/conversations/{self.conv.pk}/mark_read/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._total(), 0)

    def test_only_counts_conversations_user_joined(self):
        # alice 不参与的会话里的消息，不计入 alice 的未读
        carol = User.objects.create_user(username="carol", password="secret123")
        other = Conversation.objects.create()
        other.participants.set([self.bob, carol])
        Message.objects.create(conversation=other, sender=carol, content="与 alice 无关")
        self.assertEqual(self._total(), 0)


class MessageThreadPaginationTest(TestCase):
    """GET /messaging/conversations/messages/ —— 消息线程倒序分页。

    前端「最新优先 + 向上加载更早」消费信封：page=1 为最新一页（20/页），
    next 非空即还有更早；结果按 created_at 倒序。
    """

    URL = "/messaging/conversations/messages/"
    PAGE_SIZE = 20

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="secret123")
        self.bob = User.objects.create_user(username="bob", password="secret123")
        self.carol = User.objects.create_user(username="carol", password="secret123")
        self.conv = Conversation.objects.create()
        self.conv.participants.set([self.alice, self.bob])
        self.client.login(username="alice", password="secret123")

    def _get(self, conversation_id, page=None):
        url = f"{self.URL}?conversation_id={conversation_id}"
        if page is not None:
            url += f"&page={page}"
        return self.client.get(url)

    def test_requires_auth(self):
        resp = Client().get(f"{self.URL}?conversation_id={self.conv.pk}")
        self.assertIn(resp.status_code, (401, 403))

    def test_missing_conversation_id(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 400)

    def test_non_participant_not_found(self):
        resp = self._get(self.conv.pk + 9999)  # 不存在
        self.assertEqual(resp.status_code, 404)
        # carol 不是参与者，也应 404（视图用 participants=request.user 过滤）
        self.client.logout()
        self.client.login(username="carol", password="secret123")
        resp = self._get(self.conv.pk)
        self.assertEqual(resp.status_code, 404)

    def test_paginated_envelope(self):
        Message.objects.create(conversation=self.conv, sender=self.bob, content="你好")
        resp = self._get(self.conv.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json().keys()), {"count", "next", "previous", "results"})

    def test_newest_first_and_two_pages(self):
        # 25 条消息：page1 = 最新 20 条，page2 = 最早 5 条
        for i in range(1, 26):
            Message.objects.create(conversation=self.conv, sender=self.bob, content=f"消息{i}")

        page1 = self._get(self.conv.pk, 1).json()
        self.assertEqual(page1["count"], 25)
        self.assertEqual(len(page1["results"]), self.PAGE_SIZE)
        self.assertIsNotNone(page1["next"])
        self.assertIsNone(page1["previous"])
        # 最新在前：首条是最后发的「消息25」，末条是「消息6」
        self.assertEqual(page1["results"][0]["content"], "消息25")
        self.assertEqual(page1["results"][-1]["content"], "消息6")

        page2 = self._get(self.conv.pk, 2).json()
        self.assertEqual(len(page2["results"]), 5)
        self.assertIsNone(page2["next"])
        self.assertIsNotNone(page2["previous"])
        self.assertEqual(page2["results"][0]["content"], "消息5")
        self.assertEqual(page2["results"][-1]["content"], "消息1")

    def test_out_of_range_page_404(self):
        Message.objects.create(conversation=self.conv, sender=self.bob, content="只有一条")
        resp = self._get(self.conv.pk, 99)
        self.assertEqual(resp.status_code, 404)


class ConversationSidebarTest(TestCase):
    """会话侧栏：-updated_at 排序 + 分页信封（数字页码器消费）。"""

    URL = "/messaging/conversations/"

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="secret123")
        self.bob = User.objects.create_user(username="bob", password="secret123")
        self.client.login(username="alice", password="secret123")

    def _mk(self, n=1):
        convs = []
        for _ in range(n):
            c = Conversation.objects.create()
            c.participants.set([self.alice, self.bob])
            convs.append(c)
        return convs

    def test_list_returns_paginated_envelope(self):
        self._mk()
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json().keys()), {"count", "next", "previous", "results"})

    def test_ordered_by_updated_at_desc(self):
        c1, c2 = self._mk(2)
        # 让 c1 最近活跃（updated_at 最新）
        Conversation.objects.filter(pk=c1.pk).update(updated_at=timezone.now() + timedelta(hours=1))
        ids = [r["id"] for r in self.client.get(self.URL).json()["results"]]
        self.assertEqual(ids[0], c1.pk)
        self.assertEqual(ids[1], c2.pk)

    def test_paginated_two_pages(self):
        self._mk(25)
        page1 = self.client.get(self.URL).json()
        self.assertEqual(page1["count"], 25)
        self.assertEqual(len(page1["results"]), 20)
        self.assertIsNotNone(page1["next"])
        page2 = self.client.get(f"{self.URL}?page=2").json()
        self.assertEqual(len(page2["results"]), 5)
        self.assertIsNone(page2["next"])

    def test_list_payload_has_no_task_proposal_or_type(self):
        self._mk()
        row = self.client.get(self.URL).json()["results"][0]
        self.assertNotIn("conversation_type", row)
        self.assertNotIn("task", row)
        self.assertNotIn("proposal", row)
        concrete = {f.name for f in Conversation._meta.local_concrete_fields}
        self.assertNotIn("conversation_type", concrete)
        self.assertNotIn("task", concrete)
        self.assertNotIn("proposal", concrete)

    def test_legacy_task_and_proposal_actions_gone(self):
        # 已从路由器拿掉；POST 会落到 detail pk，DRF 对该资源不允许 POST → 405。
        for action in ("get_task_conversation", "get_proposal_conversation"):
            self.assertIn(self.client.post(f"{self.URL}{action}/").status_code, (404, 405))
            self.assertEqual(self.client.get(f"{self.URL}{action}/").status_code, 404)


def _json_post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


class CommentVisibilityHttpTest(TestCase):
    """未公开新闻的评论区不对公众开放；彻底关闭后普通读者 404。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.stranger = grant_verification(User.objects.create_user(username="stranger", password="x"))

    def test_unpublished_news_thread_not_public(self):
        news = approve_news(
            News.objects.create(title="draft", author=self.author, is_published=False),
        )
        thread = thread_for(news)
        post_comment(thread, self.author, "内部讨论")

        guest = APIClient()
        self.assertEqual(guest.get(f"/messaging/threads/?news={news.pk}").status_code, 404)
        self.assertEqual(guest.get(f"/messaging/comments/?thread={thread.pk}").status_code, 404)

        other = APIClient()
        other.force_authenticate(self.stranger)
        self.assertEqual(other.get(f"/messaging/threads/?news={news.pk}").status_code, 404)
        self.assertEqual(other.get(f"/messaging/comments/?thread={thread.pk}").status_code, 404)

        owner = APIClient()
        owner.force_authenticate(self.author)
        self.assertEqual(owner.get(f"/messaging/threads/?news={news.pk}").status_code, 200)
        self.assertEqual(owner.get(f"/messaging/comments/?thread={thread.pk}").status_code, 200)

    def test_published_news_thread_is_public_readable(self):
        news = approve_news(
            News.objects.create(title="public", author=self.author, is_published=True),
        )
        thread = thread_for(news)
        post_comment(thread, self.author, "公开评论")
        resp = APIClient().get(f"/messaging/threads/?news={news.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "open")
        comments = APIClient().get(f"/messaging/comments/?thread={thread.pk}")
        self.assertEqual(comments.status_code, 200)
        self.assertEqual(comments.json()["results"][0]["content"], "公开评论")

    def test_closed_thread_404_for_readers(self):
        news = approve_news(
            News.objects.create(title="closable", author=self.author, is_published=True),
        )
        thread = thread_for(news)
        owner = APIClient()
        owner.force_authenticate(self.author)
        patch = owner.patch(
            f"/messaging/threads/{thread.pk}/",
            {"status": "closed"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200)
        self.assertEqual(APIClient().get(f"/messaging/threads/?news={news.pk}").status_code, 404)
        other = APIClient()
        other.force_authenticate(self.stranger)
        self.assertEqual(other.get(f"/messaging/threads/?news={news.pk}").status_code, 404)
        self.assertEqual(owner.get(f"/messaging/threads/?news={news.pk}").status_code, 200)


class CommentTombstoneHttpTest(TestCase):
    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="author", password="x"))
        self.news = approve_news(
            News.objects.create(title="t", author=self.author, is_published=True),
        )
        self.thread = thread_for(self.news)
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    def test_manager_delete_returns_tombstone_and_keeps_replies(self):
        root = post_comment(self.thread, self.author, "root")
        post_comment(self.thread, self.author, "child", parent=root)
        resp = self.client.post(f"/messaging/comments/{root.pk}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["content"], "该评论已删除")
        self.assertIsNotNone(resp.json()["deleted_at"])

        listing = self.client.get(f"/messaging/comments/?thread={self.thread.pk}").json()
        tombstone = listing["results"][0]
        self.assertEqual(tombstone["content"], "该评论已删除")
        self.assertEqual(tombstone["replies"][0]["content"], "child")

    def test_news_editor_cannot_delete_on_others_thread(self):
        editor = grant_verification(User.objects.create_user(username="editor", password="x"))
        editor.user_permissions.add(
            Permission.objects.get(content_type__app_label="news", codename="manage_news"),
        )
        commenter = grant_verification(User.objects.create_user(username="c", password="x"))
        comment = post_comment(self.thread, commenter, "hi")
        other = APIClient()
        other.force_authenticate(editor)
        resp = other.post(f"/messaging/comments/{comment.pk}/delete/")
        self.assertEqual(resp.status_code, 403)


class MuteHttpTest(TestCase):
    """全站禁言拦评论和私信，不拦登录、阅读、接收。"""

    def setUp(self):
        self.mod = User.objects.create_user(username="mod", password="x")
        self.mod.user_permissions.add(
            Permission.objects.get(content_type__app_label="reviews", codename="mute_user"),
        )
        self.alice = grant_verification(
            User.objects.create_user(username="alice", password="secret123"),
        )
        self.bob = grant_verification(User.objects.create_user(username="bob", password="x"))
        self.news = approve_news(
            News.objects.create(title="public", author=self.bob, is_published=True),
        )
        self.thread = thread_for(self.news)
        post_comment(self.thread, self.bob, "先写一条")
        mute_user(self.mod, self.alice, reason="spam")

    def test_muted_user_can_still_login(self):
        resp = Client().post(
            "/auth/login/",
            data=json.dumps({"username": "alice", "password": "secret123"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_muted_user_can_read_comments(self):
        client = APIClient()
        client.force_authenticate(self.alice)
        resp = client.get(f"/messaging/comments/?thread={self.thread.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["content"], "先写一条")

    def test_muted_user_cannot_comment_or_dm(self):
        client = APIClient()
        client.force_authenticate(self.alice)
        self.assertEqual(
            _json_post(client, "/messaging/comments/", {
                "thread": self.thread.pk, "content": "被禁言",
            }).status_code,
            403,
        )
        start = _json_post(client, "/messaging/conversations/start_private/", {
            "user_id": self.bob.pk,
        })
        self.assertEqual(start.status_code, 403)

    def test_muted_user_can_receive_dm(self):
        bob = APIClient()
        bob.force_authenticate(self.bob)
        created = _json_post(bob, "/messaging/conversations/start_private/", {
            "user_id": self.alice.pk,
        })
        self.assertIn(created.status_code, (200, 201))
        conv_id = created.json()["id"]
        sent = _json_post(bob, f"/messaging/conversations/{conv_id}/send_message/", {
            "content": "你还能收到",
        })
        self.assertEqual(sent.status_code, 201)

        alice = APIClient()
        alice.force_authenticate(self.alice)
        listing = alice.get("/messaging/conversations/").json()
        self.assertEqual(listing["count"], 1)
        self.assertNotIn("conversation_type", listing["results"][0])
        self.assertNotIn("task", listing["results"][0])
        self.assertNotIn("proposal", listing["results"][0])
        messages = alice.get(
            f"/messaging/conversations/messages/?conversation_id={conv_id}",
        ).json()
        self.assertEqual(messages["results"][0]["content"], "你还能收到")


class BannerCurrentHttpTest(TestCase):
    URL = "/messaging/banners/current/"

    def test_anonymous_none_when_empty(self):
        resp = Client().get(self.URL)
        self.assertEqual(resp.status_code, 204)

    def test_expired_excluded_and_priority_wins(self):
        now = timezone.now()
        Banner.objects.create(
            body="low", starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1),
            priority=1,
        )
        Banner.objects.create(
            body="expired", starts_at=now - timedelta(days=2), ends_at=now - timedelta(hours=1),
            priority=9,
        )
        winner = Banner.objects.create(
            body="high", starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1),
            priority=5,
        )
        resp = Client().get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], winner.pk)
        self.assertEqual(resp.json()["body"], "high")


class NotificationPreferencesApiTest(TestCase):
    """订阅偏好 API：矩阵读取 / 更新 / 校验（所有通道可开关）。"""

    URL = "/messaging/notification-preferences/"

    def setUp(self):
        self.user = User.objects.create_user(username="pref", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_matrix_lists_sources_and_channels(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        source_keys = {s["key"] for s in data["sources"]}
        self.assertIn("review", source_keys)
        self.assertIn("activity", source_keys)
        self.assertIn("discipline", source_keys)
        channel_keys = {c["key"] for c in data["channels"]}
        self.assertEqual(channel_keys, {"site", "email", "webhook", "sms"})
        review = next(s for s in data["sources"] if s["key"] == "review")
        self.assertTrue(review["channels"]["site"])  # 站内默认开启（可关闭）

    def test_patch_enables_email_subscription(self):
        resp = self.client.patch(
            self.URL,
            {"updates": [{"source": "review", "channel": "email", "enabled": True}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            NotificationSubscription.objects.filter(
                user=self.user, source_key="review", channel_key="email", enabled=True,
            ).exists()
        )
        review = next(s for s in resp.json()["sources"] if s["key"] == "review")
        self.assertTrue(review["channels"]["email"])

    def test_patch_rejects_unknown_source(self):
        resp = self.client.patch(
            self.URL,
            {"updates": [{"source": "nope", "channel": "email", "enabled": True}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_site_channel_can_be_disabled(self):
        """用户有权拒绝接收：站内可与其它通道一样关闭，矩阵回读为关。"""
        resp = self.client.patch(
            self.URL,
            {"updates": [{"source": "review", "channel": "site", "enabled": False}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            NotificationSubscription.objects.filter(
                user=self.user, source_key="review", channel_key="site", enabled=False,
            ).exists()
        )
        review = next(s for s in resp.json()["sources"] if s["key"] == "review")
        self.assertFalse(review["channels"]["site"])

    def test_site_channel_can_be_reenabled(self):
        NotificationSubscription.objects.create(
            user=self.user, source_key="review", channel_key="site", enabled=False,
        )
        resp = self.client.patch(
            self.URL,
            {"updates": [{"source": "review", "channel": "site", "enabled": True}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        review = next(s for s in resp.json()["sources"] if s["key"] == "review")
        self.assertTrue(review["channels"]["site"])



class CommentCreateThrottleTest(TestCase):
    """M-3 回归：评论按用户限流。"""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.author = grant_verification(User.objects.create_user(username="cm_throttle", password="x"))
        news = approve_news(News.objects.create(title="n", author=self.author, is_published=True))
        self.thread = thread_for(news)
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def test_comment_rate_limited(self):
        for i in range(30):
            resp = _json_post(self.client, "/messaging/comments/", {"thread": self.thread.pk, "content": f"c{i}"})
            self.assertEqual(resp.status_code, 201, getattr(resp, "data", None))
        resp = _json_post(self.client, "/messaging/comments/", {"thread": self.thread.pk, "content": "overflow"})
        self.assertEqual(resp.status_code, 429)
