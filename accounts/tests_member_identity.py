"""社员身份编号（ADR-0025）：识别码 / 名册解析 / 导入对账 / 自动匹配 / 管理页。

覆盖：编码规则与签名、CSV/XLSX 解析与校验、预检对账（新增/更新/冲突）、
幂等重复导入、自动匹配（唯一 / 歧义）、后台导入页两步式、模板下载、二维码导出。
"""
import io
from zipfile import ZipFile

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.member_codes import (
    build_verify_url,
    code_prefix,
    generate_code,
    is_valid_code,
    make_signature,
    next_serial,
    verify_code_checksum,
    verify_signature,
)
from accounts.member_roster import (
    RosterParseError,
    auto_match_identities,
    commit_import,
    normalize_name,
    parse_roster,
    plan_import,
)
from accounts.models import IdentityImportBatch, MemberIdentity, Profile

HEADERS = ["姓名", "年级", "班级", "学号", "入学年份", "入社时间", "届数", "组别", "性别", "年龄", "电话号码", "识别码"]


def xlsx_bytes(rows, headers=None):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers or HEADERS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_bytes(rows, headers=None, encoding="utf-8-sig"):
    lines = [",".join(headers or HEADERS)]
    lines += [",".join(str(c) for c in row) for row in rows]
    return ("\n".join(lines)).encode(encoding)


def sample_row(name="张三", cohort=2, phone="13800008888", code="", grade="高一", admit=2026):
    return [name, grade, "1", "1", admit, "20260303", cohort, "摄影", "男", 16, phone, code]


class MemberCodesTest(TestCase):
    def test_generate_code_format_and_checksum(self):
        """识别码 = 4 位前缀 + 2 位姓名序 + 2 位校验（ISO 7064 MOD 97-10）。"""
        self.assertEqual(code_prefix(2026, 2), "2602")
        self.assertEqual(generate_code(2026, 2, 1), "26020154")  # 姓名序 01
        self.assertEqual(generate_code(2026, 2, 5), "26020542")  # 姓名序 05
        self.assertTrue(verify_code_checksum("26020542"))
        self.assertFalse(verify_code_checksum("26020541"))
        self.assertFalse(verify_code_checksum("2602054"))   # 位数不足
        self.assertFalse(verify_code_checksum("2602054a"))  # 非数字

    def test_checksum_detects_every_single_char_typo(self):
        """单字符篡改（8 位 × 9 个替代数字）全部应被校验位拒绝。"""
        code = generate_code(2026, 2, 5)
        leaks = 0
        for pos in range(8):
            for d in "0123456789":
                if d == code[pos]:
                    continue
                if verify_code_checksum(code[:pos] + d + code[pos + 1:]):
                    leaks += 1
        self.assertEqual(leaks, 0)

    def test_next_serial_continues_per_cohort(self):
        """序号接续：同届取既有最大 +1；不同届互不影响。"""
        taken = {"26020154"}
        self.assertEqual(next_serial(2025, 1, taken), 1)
        self.assertEqual(next_serial(2026, 2, taken), 2)
        self.assertEqual(next_serial(2026, 2, {"26020154", "26020251"}), 3)

    def test_serial_bounds(self):
        with self.assertRaises(Exception):
            generate_code(2026, 2, 0)
        with self.assertRaises(Exception):
            generate_code(2026, 2, 100)
        full = {generate_code(2026, 2, i) for i in range(1, 100)}
        self.assertEqual(len(full), 99)
        with self.assertRaises(Exception):
            next_serial(2026, 2, full)

    def test_signature_roundtrip_and_tamper(self):
        code = "26020542"
        sig = make_signature(code)
        self.assertTrue(verify_signature(code, sig))
        self.assertFalse(verify_signature(code, sig[:-1] + ("0" if sig[-1] != "0" else "1")))
        self.assertFalse(verify_signature("26020543", sig))
        self.assertFalse(verify_signature("", sig))

    def test_build_verify_url_contains_code_and_sig(self):
        url = build_verify_url("26020542")
        self.assertIn("#/v/26020542", url)
        self.assertIn(f"s={make_signature('26020542')}", url)

    def test_is_valid_code(self):
        self.assertTrue(is_valid_code("26020542"))
        self.assertTrue(is_valid_code("2602-0001"))
        self.assertFalse(is_valid_code(""))
        self.assertFalse(is_valid_code("短"))
        self.assertFalse(is_valid_code("a" * 17))

    def test_normalize_name_strips_whitespace_and_case(self):
        self.assertEqual(normalize_name("张 三"), "张三")
        self.assertEqual(normalize_name("张　三"), "张三")  # 全角空格
        self.assertEqual(normalize_name("Alice Chen"), "alicechen")


