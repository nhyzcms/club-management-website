"""明信片互寄测试（主 seam：HTTP 黑盒，同 events/tests.py 风格）。

覆盖：5 阶段状态机推导、条码生成/唯一性/数量校验/PDF 版面、登记全流程
（phase 门禁 / 条码占用 / 年级学校校验 / 照片魔数与 EXIF 剥离 / 零残留）、
归属三轨与 IDOR（登记码能力凭证）、管理端（配置/发布/壳锁/记录/导出公式
注入/统计/签收/审计）、公告 PDF 沙箱头。

限流测试注意：locmem cache 跨用例共享，setUp 里 clear，防串味。
"""
from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from events.models import Event

from . import barcode as barcode_mod
from . import state
from .models import (
    PostcardAuditLog,
    PostcardBarcode,
    PostcardConfig,
    PostcardItem,
    PostcardPhoto,
    PostcardRegistration,
)

DEVICE_A = "a" * 32
DEVICE_B = "b" * 32


def _jpeg_bytes(size=(64, 64), color="red", with_exif=False) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[0x0112] = 1
        img.save(buf, format="JPEG", exif=exif.tobytes())
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def _admin(name="postcard-admin"):
    user = User.objects.create_user(username=name, password="test-pass-123")
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="events", codename="manage_postcard")
    )
    return user


def _reviewer(name="postcard-reviewer"):
    user = User.objects.create_user(username=name, password="test-pass-123")
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="events", codename="review_postcard")
    )
    return user


def _config_event(*, start=None, end=None, ship=None, distribute=None, publish=True,
                  grades=None, schools=None):
    """建一个明信片活动（默认：登记中——开始于 1h 前、结束于 7d 后）。"""
    now = timezone.now()
    organizer = User.objects.create_user(
        username=f"organizer-{uuid.uuid4().hex[:8]}", password="test-pass-123",
    )
    event = Event.objects.create(
        title="明信片互寄",
        module_key="postcard",
        visibility=Event.VISIBILITY_PUBLIC,
        organizer=organizer,
        start_at=start or (now - timedelta(hours=1)),
        end_at=end or (now + timedelta(days=7)),
        status=Event.STATUS_DRAFT,
    )
    config = PostcardConfig.objects.create(
        event=event,
        allowed_grades=grades or [],
        destination_schools=schools or [
            {"region": "浦东新区", "name": "友爱中学"},
            {"region": "黄浦区", "name": "光明中学"},
        ],
        ship_at=ship,
        distribute_at=distribute,
    )
    if publish:
        event.status = state.lifecycle.initial_status(event.start_at)
        event.save(update_fields=["status"])
    return event, config


def _barcodes(event, codes):
    return PostcardBarcode.objects.bulk_create(
        [PostcardBarcode(event=event, code=c) for c in codes]
    )


def _register_payload(barcodes, **overrides):
    data = {
        "sender_name": "张三",
        "grade": "g1",
        "class_no": 3,
        "dest_region": "浦东新区",
        "dest_school": "友爱中学",
        "items": json.dumps([{"barcode": b} for b in barcodes]),
        "fingerprint": "aabbccdd00112233",
    }
    data.update(overrides)
    return data


def _register_files(n_items):
    """SimpleUploadedFile 才会被 encode_multipart 当文件（元组会被拆成表单字段）。"""
    files = {}
    for i in range(n_items):
        files[f"photo_{i}_front"] = SimpleUploadedFile(
            f"front{i}.jpg", _jpeg_bytes(color="blue"), "image/jpeg",
        )
        files[f"photo_{i}_back"] = SimpleUploadedFile(
            f"back{i}.jpg", _jpeg_bytes(color="green"), "image/jpeg",
        )
    return files


