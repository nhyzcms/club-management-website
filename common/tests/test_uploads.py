"""上传安全（common.uploads）的单元测试。

这一组测试守的是「文件落盘 → nginx 按扩展名直出 → 浏览器执行」这条链：
公开媒体目录里一旦出现 ``.html`` / ``.svg`` / ``.xml``，就等于在站点同源托管了
任意脚本（存储型 XSS）。

做法：不看客户端声明的 ``Content-Type``，只看**文件真实内容**；落盘扩展名由服务端
决定。反证方式见 ``test_safe_extension_falls_back_for_html`` —— 把
``RESTRICTED_EXTENSIONS`` 里的 ``.html`` 去掉，该用例与端点级用例会一起变红。
"""
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from common.uploads import (
    RESTRICTED_EXTENSIONS,
    extension_of,
    is_restricted,
    rename_upload,
    safe_extension,
    sniff_image_extension,
    sniff_pdf,
    sniff_zip,
)


def _png_bytes(size=(4, 4), color=(10, 20, 30, 255)) -> bytes:
    buf = BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(buf, format="JPEG")
    return buf.getvalue()


class ExtensionPolicyTest(TestCase):
    def test_restricted_covers_document_and_script_types(self):
        for name in ("a.html", "a.HTM", "a.xhtml", "a.svg", "a.xml", "a.js", "a.php", "a.phtml"):
            self.assertTrue(is_restricted(name), name)

    def test_normal_document_extensions_pass(self):
        for name in ("a.png", "a.jpg", "a.pdf", "a.docx", "a.zip", "a.txt", "a.mp4"):
            self.assertFalse(is_restricted(name), name)


class SafeExtensionTest(TestCase):
    """落盘层兜底：任何 upload_to 都不会写出发可执行的扩展名。"""

    def test_safe_extension_keeps_normal(self):
        self.assertEqual(safe_extension("book.epub"), ".epub")
        self.assertEqual(safe_extension("a.PDF"), ".pdf")  # 统一小写

    def test_safe_extension_falls_back_for_html(self):
        # ⚠️ 反证锚点：从 RESTRICTED_EXTENSIONS 删掉 .html，本用例立即变红
        self.assertEqual(safe_extension("evil.html"), ".bin")

    def test_safe_extension_falls_back_for_svg_and_xml(self):
        self.assertEqual(safe_extension("x.svg"), ".bin")
        self.assertEqual(safe_extension("x.xml"), ".bin")

    def test_safe_extension_handles_empty_and_weird(self):
        self.assertEqual(safe_extension(""), ".bin")
        self.assertEqual(safe_extension("noext"), ".bin")
        self.assertEqual(safe_extension("a." + "x" * 40), ".bin")  # 超长扩展名
        self.assertEqual(safe_extension("../../etc/passwd"), ".bin")

    def test_every_restricted_extension_is_neutralized(self):
        for ext in RESTRICTED_EXTENSIONS:
            self.assertEqual(safe_extension("file" + ext), ".bin", ext)


class ImageSniffTest(TestCase):
    def test_real_png_and_jpeg_pass(self):
        self.assertEqual(sniff_image_extension(SimpleUploadedFile("a.png", _png_bytes())), ".png")
        self.assertEqual(sniff_image_extension(SimpleUploadedFile("a.jpg", _jpeg_bytes())), ".jpg")

    def test_format_comes_from_content_not_name(self):
        """名字写 .html、content_type 写 image/png，但内容是 PNG → 按 PNG 落盘。"""
        probe = SimpleUploadedFile("evil.html", _png_bytes(), content_type="image/png")
        self.assertEqual(sniff_image_extension(probe), ".png")

    def test_html_masquerading_as_png_is_rejected(self):
        """核心攻击载荷：HTML 声称图片。"""
        probe = SimpleUploadedFile(
            "probe.html", b"<html><script>alert(document.domain)</script></html>",
            content_type="image/png",
        )
        with self.assertRaises(ValidationError):
            sniff_image_extension(probe)

    def test_svg_is_rejected_as_image(self):
        probe = SimpleUploadedFile(
            "x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type="image/svg+xml",
        )
        with self.assertRaises(ValidationError):
            sniff_image_extension(probe)

    def test_allowed_narrowing(self):
        """allowed 参数能收窄格式（证明文件不收 GIF）。"""
        buf = BytesIO()
        Image.new("P", (2, 2)).save(buf, format="GIF")
        probe = SimpleUploadedFile("a.gif", buf.getvalue(), content_type="image/gif")
        self.assertEqual(sniff_image_extension(probe), ".gif")
        with self.assertRaises(ValidationError):
            sniff_image_extension(probe, allowed={".png", ".jpg"})

    def test_restores_file_pointer(self):
        probe = SimpleUploadedFile("a.png", _png_bytes())
        sniff_image_extension(probe)
        self.assertEqual(probe.tell(), 0)


class DocSniffTest(TestCase):
    def test_pdf_magic(self):
        self.assertTrue(sniff_pdf(SimpleUploadedFile("a.pdf", b"%PDF-1.7\n...")))
        self.assertFalse(sniff_pdf(SimpleUploadedFile("a.html", b"<html></html>")))

    def test_zip_magic(self):
        self.assertTrue(sniff_zip(SimpleUploadedFile("a.docx", b"PK\x03\x04rest")))
        self.assertFalse(sniff_zip(SimpleUploadedFile("a.html", b"<html></html>")))


class RenameUploadTest(TestCase):
    def test_rename_uses_server_extension(self):
        probe = SimpleUploadedFile("用户 上传.HTML", b"x")
        rename_upload(probe, ".png")
        self.assertEqual(probe.name, "用户 上传.png")
        self.assertEqual(extension_of(probe.name), ".png")

    def test_rename_strips_path_separators(self):
        probe = SimpleUploadedFile("../../evil.html", b"x")
        rename_upload(probe, ".jpg")
        self.assertNotIn("/", probe.name)
        self.assertNotIn("\\", probe.name)
        self.assertEqual(probe.name, "evil.jpg")