class RosterParseTest(TestCase):
    def test_csv_parse_basic(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row()]))
        self.assertEqual(len(rows), 1)
        v = rows[0].values
        self.assertEqual(v["姓名"], "张三")
        self.assertEqual(v["届数"], 2)  # 转成 int
        self.assertEqual(v["入学年份"], 2026)
        self.assertEqual(v["年龄"], 16)

    def test_csv_gbk_encoding(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row()], encoding="gbk"))
        self.assertEqual(rows[0].values["姓名"], "张三")

    def test_xlsx_parse_basic(self):
        rows = parse_roster("a.xlsx", xlsx_bytes([sample_row(), sample_row(name="李四", phone="13900001111")]))
        self.assertEqual([r.values["姓名"] for r in rows], ["张三", "李四"])

    def test_missing_required_column_raises(self):
        headers = [h for h in HEADERS if h != "组别"]
        with self.assertRaises(RosterParseError):
            parse_roster("a.csv", csv_bytes([sample_row()], headers=headers))

    def test_blank_rows_skipped(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row(), ["", "", "", "", "", "", "", "", "", "", "", ""]]))
        self.assertEqual(len(rows), 1)

    def test_bad_types_flagged(self):
        bad = sample_row()
        bad[6] = "abc"  # 届数
        bad[4] = "??"  # 入学年份
        rows = parse_roster("a.csv", csv_bytes([bad]))
        self.assertTrue(rows[0].errors)

    def test_given_code_column_ignored(self):
        # 识别码一律自动生成：表格该列内容忽略（含非法内容与文件内重复）。
        rows = parse_roster("a.csv", csv_bytes([
            sample_row(code="!!bad!!"),
            sample_row(name="李四", phone="13900001111", code="26020001"),
        ]))
        self.assertFalse(rows[0].errors)
        self.assertFalse(rows[1].errors)

    def test_duplicate_name_phone_in_file_flagged(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row(), sample_row()]))
        self.assertTrue(all(r.errors for r in rows))

    def test_phone_normalized_and_short_phone_warned(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row(phone="138-0000-8888"), sample_row(name="李四", phone="123")]))
        self.assertEqual(rows[0].values["电话号码"], "13800008888")
        self.assertTrue(rows[1].warnings)

    def test_empty_phone_warned(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row(phone="")]))
        self.assertTrue(rows[0].warnings)
        self.assertEqual(rows[0].values["电话号码"], "")


