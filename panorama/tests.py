"""panorama 应用测试：DJI 元数据解析、瓦片切片、导入准入、权限与可见性。

素材全部现场合成（PIL 画一张小图 + 手写 XMP APP1 段），不依赖任何仓库内大文件，
分层规模按 1024 起（单层一整幅）以保持测试毫秒级。
"""
import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.contrib.auth.models import Permission, User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image, ImageDraw

from accounts.views import _capabilities

from .dji import adapt_initial_view, device_label, read_metadata
from .models import Panorama
from .services import PanoramaImportError, import_panorama

DJI_XMP = """<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
      xmlns:GPano="http://ns.google.com/photos/1.0/panorama/"
      xmlns:drone-dji="http://ns.dji.com/drone-dji/1.0/"
      GPano:ProjectionType="equirectangular"
      GPano:UsePanoramaViewer="True"
      GPano:FullPanoWidthPixels="4096"
      GPano:FullPanoHeightPixels="2048"
      GPano:CroppedAreaImageWidthPixels="4096"
      GPano:PoseHeadingDegrees="128.5"
      GPano:InitialViewHeadingDegrees="150"
      GPano:InitialViewPitchDegrees="-8"
      GPano:InitialViewVerticalFovDegrees="75"
      drone-dji:GimbalYawDegree="128.5"
      drone-dji:AbsoluteAltitude="+120.30"
      drone-dji:Model="FC7303" />
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

# 裁切过的全景：GPano 自报裁切宽度（4096）小于全图宽度（8192）→ 不是完整球面。
CROPPED_XMP = DJI_XMP.replace('FullPanoWidthPixels="4096"', 'FullPanoWidthPixels="8192"')


def _equirect_jpeg(width: int = 1024, height: int = 512, *, xmp: str | None = None) -> bytes:
    image = Image.new("RGB", (width, height), (40, 80, 140))
    draw = ImageDraw.Draw(image)
    for index in range(8):
        x = width * index // 8
        draw.rectangle(
            [x, 0, x + width // 16, height],
            fill=(index * 30 % 255, 120, 200 - index * 20),
        )
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70)
    data = buffer.getvalue()
    return _inject_xmp(data, xmp) if xmp else data


def _inject_xmp(jpeg: bytes, xmp: str) -> bytes:
    """把 XMP 包写成 JPEG 的 APP1 段（紧跟 SOI），模拟相机写入的文件。"""
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp.encode("utf-8")
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return jpeg[:2] + segment + jpeg[2:]


def _upload(data: bytes, name: str) -> SimpleUploadedFile:
    content_type = "application/zip" if name.lower().endswith(".zip") else "image/jpeg"
    return SimpleUploadedFile(name, data, content_type=content_type)


def _media_files() -> list[str]:
    """MEDIA_ROOT 下的全部相对路径（用于断言「没落压缩包」这类事实）。"""
    found = []
    for root, _dirs, files in os.walk(default_storage.location):
        for name in files:
            found.append(os.path.relpath(os.path.join(root, name), default_storage.location))
    return found


class _MediaRootMixin:
    """每个测试类用独立 MEDIA_ROOT——切片产物绝不落到仓库的 media/。"""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix="panorama-test-")
        cls._settings_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._settings_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._settings_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)


class DjiMetadataTest(TestCase):
    """XMP 解析：GPano + drone-dji，属性写法与缺失字段的降级。"""

    def setUp(self):
        self.meta = read_metadata(io.BytesIO(_equirect_jpeg(1024, 512, xmp=DJI_XMP)))

    def test_reads_dji_and_gpano_fields(self):
        self.assertTrue(self.meta.is_dji)
        self.assertEqual(self.meta.projection, "equirectangular")
        self.assertEqual(self.meta.full_width, 4096)
        self.assertEqual(self.meta.width, 1024)
        self.assertAlmostEqual(self.meta.heading_degrees, 128.5)
        self.assertAlmostEqual(self.meta.initial_heading, 150.0)
        self.assertEqual(self.meta.fields["drone-dji:Model"], "FC7303")

    def test_device_label_falls_back_to_drone_dji_model(self):
        # 合成图没有 EXIF 机型，机型名只能来自 XMP —— 走回落分支。
        self.assertEqual(device_label(self.meta), "FC7303")

    def test_initial_view_is_relative_to_image_centre(self):
        yaw, pitch, fov = adapt_initial_view(self.meta)
        self.assertAlmostEqual(yaw, 21.5)  # 150 - 128.5
        self.assertAlmostEqual(pitch, -8.0)
        self.assertAlmostEqual(fov, 75.0)

    def test_plain_image_without_xmp_degrades_gracefully(self):
        meta = read_metadata(io.BytesIO(_equirect_jpeg(1024, 512)))
        self.assertFalse(meta.is_dji)
        self.assertIsNone(meta.heading_degrees)
        self.assertEqual(adapt_initial_view(meta), (0.0, 0.0, 100.0))


class ImportValidationTest(_MediaRootMixin, TestCase):
    """准入校验：不是全景图 / 裁切过的全景图一律拒绝，且不留记录。"""

    def test_square_image_rejected(self):
        with self.assertRaises(PanoramaImportError) as caught:
            import_panorama(upload=_upload(_equirect_jpeg(600, 600), "square.jpg"), title="方形")
        self.assertEqual(caught.exception.reason, "not_equirectangular")
        self.assertEqual(Panorama.objects.count(), 0)

    def test_cropped_panorama_rejected(self):
        with self.assertRaises(PanoramaImportError) as caught:
            import_panorama(
                upload=_upload(_equirect_jpeg(1024, 512, xmp=CROPPED_XMP), "cropped.jpg"),
                title="裁切全景",
            )
        self.assertEqual(caught.exception.reason, "not_equirectangular")

    def test_non_image_rejected(self):
        with self.assertRaises(PanoramaImportError) as caught:
            import_panorama(upload=_upload(b"not an image at all", "note.jpg"), title="坏文件")
        self.assertEqual(caught.exception.reason, "unsupported_image")


class TilingTest(_MediaRootMixin, TestCase):
    """分层产物：层级表、层级图文件、预览 / 缩略图、以及回收。"""

    def test_single_level_pyramid(self):
        panorama = import_panorama(
            upload=_upload(_equirect_jpeg(1024, 512), "pano.jpg"), title="操场"
        )
        self.assertEqual(panorama.status, Panorama.STATUS_READY)
        self.assertEqual(panorama.error, "")
        self.assertEqual((panorama.width, panorama.height), (1024, 512))
        self.assertEqual([level["z"] for level in panorama.tile_levels], [0])
        self.assertEqual(
            panorama.tile_levels[0], {"z": 0, "width": 1024, "height": 512},
        )
        self.assertTrue(default_storage.exists(f"{panorama.tile_dir}/0.jpg"))
        self.assertTrue(default_storage.exists(panorama.preview_name))
        self.assertTrue(default_storage.exists(panorama.thumb_name))

    def test_multi_level_pyramid_is_ascending(self):
        panorama = import_panorama(
            upload=_upload(_equirect_jpeg(2048, 1024), "pano.jpg"), title="教学楼"
        )
        self.assertEqual([level["width"] for level in panorama.tile_levels], [1024, 2048])
        self.assertEqual([level["z"] for level in panorama.tile_levels], [0, 1])
        # 每级一整幅层级图（EquirectGeometry 一层一图）：z=1 的整图必须真实落盘。
        for z in (0, 1):
            self.assertTrue(default_storage.exists(f"{panorama.tile_dir}/{z}.jpg"))

    def test_tile_url_template_shape(self):
        panorama = import_panorama(
            upload=_upload(_equirect_jpeg(1024, 512), "pano.jpg"), title="操场"
        )
        template = panorama.tile_url_template
        self.assertEqual(template, f"/media/{panorama.tile_dir}/{{z}}.jpg")
        # EquirectGeometry 每层一整幅图，模板只能有 {z}；混入 {y}/{x}（立方体贴图记法）
        # 会被替换为空串 → `…/1//.jpg` 全量 404（2026-10 线上事故的回归守卫）。
        self.assertNotIn("{y}", template)
        self.assertNotIn("{x}", template)

    def test_delete_assets_purges_tiles(self):
        panorama = import_panorama(
            upload=_upload(_equirect_jpeg(1024, 512), "pano.jpg"), title="操场"
        )
        tile_path = f"{panorama.tile_dir}/0.jpg"
        self.assertTrue(default_storage.exists(tile_path))
        panorama.delete()
        self.assertFalse(default_storage.exists(tile_path))


class ArchiveImportTest(_MediaRootMixin, TestCase):
    """zip 导入：挑出最合适的全景图，压缩包本身绝不落 media。"""

    @staticmethod
    def _zip(*entries: tuple[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
        return buffer.getvalue()

    def test_picks_equirect_member_and_drops_the_archive(self):
        archive = self._zip(
            ("readme.txt", b"not an image"),
            ("__MACOSX/._DJI_0001.JPG", b"junk"),
            ("THUMB.jpg", _equirect_jpeg(512, 512)),
            ("DJI_0001.JPG", _equirect_jpeg(1024, 512, xmp=DJI_XMP)),
        )
        panorama = import_panorama(upload=_upload(archive, "pano.zip"), title="打包导入")
        self.assertEqual(panorama.status, Panorama.STATUS_READY)
        self.assertEqual(panorama.source_name, "DJI_0001.JPG")
        self.assertEqual(panorama.origin, Panorama.ORIGIN_DJI)
        self.assertEqual([name for name in _media_files() if name.endswith(".zip")], [])

    def test_archive_without_image_rejected(self):
        archive = self._zip(("readme.txt", b"nope"))
        with self.assertRaises(PanoramaImportError) as caught:
            import_panorama(upload=_upload(archive, "pano.zip"), title="空包")
        self.assertEqual(caught.exception.reason, "no_image_in_archive")

    def test_broken_archive_rejected(self):
        with self.assertRaises(PanoramaImportError) as caught:
            import_panorama(upload=_upload(b"PK\x03\x04 garbage", "pano.zip"), title="坏包")
        self.assertEqual(caught.exception.reason, "bad_zip")


class PanoramaApiTest(_MediaRootMixin, TestCase):
    """接口层：能力键、权限门禁、可见性、取片模板、删除回收。"""

    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="pw-12345")
        self.manager.user_permissions.add(
            Permission.objects.get(
                codename="manage_panoramas", content_type__app_label="panorama",
            )
        )
        self.plain = User.objects.create_user(username="plain", password="pw-12345")

    def _create(self):
        return self.client.post(
            "/panorama/panoramas/",
            {"title": "操场", "source": _upload(_equirect_jpeg(1024, 512), "pano.jpg")},
        )

    def test_capability_key_follows_permission(self):
        self.assertTrue(_capabilities(self.manager)["can_manage_panoramas"])
        self.assertFalse(_capabilities(self.plain)["can_manage_panoramas"])

    def test_anonymous_and_plain_user_cannot_create(self):
        self.assertEqual(self._create().status_code, 403)
        self.client.force_login(self.plain)
        self.assertEqual(self._create().status_code, 403)

    def test_manager_can_create_and_public_can_read(self):
        self.client.force_login(self.manager)
        response = self._create()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertIn("{z}.jpg", body["tile_url_template"])
        self.assertNotIn("{y}", body["tile_url_template"])
        # 网格时代的字段随修复下线：tile_size 不再出现在契约里。
        self.assertNotIn("tile_size", body)
        self.assertEqual(len(body["tile_levels"]), 1)

        self.client.logout()
        listed = self.client.get("/panorama/panoramas/").json()
        self.assertEqual(listed["count"], 1)
        # 原图是受限读：匿名拿到的 source_url 必须为空。
        detail = self.client.get(f"/panorama/panoramas/{body['id']}/").json()
        self.assertIsNone(detail["source_url"])

    def test_manager_sees_source_url(self):
        self.client.force_login(self.manager)
        created = self._create().json()
        detail = self.client.get(f"/panorama/panoramas/{created['id']}/").json()
        self.assertTrue(detail["source_url"].endswith(".jpg"))

    def test_unpublished_and_processing_hidden_from_public(self):
        Panorama.objects.create(title="草稿", is_published=False, status=Panorama.STATUS_READY)
        Panorama.objects.create(title="切片中", status=Panorama.STATUS_PROCESSING)
        self.assertEqual(self.client.get("/panorama/panoramas/").json()["count"], 0)

        self.client.force_login(self.manager)
        self.assertEqual(self.client.get("/panorama/panoramas/").json()["count"], 2)

    def test_delete_purges_assets(self):
        self.client.force_login(self.manager)
        created = self._create().json()
        panorama = Panorama.objects.get(pk=created["id"])
        tile_path = f"{panorama.tile_dir}/0.jpg"
        self.assertTrue(default_storage.exists(tile_path))

        response = self.client.delete(f"/panorama/panoramas/{panorama.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(default_storage.exists(tile_path))

    def test_reprocess_regenerates_tiles(self):
        self.client.force_login(self.manager)
        created = self._create().json()
        before = Panorama.objects.get(pk=created["id"]).tile_dir
        response = self.client.post(f"/panorama/panoramas/{created['id']}/reprocess/")
        self.assertEqual(response.status_code, 200)
        after = Panorama.objects.get(pk=created["id"]).tile_dir
        self.assertNotEqual(before, after)
        self.assertFalse(default_storage.exists(f"{before}/0.jpg"))


class ImportStaticPanoramasCommandTest(_MediaRootMixin, TestCase):
    """既有静态素材的导入命令：可跑、幂等、支持 --dry-run。"""

    def setUp(self):
        self.source_dir = Path(tempfile.mkdtemp(prefix="panorama-static-"))
        self.addCleanup(shutil.rmtree, self.source_dir, True)
        (self.source_dir / "pano_1.jpg").write_bytes(_equirect_jpeg(1024, 512))
        (self.source_dir / "pano_2.jpg").write_bytes(_equirect_jpeg(1024, 512))

    def test_imports_and_is_idempotent(self):
        call_command("import_static_panoramas", "--source-dir", str(self.source_dir), verbosity=0)
        self.assertEqual(Panorama.objects.count(), 2)
        self.assertEqual(Panorama.objects.filter(status=Panorama.STATUS_READY).count(), 2)
        self.assertEqual(Panorama.objects.filter(origin=Panorama.ORIGIN_IMPORT).count(), 2)

        call_command("import_static_panoramas", "--source-dir", str(self.source_dir), verbosity=0)
        self.assertEqual(Panorama.objects.count(), 2)  # 幂等：不重复导入

    def test_dry_run_writes_nothing(self):
        call_command(
            "import_static_panoramas", "--source-dir", str(self.source_dir),
            "--dry-run", verbosity=0,
        )
        self.assertEqual(Panorama.objects.count(), 0)


class PanoramaMetadataPrivacyTest(_MediaRootMixin, TestCase):
    """L-3 回归：公开侧隐去 GPS / 序列号，管理者保留全量。"""

    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user(username="pano_mgr", password="pw-12345")
        self.manager.user_permissions.add(
            Permission.objects.get(
                codename="manage_panoramas", content_type__app_label="panorama",
            )
        )
        self.pano = Panorama.objects.create(
            title="操场", status=Panorama.STATUS_READY, is_published=True,
            metadata={
                "make": "DJI", "model": "Mavic 3",
                "dji": {
                    "drone-dji:GpsLatitude": 31.23,
                    "drone-dji:GpsLongitude": 121.47,
                    "drone-dji:SerialNumber": "SN123",
                },
                "GPano:ProjectionType": "equirectangular",
            },
        )

    def test_public_metadata_redacted(self):
        body = self.client.get(f"/panorama/panoramas/{self.pano.pk}/").json()
        self.assertEqual(body["metadata"]["make"], "DJI")
        dji = body["metadata"].get("dji", {})
        self.assertNotIn("drone-dji:GpsLatitude", dji)
        self.assertNotIn("drone-dji:GpsLongitude", dji)
        self.assertNotIn("drone-dji:SerialNumber", dji)
        self.assertEqual(body["metadata"]["GPano:ProjectionType"], "equirectangular")

    def test_manager_sees_full_metadata(self):
        self.client.force_login(self.manager)
        body = self.client.get(f"/panorama/panoramas/{self.pano.pk}/").json()
        self.assertEqual(body["metadata"]["dji"]["drone-dji:SerialNumber"], "SN123")
