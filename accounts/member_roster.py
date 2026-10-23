"""名册导入 / 自动匹配 / 自助认领（社员身份编号系统，见 ADR-0025）。

职责：
- 解析 CSV / XLSX（表头识别；值宽松、关键字段严格）；
- 预检（不落库）：逐行校验 + 与库内对账（新增 / 更新 / 冲突 / 错误）；
- 确认导入：事务内落库（幂等：姓名+电话 → 同届+姓名 认行；**识别码一律自动生成**，
  表格中的「识别码」列仅作参照、导入时忽略）；
- 自动匹配：按真实姓名把名册行绑到已有账号（唯一命中才自动，歧义进人工）；
- 自助认领：候选（本人真实姓名匹配的未绑定行）/ 手机后四位校验 / 绑定。
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from .member_codes import MemberCodeError, generate_code, name_sort_key, next_serial
from .models import IdentityImportBatch, MemberIdentity, Profile

HEADERS = [
    "姓名", "年级", "班级", "学号", "入学年份", "入社时间",
    "届数", "组别", "性别", "年龄", "电话号码", "识别码",
]
REQUIRED_COLUMNS = ["姓名", "入学年份", "届数", "组别"]

_WS_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"\D")


class RosterParseError(Exception):
    """文件级解析失败（格式、编码、缺列等）。"""


class ClaimError(Exception):
    """自助认领失败（文案直接回给用户）。"""


def normalize_name(raw: str) -> str:
    """姓名归一：去全部空白（含全角）、西文大小写折叠——用于匹配而非展示。"""
    return _WS_RE.sub("", (raw or "").replace("\u3000", " ")).strip().casefold()


@dataclass
class ParsedRow:
    row_no: int  # 文件里的行号（表头为 1，数据从 2 起）
    values: dict
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _read_xlsx(content: bytes) -> list[list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb.active
        return [[_cell_str(c) for c in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _read_csv(content: bytes) -> list[list[str]]:
    text = None
    for enc in ("utf-8-sig", "gbk"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RosterParseError("无法识别文件编码（支持 UTF-8 / GBK）。")
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]


def _int_or_none(raw: str):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def parse_roster(filename: str, content: bytes) -> list[ParsedRow]:
    """解析名册文件 → 数据行列表（行级问题挂在 ``errors`` / ``warnings``）。

    文件级问题（格式 / 编码 / 缺列 / 空文件）抛 :class:`RosterParseError`。
    """
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        grid = _read_xlsx(content)
    elif name.endswith(".csv"):
        grid = _read_csv(content)
    else:
        raise RosterParseError("仅支持 .csv / .xlsx 文件。")
    if not grid:
        raise RosterParseError("文件为空。")

    header = [_cell_str(c) for c in grid[0]]
    missing = [h for h in REQUIRED_COLUMNS if h not in header]
    if missing:
        raise RosterParseError(f"缺少必需列：{'、'.join(missing)}。")
    index = {h: i for i, h in enumerate(header) if h in HEADERS}

    rows: list[ParsedRow] = []
    for offset, raw_row in enumerate(grid[1:]):
        if not any(_cell_str(c) for c in raw_row):
            continue  # 整行空白跳过
        values = {}
        for h in HEADERS:
            i = index.get(h)
            values[h] = _cell_str(raw_row[i]) if (i is not None and i < len(raw_row)) else ""
        pr = ParsedRow(row_no=offset + 2, values=values)
        _validate_row(pr)
        rows.append(pr)

    if not rows:
        raise RosterParseError("表中没有数据行。")
    _flag_file_duplicates(rows)
    return rows


def _validate_row(pr: ParsedRow) -> None:
    v = pr.values

    if not v["姓名"]:
        pr.errors.append("姓名不能为空")

    admit = _int_or_none(v["入学年份"])
    if admit is None or not (1990 <= admit <= 2100):
        pr.errors.append("入学年份须为 1990-2100 的整数")
    else:
        v["入学年份"] = admit

    cohort = _int_or_none(v["届数"])
    if cohort is None or not (1 <= cohort <= 99):
        pr.errors.append("届数须为 1-99 的整数")
    else:
        v["届数"] = cohort

    if not v["组别"]:
        pr.errors.append("组别不能为空")

    age_raw = v["年龄"]
    if age_raw:
        age = _int_or_none(age_raw)
        if age is None or not (5 <= age <= 100):
            pr.errors.append("年龄须为 5-100 的整数")
            v["年龄"] = None
        else:
            v["年龄"] = age
    else:
        v["年龄"] = None

    phone_raw = v["电话号码"]
    if phone_raw:
        digits = _DIGIT_RE.sub("", phone_raw)
        if len(digits) < 7:
            pr.warnings.append(f"电话号码位数异常（{phone_raw}），已按原样保留")
        v["电话号码"] = digits
    else:
        pr.warnings.append("未登记电话号码：该身份不可自助认领，只能由管理员绑定")

    # 注：「识别码」列内容忽略——识别码一律由系统按规则生成（ADR-0025）。


def _flag_file_duplicates(rows: list[ParsedRow]) -> None:
    by_name_phone: dict[tuple, list[int]] = defaultdict(list)
    for pr in rows:
        v = pr.values
        if v["姓名"] and v["电话号码"]:
            by_name_phone[(normalize_name(v["姓名"]), v["电话号码"])].append(pr.row_no)
    for _, nos in by_name_phone.items():
        if len(nos) > 1:
            for pr in rows:
                key = (normalize_name(pr.values["姓名"]), pr.values["电话号码"])
                if key in by_name_phone and pr.row_no in nos:
                    others = [f"第 {n} 行" for n in nos if n != pr.row_no]
                    pr.errors.append(f"与{'、'.join(others)}疑似重复（同名同电话）")


def plan_import(rows: list[ParsedRow]) -> dict:
    """与库内对账 → 逐行动作（create / update / conflict / error），不落库。

    认行键：姓名+电话 →（无电话时）届数+姓名。识别码一律自动生成
    （表格「识别码」列内容忽略；更新行保留既有编码；新增行按「当届已有最大序号 + 1」
    接续，同批新增之间按姓名 GBK 序排序分配——不重排已发码）。
    """
    existing = list(MemberIdentity.objects.all())
    taken = {r.code for r in existing}
    by_name_phone: dict[tuple, list[MemberIdentity]] = defaultdict(list)
    by_cohort_name: dict[tuple, list[MemberIdentity]] = defaultdict(list)
    for r in existing:
        n = normalize_name(r.name)
        if r.phone:
            by_name_phone[(n, r.phone)].append(r)
        by_cohort_name[(r.cohort, n)].append(r)

    items: list[dict] = []
    pending: list[tuple[int, ParsedRow]] = []
    counts = {"create": 0, "update": 0, "conflict": 0, "error": 0}

    for pr in rows:
        if pr.errors:
            counts["error"] += 1
            items.append({
                "row": pr, "action": "error", "target": None, "code": None,
                "note": "；".join(pr.errors),
            })
            continue

        v = pr.values
        name_n = normalize_name(v["姓名"])
        notes = list(pr.warnings)
        target = None

        if v["电话号码"]:
            matches = by_name_phone.get((name_n, v["电话号码"]), [])
        else:
            matches = by_cohort_name.get((v["届数"], name_n), [])
        if len(matches) == 1:
            target = matches[0]
        elif len(matches) > 1:
            counts["conflict"] += 1
            items.append({
                "row": pr, "action": "conflict", "target": None, "code": None,
                "note": f"库内 {len(matches)} 条既有行匹配（同名同电话 / 同名同届），需人工处理",
            })
            continue

        if target is not None:
            counts["update"] += 1
            items.append({"row": pr, "action": "update", "target": target, "code": target.code, "note": "；".join(notes)})
            continue

        # 新增：先占位，第二遍按「当次名单姓名序」统一分配识别码。
        items.append({"row": pr, "action": "create", "target": None, "code": None, "note": "；".join(notes)})
        pending.append((len(items) - 1, pr))

    # 第二遍：同届（入学年份 + 届数）内按姓名 GBK 序分配「接续序号」——不重排已发码。
    groups: dict[tuple[int, int], list[tuple[int, ParsedRow]]] = defaultdict(list)
    for idx, pr in pending:
        v = pr.values
        groups[(v["入学年份"], v["届数"])].append((idx, pr))

    for (admit_year, cohort), members in groups.items():
        members.sort(key=lambda pair: (
            name_sort_key(pair[1].values["姓名"]),
            pair[1].values["电话号码"] or "",
            pair[1].row_no,
        ))
        for idx, pr in members:
            try:
                serial = next_serial(admit_year, cohort, taken)
                code = generate_code(admit_year, cohort, serial)
            except MemberCodeError as exc:
                items[idx]["action"] = "error"
                items[idx]["note"] = str(exc)
                counts["error"] += 1
                continue
            taken.add(code)
            items[idx]["code"] = code
            counts["create"] += 1

    return {"items": items, "counts": counts}


def commit_import(rows: list[ParsedRow], *, file_name: str, operator=None) -> IdentityImportBatch:
    """确认导入：事务内落库 + 批次留痕 + 全库自动匹配。"""
    plan = plan_import(rows)
    with transaction.atomic():
        batch = IdentityImportBatch.objects.create(
            file_name=(file_name or "")[:255], uploaded_by=operator,
        )
        created = updated = 0
        for item in plan["items"]:
            action = item["action"]
            if action == "create":
                v = item["row"].values
                MemberIdentity.objects.create(
                    import_batch=batch, code=item["code"],
                    name=v["姓名"], grade=v["年级"], class_no=v["班级"], student_no=v["学号"],
                    admit_year=v["入学年份"], joined_on_raw=v["入社时间"], cohort=v["届数"],
                    group=v["组别"], gender=v["性别"], age=v["年龄"], phone=v["电话号码"],
                )
                created += 1
            elif action == "update":
                obj, v = item["target"], item["row"].values
                obj.name, obj.grade, obj.class_no, obj.student_no = v["姓名"], v["年级"], v["班级"], v["学号"]
                obj.admit_year, obj.joined_on_raw, obj.cohort = v["入学年份"], v["入社时间"], v["届数"]
                obj.group, obj.gender, obj.age, obj.phone = v["组别"], v["性别"], v["年龄"], v["电话号码"]
                obj.import_batch = batch
                obj.save()
                updated += 1
        matched = auto_match_identities()
        batch.summary = {
            "total": len(rows),
            "created": created,
            "updated": updated,
            "conflicts": plan["counts"]["conflict"],
            "errors": plan["counts"]["error"],
            "auto_matched": matched,
        }
        batch.save(update_fields=["summary"])
    return batch


def auto_match_identities(rows: list[MemberIdentity] | None = None) -> int:
    """把未绑定名册行按「真实姓名唯一命中」自动绑到已有账号；返回绑定数。

    - 同名多人 / 多行同名 → 不动作（留给管理员或用户自助认领）；
    - ``rows`` 为 None 时对全库未绑定行重跑（管理员动作 / 每次导入收尾）。
    """
    qs = MemberIdentity.objects.filter(user__isnull=True)
    if rows is not None:
        qs = qs.filter(pk__in=[r.pk for r in rows])
    unbound = list(qs)
    if not unbound:
        return 0

    profiles = (
        Profile.objects.exclude(real_name="")
        # 已注销 / 已停用账号不参与自动匹配（ADR-0027）：否则同名的新名册行会被绑到
        # 一个永远不会再登录的账号上，且无法再被本人认领。
        .filter(user__is_active=True, deleted_at__isnull=True)
        .filter(user__member_identity__isnull=True)
        .select_related("user")
    )
    candidates: dict[str, list] = defaultdict(list)
    for p in profiles:
        candidates[normalize_name(p.real_name)].append(p.user)

    bound_ids = set(
        MemberIdentity.objects.exclude(user__isnull=True).values_list("user_id", flat=True)
    )
    matched = 0
    now = timezone.now()
    for row in unbound:
        pool = [u for u in candidates.get(normalize_name(row.name), []) if u.pk not in bound_ids]
        if len(pool) != 1:
            continue
        user = pool[0]
        row.user = user
        row.bound_at = now
        row.bound_by = None
        row.bind_method = MemberIdentity.BIND_AUTO
        row.save(update_fields=["user", "bound_at", "bound_by", "bind_method", "updated_at"])
        bound_ids.add(user.pk)
        matched += 1
    return matched


def claim_candidates(user) -> list[MemberIdentity]:
    """本人可认领的候选：真实姓名匹配、尚未绑定的名册行。"""
    profile = getattr(user, "profile", None)
    if profile is None or not (profile.real_name or "").strip():
        return []
    name_n = normalize_name(profile.real_name)
    return [
        row
        for row in MemberIdentity.objects.filter(user__isnull=True)
        if normalize_name(row.name) == name_n
    ]


def claim_identity(user, identity_id: int, phone_last4: str) -> MemberIdentity:
    """自助认领：姓名匹配 + 手机号后四位校验 → 绑定（事务 + 行锁）。"""
    digits = _DIGIT_RE.sub("", phone_last4 or "")
    if len(digits) != 4:
        raise ClaimError("请输入手机号后四位（4 个数字）。")

    with transaction.atomic():
        row = MemberIdentity.objects.select_for_update().filter(pk=identity_id).first()
        if row is None:
            raise ClaimError("该身份不存在或已失效。")
        if MemberIdentity.objects.filter(user=user).exists():
            raise ClaimError("你的账号已绑定过社员身份。")
        if row.user_id:
            raise ClaimError("该身份已被认领。")

        profile = getattr(user, "profile", None)
        if profile is None or normalize_name(profile.real_name) != normalize_name(row.name):
            raise ClaimError("身份信息与账号不匹配，无法认领。")

        row_digits = _DIGIT_RE.sub("", row.phone or "")
        if len(row_digits) < 4:
            raise ClaimError("该身份未登记电话号码，无法自助认领，请联系管理员。")
        if row_digits[-4:] != digits:
            raise ClaimError("手机号后四位不匹配。")

        row.user = user
        row.bound_at = timezone.now()
        row.bound_by = None
        row.bind_method = MemberIdentity.BIND_SELF
        row.save(update_fields=["user", "bound_at", "bound_by", "bind_method", "updated_at"])
    return row