class ImportPlanTest(TestCase):
    def test_plan_create_with_generated_codes(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row(), sample_row(name="李四", phone="13900001111")]))
        plan = plan_import(rows)
        self.assertEqual(plan["counts"]["create"], 2)
        codes = [i["code"] for i in plan["items"]]  # 输出顺序 = 行顺序
        # 姓名 GBK 序：李四(li) < 张三(zhang) → 李四序号 01、张三序号 02
        self.assertEqual(codes, ["26020251", "26020154"])

    def test_plan_reimport_updates(self):
        commit_import(parse_roster("a.csv", csv_bytes([sample_row()])), file_name="a.csv")
        rows = parse_roster("a.csv", csv_bytes([sample_row(grade="高二")]))
        plan = plan_import(rows)
        self.assertEqual(plan["counts"]["update"], 1)
        self.assertEqual(plan["counts"]["create"], 0)
        self.assertEqual(plan["items"][0]["target"].code, "26020154")

    def test_plan_reimport_keeps_existing_code_ignoring_given(self):
        # 表内带码（哪怕同码）不参与认行：仍按 姓名+电话 命中 → 保留既有编码。
        commit_import(parse_roster("a.csv", csv_bytes([sample_row()])), file_name="a.csv")
        rows = parse_roster("a.csv", csv_bytes([sample_row(code="26020154", grade="高二")]))
        plan = plan_import(rows)
        self.assertEqual(plan["counts"]["update"], 1)
        self.assertEqual(plan["items"][0]["code"], "26020154")

    def test_plan_ignores_given_code_uses_generated(self):
        rows = parse_roster("a.csv", csv_bytes([sample_row(code="26027777")]))
        plan = plan_import(rows)
        self.assertEqual(plan["items"][0]["code"], "26020154")

    def test_given_code_not_used_for_matching(self):
        # 表带码与库内既有行相同、但姓名不同 → 不按码更新：作为新行处理并自动生成新码。
        commit_import(parse_roster("a.csv", csv_bytes([sample_row()])), file_name="a.csv")
        rows = parse_roster("a.csv", csv_bytes([sample_row(name="李四", phone="13900001111", code="26020001")]))
        plan = plan_import(rows)
        self.assertEqual(plan["counts"]["create"], 1)
        self.assertEqual(plan["counts"]["update"], 0)
        self.assertEqual(plan["items"][0]["code"], "26020251")  # 李四接续序号 02

    def test_plan_conflict_on_multiple_existing_matches(self):
        user = User.objects.create_user(username="u1", password="x")
        MemberIdentity.objects.create(name="张三", admit_year=2026, cohort=2, group="摄影", phone="13800008888", code="26020001")
        MemberIdentity.objects.create(name="张三", admit_year=2026, cohort=2, group="摄影", phone="13800008888", code="26020002")
        rows = parse_roster("a.csv", csv_bytes([sample_row()]))
        plan = plan_import(rows)
        self.assertEqual(plan["counts"]["conflict"], 1)

    def test_commit_creates_batch_and_rows(self):
        batch = commit_import(parse_roster("a.csv", csv_bytes([sample_row()])), file_name="a.csv")
        self.assertEqual(MemberIdentity.objects.count(), 1)
        self.assertEqual(IdentityImportBatch.objects.count(), 1)
        self.assertEqual(batch.summary["created"], 1)
        row = MemberIdentity.objects.get()
        self.assertEqual(row.code, "26020154")
        self.assertEqual(row.import_batch_id, batch.id)

    def test_commit_idempotent_second_run_updates_and_preserves_binding(self):
        batch1 = commit_import(parse_roster("a.csv", csv_bytes([sample_row()])), file_name="a.csv")
        row = MemberIdentity.objects.get()
        user = User.objects.create_user(username="u1", password="x")
        row.user = user
        row.bind_method = MemberIdentity.BIND_ADMIN
        row.save()
        batch2 = commit_import(parse_roster("a.csv", csv_bytes([sample_row(grade="高二")])), file_name="a.csv")
        row.refresh_from_db()
        self.assertEqual(batch2.summary["created"], 0)
        self.assertEqual(batch2.summary["updated"], 1)
        self.assertEqual(row.user_id, user.id)  # 绑定保留
        self.assertEqual(row.code, "26020154")  # 识别码保留
        self.assertEqual(row.grade, "高二")  # 动态字段更新

    def test_plan_second_batch_appends_serials(self):
        """同届追加导入：新行序号接续已有最大序号（不重排已发码）。"""
        commit_import(parse_roster("a.csv", csv_bytes([sample_row()])), file_name="a.csv")  # 张三 → 序号 01
        rows = parse_roster("a.csv", csv_bytes([sample_row(name="李四", phone="13900001111")]))
        plan = plan_import(rows)
        self.assertEqual(plan["counts"]["create"], 1)
        self.assertEqual(plan["items"][0]["code"], "26020251")  # 接续序号 02

    def test_plan_serial_exhaustion_marks_error(self):
        """单届序号上限 99：第 100 行标记错误，其余 99 行正常创建。"""
        rows = parse_roster("a.csv", csv_bytes([
            sample_row(name=f"学生{i:03d}", phone=f"1380000{i:04d}") for i in range(1, 101)
        ]))
        plan = plan_import(rows)
        self.assertEqual(plan["counts"]["create"], 99)
        self.assertEqual(plan["counts"]["error"], 1)


