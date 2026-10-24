"""TOTP 纯函数测试：RFC 6238 官方向量、重放保护、恢复代码、密钥加密。"""
from django.test import SimpleTestCase

from . import totp


class TotpVectorTests(SimpleTestCase):
    # RFC 6238 附录 B 的 SHA-1 种子（ASCII "12345678901234567890" 的 base32）
    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    def test_rfc6238_vectors(self):
        cases = {
            59: "287082",
            1111111109: "081804",
            1111111111: "050471",
            1234567890: "005924",
            2000000000: "279037",
        }
        for ts, expected in cases.items():
            self.assertEqual(totp.code_at(self.SECRET, ts), expected, f"ts={ts}")

    def test_verify_accepts_current_step(self):
        secret = totp.generate_secret()
        now = 1_700_000_000
        code = totp.code_at(secret, now)
        self.assertEqual(totp.verify(secret, code, at=now), totp.step_at(now))

    def test_verify_rejects_replay(self):
        secret = totp.generate_secret()
        now = 1_700_000_000
        code = totp.code_at(secret, now)
        step = totp.verify(secret, code, at=now)
        self.assertIsNone(totp.verify(secret, code, last_step=step, at=now))

    def test_verify_accepts_previous_step_without_replay_record(self):
        secret = totp.generate_secret()
        now = 1_700_000_000
        previous = totp.code_at(secret, now - totp.PERIOD)
        self.assertIsNotNone(totp.verify(secret, previous, last_step=0, at=now))

    def test_verify_rejects_garbage(self):
        secret = totp.generate_secret()
        for code in ("", "12345", "1234567", "abcdef", "000000"):
            self.assertIsNone(totp.verify(secret, code, at=1_700_000_000), code)

    def test_provisioning_uri(self):
        secret = totp.generate_secret()
        uri = totp.provisioning_uri(secret, "张三-1")
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn(f"secret={secret}", uri)
        self.assertIn("period=30", uri)
        self.assertIn("digits=6", uri)


class TotpStorageTests(SimpleTestCase):
    def test_secret_encrypt_roundtrip(self):
        secret = totp.generate_secret()
        token = totp.encrypt_secret(secret)
        self.assertNotIn(secret, token)
        self.assertEqual(totp.decrypt_secret(token), secret)

    def test_recovery_codes_shape_and_hash(self):
        codes = totp.generate_recovery_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual({len(c) for c in codes}, {10})
        joined = "".join(codes)
        # 去掉易混淆字符
        for ch in "O0I1":
            self.assertNotIn(ch, joined)
        self.assertEqual(totp.hash_recovery_code(" abc "), totp.hash_recovery_code("ABC"))
