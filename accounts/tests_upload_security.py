"""上传端点的 XSS 回归测试（账户侧：头像 / 身份证明）。

威胁模型（2026-10 实测漏洞）：所有上传端点原先只信客户端声明的 ``content_type``
与文件名扩展名。攻击者上传 ``probe.html`` 并声称 ``image/png``，文件就以 ``.html``
落进公开媒体目录，nginx 按扩展名返回 ``text/html`` —— 打开链接即在站点同源执行
任意脚本（可读 CSRF token、以受害者身份调 API）。

修复后的契约：
1. 图片类型由 **Pillow 真实解码** 决定，与声明无关；
2. 落盘扩展名由服务端决定（``rename_upload``），客户端写的 ``.html`` 不会留下；
3. ``upload_to`` 层还有 ``safe_extension`` 兜底：绕过视图直接 save 也写不出可执行扩展名。
"""
import glob
import os
import tempfile
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import Profile

_PROBE_HTML = b"<html><body><script>alert(document.domain)</script></body></html>"
_TEST_MEDIA = tempfile.mkdtemp(prefix="club-test-media-")


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGBA", (4, 4), (1, 2, 3, 255)).save(buf, format="PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class AvatarUploadSecurityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="avatar_probe", password="x")
        self.client.force_login(self.user)

    def test_html_disguised_as_image_is_rejected(self):
        probe = SimpleUploadedFile("probe.html", _PROBE_HTML, content_type="image/png")
        resp = self.client.post("/auth/profile/update/", {"avatar": probe})
        self.assertEqual(resp.status_code, 400, resp.content)
        profile = Profile.objects.get(user=self.user)
        self.assertFalse(profile.avatar)
        self.assertEqual(
            glob.glob(os.path.join(_TEST_MEDIA, "avatars", "*.html")), []
        )

    def test_real_image_gets_server_side_extension(self):
        """真的 PNG、但文件名与 content_type 都在撒谎 → 仍按 PNG 落盘。"""
        probe = SimpleUploadedFile("photo.html", _png(), content_type="text/plain")
        resp = self.client.post("/auth/profile/update/", {"avatar": probe})
        self.assertEqual(resp.status_code, 200, resp.content)
        profile = Profile.objects.get(user=self.user)
        self.assertTrue(profile.avatar.name.endswith(".png"), profile.avatar.name)

    def test_upload_to_fallback_blocks_executable_extension(self):
        """兜底层：绕过视图直接 save('evil.html')，落盘也不得是 .html。"""
        profile, _ = Profile.objects.get_or_create(user=self.user)
        profile.avatar.save("evil.html", ContentFile(_PROBE_HTML), save=True)
        self.assertFalse(profile.avatar.name.endswith(".html"), profile.avatar.name)
        self.assertTrue(profile.avatar.name.endswith(".bin"), profile.avatar.name)
