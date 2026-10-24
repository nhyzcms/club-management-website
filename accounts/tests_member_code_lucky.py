"""识别码末位偏好（避开 0/2/4）：跳号分配 + 整批重算命令。

规则说明见 ``accounts/member_codes.py``：校验码由前 6 位唯一决定，所以只能在分配
序号时跳号；每届 99 个序号里约 69 个可用，序号会出现空洞。
"""
import io
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from accounts.member_codes import (
    MemberCodeError,
    generate_code,
    is_preferred_code,
    next_serial,
    verify_code_checksum,
)
from accounts.member_roster import commit_import, parse_roster
from accounts.models import MemberIdentity

HEADERS = ["姓名", "班级", "校牌号", "入学年份", "入社时间", "届数", "性别", "电话号码"]


def csv_bytes(rows, headers=None):
    lines = [",".join(headers or HEADERS)]
    lines += [",".join(str(c) for c in row) for row in rows]
    return ("\n".join(lines)).encode("utf-8-sig")


def sample_row(name, admit=2026, cohort=2, phone=""):
    return [name, "1", "1", admit, "20260303", cohort, "摄影", "男", phone]


class NextSerialLuckyTest(TestCase):
    def test_is_preferred_code(self):
        self.assertTrue(is_preferred_code("26020251"))   # 校验码 51
        self.assertTrue(is_preferred_code("26020639"))   # 校验码 39
        self.assertTrue(is_preferred_code("26020736"))   # 校验码 36
        # 校验码含 2/4，或末位是 0 → 一律不合规
        for code in ("26020154", "26020930", "26020348", "26020542"):
            self.assertFalse(is_preferred_code(code))
        self.assertFalse(is_preferred_code("2602054"))     # 位数不足
        self.assertFalse(is_preferred_code("2602054a"))    # 非数字
        self.assertFalse(is_preferred_code(""))

    def test_first_serial_skips_unlucky_tail(self):
        # 2026 入学 · 第 2 届：序号 01 → 26020154（校验码 54 含 4，跳过），首个应给 02。
        self.assertEqual(generate_code(2026, 2, 1), "26020154")
        self.assertEqual(next_serial(2026, 2, set()), 2)

    def test_continues_from_max_and_skips(self):
        taken = {generate_code(2026, 2, 2)}
        # 03 → 26020348、04 → 26020445、05 → 26020542 的校验码分别含 4/4/4·2，全部跳过
        self.assertEqual(next_serial(2026, 2, taken), 6)

    def test_later_serial_also_skipped(self):
        # 03/04/05 都应跳过（校验码含 4 或 2）：占住它们后应给 06。
        taken = {generate_code(2026, 2, i) for i in (2, 3, 4)}
        self.assertEqual(next_serial(2026, 2, taken), 6)

    def test_capacity_and_exhaustion(self):
        taken = set()
        serials = []
        for _ in range(55):
            serial = next_serial(2026, 2, taken)
            code = generate_code(2026, 2, serial)
            self.assertTrue(is_preferred_code(code), code)
            self.assertTrue(verify_code_checksum(code), code)
            taken.add(code)
            serials.append(serial)
        self.assertEqual(len(set(serials)), 55)
        self.assertEqual(serials, sorted(serials))
        with self.assertRaises(MemberCodeError) as ctx:
            next_serial(2026, 2, taken)
        self.assertIn("已用尽", str(ctx.exception))

    def test_cohorts_are_independent(self):
        # 其他届的占用不影响本届；2025 入学 · 第 1 届的序号 01 → 25010190 末位 0，同样跳过。
        taken = {generate_code(2026, 2, 2)}
        self.assertEqual(generate_code(2025, 1, 1), "25010190")
        self.assertEqual(next_serial(2025, 1, taken), 2)


class ImportLuckyTest(TestCase):
    def test_commit_import_allocates_preferred_tails(self):
        rows = parse_roster(
            "a.csv",
            csv_bytes([sample_row(f"社员{i:02d}") for i in range(10)]),
        )
        commit_import(rows, file_name="a.csv")
        codes = sorted(MemberIdentity.objects.values_list("code", flat=True))
        self.assertEqual(len(codes), 10)
        for code in codes:
            self.assertTrue(is_preferred_code(code), code)
            self.assertTrue(verify_code_checksum(code), code)
        serials = [int(c[4:6]) for c in codes]
        self.assertEqual(serials, sorted(serials))
        self.assertNotIn(1, serials)  # 序号 01 → 末位 4，被跳过


class RenumberCommandTest(TestCase):
    def _row(self, name, code, user=None):
        return MemberIdentity.objects.create(
            name=name, admit_year=2026, cohort=2, code=code, user=user,
        )

    def test_dry_run_does_not_write(self):
        row = self._row("张三", "26020154")
        out = StringIO()
        call_command("renumber_member_codes", stdout=out)
        row.refresh_from_db()
        self.assertEqual(row.code, "26020154")
        self.assertIn("预览模式", out.getvalue())

    def test_apply_renumbers_and_keeps_binding(self):
        user = User.objects.create_user("u1", password="pass-1234")
        # 乙 的旧码（序号 01，末位 4）会被改成 甲 的旧码（序号 02）——两步法必须扛住。
        jia = self._row("甲", "26020251")
        yi = self._row("乙", "26020154", user=user)
        out = StringIO()
        call_command("renumber_member_codes", "--apply", stdout=out)
        jia.refresh_from_db()
        yi.refresh_from_db()
        self.assertEqual(yi.code, "26020251")   # 序号 02
        self.assertEqual(jia.code, "26020639")  # 序号 06（03/04/05 校验码含 4/2）
        self.assertEqual(yi.user_id, user.id)
        self.assertIn("已重算", out.getvalue())

    def test_apply_is_idempotent(self):
        self._row("乙", "26020154")
        call_command("renumber_member_codes", "--apply", stdout=StringIO())
        out = StringIO()
        call_command("renumber_member_codes", "--apply", stdout=out)
        self.assertIn("无需重算", out.getvalue())
        for code in MemberIdentity.objects.values_list("code", flat=True):
            self.assertTrue(is_preferred_code(code), code)
