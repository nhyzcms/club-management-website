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
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from events.models import Event

from . import ai as ai_mod
from . import barcode as barcode_mod
from . import lifecycle as lifecycle_mod
from . import state
from .models import (
    PostcardAIConfig,
    PostcardAISample,
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


def _add_sample(event, caption="样例：正面写寄达信息，反面写祝福语"):
    """建一条 AI 填写样例（PR2 登记门禁要求至少一条）。"""
    sample = PostcardAISample(event=event, caption=caption)
    sample.image.save("sample.jpg", ContentFile(_jpeg_bytes(color="white")), save=True)
    return sample


def _ai_config(*, enabled=True, base_url="https://ai.example.com/v1", model="gpt-4o-mini"):
    cfg = PostcardAIConfig.objects.create(
        base_url=base_url, api_key="sk-test-key", model=model, enabled=enabled,
    )
    return cfg


def _make_registration(event, codes, device=DEVICE_A, fingerprint="aabbccdd00112233"):
    """直接建登记单（不走 HTTP，AI 流测试用——快且不依赖门禁/限流）。"""
    reg = PostcardRegistration.objects.create(
        event=event, reg_code="654321", sender_name="李四", grade="g2", class_no=5,
        dest_region="浦东新区", dest_school="友爱中学",
        device_id=device,
        fingerprint_hash=hashlib.sha256(fingerprint.encode()).hexdigest() if fingerprint else "",
    )
    for code in codes:
        barcode = PostcardBarcode.objects.get(event=event, code=code)
        item = PostcardItem.objects.create(registration=reg, barcode=barcode)
        for side in ("front", "back"):
            photo = PostcardPhoto(item=item, side=side)
            photo.file.save(f"{item.pk}-{side}.jpg", ContentFile(_jpeg_bytes()), save=True)
    return reg


def _verdict(matched=True, mismatched=None, blacklist_hit=False, names=None):
    return {
        "matched": matched,
        "mismatched_items": mismatched or [],
        "blacklist_hit": blacklist_hit,
        "blacklist_names": names or [],
        "comment": "ok",
    }


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
        _add_sample(self.event)  # PR2：样例门禁
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
        _add_sample(self.event)  # PR2：样例门禁
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
        _add_sample(self.event)  # PR2：样例门禁
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


# ===========================================================================
# PR2：AI 审核与人工复核
# ===========================================================================


class AISampleGateTest(TestCase):
    """样例门禁：活动开始前必须配填写样例，否则登记不开放。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001"])
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A

    def test_no_sample_blocks_register(self):
        data = self.client.get("/events/postcard/portal/").json()
        self.assertFalse(data["sample_ready"])
        resp = self.client.post(
            "/events/postcard/register/",
            {**_register_payload(["1000001"]), **_register_files(1)},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("样例", resp.json()["detail"])
        self.assertEqual(PostcardRegistration.objects.count(), 0)

    def test_sample_opens_register(self):
        _add_sample(self.event)
        data = self.client.get("/events/postcard/portal/").json()
        self.assertTrue(data["sample_ready"])
        resp = self.client.post(
            "/events/postcard/register/",
            {**_register_payload(["1000001"]), **_register_files(1)},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_no_event_sample_ready_false(self):
        data = self.client.get("/events/postcard/portal/").json()
        self.assertFalse(data["sample_ready"])


class AIConfigAdminTest(TestCase):
    """AI 配置管理端：api_key 写后不可读（掩码）、默认黑名单、权限。"""

    def setUp(self):
        cache.clear()
        self.admin = _admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_get_unconfigured(self):
        data = self.client.get("/events/postcard/admin/ai/config/").json()
        self.assertFalse(data["configured"])

    def test_put_then_masked_get(self):
        resp = self.client.put("/events/postcard/admin/ai/config/", {
            "base_url": "https://ai.example.com/v1/",
            "api_key": "sk-secret-123",
            "model": "gpt-4o-mini",
            "enabled": True,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = self.client.get("/events/postcard/admin/ai/config/").json()
        self.assertTrue(data["api_key_set"])
        self.assertTrue(data["ready"])
        self.assertEqual(data["base_url"], "https://ai.example.com/v1")  # 尾斜杠归一
        self.assertNotIn("sk-secret-123", str(data))  # 明文绝不回显
        self.assertNotIn("api_key", data)  # 连字段都不出现

    def test_put_empty_api_key_keeps_old(self):
        self.client.put("/events/postcard/admin/ai/config/", {
            "api_key": "sk-first", "base_url": "https://a.example/v1", "model": "m",
        }, format="json")
        self.client.put("/events/postcard/admin/ai/config/", {
            "api_key": "", "enabled": True,
        }, format="json")
        cfg = PostcardAIConfig.load()
        self.assertEqual(cfg.api_key, "sk-first")

    def test_default_blacklist_preset(self):
        self.client.put("/events/postcard/admin/ai/config/", {
            "base_url": "https://a.example/v1", "model": "m",
        }, format="json")
        data = self.client.get("/events/postcard/admin/ai/config/").json()
        self.assertIn("进击的巨人", data["ip_blacklist"])
        self.assertTrue(len(data["ip_blacklist"]) >= 10)

    def test_plain_user_forbidden(self):
        user = User.objects.create_user(username="plain", password="test-pass-123")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.put("/events/postcard/admin/ai/config/", {"enabled": True}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_bad_base_url_rejected(self):
        resp = self.client.put("/events/postcard/admin/ai/config/", {
            "base_url": "ftp://bad.example",
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_timeout_bounds(self):
        resp = self.client.put("/events/postcard/admin/ai/config/", {
            "timeout_seconds": 300,
        }, format="json")
        self.assertEqual(resp.status_code, 400)


class AISamplesAdminTest(TestCase):
    """样例上传/列表/删除/下发：与用户照片同一道安全管线。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        self.admin = _admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _upload(self, content=None, caption="正面样例"):
        return self.client.post(
            "/events/postcard/admin/ai/samples/",
            {
                "caption": caption,
                "image": SimpleUploadedFile(
                    "s.jpg", content or _jpeg_bytes(color="white"), "image/jpeg",
                ),
            },
            format="multipart",
        )

    def test_upload_and_list(self):
        resp = self._upload()
        self.assertEqual(resp.status_code, 201, resp.content)
        data = self.client.get("/events/postcard/admin/ai/samples/").json()
        self.assertTrue(data["sample_ready"])
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["caption"], "正面样例")

    def test_fake_image_rejected(self):
        resp = self._upload(content=b"definitely not an image")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PostcardAISample.objects.count(), 0)

    def test_delete(self):
        sample = _add_sample(self.event)
        resp = self.client.delete(f"/events/postcard/admin/ai/samples/{sample.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["sample_ready"])
        self.assertEqual(PostcardAISample.objects.count(), 0)

    def test_image_requires_permission(self):
        sample = _add_sample(self.event)
        url = f"/events/postcard/admin/ai/samples/{sample.pk}/image/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/jpeg")
        anonymous = APIClient()
        self.assertEqual(anonymous.get(url).status_code, 403)
        reviewer = _reviewer()
        rc = APIClient()
        rc.force_authenticate(user=reviewer)
        self.assertEqual(rc.get(url).status_code, 200)

    def test_upload_requires_event(self):
        PostcardConfig.objects.get(event=self.event).delete()
        self.event.delete()
        resp = self._upload()
        self.assertEqual(resp.status_code, 400)


