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

    def test_generate_replace_clears_unused(self):
        """覆盖生成：清空未占用的旧条码，只留新的一批。"""
        event, _ = _config_event()
        barcode_mod.generate_barcodes(event, 1500)
        second = barcode_mod.generate_barcodes(event, 1500, replace=True)
        db_codes = set(
            PostcardBarcode.objects.filter(event=event).values_list("code", flat=True)
        )
        self.assertEqual(len(db_codes), 1500)
        self.assertEqual(db_codes, {r.code for r in second})

    def test_generate_replace_refuses_when_bound(self):
        """覆盖生成：有条码已被登记占用时拒绝，绝不删已发出去的条码。"""
        event, _ = _config_event()
        barcode_mod.generate_barcodes(event, 1500)
        code = PostcardBarcode.objects.filter(event=event).values_list("code", flat=True).first()
        _make_registration(event, [code])
        with self.assertRaises(ValueError):
            barcode_mod.generate_barcodes(event, 1500, replace=True)
        self.assertEqual(PostcardBarcode.objects.filter(event=event).count(), 1500)

    def test_admin_barcode_replace_endpoint(self):
        event, _ = _config_event()
        barcode_mod.generate_barcodes(event, 1500)
        client = APIClient()
        client.force_authenticate(user=_admin())
        resp = client.post(
            "/events/postcard/admin/barcodes/", {"count": 2000, "replace": True}, format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["total"], 2000)
        self.assertTrue(resp.json()["replaced"])
        self.assertEqual(
            PostcardAuditLog.objects.filter(event=event, action="barcode_regenerate").count(), 1,
        )

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
        # 年级下拉 = 键值对（value 即登记接口的 grade 键；PR3 前端表单直接消费）
        self.assertEqual(
            data["grades"],
            [{"value": "g1", "label": "高一"}, {"value": "g2", "label": "高二"},
             {"value": "g3", "label": "高三"}],
        )
        self.assertEqual(len(data["schools"]), 2)
        self.assertEqual(data["classes"], list(range(1, 9)))
        # 寄达区 = 写死的 16 区固定清单（顺序即展示顺序）
        self.assertEqual(data["regions"][:3], ["浦东新区", "宝山区", "崇明区"])
        self.assertEqual(len(data["regions"]), 16)

    def test_announcement_body_served(self):
        """公告正文随 portal 下发（PR3 用户侧渲染；入库前已 bleach 净化）。"""
        event, config = _config_event()
        config.announcement_body = "<p>活动公告内容</p>"
        config.save(update_fields=["announcement_body"])
        data = self.client.get("/events/postcard/portal/").json()
        self.assertEqual(data["announcement_body"], "<p>活动公告内容</p>")

    def test_non_registering_keeps_metadata_for_editing(self):
        """登记截止后仍下发年级/区/校：历史记录的「修改」表单需要下拉项（2026-11-08 修复）。"""
        now = timezone.now()
        _config_event(start=now - timedelta(days=3), ship=now - timedelta(days=1),
                      end=now + timedelta(days=1))
        resp = self.client.get("/events/postcard/portal/")
        data = resp.json()
        self.assertEqual(data["phase"], "shipped")
        self.assertFalse(data["can_register"])
        self.assertTrue(data["grades"])
        self.assertEqual(len(data["regions"]), 16)
        self.assertTrue(data["schools"])

    def test_not_started_still_hides_metadata(self):
        """未开始时对普通用户仍不泄露表单元数据。"""
        now = timezone.now()
        _config_event(start=now + timedelta(days=2), end=now + timedelta(days=9))
        data = self.client.get("/events/postcard/portal/").json()
        self.assertEqual(data["phase"], "not_started")
        self.assertEqual(data["grades"], [])
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
        self.assertEqual(
            data["grades"],
            [{"value": "g1", "label": "高一"}, {"value": "g2", "label": "高二"},
             {"value": "g3", "label": "高三"}],
        )


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

    def test_reencode_compresses_to_audit_size(self):
        """默认压缩（2026-11-08 用户定调）：大图重编码到最长边 1280。"""
        from .photos import MAX_EDGE, validate_and_reencode

        content = validate_and_reencode(
            SimpleUploadedFile("big.jpg", _jpeg_bytes(size=(3000, 2000)), "image/jpeg"),
        )
        img = Image.open(content)
        self.assertLessEqual(max(img.size), MAX_EDGE)
        self.assertEqual(max(img.size), 1280)  # 3000x2000 → 1280x853
        # 小图不放大：64x64 保持原尺寸
        small = validate_and_reencode(
            SimpleUploadedFile("small.jpg", _jpeg_bytes(size=(64, 64)), "image/jpeg"),
        )
        self.assertEqual(max(Image.open(small).size), 64)