class AutoMatchTest(TestCase):
    def _user_with_name(self, username, real_name):
        user = User.objects.create_user(username=username, password="x")
        Profile.objects.create(user=user, real_name=real_name)
        return user

    def _row(self, name, code):
        return MemberIdentity.objects.create(
            name=name, admit_year=2026, cohort=2, group="摄影", phone="13800008888", code=code,
        )

    def test_unique_name_binds(self):
        user = self._user_with_name("u1", "张 三")
        row = self._row("张三", "26020001")
        matched = auto_match_identities()
        row.refresh_from_db()
        self.assertEqual(matched, 1)
        self.assertEqual(row.user_id, user.id)
        self.assertEqual(row.bind_method, MemberIdentity.BIND_AUTO)

    def test_ambiguous_name_not_bound(self):
        self._user_with_name("u1", "张三")
        self._user_with_name("u2", "张三")
        row = self._row("张三", "26020001")
        matched = auto_match_identities()
        row.refresh_from_db()
        self.assertEqual(matched, 0)
        self.assertIsNone(row.user_id)

    def test_already_bound_user_not_reused(self):
        user = self._user_with_name("u1", "张三")
        self._row("张三", "26020001").user = user
        MemberIdentity.objects.filter(code="26020001").update(user=user)
        row2 = self._row("张三", "26020002")
        matched = auto_match_identities()
        row2.refresh_from_db()
        self.assertEqual(matched, 0)
        self.assertIsNone(row2.user_id)


class AdminImportTest(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("admin:accounts_memberidentity_import")
        self.user = User.objects.create_user(username="roster-admin", password="x", is_staff=True)
        perm = Permission.objects.get(content_type__app_label="accounts", codename="manage_member_roster")
        self.user.user_permissions.add(perm)

    def test_requires_permission(self):
        plain = User.objects.create_user(username="plain", password="x", is_staff=True)
        self.client.force_login(plain)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_changelist_renders_import_link(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("admin:accounts_memberidentity_changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "导入名册")

    def test_two_step_import_flow(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "roster.csv", csv_bytes([sample_row(), sample_row(name="李四", phone="13900001111")]),
            content_type="text/csv",
        )
        resp = self.client.post(self.url, {"file": upload})
        self.assertEqual(resp.status_code, 200)
        preview = resp.context["preview"]
        self.assertEqual(preview["counts"]["create"], 2)
        stash_id = preview["stash_id"]

        resp2 = self.client.post(self.url, {"stash": stash_id})
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(MemberIdentity.objects.count(), 2)
        self.assertEqual(resp2.context["report"]["created"], 2)

    def test_confirm_with_expired_stash(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {"stash": "nope"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["report"])

    def test_template_download(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("admin:accounts_memberidentity_import_template"))
        self.assertEqual(resp.status_code, 200)
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(resp.content))
        header = [c.value for c in next(wb.active.iter_rows(max_row=1))]
        self.assertEqual(header, HEADERS)

    def test_export_qr_zip_action(self):
        admin = User.objects.create_superuser(username="root", password="x", email="root@example.com")
        self.client.force_login(admin)
        row1 = MemberIdentity.objects.create(name="张三", admit_year=2026, cohort=2, group="摄影", phone="13800008888", code="26020001")
        row2 = MemberIdentity.objects.create(name="李四", admit_year=2025, cohort=1, group="信息", phone="13900001111", code="25010001")
        resp = self.client.post(
            reverse("admin:accounts_memberidentity_changelist"),
            {"action": "export_member_qr", "_selected_action": [str(row1.pk), str(row2.pk)]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        with ZipFile(io.BytesIO(resp.content)) as zf:
            names = sorted(zf.namelist())
            self.assertEqual(names, ["25010001_李四.png", "26020001_张三.png"])
            self.assertTrue(zf.read(names[0]).startswith(b"\x89PNG"))
