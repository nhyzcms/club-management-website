from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from about.models import AboutBlock, AboutPage


def _change_perm():
    return Permission.objects.get(codename="manage_aboutpage")


class AboutReadTest(TestCase):
    """GET /about/：公开可读，返回全部区块 + 概览。"""

    def setUp(self):
        self.client = APIClient()

    def test_anon_get_returns_blocks_and_overview(self):
        resp = self.client.get("/about/")
        self.assertEqual(resp.status_code, 200)
        keys = [b["key"] for b in resp.data["blocks"]]
        self.assertEqual(keys, ["club", "school", "site", "contact", "campus-overview", "support-us"])
        self.assertEqual(resp.data["blocks"][0]["title"], "关于我们")  # 单例标题迁入第一块
        self.assertIn("overview", resp.data)
        self.assertEqual(resp.data["overview"]["founded"], "2026.03")
        self.assertEqual(resp.data["overview"]["advisor"], "信息组")
        self.assertIn("updated_at", resp.data)

    def test_legacy_singleton_migrated_into_first_block(self):
        AboutPage.objects.filter(pk=1).update(title="传媒社", content="<p>旧正文</p>")
        AboutBlock.objects.filter(key="club").update(title="传媒社", content="<p>旧正文</p>")
        resp = self.client.get("/about/")
        club = resp.data["blocks"][0]
        self.assertEqual(club["key"], "club")
        self.assertEqual(club["title"], "传媒社")
        self.assertIn("旧正文", club["content"])