class AIReviewFlowTest(TestCase):
    """AI 审核流：通过即删 / 不匹配告知项 / 黑名单打回 / 重试转人工 / 重入安全。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        _add_sample(self.event)
        _ai_config()
        self.reg = _make_registration(self.event, ["1000001", "1000002"])

    def _review(self):
        with mock.patch.object(ai_mod, "_sleep", lambda s: None):
            return ai_mod.review_registration(self.reg)

    def test_ai_pass_purges_files(self):
        with mock.patch.object(ai_mod, "call_once", return_value=_verdict(matched=True)):
            stats = self._review()
        self.assertEqual(stats, {"passed": 2, "failed": 0, "manual": 0})
        for photo in PostcardPhoto.objects.all():
            self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_AI_PASSED)
            self.assertEqual(photo.file, "")  # 通过即删（行保留、file 置空）

    def test_ai_fail_reports_mismatch(self):
        verdict = _verdict(matched=False, mismatched=["寄达校与照片不一致", "条码未贴"])
        with mock.patch.object(ai_mod, "call_once", return_value=verdict):
            self._review()
        photo = PostcardPhoto.objects.first()
        self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_AI_FAILED)
        self.assertNotEqual(photo.file, "")  # 失败保留（用户可申请复核）
        # 用户侧能看到「哪里填错」
        client = APIClient()
        client.cookies["club_device"] = DEVICE_A
        data = client.get(f"/events/postcard/my/{self.reg.reg_code}/").json()
        mismatched = [it["mismatched"] for it in data["items"]]
        self.assertIn("寄达校与照片不一致", mismatched[0])

    def test_blacklist_hit_rejected(self):
        verdict = _verdict(matched=True, blacklist_hit=True, names=["进击的巨人"])
        with mock.patch.object(ai_mod, "call_once", return_value=verdict):
            self._review()
        photo = PostcardPhoto.objects.first()
        self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_AI_FAILED)
        self.assertIn("进击的巨人", photo.ai_verdict["blacklist_names"])

    def test_retry_then_success(self):
        verdict = _verdict(matched=True)
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise ai_mod.AIReviewError("boom")
            return verdict

        with mock.patch.object(ai_mod, "call_once", side_effect=flaky):
            stats = self._review()
        self.assertEqual(stats["passed"], 2)  # 每张前 2 次失败、第 3 次成功

    def test_retry_exhausted_to_manual(self):
        with mock.patch.object(ai_mod, "call_once", side_effect=ai_mod.AIReviewError("down")):
            stats = self._review()
        self.assertEqual(stats["manual"], 2)
        for photo in PostcardPhoto.objects.all():
            self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_MANUAL_PENDING)
            self.assertNotEqual(photo.file, "")
        # 技术失败计入连续失败 streak（告警计数）
        self.assertEqual(cache.get("postcard:ai:fail-streak"), 1)

    def test_ai_unavailable_goes_manual_synchronously(self):
        PostcardAIConfig.objects.update(enabled=False)
        state_ = ai_mod.queue_registration_review(self.reg)
        self.assertEqual(state_, PostcardPhoto.REVIEW_MANUAL_PENDING)
        photo = PostcardPhoto.objects.first()
        self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_MANUAL_PENDING)

    def test_queue_enabled_returns_pending_without_blocking(self):
        started = []
        with mock.patch.object(ai_mod.threading, "Thread") as thread_cls:
            thread_cls.return_value.start.side_effect = lambda: started.append(1)
            state_ = ai_mod.queue_registration_review(self.reg)
        self.assertEqual(state_, PostcardPhoto.REVIEW_PENDING)
        self.assertEqual(len(started), 1)  # 起线程、不阻塞

    def test_reentry_safe(self):
        with mock.patch.object(ai_mod, "call_once", return_value=_verdict(matched=True)):
            self._review()
            stats2 = self._review()  # 第二遍：全部已终态 → 跳过
        self.assertEqual(stats2, {"passed": 0, "failed": 0, "manual": 0})

    def test_worker_exception_fallback(self):
        with mock.patch.object(
            ai_mod, "review_registration", side_effect=RuntimeError("unexpected"),
        ):
            ai_mod._review_worker(self.reg.pk)
        photo = PostcardPhoto.objects.first()
        self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_MANUAL_PENDING)
        self.assertEqual(photo.ai_verdict, {"reason": "ai_worker_error"})

    def test_verdict_parser_strict(self):
        good = '{"matched": true, "blacklist_hit": false, "mismatched_items": [], "comment": "ok"}'
        self.assertTrue(ai_mod.parse_verdict(good)["matched"])
        self.assertTrue(ai_mod.parse_verdict("废话一堆 " + good + " 后缀")["matched"])
        for bad in ["no json", "{}", '{"matched": "yes"}', "[1,2]", '{"matched": true}']:
            with self.assertRaises(ai_mod.AIReviewError):
                ai_mod.parse_verdict(bad)


class AIAlertTest(TestCase):
    """连续 5 个不同用户失败 → 邮件告警；同用户去重；成功重置；冷却防轰炸。"""

    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.admin = _admin()
        self.admin.email = "admin@example.com"
        self.admin.save()

    def test_five_distinct_users_trigger_email(self):
        for i in range(4):
            ai_mod.note_review_failure(f"d:user{i}")
            self.assertEqual(len(mail.outbox), 0)
        ai_mod.note_review_failure("d:user4")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("AI 审核连续失败", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["admin@example.com"])
        # 告警后 streak 重置
        self.assertIsNone(cache.get("postcard:ai:fail-streak"))

    def test_same_user_not_double_counted(self):
        for _ in range(10):
            ai_mod.note_review_failure("d:same")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(cache.get("postcard:ai:fail-streak"), 1)

    def test_success_resets_streak(self):
        for i in range(4):
            ai_mod.note_review_failure(f"d:u{i}")
        ai_mod.note_review_success("d:any")
        ai_mod.note_review_failure("d:u9")
        self.assertEqual(cache.get("postcard:ai:fail-streak"), 1)

    def test_cooldown_prevents_spam(self):
        for i in range(5):
            ai_mod.note_review_failure(f"d:a{i}")
        self.assertEqual(len(mail.outbox), 1)
        for i in range(5):
            ai_mod.note_review_failure(f"d:b{i}")
        self.assertEqual(len(mail.outbox), 1)  # 1h 冷却内不重发

    def test_no_recipients_no_crash(self):
        self.admin.email = ""
        self.admin.save()
        for i in range(5):
            ai_mod.note_review_failure(f"d:c{i}")
        self.assertEqual(len(mail.outbox), 0)  # 无收件人：静默不炸


class ReviewDeskTest(TestCase):
    """人工复核台：队列 / 判定 / 权限 / 跨活动 IDOR / 审计。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        _add_sample(self.event)
        self.reg = _make_registration(self.event, ["1000001", "1000002"])
        # 一张待人工、一张 AI 不匹配 → 都应出现在队列
        lifecycle_mod.settle_item_photos(
            self.reg.items.get(barcode__code="1000001"), PostcardPhoto.REVIEW_MANUAL_PENDING,
        )
        lifecycle_mod.settle_item_photos(
            self.reg.items.get(barcode__code="1000002"), PostcardPhoto.REVIEW_AI_FAILED,
            verdict=_verdict(matched=False, mismatched=["字迹不清"]),
        )
        self.reviewer = _reviewer()
        self.client = APIClient()
        self.client.force_authenticate(user=self.reviewer)

    def _item(self, code):
        return PostcardItem.objects.get(registration=self.reg, barcode__code=code)

    def test_queue_lists_both_states(self):
        data = self.client.get("/events/postcard/admin/review/").json()
        self.assertEqual(len(data["results"]), 2)
        codes = {r["barcode"] for r in data["results"]}
        self.assertEqual(codes, {"1000001", "1000002"})
        entry = next(r for r in data["results"] if r["barcode"] == "1000002")
        self.assertEqual(entry["review_state"], PostcardPhoto.REVIEW_AI_FAILED)
        self.assertEqual(entry["registration"]["sender_name"], "李四")
        self.assertTrue(entry["photo_ids"])

    def test_pass_purges_files_and_audits(self):
        item = self._item("1000001")
        resp = self.client.post(
            f"/events/postcard/admin/review/{item.pk}/",
            {"decision": "pass", "note": "人工确认无误"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["review_state"], PostcardPhoto.REVIEW_MANUAL_PASSED)
        for photo in item.photos.all():
            self.assertEqual(photo.file, "")  # 通过即删
        self.assertTrue(PostcardAuditLog.objects.filter(
            action="review_decision", target=f"item#{item.pk}",
        ).exists())

    def test_fail_keeps_files_for_ttl(self):
        item = self._item("1000002")
        resp = self.client.post(
            f"/events/postcard/admin/review/{item.pk}/", {"decision": "fail"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        for photo in item.photos.all():
            self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_MANUAL_FAILED)
            self.assertNotEqual(photo.file, "")  # 24h TTL 内保留

    def test_only_reviewable_states_accepted(self):
        item = self._item("1000001")
        self.client.post(f"/events/postcard/admin/review/{item.pk}/", {"decision": "pass"}, format="json")
        resp = self.client.post(
            f"/events/postcard/admin/review/{item.pk}/", {"decision": "fail"}, format="json",
        )
        self.assertEqual(resp.status_code, 400)  # 已终态不能再判

    def test_plain_user_forbidden(self):
        user = User.objects.create_user(username="plain2", password="test-pass-123")
        client = APIClient()
        client.force_authenticate(user=user)
        item = self._item("1000001")
        resp = client.post(
            f"/events/postcard/admin/review/{item.pk}/", {"decision": "pass"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_item_from_other_event_404(self):
        # 再建一个更晚的活动 → current_event 切走；旧活动条目对新活动 404
        event2, _ = _config_event()
        item = self._item("1000001")
        resp = self.client.post(
            f"/events/postcard/admin/review/{item.pk}/", {"decision": "pass"}, format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_unknown_item_404(self):
        resp = self.client.post(
            "/events/postcard/admin/review/999999/", {"decision": "pass"}, format="json",
        )
        self.assertEqual(resp.status_code, 404)


class UserReviewRequestTest(TestCase):
    """用户申请人工复核：ai_failed → manual_pending；非本人 404。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001"])
        _add_sample(self.event)
        self.reg = _make_registration(self.event, ["1000001"])
        lifecycle_mod.settle_item_photos(
            self.reg.items.first(), PostcardPhoto.REVIEW_AI_FAILED,
            verdict=_verdict(matched=False, mismatched=["寄达区不符"]),
        )
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A

    def test_request_moves_to_manual(self):
        resp = self.client.post(f"/events/postcard/my/{self.reg.reg_code}/review-request/")
        self.assertEqual(resp.status_code, 200, resp.content)
        photo = PostcardPhoto.objects.first()
        self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_MANUAL_PENDING)
        # AI 判定保留（复核员要看 AI 判了什么）
        self.assertEqual(photo.ai_verdict["mismatched_items"], ["寄达区不符"])

    def test_no_failed_returns_400(self):
        lifecycle_mod.settle_item_photos(
            self.reg.items.first(), PostcardPhoto.REVIEW_AI_PASSED, purge_files=True,
        )
        resp = self.client.post(f"/events/postcard/my/{self.reg.reg_code}/review-request/")
        self.assertEqual(resp.status_code, 400)

    def test_not_owner_404(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.post(f"/events/postcard/my/{self.reg.reg_code}/review-request/")
        self.assertEqual(resp.status_code, 404)


class PhotoPurgeAndGCTest(TestCase):
    """sendBeacon 清理 + 周期兜底 GC + 活动结束惰性全清。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        _add_sample(self.event)
        self.reg = _make_registration(self.event, ["1000001", "1000002"])
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A

    def _photo(self, code, side="front"):
        return PostcardPhoto.objects.get(
            item__registration=self.reg, item__barcode__code=code, side=side,
        )

    def test_sendbeacon_purges_failed_only(self):
        lifecycle_mod.settle_item_photos(
            self.reg.items.get(barcode__code="1000001"), PostcardPhoto.REVIEW_AI_FAILED,
        )
        # 另一张保持 pending（还在审，不能删）
        resp = self.client.post(f"/events/postcard/my/{self.reg.reg_code}/purge-photos/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["purged"], 2)  # 失败那张的正反两面
        self.assertEqual(self._photo("1000001").file, "")
        self.assertNotEqual(self._photo("1000002").file, "")

    def test_sendbeacon_works_without_csrf_token(self):
        """sendBeacon 带不了 CSRF header——豁免 SessionAuthentication 后必须可达。"""
        lifecycle_mod.settle_item_photos(
            self.reg.items.first(), PostcardPhoto.REVIEW_MANUAL_FAILED,
        )
        strict = APIClient(enforce_csrf_checks=True)
        strict.cookies["club_device"] = DEVICE_A
        resp = strict.post(
            f"/events/postcard/my/{self.reg.reg_code}/purge-photos/",
            data=json.dumps({"fingerprint": "aabbccdd00112233"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_not_owner_404(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.post(f"/events/postcard/my/{self.reg.reg_code}/purge-photos/")
        self.assertEqual(resp.status_code, 404)

    def test_gc_ended_event_purges_all(self):
        now = timezone.now()
        self.event.start_at = now - timedelta(days=10)
        self.event.end_at = now - timedelta(days=1)
        self.event.status = Event.STATUS_ENDED
        self.event.save()
        stats = lifecycle_mod.gc_sweep()
        self.assertGreaterEqual(stats["ended_events_purged"], 4)
        for photo in PostcardPhoto.objects.all():
            self.assertEqual(photo.file, "")  # 全清（含 pending）
            self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_PENDING)  # 状态保留

    def test_gc_ttl_purges_failed_after_24h(self):
        photo = self._photo("1000001")
        # update() 绕过 auto_now，才能把 updated_at 拨回 25h 前
        PostcardPhoto.objects.filter(pk=photo.pk).update(
            review_state=PostcardPhoto.REVIEW_AI_FAILED,
            updated_at=timezone.now() - timedelta(hours=25),
        )
        stats = lifecycle_mod.gc_sweep()
        self.assertEqual(stats["ttl_purged"], 1)
        photo.refresh_from_db()
        self.assertEqual(photo.file, "")

    def test_gc_stale_pending_to_manual(self):
        photo = self._photo("1000001")
        PostcardPhoto.objects.filter(pk=photo.pk).update(
            created_at=timezone.now() - timedelta(minutes=61),
        )
        stats = lifecycle_mod.gc_sweep()
        self.assertEqual(stats["stale_pending_to_manual"], 1)
        photo.refresh_from_db()
        self.assertEqual(photo.review_state, PostcardPhoto.REVIEW_MANUAL_PENDING)

    def test_maybe_purge_ended_event_lazy(self):
        now = timezone.now()
        self.event.start_at = now - timedelta(days=10)
        self.event.end_at = now - timedelta(days=1)
        self.event.status = Event.STATUS_ENDED
        self.event.save()
        # 任意明信片请求过 _phase_guard → 惰性触发全清
        self.client.get("/events/postcard/portal/")
        for photo in PostcardPhoto.objects.all():
            self.assertEqual(photo.file, "")

    def test_command_runs(self):
        from django.core.management import call_command

        out = io.StringIO()
        call_command("postcard_photo_gc", stdout=out)
        stats = json.loads(out.getvalue())
        self.assertIn("ended_events_purged", stats)
