"""条形码签名载荷（工牌条码 → 查询入口）的服务与端点测试。

口径：12 位载荷（6 位唯一键 + 6 位十进制短签名）匿名可查、**不消耗** 24 小时额度；
防枚举由端点级 IP 频控兜底（签名空间 10^6）。8 位识别码 / 真实姓名仍走
`accounts.member_lookup` 的身份分档额度，由 `tests_member_lookup` 覆盖。
"""
from django.core.cache import cache
from django.test import TestCase

from accounts.member_codes import (
    barcode_payload,
    compose_code,
    make_barcode_signature,
    make_signature,
    split_barcode_payload,
)
from accounts.member_lookup import is_signed_payload, resolve_signed_payload
from accounts.models import MemberIdentity
from common.models import SiteSettings
from common.policy import CACHE_KEY

CODE = compose_code("260205")  # 26020542


def make_row(name="张三", cohort=2, code=CODE, phone="11451419198"):
    return MemberIdentity.objects.create(
        name=name, admit_year=2026, cohort=cohort, phone=phone, code=code,
    )


def lookup(client, query):
    return client.post(
        "/auth/member/lookup/",
        data={"q": query},
        content_type="application/json",
    )


class BarcodePayloadTest(TestCase):
    def test_payload_is_twelve_digits_and_keeps_key(self):
        payload = barcode_payload(CODE)
        self.assertEqual(len(payload), 12)
        self.assertTrue(payload.isdigit())
        self.assertEqual(payload[:6], CODE[:6])
        self.assertEqual(payload[6:], make_barcode_signature(CODE))

    def test_payload_rejects_bad_code(self):
        with self.assertRaises(Exception):
            barcode_payload("2602")

    def test_split_rejects_wrong_shapes(self):
        self.assertIsNone(split_barcode_payload(CODE))
        self.assertIsNone(split_barcode_payload("26020500235"))
        self.assertIsNone(split_barcode_payload("26020500235A"))

    def test_barcode_signature_domain_separated_from_qr(self):
        # 同一识别码的两种签名必须互不相同：短签名不能成为二维码路径的旁路。
        self.assertNotEqual(make_barcode_signature(CODE), make_signature(CODE))
        self.assertEqual(len(make_barcode_signature(CODE)), 6)

    def test_payload_is_deterministic(self):
        self.assertEqual(barcode_payload(CODE), barcode_payload(CODE))


class SignedPayloadServiceTest(TestCase):
    def test_shape_detection(self):
        self.assertTrue(is_signed_payload(barcode_payload(CODE)))
        self.assertFalse(is_signed_payload(CODE))
        self.assertFalse(is_signed_payload("张三"))

    def test_resolve_hit_and_miss(self):
        make_row()
        self.assertEqual(
            [r.code for r in resolve_signed_payload(barcode_payload(CODE))], [CODE]
        )
        self.assertEqual(resolve_signed_payload(CODE[:6] + "000000"), [])

    def test_signature_is_bound_to_full_code(self):
        make_row()
        other = compose_code("260206")
        make_row(name="李四", code=other, phone="13900001111")
        payload = CODE[:6] + make_barcode_signature(other)
        self.assertEqual(resolve_signed_payload(payload), [])


class SignedPayloadEndpointTest(TestCase):
    def setUp(self):
        cache.clear()  # 频控按 IP 计数，locmem 缓存跨用例共享。

    def test_signed_payload_hits_without_quota(self):
        make_row()
        resp = lookup(self.client, barcode_payload(CODE))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["found"])
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "张三")
        self.assertNotIn("phone", data["results"][0])
        # 匿名额度 3 次：签名路径不计数
        self.assertEqual(data["quota"]["used"], 0)
        self.assertEqual(data["quota"]["remaining"], 3)

    def test_signed_payload_does_not_consume_quota_repeatedly(self):
        """现场连扫：同一 IP 连查 5 次（> 匿名额度 3）仍然放行。"""
        make_row()
        payload = barcode_payload(CODE)
        for _ in range(5):
            data = lookup(self.client, payload).json()
            self.assertTrue(data["found"])
            self.assertEqual(data["quota"]["used"], 0)

    def test_anonymous_quota_still_applies_to_bare_code(self):
        """对照：8 位裸码还是走额度，第 4 次被拒（429）。"""
        make_row()
        for _ in range(3):
            self.assertEqual(lookup(self.client, CODE).status_code, 200)
        resp = lookup(self.client, CODE)
        self.assertEqual(resp.status_code, 429)
        self.assertIn("quota", resp.json())

    def test_bad_signature_is_not_found_and_not_counted(self):
        make_row()
        wrong = "0" * 6 if make_barcode_signature(CODE) != "0" * 6 else "1" * 6
        resp = lookup(self.client, CODE[:6] + wrong)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["found"])
        self.assertEqual(resp.json()["results"], [])
        self.assertEqual(resp.json()["quota"]["used"], 0)

    def test_unknown_key_is_not_found(self):
        make_row()
        payload = "999999" + make_barcode_signature(CODE)
        self.assertFalse(lookup(self.client, payload).json()["found"])

    def test_signed_path_throttled_by_ip(self):
        SiteSettings.objects.get_or_create(pk=1)
        SiteSettings.objects.filter(pk=1).update(member_lookup_per_ip_per_hour=2)
        cache.delete(CACHE_KEY)
        make_row()
        payload = barcode_payload(CODE)
        self.assertEqual(lookup(self.client, payload).status_code, 200)
        self.assertEqual(lookup(self.client, payload).status_code, 200)
        self.assertEqual(lookup(self.client, payload).status_code, 429)