class AboutBlockWriteTest(TestCase):
    """PATCH /about/blocks/<key>/：仅持 about.manage_aboutpage 者可改。"""

    def setUp(self):
        self.client = APIClient()
        self.editor = User.objects.create_user(username="editor", password="x")
        self.editor.user_permissions.add(_change_perm())
        self.normal = User.objects.create_user(username="normal", password="x")

    def test_anon_patch_denied(self):
        resp = self.client.patch("/about/blocks/club/", {"title": "x"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_normal_patch_forbidden(self):
        self.client.force_authenticate(self.normal)
        resp = self.client.patch("/about/blocks/club/", {"title": "x"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_editor_can_update_block(self):
        self.client.force_authenticate(self.editor)
        resp = self.client.patch(
            "/about/blocks/school/",
            {"title": "关于南汇一中", "content": "<p>校园</p>"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        block = AboutBlock.objects.get(key="school")
        self.assertEqual(block.title, "关于南汇一中")
        self.assertEqual(block.content, "<p>校园</p>")

    def test_editor_content_sanitized(self):
        self.client.force_authenticate(self.editor)
        self.client.patch(
            "/about/blocks/club/",
            {"content": "<p>ok</p><script>alert(1)</script>"},
            format="json",
        )
        block = AboutBlock.objects.get(key="club")
        self.assertNotIn("<script", block.content)
        self.assertIn("ok", block.content)

    def test_same_perm_covers_all_blocks(self):
        self.client.force_authenticate(self.editor)
        for key in ("club", "school", "site", "contact", "campus-overview", "support-us"):
            resp = self.client.patch(f"/about/blocks/{key}/", {"title": f"t-{key}"}, format="json")
            self.assertEqual(resp.status_code, 200, key)


class CampusOverviewTest(TestCase):
    """校园一览第五块 + panorama_url。"""

    def setUp(self):
        self.client = APIClient()
        self.editor = User.objects.create_user(username="editor", password="x")
        self.editor.user_permissions.add(_change_perm())

    def test_fifth_block_is_campus_overview(self):
        resp = self.client.get("/about/")
        self.assertEqual(resp.data["blocks"][4]["key"], "campus-overview")
        self.assertEqual(resp.data["blocks"][4]["panorama_url"], "")

    def test_editor_sets_panorama_url(self):
        self.client.force_authenticate(self.editor)
        resp = self.client.patch(
            "/about/blocks/campus-overview/",
            {"panorama_url": "https://panorama.example/nhyz"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["panorama_url"], "https://panorama.example/nhyz")
        public = APIClient().get("/about/")
        self.assertEqual(public.data["blocks"][4]["panorama_url"], "https://panorama.example/nhyz")


class AboutDocumentImportTest(TestCase):
    """区块文档保真导入：PDF / docx 原件可下载，上传替换，删除即移除。"""

    def setUp(self):
        self.client = APIClient()
        self.editor = User.objects.create_user(username="editor", password="x")
        self.editor.user_permissions.add(_change_perm())
        self.client.force_authenticate(self.editor)

    def test_upload_pdf_returns_download_url(self):
        pdf = SimpleUploadedFile("章程.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        resp = self.client.patch("/about/blocks/club/", {"document": pdf}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["document_url"])
        self.assertIn("club", resp.data["document_name"])

    def test_upload_replaces_existing_document(self):
        a = SimpleUploadedFile("a.pdf", b"%PDF-1.4 a", content_type="application/pdf")
        b = SimpleUploadedFile("b.pdf", b"%PDF-1.4 b", content_type="application/pdf")
        self.client.patch("/about/blocks/club/", {"document": a}, format="multipart")
        resp = self.client.patch("/about/blocks/club/", {"document": b}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("club", resp.data["document_name"])

    def test_clear_document_removes_file(self):
        pdf = SimpleUploadedFile("a.pdf", b"%PDF-1.4 a", content_type="application/pdf")
        self.client.patch("/about/blocks/club/", {"document": pdf}, format="multipart")
        resp = self.client.patch("/about/blocks/club/", {"clear_document": "true"}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["document_url"])

    def test_rejects_non_document(self):
        txt = SimpleUploadedFile("x.txt", b"hello", content_type="text/plain")
        resp = self.client.patch("/about/blocks/club/", {"document": txt}, format="multipart")
        self.assertEqual(resp.status_code, 400)


class ClubOverviewWriteTest(TestCase):
    """PUT /about/overview/：静态行可编辑；成员数/作品数仍走 news.overview。"""

    def setUp(self):
        self.client = APIClient()
        self.editor = User.objects.create_user(username="editor", password="x")
        self.editor.user_permissions.add(_change_perm())
        self.normal = User.objects.create_user(username="normal", password="x")

    def test_anon_can_read_overview(self):
        resp = self.client.get("/about/overview/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["founded"], "2026.03")

    def test_normal_cannot_update(self):
        self.client.force_authenticate(self.normal)
        resp = self.client.put(
            "/about/overview/",
            {"founded": "2019", "advisor": "x", "intro": "y"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_editor_can_update_static_rows(self):
        self.client.force_authenticate(self.editor)
        resp = self.client.put(
            "/about/overview/",
            {"founded": "2019.09", "advisor": "信息组 / 团委", "intro": "用镜头记录青春"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        solo = AboutPage.objects.get_solo()
        self.assertEqual(solo.founded, "2019.09")
        self.assertEqual(solo.advisor, "信息组 / 团委")
        self.assertEqual(solo.intro, "用镜头记录青春")


class AboutCapabilityTest(TestCase):
    """/auth/me/ 透出 can_edit_about（由 has_perm 派生）。"""

    def test_capability_reflects_perm(self):
        from accounts.views import _capabilities

        holder = User.objects.create_user(username="h", password="x")
        holder.user_permissions.add(_change_perm())
        self.assertTrue(_capabilities(holder)["can_edit_about"])

        nope = User.objects.create_user(username="n", password="x")
        self.assertFalse(_capabilities(nope)["can_edit_about"])

    def test_me_exposes_can_edit_about(self):
        holder = User.objects.create_user(username="h", password="x")
        holder.user_permissions.add(_change_perm())
        c = APIClient()
        c.login(username="h", password="x")
        resp = c.get("/auth/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["user"]["permissions"]["can_edit_about"])


class AboutSingletonTest(TestCase):
    """AboutPage 为单例：全局仅一行（pk 恒为 1），且始终存在。"""

    def test_only_one_row(self):
        AboutPage.objects.create(title="a")
        AboutPage.objects.create(title="b")
        self.assertEqual(AboutPage.objects.count(), 1)
        self.assertEqual(AboutPage.objects.get().title, "b")

    def test_get_solo_always_returns_pk1(self):
        solo = AboutPage.objects.get_solo()
        self.assertEqual(solo.pk, 1)
        self.assertEqual(solo.title, "关于我们")