class MyRecordsAndIDORTest(TestCase):
    """归属三轨（列表归集）+ 登记码即能力凭证（详情/改/取消，任何设备凭码可用）。"""

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
        # PR3：条目摘要带照片 id/side——用户侧历史记录据此构造鉴权照片 URL
        first = results[0]["items"][0]
        self.assertEqual(
            sorted(p["side"] for p in first["photos"]), ["back", "front"],
        )
        self.assertTrue(all(p["id"] for p in first["photos"]))

    def test_my_list_fingerprint_alone_is_not_enough(self):
        """2026-11-08 收紧：指纹可被复制，单轨不再能列出他人登记。"""
        client = APIClient()  # 无 device / 未登录
        resp = client.get("/events/postcard/my/?fingerprint=aabbccdd00112233")
        self.assertEqual(resp.json()["results"], [])

    def test_my_list_fingerprint_with_device(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_A
        resp = client.get("/events/postcard/my/?fingerprint=aabbccdd00112233")
        self.assertEqual(len(resp.json()["results"]), 1)

    def test_other_device_sees_nothing(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.get("/events/postcard/my/")
        self.assertEqual(resp.json()["results"], [])

    def test_detail_by_code_any_device(self):
        """2026-11-08 起：登记码即凭证——换设备凭码可查（用户要求）。"""
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.get(f"/events/postcard/my/{self.reg_code}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["reg_code"], self.reg_code)

    def test_detail_unknown_code_404(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.get("/events/postcard/my/000000/")
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

    def test_edit_by_code_any_device(self):
        """换设备凭码可改（登记码即凭证）。"""
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.patch(f"/events/postcard/my/{self.reg_code}/", {"sender_name": "李四"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.sender_name, "李四")

    def test_edit_unknown_code_404(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.patch("/events/postcard/my/000000/", {"sender_name": "黑客"})
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
        # 他人设备 + 正确登记码 → 200（登记码即凭证）
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        self.assertEqual(client.get(f"{url}?reg_code={self.reg_code}").status_code, 200)
        # 他人设备 + 错误登记码 → 403
        self.assertEqual(client.get(f"{url}?reg_code=000000").status_code, 403)
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


class LookupTest(TestCase):
    """用户侧查询入口：登记码 → 完整摘要；姓名 → 掩码摘要（需完整码才能改）。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001"])
        _add_sample(self.event)
        self.reg = _make_registration(self.event, ["1000001"])
        self.client = APIClient()
        # 预置设备 Cookie：否则首个请求计入 IP 轨、之后计入设备轨（限流计数
        # 会多放行 1 次），测试对不上；真实浏览器同理（首访响应才种 Cookie）。
        self.client.cookies["club_device"] = DEVICE_A

    def test_lookup_by_code_full_summary(self):
        resp = self.client.post("/events/postcard/lookup/", {"q": self.reg.reg_code})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["kind"], "code")
        self.assertEqual(len(data["results"]), 1)
        row = data["results"][0]
        self.assertEqual(row["reg_code"], self.reg.reg_code)
        self.assertEqual(row["sender_name"], "李四")
        self.assertEqual(len(row["items"]), 1)
        self.assertTrue(row["items"][0]["photos"])  # 完整码可见照片 id

    def test_lookup_by_code_from_any_device(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.post("/events/postcard/lookup/", {"q": self.reg.reg_code})
        self.assertEqual(len(resp.json()["results"]), 1)

    def test_lookup_by_name_masked(self):
        resp = self.client.post("/events/postcard/lookup/", {"q": "李四"})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["kind"], "name")
        self.assertEqual(len(data["results"]), 1)
        row = data["results"][0]
        # 姓名查询只给掩码，不能据此改他人记录
        self.assertEqual(row["reg_code"], f"{self.reg.reg_code[:2]}****")
        self.assertEqual(row["items"][0]["photos"], [])

    def test_lookup_by_name_exact_match_only(self):
        resp = self.client.post("/events/postcard/lookup/", {"q": "王"})
        self.assertEqual(resp.status_code, 400)  # 至少 2 字
        resp = self.client.post("/events/postcard/lookup/", {"q": "王五"})
        self.assertEqual(resp.json()["results"], [])

    def test_lookup_unknown_code_empty(self):
        resp = self.client.post("/events/postcard/lookup/", {"q": "000000"})
        self.assertEqual(resp.json(), {"kind": "code", "results": []})

    def test_lookup_empty_rejected(self):
        resp = self.client.post("/events/postcard/lookup/", {"q": ""})
        self.assertEqual(resp.status_code, 400)

    def test_lookup_throttled(self):
        for _ in range(20):
            self.assertEqual(
                self.client.post("/events/postcard/lookup/", {"q": "李四"}).status_code, 200,
            )
        self.assertEqual(
            self.client.post("/events/postcard/lookup/", {"q": "李四"}).status_code, 429,
        )


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

    def test_multipart_json_schools(self):
        """前端 FormData 只能把寄达校清单序列化成 JSON 串提交（含公告 PDF 时必走 multipart）。"""
        now = timezone.now()
        resp = self.client.put(
            "/events/postcard/admin/config/",
            {
                "title": "t",
                "start_at": now.isoformat(),
                "end_at": (now + timedelta(days=30)).isoformat(),
                "allowed_grades": ["g1"],
                "destination_schools": json.dumps(
                    [{"region": "黄浦区", "name": "光明中学"}], ensure_ascii=False,
                ),
                "announcement_pdf": SimpleUploadedFile(
                    "a.pdf", b"%PDF-1.4\n%fake\n", "application/pdf",
                ),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            resp.json()["destination_schools"],
            [{"region": "黄浦区", "name": "光明中学"}],
        )
        self.assertTrue(resp.json()["has_announcement_pdf"])


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

    def test_code_authorizes_any_device(self):
        """登记码即凭证：换设备凭码可申请复核。"""
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.post(f"/events/postcard/my/{self.reg.reg_code}/review-request/")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_unknown_code_404(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.post("/events/postcard/my/000000/review-request/")
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

    def test_code_authorizes_any_device(self):
        """登记码即凭证：换设备凭码可触发关页清理（仅删自己失败照片）。"""
        lifecycle_mod.settle_item_photos(
            self.reg.items.first(), PostcardPhoto.REVIEW_AI_FAILED,
        )
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.post(f"/events/postcard/my/{self.reg.reg_code}/purge-photos/")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_unknown_code_404(self):
        client = APIClient()
        client.cookies["club_device"] = DEVICE_B
        resp = client.post("/events/postcard/my/000000/purge-photos/")
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


class SharedCodeAndGrantTest(TestCase):
    """同一发件人共用登记码（B：姓名 + 年级 + 班级）+ 服务端发码门禁。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002", "1000003"])
        _add_sample(self.event)
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A

    def _register(self, codes, **overrides):
        return self.client.post(
            "/events/postcard/register/",
            {**_register_payload(codes, **overrides), **_register_files(len(codes))},
            format="multipart",
        )

    def test_same_sender_reuses_code(self):
        r1 = self._register(["1000001"])
        r2 = self._register(["1000002"])
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(r2.status_code, 201, r2.content)
        self.assertEqual(r1.json()["reg_code"], r2.json()["reg_code"])
        regs = PostcardRegistration.objects.filter(event=self.event)
        self.assertEqual(regs.count(), 2)
        self.assertEqual(regs.values("reg_code").distinct().count(), 1)
        # 每次提交仍是独立一行（各自寄达校与审核状态）
        self.assertEqual(regs.values("sender_name").distinct().count(), 1)

    def test_different_class_gets_new_code(self):
        r1 = self._register(["1000001"])
        r2 = self._register(["1000002"], class_no=4)
        self.assertNotEqual(r1.json()["reg_code"], r2.json()["reg_code"])

    def test_cross_track_reuse_is_audited(self):
        self._register(["1000001"])
        other = APIClient()
        other.cookies["club_device"] = DEVICE_B
        resp = other.post(
            "/events/postcard/register/",
            {**_register_payload(["1000002"], fingerprint="ffffffffffffffff"), **_register_files(1)},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(
            PostcardAuditLog.objects.filter(action="code_reused_cross_track").exists()
        )
        self.assertEqual(
            PostcardRegistration.objects.filter(event=self.event).values("reg_code").distinct().count(), 1
        )

    def test_pending_does_not_reveal_code(self):
        with mock.patch(
            "events.modules.postcard.ai.queue_registration_review",
            return_value=PostcardPhoto.REVIEW_PENDING,
        ):
            resp = self._register(["1000001"])
        body = resp.json()
        self.assertIsNone(body["reg_code"])
        self.assertFalse(body["code_granted"])
        self.assertTrue(body["access_token"])
        self.assertIn("****", body["registration"]["reg_code"])

        listing = self.client.get("/events/postcard/my/").json()["results"][0]
        self.assertFalse(listing["code_granted"])
        self.assertIn("****", listing["reg_code"])

        # 转为人工复核 → 凭证拿真码
        reg = PostcardRegistration.objects.get(event=self.event)
        PostcardPhoto.objects.filter(item__registration=reg).update(
            review_state=PostcardPhoto.REVIEW_MANUAL_PENDING
        )
        status = self.client.get(f"/events/postcard/my/token/{body['access_token']}/").json()
        self.assertTrue(status["code_granted"])
        self.assertEqual(status["reg_code"], reg.reg_code)

    def test_token_review_request_grants_code(self):
        with mock.patch(
            "events.modules.postcard.ai.queue_registration_review",
            return_value=PostcardPhoto.REVIEW_PENDING,
        ):
            token = self._register(["1000001"]).json()["access_token"]
        reg = PostcardRegistration.objects.get(event=self.event)
        PostcardPhoto.objects.filter(item__registration=reg).update(
            review_state=PostcardPhoto.REVIEW_AI_FAILED,
            ai_verdict={"matched": False, "mismatched_items": ["寄达校"]},
        )
        resp = self.client.post(f"/events/postcard/my/token/{token}/review-request/")
        self.assertEqual(resp.status_code, 200, resp.content)
        status = self.client.get(f"/events/postcard/my/token/{token}/").json()
        self.assertTrue(status["code_granted"])
        self.assertEqual(status["reg_code"], reg.reg_code)

    def test_unknown_token_404(self):
        self.assertEqual(
            self.client.get("/events/postcard/my/token/deadbeef/").status_code, 404,
        )

    def test_cancel_one_then_all(self):
        self._register(["1000001"])
        self._register(["1000002"])
        regs = list(PostcardRegistration.objects.filter(event=self.event).order_by("pk"))
        code = regs[0].reg_code
        resp = self.client.post(
            f"/events/postcard/my/{code}/?id={regs[1].pk}", {"scope": "one"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        regs[1].refresh_from_db()
        regs[0].refresh_from_db()
        self.assertEqual(regs[1].status, PostcardRegistration.STATUS_CANCELLED)
        self.assertEqual(regs[0].status, PostcardRegistration.STATUS_REGISTERED)

        resp = self.client.post(f"/events/postcard/my/{code}/", {"scope": "all"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["cancelled_count"], 1)  # 已取消的那份跳过
        self.assertFalse(
            PostcardRegistration.objects.filter(event=self.event)
            .exclude(status=PostcardRegistration.STATUS_CANCELLED).exists()
        )

    def test_patch_validates_school_pair(self):
        self._register(["1000001"])
        reg = PostcardRegistration.objects.get(event=self.event)
        url = f"/events/postcard/my/{reg.reg_code}/?id={reg.pk}"
        bad = self.client.patch(url, {"dest_school": "不存在的中学"}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.patch(
            url, {"dest_region": "黄浦区", "dest_school": "光明中学"}, format="json",
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        reg.refresh_from_db()
        self.assertEqual(reg.dest_school, "光明中学")

    def test_sync_status_ignores_cancelled(self):
        self._register(["1000001", "1000002"])
        reg = PostcardRegistration.objects.get(event=self.event)
        items = list(reg.items.order_by("pk"))
        items[0].status = PostcardItem.STATUS_REPORTED
        items[0].save(update_fields=["status"])
        items[1].status = PostcardItem.STATUS_CANCELLED
        items[1].save(update_fields=["status"])
        reg.sync_status_from_items()
        reg.refresh_from_db()
        self.assertEqual(reg.status, PostcardRegistration.STATUS_REPORTED)

    def test_admin_by_id_and_ambiguous_code(self):
        self._register(["1000001"])
        self._register(["1000002"])
        admin = _admin()
        client = APIClient()
        client.force_authenticate(user=admin)
        regs = list(PostcardRegistration.objects.filter(event=self.event).order_by("pk"))
        code = regs[0].reg_code

        ambiguous = client.patch(
            f"/events/postcard/admin/registrations/{code}/", {"sender_name": "王五"}, format="json",
        )
        self.assertEqual(ambiguous.status_code, 400)

        ok = client.patch(
            f"/events/postcard/admin/registrations/by-id/{regs[0].pk}/",
            {"sender_name": "王五"}, format="json",
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        regs[0].refresh_from_db()
        self.assertEqual(regs[0].sender_name, "王五")

        deleted = client.delete(f"/events/postcard/admin/registrations/by-id/{regs[1].pk}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(PostcardRegistration.objects.filter(pk=regs[1].pk).exists())


class PortalMetadataAfterRegisteringTest(TestCase):
    """登记截止后，用户改自己的记录仍需要年级/区/校下拉（2026-11-08 修复）。"""

    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.event, _ = _config_event(
            start=now - timedelta(days=5), end=now + timedelta(days=5),
            ship=now - timedelta(days=1),
        )
        _add_sample(self.event)

    def test_metadata_present_after_registration_closed(self):
        data = APIClient().get("/events/postcard/portal/").json()
        self.assertEqual(data["phase"], "shipped")
        self.assertFalse(data["can_register"])
        self.assertTrue(data["grades"])
        self.assertEqual(len(data["regions"]), 16)
        self.assertTrue(data["schools"])


class AITestEndpointTest(TestCase):
    """管理端「测试连接」：成功/失败文案、不泄露 key、审计留痕。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _ai_config()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_success(self):
        body = json.dumps({"choices": [{"message": {"content": "正常"}}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self.client.post("/events/postcard/admin/ai/test/")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["reply"], "正常")
        self.assertGreaterEqual(data["latency_ms"], 0)
        self.assertNotIn("sk-test-key", json.dumps(data))
        self.assertTrue(
            PostcardAuditLog.objects.filter(action="ai_test", detail__ok=True).exists()
        )

    def test_http_error_is_friendly_and_hides_key(self):
        import urllib.error

        err = urllib.error.HTTPError(
            "https://ai.example.com/v1/chat/completions", 401, "Unauthorized", {}, None,
        )
        with mock.patch("events.modules.postcard.ai.urllib.request.urlopen", side_effect=err):
            resp = self.client.post("/events/postcard/admin/ai/test/")
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("API Key", data["error"])
        self.assertNotIn("sk-test-key", json.dumps(data))

    def test_incomplete_config(self):
        PostcardAIConfig.objects.update(enabled=False)
        data = self.client.post("/events/postcard/admin/ai/test/").json()
        self.assertFalse(data["ok"])
        self.assertIn("配置不完整", data["error"])

    def test_requires_manage_permission(self):
        client = APIClient()
        client.force_authenticate(user=_reviewer())
        self.assertEqual(client.post("/events/postcard/admin/ai/test/").status_code, 403)


class AISampleExplainTest(TestCase):
    """「让 AI 读样例」：成功返回理解正文、失败给人话、审计留痕、权限门禁。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _ai_config()
        self.sample = PostcardAISample(event=self.event, caption="姓名写在左上角")
        self.sample.image.save("sample.jpg", ContentFile(_jpeg_bytes()), save=True)
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())
        self.url = f"/events/postcard/admin/ai/samples/{self.sample.pk}/explain/"

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_success_returns_understanding(self):
        body = json.dumps({"choices": [{"message": {"content": "要求：姓名正楷写在左上角。"}}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("姓名正楷", resp.json()["text"])
        self.assertNotIn("sk-test-key", json.dumps(resp.json()))
        self.assertTrue(
            PostcardAuditLog.objects.filter(action="ai_sample_explain", detail__ok=True).exists()
        )

    def test_network_error_is_friendly_and_hides_key(self):
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            side_effect=TimeoutError("boom"),
        ):
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 502)
        self.assertIn("网络不可达或超时", resp.json()["detail"])
        self.assertNotIn("sk-test-key", json.dumps(resp.json()))

    def test_incomplete_config(self):
        PostcardAIConfig.objects.update(enabled=False)
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("AI 未启用", resp.json()["detail"])

    def test_requires_manage_permission(self):
        client = APIClient()
        client.force_authenticate(user=_reviewer())
        self.assertEqual(client.post(self.url).status_code, 403)

    def test_unknown_sample_404(self):
        resp = self.client.post("/events/postcard/admin/ai/samples/999999/explain/")
        self.assertEqual(resp.status_code, 404)


class PostcardReviewNotifyTest(TestCase):
    """新审核申请 → 站内信（权限驱动，与内容送审同规则；同码未读聚合）。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        self.reviewer = _reviewer()
        self.admin = _admin()

    def test_manual_transfer_notifies_reviewers(self):
        reg = _make_registration(self.event, ["1000001"])
        from events.modules.postcard import ai as ai_mod

        state = ai_mod.queue_registration_review(reg)  # 未配置 AI → 同步转人工
        self.assertEqual(state, PostcardPhoto.REVIEW_MANUAL_PENDING)
        rows = list(self.reviewer.notifications.all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].category, "review")
        self.assertEqual(rows[0].event, "postcard_submitted")
        self.assertEqual(rows[0].payload["type"], "postcard")
        self.assertEqual(rows[0].payload["url"], "/reviews?kind=postcard")
        # 管理权限也收（can_review_postcard 包含 manage 授权）
        self.assertEqual(len(list(self.admin.notifications.all())), 1)

    def test_same_code_aggregates_unread(self):
        reg1 = _make_registration(self.event, ["1000001"])
        reg2 = PostcardRegistration.objects.create(
            event=self.event, reg_code=reg1.reg_code, sender_name="李四", grade="g2", class_no=5,
            dest_region="浦东新区", dest_school="友爱中学",
        )
        barcode = PostcardBarcode.objects.get(event=self.event, code="1000002")
        item = PostcardItem.objects.create(registration=reg2, barcode=barcode)
        photo = PostcardPhoto(item=item, side="front")
        photo.file.save("x-front.jpg", ContentFile(_jpeg_bytes()), save=True)

        from events.modules.postcard import ai as ai_mod

        ai_mod.queue_registration_review(reg1)
        ai_mod.queue_registration_review(reg2)
        rows = list(self.reviewer.notifications.all())
        self.assertEqual(len(rows), 1)  # 同码未读合并
        self.assertEqual(rows[0].payload.get("count"), 2)


class ReviewQueueForDeskTest(TestCase):
    """审核台消费的队列：带通用 id，可按状态分桌。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        self.reg = _make_registration(self.event, ["1000001", "1000002"])
        items = list(self.reg.items.order_by("pk"))
        lifecycle_mod.settle_item_photos(items[0], PostcardPhoto.REVIEW_MANUAL_PENDING)
        lifecycle_mod.settle_item_photos(items[1], PostcardPhoto.REVIEW_AI_FAILED)
        self.client = APIClient()
        self.client.force_authenticate(user=_reviewer())

    def test_queue_has_id(self):
        rows = self.client.get("/events/postcard/admin/review/").json()["results"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["id"] == r["item_id"] for r in rows))

    def test_state_filter(self):
        manual = self.client.get(
            "/events/postcard/admin/review/?state=manual_pending"
        ).json()["results"]
        failed = self.client.get(
            "/events/postcard/admin/review/?state=ai_failed"
        ).json()["results"]
        self.assertEqual(len(manual), 1)
        self.assertEqual(len(failed), 1)
        self.assertNotEqual(manual[0]["id"], failed[0]["id"])


class MultiSeasonTest(TestCase):
    """多届活动：归档 + 开启新一届（2026-11-08 用户需求）。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event(grades=["g1"], schools=[{"region": "黄浦区", "name": "光明中学"}])
        self.admin = _admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_new_season_archives_old_and_creates_draft(self):
        resp = self.client.post("/events/postcard/admin/new-season/")
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(data["previous_event"], self.event.pk)

        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.STATUS_ARCHIVED)

        new_event = Event.objects.get(pk=data["event_id"])
        self.assertEqual(new_event.module_key, "postcard")
        self.assertEqual(new_event.status, Event.STATUS_DRAFT)
        new_config = new_event.postcard_config
        self.assertEqual(new_config.allowed_grades, ["g1"])
        self.assertEqual(new_config.destination_schools, [{"region": "黄浦区", "name": "光明中学"}])
        self.assertTrue(
            PostcardAuditLog.objects.filter(action="new_season", event=new_event).exists()
        )

        # 之后 PUT 配置作用在新一届上，不再被旧活动的壳锁挡住
        now = timezone.now()
        resp = self.client.put("/events/postcard/admin/config/", {
            "title": "2027 明信片互寄",
            "start_at": (now + timedelta(days=1)).isoformat(),
            "end_at": (now + timedelta(days=30)).isoformat(),
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["event"]["title"], "2027 明信片互寄")

    def test_new_season_inherits_ai_config_but_clears_api_key(self):
        PostcardAIConfig.objects.create(
            base_url="https://api.example.com/v1",
            api_key="sk-old",
            model="demo-model",
            extra_headers={"x-api-key": "header"},
            timeout_seconds=42,
            ip_blacklist=["喜羊羊"],
            prompt_prefix="沿用去年的提示词",
            enabled=True,
        )

        resp = self.client.post("/events/postcard/admin/new-season/")
        self.assertEqual(resp.status_code, 201, resp.content)

        cfg = PostcardAIConfig.load()
        self.assertEqual(cfg.api_key, "")  # 唯一不继承的字段
        self.assertEqual(cfg.base_url, "https://api.example.com/v1")
        self.assertEqual(cfg.model, "demo-model")
        self.assertEqual(cfg.extra_headers, {"x-api-key": "header"})
        self.assertEqual(cfg.timeout_seconds, 42)
        self.assertEqual(cfg.ip_blacklist, ["喜羊羊"])
        self.assertEqual(cfg.prompt_prefix, "沿用去年的提示词")
        self.assertTrue(cfg.enabled)

        log = PostcardAuditLog.objects.get(action="new_season", event_id=resp.json()["event_id"])
        self.assertTrue(log.detail["api_key_cleared"])

    def test_archive_endpoint(self):
        resp = self.client.post("/events/postcard/admin/archive/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.STATUS_ARCHIVED)
        self.assertEqual(self.client.post("/events/postcard/admin/archive/").status_code, 400)

    def test_archived_event_displayed_as_ended_to_public(self):
        self.event.status = Event.STATUS_ARCHIVED
        self.event.save(update_fields=["status"])
        data = APIClient().get("/events/postcard/portal/").json()
        self.assertEqual(data["phase"], "ended")
        self.assertFalse(data["can_register"])


class ConfigPartialAndPdfTest(TestCase):
    """配置 PUT：可选字段缺省 = 不变；公告 PDF 替换不产生孤儿文件。"""

    def setUp(self):
        cache.clear()
        self.event, self.config = _config_event()
        self.config.ship_at = timezone.now() + timedelta(days=3)
        self.config.announcement_body = "<p>原公告</p>"
        self.config.save()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())
        now = timezone.now()
        self.base = {
            "title": self.event.title,
            "start_at": self.event.start_at.isoformat(),
            "end_at": self.event.end_at.isoformat(),
        }

    def test_omitted_optional_fields_are_kept(self):
        before_ship = self.config.ship_at
        resp = self.client.put("/events/postcard/admin/config/", self.base, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.config.refresh_from_db()
        self.assertEqual(self.config.announcement_body, "<p>原公告</p>")
        self.assertEqual(self.config.ship_at, before_ship)
        self.assertEqual(self.config.destination_schools[0]["name"], "友爱中学")

    def test_pdf_replacement_leaves_single_file(self):
        def upload(name, payload):
            return self.client.put(
                "/events/postcard/admin/config/",
                {**self.base, "announcement_pdf": SimpleUploadedFile(
                    name, b"%PDF-1.4\n" + payload, "application/pdf",
                )},
                format="multipart",
            )

        self.assertEqual(upload("a.pdf", b"one").status_code, 200)
        self.config.refresh_from_db()
        first = self.config.announcement_pdf.name
        storage = self.config.announcement_pdf.storage
        self.assertTrue(storage.exists(first))

        self.assertEqual(upload("b.pdf", b"two").status_code, 200)
        self.config.refresh_from_db()
        second = self.config.announcement_pdf.name
        self.assertTrue(storage.exists(second))
        # 替换前的旧文件必须被删掉（否则每次换公告都留一个孤儿）
        self.assertFalse(storage.exists(first))


class RegisterBarcodeRaceTest(TestCase):
    """并发抢占同一条码：唯一约束兜底 → 友好 400，而不是 500。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001"])
        _add_sample(self.event)
        self.client = APIClient()
        self.client.cookies["club_device"] = DEVICE_A

    def test_integrity_error_returns_400(self):
        from django.db import IntegrityError

        with mock.patch(
            "events.modules.postcard.views.PostcardItem.objects.create",
            side_effect=IntegrityError("duplicate barcode"),
        ):
            resp = self.client.post(
                "/events/postcard/register/",
                {**_register_payload(["1000001"]), **_register_files(1)},
                format="multipart",
            )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("占用", resp.json()["detail"])
        self.assertFalse(PostcardRegistration.objects.filter(event=self.event).exists())


class RegisterThrottleRateTest(TestCase):
    """IP 轨必须比单设备宽松（学校 NAT 共用出口）。"""

    def test_ip_rate_is_looser_than_device(self):
        from .throttles import RegisterDeviceThrottle, RegisterIPThrottle

        self.assertEqual(RegisterIPThrottle.RATE, "60/hour")
        self.assertEqual(RegisterDeviceThrottle.RATE, "10/hour")


class StatsExcludeCancelledTest(TestCase):
    """统计口径：已取消不计入总数与分布（2026-11-08 定）。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _barcodes(self.event, ["1000001", "1000002"])
        self.reg = _make_registration(self.event, ["1000001", "1000002"])
        items = list(self.reg.items.order_by("pk"))
        items[1].status = PostcardItem.STATUS_CANCELLED
        items[1].save(update_fields=["status"])
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    def test_cancelled_excluded_from_totals(self):
        data = self.client.get("/events/postcard/admin/stats/").json()
        self.assertEqual(data["items"]["total"], 1)
        self.assertEqual(data["items"]["cancelled"], 1)
        self.assertEqual(data["by_school"][0]["total"], 1)
        self.assertEqual(sum(g["total"] for g in data["by_grade"]), 1)
        self.assertEqual(sum(d["total"] for d in data["by_day"]), 1)


class AIRetryAttemptsTest(TestCase):
    """「5 次重试机会」= 1 次初始 + 5 次重试（共 6 次尝试）。"""

    def test_six_attempts_then_manual(self):
        cache.clear()
        event, _ = _config_event()
        _barcodes(event, ["1000001"])
        _ai_config()
        reg = _make_registration(event, ["1000001"])
        calls = {"n": 0}

        def always_fail(*args, **kwargs):
            calls["n"] += 1
            raise ai_mod.AIReviewError("down")

        with mock.patch.object(ai_mod, "call_once", side_effect=always_fail), \
                mock.patch.object(ai_mod, "_sleep", lambda *_a, **_k: None):
            stats = ai_mod.review_registration(reg)
        self.assertEqual(calls["n"], 6)
        self.assertEqual(stats["manual"], 1)


class SchoolsImportTest(TestCase):
    """导入海报：AI 未配置门禁、区名/编号归一、图片安全管线、权限与审计。

    识别结果**不落库**（管理员核对后点保存才生效），所以这里只断言响应与审计。
    """

    def setUp(self):
        cache.clear()
        self.event, self.config = _config_event()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _post(self, filename="poster.jpg", payload=None):
        image = SimpleUploadedFile(
            filename, payload if payload is not None else _jpeg_bytes(size=(120, 120)), "image/jpeg",
        )
        return self.client.post(
            "/events/postcard/admin/schools/import/", {"image": image}, format="multipart",
        )

    @staticmethod
    def _body(content: str) -> bytes:
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def test_requires_ai_config(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json(), {"code": "ai_not_configured", "detail": "请先配置AI"})
        # 未配置时不该走到模型调用
        self.assertFalse(PostcardAuditLog.objects.filter(action="schools_import").exists())

    def test_disabled_ai_is_not_configured(self):
        _ai_config(enabled=False)
        resp = self._post()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["detail"], "请先配置AI")

    def test_parses_and_normalizes_schools(self):
        _ai_config()
        content = json.dumps({"schools": [
            {"region": "上海市浦东新区", "no": "浦东新区12", "name": "1. 某某中学"},
            {"region": "浦东", "no": 3, "name": "浦东新区3 临港一中"},
            {"region": "火星", "no": 1, "name": "外星中学"},
            {"region": "黄浦区", "no": 2, "name": "光明中学"},
            {"region": "黄浦区", "no": 2, "name": "光明中学"},
        ]}, ensure_ascii=False)
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(self._body(content)),
        ):
            resp = self._post()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["schools"], [
            {"region": "浦东新区", "no": 12, "name": "某某中学"},
            {"region": "浦东新区", "no": 3, "name": "临港一中"},
            {"region": "黄浦区", "no": 2, "name": "光明中学"},
        ])
        self.assertEqual(len(data["skipped"]), 1)
        self.assertEqual(data["missing_no"], 0)
        self.assertTrue(
            PostcardAuditLog.objects.filter(action="schools_import", detail__recognized=3).exists()
        )
        # 不落库：清单原样不动
        self.config.refresh_from_db()
        self.assertEqual(len(self.config.destination_schools), 2)

    def test_keeps_school_without_number_but_flags_it(self):
        _ai_config()
        content = json.dumps({"schools": [
            {"region": "浦东新区", "name": "无编号中学"},
        ]}, ensure_ascii=False)
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(self._body(content)),
        ):
            data = self._post().json()
        self.assertEqual(data["schools"], [{"region": "浦东新区", "no": None, "name": "无编号中学"}])
        self.assertEqual(data["missing_no"], 1)

    def test_retries_once_then_reports_friendly_error(self):
        import urllib.error

        _ai_config()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            side_effect=urllib.error.URLError("boom"),
        ) as patched:
            resp = self._post()
        self.assertEqual(resp.status_code, 502, resp.content)
        self.assertIn("识别失败", resp.json()["detail"])
        self.assertNotIn("boom", resp.content.decode())
        self.assertEqual(patched.call_count, 2)

    def test_rejects_non_image_payload(self):
        _ai_config()
        with mock.patch("events.modules.postcard.ai.urllib.request.urlopen") as patched:
            resp = self._post(payload=b"<html>not an image</html>")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("JPEG", resp.json()["detail"])
        patched.assert_not_called()

    def test_requires_manage_permission(self):
        client = APIClient()
        client.force_authenticate(user=_reviewer())
        image = SimpleUploadedFile("poster.jpg", _jpeg_bytes(), "image/jpeg")
        resp = client.post(
            "/events/postcard/admin/schools/import/", {"image": image}, format="multipart",
        )
        self.assertEqual(resp.status_code, 403)


class SchoolNumberConfigTest(TestCase):
    """配置写入接受区内编号：字符串数字归一为 int，非法值拒绝。"""

    def setUp(self):
        cache.clear()
        self.event, self.config = _config_event()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())
        self.base = {
            "title": self.event.title,
            "start_at": self.event.start_at.isoformat(),
            "end_at": self.event.end_at.isoformat(),
        }

    def _put(self, schools):
        return self.client.put(
            "/events/postcard/admin/config/",
            {**self.base, "destination_schools": json.dumps(schools, ensure_ascii=False)},
            format="multipart",
        )

    def test_number_is_stored_as_int(self):
        resp = self._put([{"region": "浦东新区", "name": "友爱中学", "no": "7"}])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.config.refresh_from_db()
        self.assertEqual(self.config.destination_schools[0]["no"], 7)

    def test_invalid_number_is_rejected(self):
        resp = self._put([{"region": "浦东新区", "name": "友爱中学", "no": "七"}])
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("编号须为数字", resp.content.decode())

    def test_legacy_school_without_number_still_saves(self):
        resp = self._put([{"region": "浦东新区", "name": "友爱中学"}])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.config.refresh_from_db()
        self.assertNotIn("no", self.config.destination_schools[0])
class AITestTempParamsTest(TestCase):
    """模拟环境用：「测试连接」可带临时参数，但绝不落库、绝不回显 key。

    模拟环境（前端 `?sim=1`）的 AI 配置只存浏览器内存，要验证「这套参数能不能通」
    就得让后端用一次性的配置去测——用户的红线是模拟不得改动正式配置。
    """

    def setUp(self):
        cache.clear()
        _config_event()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_temp_params_are_used_but_not_saved(self):
        _ai_config(base_url="https://saved.example.com/v1", model="saved-model")
        body = json.dumps({"choices": [{"message": {"content": "正常"}}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ) as urlopen:
            resp = self.client.post(
                "/events/postcard/admin/ai/test/",
                {"base_url": "https://temp.example.com/v1", "model": "temp-model",
                 "api_key": "sk-temp-key"},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(resp.json()["model"], "temp-model")
        # 真的打到了临时 base_url，且用的临时 key
        req = urlopen.call_args[0][0]
        self.assertTrue(req.full_url.startswith("https://temp.example.com/v1"))
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-temp-key")
        # 正式配置一个字都没动
        cfg = PostcardAIConfig.load()
        self.assertEqual(cfg.base_url, "https://saved.example.com/v1")
        self.assertEqual(cfg.model, "saved-model")
        self.assertEqual(cfg.api_key, "sk-test-key")
        self.assertNotIn("sk-temp-key", json.dumps(resp.json()))

    def test_temp_params_work_without_saved_config(self):
        PostcardAIConfig.objects.all().delete()
        body = json.dumps({"choices": [{"message": {"content": "正常"}}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self.client.post(
                "/events/postcard/admin/ai/test/",
                {"base_url": "https://temp.example.com/v1", "model": "temp-model"},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(PostcardAIConfig.objects.count(), 0)

    def test_incomplete_temp_params_are_friendly(self):
        PostcardAIConfig.objects.all().delete()
        data = self.client.post(
            "/events/postcard/admin/ai/test/", {"base_url": ""}, format="json",
        ).json()
        self.assertFalse(data["ok"])
        self.assertIn("配置不完整", data["error"])

    def test_requires_manage_permission(self):
        client = APIClient()
        client.force_authenticate(user=_reviewer())
        resp = client.post(
            "/events/postcard/admin/ai/test/",
            {"base_url": "https://temp.example.com/v1", "model": "m"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class AdminAIModelsTest(TestCase):
    """「模型选择」下拉的数据源：只把服务商 `/models` 的结果交给前端。

    红线：不在后端/前端内置任何写死模型清单；失败文案要能指导管理员自查，
    且绝不回显 api_key。
    """

    def setUp(self):
        cache.clear()
        _config_event()
        _ai_config()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self, size=None):
            return self._body if size is None else self._body[:size]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _post(self, payload=None):
        return self.client.post(
            "/events/postcard/admin/ai/models/", payload or {}, format="json",
        )

    def test_returns_provider_models_deduped_and_sanitized(self):
        body = json.dumps({"data": [
            {"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"},
            {"id": "bad id!"}, {"id": "deepseek-flash"}, {"id": 123},
        ]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self._post()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(resp.json()["models"], ["deepseek-flash", "deepseek-v4-pro"])

    def test_accepts_bare_list_of_ids(self):
        body = json.dumps(["kimi-k3", "glm-5.3"]).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self._post()
        self.assertEqual(resp.json()["models"], ["kimi-k3", "glm-5.3"])

    def test_404_is_human_readable(self):
        from urllib.error import HTTPError

        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            side_effect=HTTPError("https://x/v1/models", 404, "Not Found", {}, None),
        ):
            resp = self._post()
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("没有 /models 接口", data["error"])

    def test_non_json_is_reported(self):
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(b"<html>404</html>"),
        ):
            resp = self._post()
        self.assertFalse(resp.json()["ok"])
        self.assertIn("不是 JSON", resp.json()["error"])

    def test_temp_params_and_custom_headers_are_used_but_not_saved(self):
        body = json.dumps({"data": [{"id": "deepseek-v4.1-flash"}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ) as urlopen:
            resp = self._post({
                "base_url": "https://opencode.ai/zen/go/v1",
                "api_key": "sk-temp-key",
                "extra_headers": {"x-opencode-session": "sess-1"},
            })
        self.assertTrue(resp.json()["ok"])
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://opencode.ai/zen/go/v1/models")
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-temp-key")
        self.assertEqual(req.get_header("X-opencode-session"), "sess-1")
        cfg = PostcardAIConfig.load()
        self.assertEqual(cfg.base_url, "https://ai.example.com/v1")
        self.assertNotIn("sk-temp-key", json.dumps(resp.json()))

    def test_requires_manage_permission(self):
        client = APIClient()
        client.force_authenticate(user=_reviewer())
        resp = client.post("/events/postcard/admin/ai/models/", {}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_throttle_rate_pinned(self):
        from .throttles import AIModelsThrottle

        self.assertEqual(AIModelsThrottle.RATE, "120/hour")


class AIExplainUploadTest(TestCase):
    """模拟环境用：「让 AI 读样例」支持一次性上传（不落库、不留文件）。"""

    def setUp(self):
        cache.clear()
        _config_event()
        _ai_config()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())
        self.url = "/events/postcard/admin/ai/explain/"

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_success_returns_text_and_keeps_no_sample(self):
        before = PostcardAISample.objects.count()
        body = json.dumps({"choices": [{"message": {"content": "姓名写在左上角"}}]}).encode()
        upload = SimpleUploadedFile("s.jpg", _jpeg_bytes(), content_type="image/jpeg")
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self.client.post(self.url, {"image": upload, "caption": "样例"}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("左上角", resp.json()["text"])
        self.assertNotIn("sk-test-key", json.dumps(resp.json()))
        # 一次性：不新增样例行
        self.assertEqual(PostcardAISample.objects.count(), before)

    def test_rejects_non_image(self):
        upload = SimpleUploadedFile("evil.jpg", b"<script>alert(1)</script>", content_type="image/jpeg")
        resp = self.client.post(self.url, {"image": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("仅支持", resp.json()["detail"])

    def test_missing_image(self):
        resp = self.client.post(self.url, {}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_incomplete_ai_config(self):
        PostcardAIConfig.objects.update(enabled=False)
        upload = SimpleUploadedFile("s.jpg", _jpeg_bytes(), content_type="image/jpeg")
        resp = self.client.post(self.url, {"image": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("AI 未启用", resp.json()["detail"])

    def test_requires_manage_permission(self):
        client = APIClient()
        client.force_authenticate(user=_reviewer())
        upload = SimpleUploadedFile("s.jpg", _jpeg_bytes(), content_type="image/jpeg")
        resp = client.post(self.url, {"image": upload}, format="multipart")
        self.assertEqual(resp.status_code, 403)


class SimDryRunNoAuditTest(TestCase):
    """模拟环境（前端 `?sim=1`）：AI 相关调用带 dry_run，正式审计不留痕。

    模拟层唯一会真打的三个后端接口里，「测试连接」「导入海报」原本会写 `ai_test` /
    `schools_import` 审计——管理员在模拟里点两下就会在正式审计日志里留下假记录，
    与「模拟不与正式联动」的红线冲突。带 `dry_run` 时跳过审计，其余行为不变。
    """

    def setUp(self):
        cache.clear()
        _config_event()
        _ai_config()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_ai_test_dry_run_skips_audit(self):
        body = json.dumps({"choices": [{"message": {"content": "正常"}}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self.client.post(
                "/events/postcard/admin/ai/test/",
                {"base_url": "https://temp.example.com/v1", "model": "temp", "dry_run": True},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["ok"])
        self.assertFalse(PostcardAuditLog.objects.filter(action="ai_test").exists())

    def test_ai_test_without_dry_run_audits(self):
        body = json.dumps({"choices": [{"message": {"content": "正常"}}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            resp = self.client.post("/events/postcard/admin/ai/test/", {}, format="json")
        self.assertTrue(resp.json()["ok"])
        self.assertTrue(PostcardAuditLog.objects.filter(action="ai_test").exists())

    def test_schools_import_dry_run_skips_audit(self):
        fake = {
            "schools": [{"region": "浦东新区", "name": "建平中学", "no": 1}],
            "skipped": [],
            "missing_no": 0,
        }
        image = SimpleUploadedFile("poster.jpg", _jpeg_bytes(size=(120, 120)), "image/jpeg")
        with mock.patch("events.modules.postcard.ai.extract_schools", return_value=fake):
            resp = self.client.post(
                "/events/postcard/admin/schools/import/",
                {"image": image, "dry_run": "1"},
                format="multipart",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.json()["schools"]), 1)
        self.assertFalse(PostcardAuditLog.objects.filter(action="schools_import").exists())

    def test_schools_import_without_dry_run_audits(self):
        fake = {"schools": [], "skipped": [], "missing_no": 0}
        image = SimpleUploadedFile("poster.jpg", _jpeg_bytes(size=(120, 120)), "image/jpeg")
        with mock.patch("events.modules.postcard.ai.extract_schools", return_value=fake):
            resp = self.client.post(
                "/events/postcard/admin/schools/import/", {"image": image}, format="multipart",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(PostcardAuditLog.objects.filter(action="schools_import").exists())


class AICallThrottleTest(TestCase):
    """AI 端点限流：一次请求 = 一次真花钱的模型调用。

    「管理端不限流」的前提是低频 + 已鉴权，但这两个按钮被连点 / 脚本重放时
    账单和 worker 都吃不消（与导入海报同一个理由）。
    """

    def setUp(self):
        cache.clear()
        _config_event()
        _ai_config()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_ai_test_throttled_at_60_per_hour(self):
        body = json.dumps({"choices": [{"message": {"content": "正常"}}]}).encode()
        with mock.patch(
            "events.modules.postcard.ai.urllib.request.urlopen",
            return_value=self._Resp(body),
        ):
            for _ in range(60):
                resp = self.client.post("/events/postcard/admin/ai/test/", {}, format="json")
                self.assertEqual(resp.status_code, 200, resp.content)
            denied = self.client.post("/events/postcard/admin/ai/test/", {}, format="json")
        self.assertEqual(denied.status_code, 429)

    def test_ai_explain_throttled_at_10_per_hour(self):
        with mock.patch("events.modules.postcard.ai.explain_sample", return_value="理解"):
            for _ in range(10):
                image = SimpleUploadedFile("s.jpg", _jpeg_bytes(), "image/jpeg")
                resp = self.client.post(
                    "/events/postcard/admin/ai/explain/", {"image": image}, format="multipart",
                )
                self.assertEqual(resp.status_code, 200, resp.content)
            image = SimpleUploadedFile("s.jpg", _jpeg_bytes(), "image/jpeg")
            denied = self.client.post(
                "/events/postcard/admin/ai/explain/", {"image": image}, format="multipart",
            )
        self.assertEqual(denied.status_code, 429)


class AIReviewPreviewTest(TestCase):
    """模拟环境的「真调 AI 判定」：同一套 prompt，但不落库、不存照片、不写审计。"""

    URL = "/events/postcard/admin/ai/preview/"

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        _ai_config()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    @staticmethod
    def _payload(**over):
        data = {
            "sender_name": "张三",
            "grade_label": "高一",
            "class_no": "3",
            "dest_region": "浦东新区",
            "dest_school": "建平中学",
            "barcode": "1234567",
        }
        data.update(over)
        data["photo_front"] = SimpleUploadedFile("f.jpg", _jpeg_bytes(), "image/jpeg")
        data["photo_back"] = SimpleUploadedFile("b.jpg", _jpeg_bytes(), "image/jpeg")
        return data

    def test_preview_returns_verdict_and_writes_nothing(self):
        verdict = {
            "matched": False,
            "mismatched_items": ["寄达校写错"],
            "blacklist_hit": False,
            "blacklist_names": [],
            "comment": "请核对寄达校",
        }
        before = (
            PostcardRegistration.objects.count(),
            PostcardAuditLog.objects.count(),
        )
        with mock.patch(
            "events.modules.postcard.ai.preview_judgement", return_value=verdict,
        ) as preview:
            resp = self.client.post(self.URL, self._payload(), format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["verdict"]["mismatched_items"], ["寄达校写错"])
        # 传给 AI 的是表单 + 两面照片
        kwargs = preview.call_args.kwargs
        self.assertEqual(kwargs["form"]["sender_name"], "张三")
        self.assertEqual(len(kwargs["photos"]), 2)
        # 零写入
        self.assertEqual(
            (PostcardRegistration.objects.count(), PostcardAuditLog.objects.count()), before,
        )

    def test_ai_not_ready(self):
        PostcardAIConfig.objects.update(enabled=False)
        resp = self.client.post(self.URL, self._payload(), format="multipart")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": False, "reason": "ai_not_ready"})

    def test_ai_error_degrades_to_manual(self):
        with mock.patch(
            "events.modules.postcard.ai.preview_judgement",
            side_effect=ai_mod.AIReviewError("network: boom"),
        ):
            resp = self.client.post(self.URL, self._payload(), format="multipart")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": False, "reason": "ai_error"})

    def test_rejects_non_image(self):
        payload = self._payload()
        payload["photo_front"] = SimpleUploadedFile("x.jpg", b"<html>", "image/jpeg")
        resp = self.client.post(self.URL, payload, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("仅支持", resp.json()["detail"])

    def test_requires_manage_permission(self):
        client = APIClient()
        client.force_authenticate(user=_reviewer())
        resp = client.post(self.URL, self._payload(), format="multipart")
        self.assertEqual(resp.status_code, 403)


class AIPromptPrefixTest(TestCase):
    """前置提示词：AI 设置页多行文本，每次请求前置为 system 消息（2026-11-09）。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        self.admin = _admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_config_roundtrip_keeps_newlines(self):
        prefix = "第一行：用简体中文。\n第二行：只输出 JSON。"
        resp = self.client.put("/events/postcard/admin/ai/config/", {
            "base_url": "https://api.example.com/v1",
            "model": "demo-model",
            "prompt_prefix": prefix,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = self.client.get("/events/postcard/admin/ai/config/").json()
        self.assertEqual(data["prompt_prefix"], prefix)
        self.assertEqual(PostcardAIConfig.load().prompt_prefix, prefix)
        log = PostcardAuditLog.objects.filter(action="ai_config_update").first()
        self.assertEqual(log.detail["prompt_prefix_len"], len(prefix))

    def test_partial_put_keeps_existing_prefix(self):
        PostcardAIConfig.objects.create(prompt_prefix="保留我", base_url="https://a/v1", model="m")
        resp = self.client.put("/events/postcard/admin/ai/config/", {"enabled": True}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(PostcardAIConfig.load().prompt_prefix, "保留我")

    def test_prefix_merged_into_first_system_message(self):
        cfg = mock.Mock(prompt_prefix="总则：用简体中文")
        messages = [
            {"role": "system", "content": "细则"},
            {"role": "user", "content": "hi"},
        ]
        merged = ai_mod._with_prefix(cfg, messages)
        self.assertEqual(len(merged), 2)  # 合并而非新增 system（部分服务商只收一条）
        self.assertEqual(merged[0]["content"], "总则：用简体中文\n\n细则")
        self.assertEqual(merged[1], {"role": "user", "content": "hi"})

    def test_prefix_prepended_without_system(self):
        cfg = mock.Mock(prompt_prefix="总则")
        merged = ai_mod._with_prefix(cfg, [{"role": "user", "content": "hi"}])
        self.assertEqual(merged[0], {"role": "system", "content": "总则"})
        self.assertEqual(len(merged), 2)

    def test_blank_prefix_is_noop(self):
        cfg = mock.Mock(prompt_prefix="   ")
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(ai_mod._with_prefix(cfg, messages), messages)


class DeleteSeasonTest(TestCase):
    """Django admin 删除整届：物理文件与库内全部数据一并清除（2026-11-09）。"""

    def setUp(self):
        cache.clear()
        self.event, _ = _config_event()
        self.sample = _add_sample(self.event)
        self.sample_name = self.sample.image.name

    def test_delete_season_removes_event_and_files(self):
        storage = self.sample.image.storage
        self.assertTrue(storage.exists(self.sample_name))

        stats = lifecycle_mod.delete_season(self.event)

        self.assertEqual(stats["samples"], 1)
        self.assertFalse(Event.objects.filter(pk=self.event.pk).exists())
        self.assertFalse(PostcardConfig.objects.filter(event_id=self.event.pk).exists())
        self.assertFalse(PostcardAISample.objects.filter(pk=self.sample.pk).exists())
        self.assertFalse(storage.exists(self.sample_name))

    def test_plain_event_delete_also_purges_files(self):
        """任何删除入口（活动后台 / shell）都经 pre_delete 信号清私有文件。"""
        storage = self.sample.image.storage
        event_pk = self.event.pk
        self.event.delete()
        self.assertFalse(Event.objects.filter(pk=event_pk).exists())
        self.assertFalse(storage.exists(self.sample_name))

    def test_delete_season_leaves_other_events_alone(self):
        other = Event.objects.create(
            title="运动会", module_key="", start_at=timezone.now(), end_at=timezone.now(),
        )
        lifecycle_mod.delete_season(self.event)
        self.assertTrue(Event.objects.filter(pk=other.pk).exists())