class PhaseStateTest(TestCase):
    """5 阶段推导：时间惰性、空节点跳过、draft/archived 语义。"""

    def test_no_event_is_not_started(self):
        self.assertEqual(state.phase_of(None, None), state.PHASE_NOT_STARTED)

    def test_draft_is_not_started(self):
        event, config = _config_event(publish=False)
        self.assertEqual(state.phase_of(event, config), state.PHASE_NOT_STARTED)

    def test_registering_window(self):
        event, config = _config_event()
        self.assertEqual(state.phase_of(event, config), state.PHASE_REGISTERING)

    def test_shipped_and_distributing(self):
        now = timezone.now()
        event, config = _config_event(
            start=now - timedelta(days=3),
            ship=now - timedelta(days=2),
            distribute=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )
        self.assertEqual(state.phase_of(event, config), state.PHASE_DISTRIBUTING)
        # 时间旅行到 ship 与 distribute 之间 → 已寄出
        self.assertEqual(
            state.phase_of(event, config, now=now - timedelta(days=1, hours=12)),
            state.PHASE_SHIPPED,
        )

    def test_ended_by_end_at(self):
        now = timezone.now()
        event, config = _config_event(start=now - timedelta(days=9), end=now - timedelta(days=1))
        event.status = Event.STATUS_ENDED
        event.save(update_fields=["status"])
        self.assertEqual(state.phase_of(event, config), state.PHASE_ENDED)

    def test_null_milestones_skip_phases(self):
        now = timezone.now()
        event, config = _config_event(start=now - timedelta(days=3), end=now + timedelta(days=1))
        # 无 ship/distribute：登记中直到结束
        self.assertEqual(state.phase_of(event, config), state.PHASE_REGISTERING)

    def test_progress_nodes(self):
        now = timezone.now()
        event, config = _config_event(
            start=now - timedelta(days=2),
            ship=now - timedelta(days=1),
            distribute=None,
            end=now + timedelta(days=1),
        )
        nodes = state.progress_nodes(event, config)
        self.assertEqual([n["key"] for n in nodes], ["start", "ship", "distribute", "end"])
        self.assertEqual([n["reached"] for n in nodes], [True, True, False, False])
        self.assertIsNone(nodes[2]["time"])


class BarcodeTest(TestCase):
    def test_count_validation(self):
        with self.assertRaises(ValueError):
            barcode_mod.validate_count(1400)
        with self.assertRaises(ValueError):
            barcode_mod.validate_count(1700)  # 非步进
        with self.assertRaises(ValueError):
            barcode_mod.validate_count(10500)
        self.assertEqual(barcode_mod.validate_count(6000), 6000)
        self.assertEqual(barcode_mod.validate_count(1500), 1500)
        self.assertEqual(barcode_mod.validate_count(10000), 10000)

    def test_generate_unique_and_seven_digits(self):
        event, _ = _config_event()
        rows = barcode_mod.generate_barcodes(event, 1500)
        self.assertEqual(len(rows), 1500)
        codes = [r.code for r in rows]
        self.assertEqual(len(set(codes)), 1500)
        self.assertTrue(all(len(c) == 7 and c.isdigit() for c in codes))

    def test_generate_incremental_no_duplicate(self):
        event, _ = _config_event()
        barcode_mod.generate_barcodes(event, 1500)
        second = barcode_mod.generate_barcodes(event, 1500)
        self.assertEqual(len(second), 1500)
        total = PostcardBarcode.objects.filter(event=event).count()
        self.assertEqual(total, 3000)

    def test_generate_total_cap(self):
        event, _ = _config_event()
        barcode_mod.generate_barcodes(event, 9000)
        with self.assertRaises(ValueError):
            barcode_mod.generate_barcodes(event, 1500)  # 9000+1500 > 10000

    def test_pdf_layout_pages(self):
        event, _ = _config_event()
        _barcodes(event, [f"{i:07d}" for i in range(66)])  # 65/页 → 2 页
        resp = barcode_mod.export_pdf(event, title="测试活动")
        self.assertEqual(resp["Content-Type"], "application/pdf")
        body = b"".join(resp.streaming_content) if hasattr(resp, "streaming_content") else resp.content
        self.assertTrue(body.startswith(b"%PDF"))
        pages = body.count(b"/Type /Page") - body.count(b"/Type /Pages")
        self.assertEqual(pages, 2)

    def test_pdf_empty_event(self):
        event, _ = _config_event()
        resp = barcode_mod.export_pdf(event)
        body = b"".join(resp.streaming_content) if hasattr(resp, "streaming_content") else resp.content
        self.assertTrue(body.startswith(b"%PDF"))


class PortalTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_no_event(self):
        resp = self.client.get("/events/postcard/portal/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["phase"], "not_started")
        self.assertFalse(resp.json()["can_register"])

    def test_draft_hidden_from_public(self):
        _config_event(publish=False)
        resp = self.client.get("/events/postcard/portal/")
        data = resp.json()
        self.assertEqual(data["phase"], "not_started")
        self.assertIsNone(data["event"])

    def test_registering_exposes_metadata(self):
        _config_event()
        resp = self.client.get("/events/postcard/portal/")
        data = resp.json()
        self.assertEqual(data["phase"], "registering")
        self.assertTrue(data["can_register"])
        self.assertEqual(data["grades"], ["高一", "高二", "高三"])
        self.assertEqual(len(data["schools"]), 2)
        self.assertEqual(data["classes"], list(range(1, 9)))
        # 寄达区 = 写死的 16 区固定清单（顺序即展示顺序）
        self.assertEqual(data["regions"][:3], ["浦东新区", "宝山区", "崇明区"])
        self.assertEqual(len(data["regions"]), 16)

    def test_non_registering_hides_metadata(self):
        now = timezone.now()
        _config_event(start=now - timedelta(days=3), ship=now - timedelta(days=1),
                      end=now + timedelta(days=1))
        resp = self.client.get("/events/postcard/portal/")
        data = resp.json()
        self.assertEqual(data["phase"], "shipped")
        self.assertFalse(data["can_register"])
        self.assertEqual(data["grades"], [])  # 不泄露表单元数据
        self.assertEqual(data["schools"], [])

    def test_admin_sees_metadata_in_any_phase(self):
        admin = _admin()
        now = timezone.now()
        _config_event(start=now - timedelta(days=3), ship=now - timedelta(days=1),
                      end=now + timedelta(days=1))
        client = APIClient()
        client.force_authenticate(user=admin)
        data = client.get("/events/postcard/portal/").json()
        self.assertTrue(data["is_admin"])
        self.assertEqual(data["grades"], ["高一", "高二", "高三"])


class RegisterFlowTest(TestCase):
    """登记全流程：成功、门禁、校验、照片安全、零残留。"""

    def setUp(self):
        cache.clear()
        self.event, self.config = _config_event()
        _barcodes(self.event, ["1000001", "1000002", "1000003"])
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A

    def _post(self, data, files=None):
        # DRF 测试客户端：文件必须并进 data 字典（files= 关键字会被静默丢弃）
        return self.client.post(
            "/events/postcard/register/", {**data, **(files or {})}, format="multipart",
        )

    def test_success(self):
        resp = self._post(_register_payload(["1000001"]), _register_files(1))
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertRegex(body["reg_code"], r"^\d{6}$")
        reg = PostcardRegistration.objects.get(event=self.event)
        self.assertEqual(reg.sender_name, "张三")
        self.assertEqual(reg.device_id, DEVICE_A)
        self.assertEqual(
            reg.fingerprint_hash, hashlib.sha256(b"aabbccdd00112233").hexdigest(),
        )
        self.assertEqual(reg.items.count(), 1)
        self.assertEqual(reg.items.first().barcode.code, "1000001")
        self.assertEqual(PostcardPhoto.objects.count(), 2)  # 正反两面
        photo = PostcardPhoto.objects.first()
        # 私有存储：物理路径在 PRIVATE_MEDIA_ROOT 下（绝不在公开 MEDIA_ROOT）
        from django.conf import settings

        self.assertTrue(photo.file.path.startswith(str(settings.PRIVATE_MEDIA_ROOT)))

    def test_multiple_items_one_submission(self):
        resp = self._post(_register_payload(["1000001", "1000002", "1000003"]), _register_files(3))
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(PostcardItem.objects.count(), 3)
        self.assertEqual(PostcardPhoto.objects.count(), 6)

    def test_phase_gate(self):
        now = timezone.now()
        self.event.start_at = now - timedelta(days=3)
        self.event.save(update_fields=["start_at"])
        self.config.ship_at = now - timedelta(days=1)
        self.config.save(update_fields=["ship_at"])
        resp = self._post(_register_payload(["1000001"]), _register_files(1))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("登记期", resp.json()["detail"])

    def test_unknown_barcode(self):
        resp = self._post(_register_payload(["9999999"]), _register_files(1))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不存在", resp.json()["detail"])

    def test_claimed_barcode_rejected(self):
        self._post(_register_payload(["1000001"]), _register_files(1))
        resp = self._post(_register_payload(["1000001"]), _register_files(1))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("已被登记", resp.json()["detail"])

    def test_duplicate_barcodes_in_submission(self):
        resp = self._post(_register_payload(["1000001", "1000001"]), _register_files(2))
        self.assertEqual(resp.status_code, 400)

    def test_too_many_items(self):
        codes = ["1000001", "1000002", "1000003", "1000001", "1000002", "1000003"]
        resp = self._post(_register_payload(codes[:6]), _register_files(6))
        self.assertEqual(resp.status_code, 400)

    def test_grade_not_allowed(self):
        self.config.allowed_grades = ["g2"]
        self.config.save(update_fields=["allowed_grades"])
        resp = self._post(_register_payload(["1000001"]), _register_files(1))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("年级", resp.json()["detail"])

    def test_school_not_in_list(self):
        resp = self._post(_register_payload(["1000001"], dest_school="野鸡中学"), _register_files(1))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("寄达校", resp.json()["detail"])

    def test_region_not_in_fixed_list(self):
        resp = self._post(_register_payload(["1000001"], dest_region="野鸡区"), _register_files(1))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("寄达区", resp.json()["detail"])

    def test_region_school_pair_must_match(self):
        # 校名合法但配错区（友爱中学在浦东新区，不是黄浦区）→ 拒
        resp = self._post(
            _register_payload(["1000001"], dest_region="黄浦区", dest_school="友爱中学"),
            _register_files(1),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("寄达校", resp.json()["detail"])

    def test_missing_photo_zero_residue(self):
        resp = self._post(_register_payload(["1000001"]), files={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("照片", resp.json()["detail"])
        # 零残留：无登记、无条目、无照片
        self.assertEqual(PostcardRegistration.objects.count(), 0)
        self.assertEqual(PostcardItem.objects.count(), 0)
        self.assertEqual(PostcardPhoto.objects.count(), 0)

    def test_fake_image_rejected(self):
        files = {
            "photo_0_front": SimpleUploadedFile("evil.jpg", b"not an image at all", "image/jpeg"),
            "photo_0_back": SimpleUploadedFile("back.jpg", _jpeg_bytes(), "image/jpeg"),
        }
        resp = self._post(_register_payload(["1000001"]), files)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PostcardPhoto.objects.count(), 0)

    def test_exif_stripped(self):
        files = {
            "photo_0_front": SimpleUploadedFile("front.jpg", _jpeg_bytes(with_exif=True), "image/jpeg"),
            "photo_0_back": SimpleUploadedFile("back.jpg", _jpeg_bytes(with_exif=True), "image/jpeg"),
        }
        resp = self._post(_register_payload(["1000001"]), files)
        self.assertEqual(resp.status_code, 201, resp.content)
        for photo in PostcardPhoto.objects.all():
            img = Image.open(photo.file.open("rb"))
            self.assertEqual(len(img.getexif()), 0, "EXIF 必须被重编码剥离")

    def test_oversize_rejected(self):
        big = _jpeg_bytes(size=(300, 300)) + b"\x00" * (5 * 1024 * 1024)
        files = {
            "photo_0_front": SimpleUploadedFile("big.jpg", big, "image/jpeg"),
            "photo_0_back": SimpleUploadedFile("back.jpg", _jpeg_bytes(), "image/jpeg"),
        }
        resp = self._post(_register_payload(["1000001"]), files)
        self.assertEqual(resp.status_code, 400)


class MyRecordsAndIDORTest(TestCase):
    """归属三轨 + 登记码能力凭证 + IDOR（非本人一律 404）。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A
        resp = self.client.post(
            "/events/postcard/register/",
            {**_register_payload(["1000001", "1000002"]), **_register_files(2)},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.reg_code = resp.json()["reg_code"]
        self.reg = PostcardRegistration.objects.get(event=self.event)

    def test_my_list_by_device(self):
        resp = self.client.get("/events/postcard/my/")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["reg_code"], self.reg_code)
        self.assertEqual(len(results[0]["items"]), 2)

    def test_my_list_by_fingerprint(self):
        client = APIClient()  # 无 device cookie，靠指纹
        resp = client.get("/events/postcard/my/?fingerprint=aabbccdd00112233")
        self.assertEqual(len(resp.json()["results"]), 1)

    def test_other_device_sees_nothing(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.get("/events/postcard/my/")
        self.assertEqual(resp.json()["results"], [])

    def test_detail_requires_ownership(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.get(f"/events/postcard/my/{self.reg_code}/")
        self.assertEqual(resp.status_code, 404)  # 不泄露存在性

    def test_edit_own_record(self):
        resp = self.client.patch(
            f"/events/postcard/my/{self.reg_code}/",
            {"sender_name": "李四", "class_no": 5},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.sender_name, "李四")
        self.assertEqual(self.reg.class_no, 5)

    def test_edit_by_other_rejected(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.patch(f"/events/postcard/my/{self.reg_code}/", {"sender_name": "黑客"})
        self.assertEqual(resp.status_code, 404)
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.sender_name, "张三")

    def test_cancel_own_record(self):
        resp = self.client.post(f"/events/postcard/my/{self.reg_code}/")
        self.assertEqual(resp.status_code, 200)
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.status, "cancelled")
        self.assertTrue(self.reg.items.exclude(status="cancelled").count() == 0)

    def test_photo_access_control(self):
        photo = PostcardPhoto.objects.first()
        url = f"/events/postcard/photo/{photo.pk}/"
        # 匿名无凭证 → 403
        self.assertEqual(APIClient().get(url).status_code, 403)
        # 他人设备 + 正确登记码 → 403
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        self.assertEqual(client.get(f"{url}?reg_code={self.reg_code}").status_code, 403)
        # 本人设备 + 登记码 → 200
        resp = self.client.get(f"{url}?reg_code={self.reg_code}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/jpeg")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        # 复核权限 → 200（无需登记码）
        reviewer = _reviewer()
        rc = APIClient()
        rc.force_authenticate(user=reviewer)
        self.assertEqual(rc.get(url).status_code, 200)


class SuggestionTest(TestCase):
    def setUp(self):
        cache.clear()
        _config_event()

    def test_create(self):
        resp = self.client.post(
            "/events/postcard/suggestions/",
            {"content": "希望能寄到更多学校", "contact": ""},
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_throttled(self):
        for _ in range(5):
            self.assertEqual(
                self.client.post("/events/postcard/suggestions/", {"content": "x"}).status_code, 201,
            )
        self.assertEqual(
            self.client.post("/events/postcard/suggestions/", {"content": "x"}).status_code, 429,
        )


class AnnouncementPdfTest(TestCase):
    def test_404_when_none(self):
        resp = self.client.get("/events/postcard/announcement-pdf/")
        self.assertEqual(resp.status_code, 404)

    def test_sandbox_headers(self):
        event, config = _config_event()
        config.announcement_pdf.save("announcement.pdf", io.BytesIO(b"%PDF-1.4 fake"), save=True)
        resp = self.client.get("/events/postcard/announcement-pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Security-Policy"], "sandbox")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")


class AdminConfigTest(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = _admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _put(self, **overrides):
        now = timezone.now()
        data = {
            "title": "2026 明信片互寄",
            "summary": "给一年后的自己",
            "body": "<p>公告内容</p>",
            "start_at": (now + timedelta(days=1)).isoformat(),
            "end_at": (now + timedelta(days=30)).isoformat(),
            "ship_at": (now + timedelta(days=10)).isoformat(),
            "distribute_at": (now + timedelta(days=20)).isoformat(),
            "allowed_grades": ["g1", "g2"],
            "destination_schools": [{"region": "浦东新区", "name": "友爱中学"}],
        }
        data.update(overrides)
        return self.client.put("/events/postcard/admin/config/", data, format="json")

    def test_anonymous_forbidden(self):
        self.assertEqual(APIClient().get("/events/postcard/admin/config/").status_code, 403)

    def test_plain_user_forbidden(self):
        user = User.objects.create_user(username="plain", password="test-pass-123")
        client = APIClient()
        client.force_authenticate(user=user)
        self.assertEqual(client.get("/events/postcard/admin/config/").status_code, 403)

    def test_first_put_creates_draft_event(self):
        resp = self._put()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["configured"])
        event = Event.objects.get(module_key="postcard")
        self.assertEqual(event.status, Event.STATUS_DRAFT)
        self.assertEqual(event.visibility, Event.VISIBILITY_PUBLIC)
        config = event.postcard_config
        self.assertEqual(config.allowed_grades, ["g1", "g2"])
        self.assertIn("<p>公告内容</p>", config.announcement_body)

    def test_body_sanitized(self):
        resp = self._put(body="<p>ok</p><script>alert(1)</script><img src=x onerror=alert(2)>")
        self.assertEqual(resp.status_code, 200)
        body = Event.objects.get(module_key="postcard").postcard_config.announcement_body
        self.assertNotIn("<script>", body)
        self.assertNotIn("onerror", body)

    def test_publish(self):
        self._put()
        resp = self.client.post("/events/postcard/admin/publish/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], "scheduled")  # start 在未来

    def test_shell_locked_after_active(self):
        now = timezone.now()
        start = (now - timedelta(hours=1)).isoformat()
        end = (now + timedelta(days=7)).isoformat()
        resp = self._put(start_at=start, end_at=end, ship_at=None, distribute_at=None)
        self.assertEqual(resp.status_code, 200)
        self.client.post("/events/postcard/admin/publish/")
        # 改标题 → 拒（壳字段锁定）
        resp = self._put(title="新标题", start_at=start, end_at=end, ship_at=None, distribute_at=None)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("锁定", resp.json()["detail"])
        # 壳字段不变、只改模块字段 → 行
        resp = self._put(
            start_at=start, end_at=end, ship_at=None, distribute_at=None,
            destination_schools=[{"region": "黄浦区", "name": "光明中学"}],
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_pdf_upload_magic_check(self):
        now = timezone.now()
        resp = self.client.put(
            "/events/postcard/admin/config/",
            {
                "title": "t",
                "start_at": now.isoformat(),
                "end_at": (now + timedelta(days=1)).isoformat(),
                "announcement_pdf": SimpleUploadedFile("evil.pdf", b"not a pdf", "application/pdf"),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_time_ordering_validated(self):
        now = timezone.now()
        resp = self._put(
            start_at=(now + timedelta(days=5)).isoformat(),
            end_at=(now + timedelta(days=1)).isoformat(),
        )
        self.assertEqual(resp.status_code, 400)


class AdminRecordsAndOpsTest(TestCase):
    """记录管理 / 导出 / 统计 / 签收三件套 / 审计。"""

    def setUp(self):
        cache.clear()
        self.admin = _admin()
        self.reviewer = _reviewer()
        self.event, self.config = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A
        resp = self.client.post(
            "/events/postcard/register/",
            {**_register_payload(["1000001", "1000002"]), **_register_files(2)},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.reg_code = resp.json()["reg_code"]
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.reviewer_client = APIClient()
        self.reviewer_client.force_authenticate(user=self.reviewer)

    def test_records_list_and_search(self):
        resp = self.admin_client.get("/events/postcard/admin/records/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)  # 两条目
        # 按条码搜
        resp = self.admin_client.get("/events/postcard/admin/records/?q=1000002")
        self.assertEqual(resp.json()["count"], 1)
        # 按姓名搜
        resp = self.admin_client.get("/events/postcard/admin/records/?q=张三")
        self.assertEqual(resp.json()["count"], 2)
        # 按登记码搜
        resp = self.admin_client.get(f"/events/postcard/admin/records/?q={self.reg_code}")
        self.assertEqual(resp.json()["count"], 2)

    def test_records_permission(self):
        self.assertEqual(APIClient().get("/events/postcard/admin/records/").status_code, 403)
        # reviewer 无 manage 权限 → 403
        self.assertEqual(self.reviewer_client.get("/events/postcard/admin/records/").status_code, 403)

    def test_registration_edit_and_cancel(self):
        resp = self.admin_client.patch(
            f"/events/postcard/admin/registrations/{self.reg_code}/",
            {"sender_name": "王五", "status": "cancelled"},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        reg = PostcardRegistration.objects.get(reg_code=self.reg_code)
        self.assertEqual(reg.sender_name, "王五")
        self.assertEqual(reg.status, "cancelled")
        self.assertEqual(reg.items.exclude(status="cancelled").count(), 0)

    def test_registration_delete(self):
        resp = self.admin_client.delete(f"/events/postcard/admin/registrations/{self.reg_code}/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(PostcardRegistration.objects.count(), 0)
        self.assertEqual(PostcardPhoto.objects.count(), 0)

    def test_export_xlsx_formula_injection(self):
        # 寄出人名字以 = 开头 → 导出单元格必须前置 '
        reg = PostcardRegistration.objects.get(reg_code=self.reg_code)
        reg.sender_name = "=cmd|' /C calc'!A0"
        reg.save(update_fields=["sender_name"])
        resp = self.admin_client.get("/events/postcard/admin/export/?fmt=xlsx")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        ws = wb.active
        names = [row[1].value for row in ws.iter_rows(min_row=2)]
        self.assertTrue(all(str(n).startswith("'=") for n in names), names)

    def test_export_pdf(self):
        resp = self.admin_client.get("/events/postcard/admin/export/?fmt=pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_stats(self):
        resp = self.admin_client.get("/events/postcard/admin/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["items"]["total"], 2)
        self.assertEqual(data["registrations"]["total"], 1)
        self.assertEqual(data["destination_schools"], 1)
        self.assertEqual(data["by_school"][0]["school"], "友爱中学")

    def test_lookup_and_confirm(self):
        # 未登记条码
        resp = self.reviewer_client.get("/events/postcard/admin/lookup/?barcode=9999999")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "明信片未登记，请先登记！")
        # 命中
        resp = self.reviewer_client.get("/events/postcard/admin/lookup/?barcode=1000001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["registration"]["reg_code"], self.reg_code)
        # 签收确认
        resp = self.reviewer_client.post("/events/postcard/admin/confirm/", {"barcode": "1000001"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.json()["already_reported"])
        item = PostcardItem.objects.get(barcode__code="1000001")
        self.assertEqual(item.status, "reported")
        # 幂等
        resp = self.reviewer_client.post("/events/postcard/admin/confirm/", {"barcode": "1000001"})
        self.assertTrue(resp.json()["already_reported"])
        # 全部签收 → 登记单联动已报寄
        self.reviewer_client.post("/events/postcard/admin/confirm/", {"barcode": "1000002"})
        reg = PostcardRegistration.objects.get(reg_code=self.reg_code)
        self.assertEqual(reg.status, "reported")

    def test_confirm_requires_review_perm(self):
        self.assertEqual(
            APIClient().post("/events/postcard/admin/confirm/", {"barcode": "1000001"}).status_code, 403,
        )

    def test_unreport(self):
        self.reviewer_client.post("/events/postcard/admin/confirm/", {"barcode": "1000001"})
        resp = self.reviewer_client.post("/events/postcard/admin/unreport/", {"barcode": "1000001"})
        self.assertEqual(resp.status_code, 200)
        item = PostcardItem.objects.get(barcode__code="1000001")
        self.assertEqual(item.status, "registered")

    def test_audit_log_written(self):
        self.reviewer_client.post("/events/postcard/admin/confirm/", {"barcode": "1000001"})
        self.admin_client.get("/events/postcard/admin/export/?fmt=xlsx")
        actions = set(
            PostcardAuditLog.objects.values_list("action", flat=True)
        )
        self.assertIn("confirm_receipt", actions)
        self.assertIn("export", actions)
        # 审计可读
        resp = self.admin_client.get("/events/postcard/admin/audit/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 2)

    def test_suggestions_admin_list(self):
        from .models import PostcardSuggestion

        PostcardSuggestion.objects.create(event=self.event, content="建议")
        resp = self.admin_client.get("/events/postcard/admin/suggestions/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)
