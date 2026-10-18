"""E2E 种子数据：为 Playwright 测试准备确定性环境（幂等，可重复执行）。

内容（覆盖前端全部模块）：
- ``e2e_info``：超管账号（具备全部管理权限；发布即过审）——E2E 主账号；
- ``e2e_plain``：普通账号（无管理权限）——登录 / 审核对象等用例使用；
- 标签「E2E公告 / E2E活动」+ 一条已过审的已发布新闻（首页动态可见）；
- 待审新闻 ×2（审核台「发布审核桌」+「下一条」浏览）；
- 活动 ×2：公开众议（带投票选项）、公开调研（带问卷）；
- 教程 ×1（文档型）；任务 ×1；
- 反馈 ×1（匿名）；举报 ×1（e2e_plain 对种子新闻）；
- 认证 ×1：e2e_plain 待审人工认证（含证明材料图）；
- 通知 ×1（e2e_info「新意见反馈」）；私信会话 ×1（e2e_plain ↔ e2e_info）；
- 招生公告 + 自我介绍问卷 Schema；考试板：当天日期的一场考试；
- 社员身份 ×1（「谢二」）：认领 / 扫码校验夹具，并把签名后的二维码参数写入
  ``frontend/e2e/.member-qr.json``（Playwright 用例读取，免在 spec 里复刻 HMAC）；
- 重置两个账号的登录会话：登录保护窗口会把 10 分钟内的「再次登录」拒掉，
  每次跑 E2E 前必须清掉旧会话，否则第二次运行会 409。

密码：环境变量 ``E2E_PASSWORD``，默认 ``e2e-pass-123``（测试环境固定值，非机密）。
生产环境（DEBUG=False）需显式 ``--force`` 才可执行。
"""
import json
import os
import struct
import zlib
from datetime import time as dtime
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from about.models import AboutBlock, AboutPage
from accounts import stepup
from accounts.member_codes import make_signature
from accounts.models import IdentityProof, MemberIdentity, Profile, UserSession, Verification
from activities.models import Activity, Questionnaire, VoteOption, default_join_schema
from exam_board.models import Exam, ExamBatch, ExamSubject
from messaging.models import Conversation, Message, Notification
from news.models import News
from recruitment.models import RecruitmentNotice
from reviews.models import Feedback, ReportCase, ReportFiling, Review
from tasks.models import Tag, Task
from tutorials.models import Tutorial

E2E_USERS = ("e2e_info", "e2e_plain", "e2e_stepup")
DEFAULT_PASSWORD = "e2e-pass-123"


def _make_png(width: int = 64, height: int = 64) -> bytes:
    """纯标准库生成一张 64×64 纯色 PNG（认证证明材料用，无需 Pillow）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes((232, 48, 48)) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class Command(BaseCommand):
    help = "为 Playwright E2E 准备种子数据（幂等；含登录会话重置）"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="非 DEBUG 环境下强制执行（仅供测试）")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("当前环境 DEBUG=False；确需执行请加 --force（仅供测试）。")

        password = os.environ.get("E2E_PASSWORD", DEFAULT_PASSWORD)

        info, _ = User.objects.get_or_create(username="e2e_info", defaults={"email": "e2e_info@example.test"})
        info.is_superuser = True
        info.is_staff = True
        info.is_active = True
        info.set_password(password)
        info.save()

        plain, _ = User.objects.get_or_create(username="e2e_plain", defaults={"email": "e2e_plain@example.test"})
        plain.is_superuser = False
        plain.is_staff = False
        plain.is_active = True
        plain.set_password(password)
        plain.save()

        # 改密全流程专属：改密会轮换 session key（见 ADR-0026），不能拿共享 storageState 的 e2e_info 做改密。
        stepup_user, _ = User.objects.get_or_create(username="e2e_stepup", defaults={"email": "e2e_stepup@example.test"})
        stepup_user.is_superuser = False
        stepup_user.is_staff = False
        stepup_user.is_active = True
        stepup_user.set_password(password)
        stepup_user.save()

        for user, nickname in ((info, "E2E 信息员"), (plain, "E2E 普通成员"), (stepup_user, "E2E 安全验证成员")):
            Profile.objects.update_or_create(user=user, defaults={"nickname": nickname})

        # 登录保护：清掉旧会话，保证每次运行的首次登录都被放行
        UserSession.objects.filter(user__username__in=E2E_USERS).delete()

        # ── 社员身份（Part A / ADR-0025）：认领 + 扫码校验夹具 ──────────
        # 「谢二」未被绑定：注册用例用同名真实姓名注册后可自助认领；
        # 签名参数另写入 frontend/e2e/.member-qr.json，供扫码校验用例直读。
        member_row, _ = MemberIdentity.objects.get_or_create(
            code="26090001",
            defaults={
                "name": "谢二",
                "admit_year": 2026,
                "cohort": 9,
                "group": "信息",
                "phone": "13800001234",
            },
        )
        qr_fixture = {
            "code": member_row.code,
            "sig": make_signature(member_row.code),
            "name": member_row.name,
        }
        fixture_path = Path(settings.BASE_DIR) / "frontend" / "e2e" / ".member-qr.json"
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(json.dumps(qr_fixture, ensure_ascii=False, indent=2), encoding="utf-8")

        # 安全验证（ADR-0026）：预置安全问题（答案 e2e-answer，归一化比对）
        # ——info 供「安全验证」面板查看用例；e2e_stepup 供改密全流程用例。
        for user in (info, stepup_user):
            stepup.set_security_questions(user, [{"key": "primary_school", "answer": "e2e-answer"}])

        tag_notice, _ = Tag.objects.get_or_create(name="E2E公告")
        tag_event, _ = Tag.objects.get_or_create(name="E2E活动")

        # ── 新闻：种子新闻（已过审） + 待审 ×2 ──────────────────────────
        news, _ = News.objects.get_or_create(
            title="E2E 种子新闻",
            defaults={
                "summary": "种子数据：E2E 首页动态可见。",
                "content": "<p>E2E 种子新闻正文，用于列表与详情页断言。</p>",
                "author": info,
                "is_published": True,
                "published_at": timezone.now(),
            },
        )
        news.tags.set([tag_notice, tag_event])
        if news.published_at is None:
            news.published_at = timezone.now()
            news.save(update_fields=["published_at"])
        Review.objects.update_or_create(news=news, defaults={"status": Review.STATUS_APPROVED})

        for suffix in ("甲", "乙"):
            pending, _ = News.objects.get_or_create(
                title=f"E2E 待审新闻{suffix}",
                defaults={
                    "summary": f"种子数据：待审新闻{suffix}。",
                    "content": f"<p>待审新闻{suffix}正文。</p>",
                    "author": plain,
                    "is_published": True,
                    "published_at": timezone.now(),
                },
            )
            Review.objects.update_or_create(news=pending, defaults={"status": Review.STATUS_PENDING})

        # ── 活动：公开众议（投票） + 公开调研（问卷） ──────────────────
        vote_act, _ = Activity.objects.get_or_create(
            title="E2E 投票活动",
            defaults={
                "type": "deliberation",
                "status": "open",
                "audience": "public",
                "voting_enabled": True,
                "body": "<p>E2E 投票活动正文：请选择你支持的一项。</p>",
                "creator": info,
            },
        )
        for order, text in enumerate(("选项甲", "选项乙")):
            VoteOption.objects.get_or_create(activity=vote_act, text=text, defaults={"order": order})
        Review.objects.update_or_create(activity=vote_act, defaults={"status": Review.STATUS_APPROVED})

        # 第二场众议：不被任何用例投票，专供「待办」收件箱断言（投票后条目会消失）
        todo_act, _ = Activity.objects.get_or_create(
            title="E2E 待办活动",
            defaults={
                "type": "deliberation",
                "status": "open",
                "audience": "public",
                "voting_enabled": True,
                "body": "<p>E2E 待办活动正文：用于待办收件箱。</p>",
                "creator": info,
            },
        )
        for order, text in enumerate(("待办选项一", "待办选项二")):
            VoteOption.objects.get_or_create(activity=todo_act, text=text, defaults={"order": order})
        Review.objects.update_or_create(activity=todo_act, defaults={"status": Review.STATUS_APPROVED})

        survey_schema = {
            "title": "E2E 调研问卷",
            "pages": [
                {
                    "name": "page1",
                    "elements": [
                        {
                            "type": "radiogroup",
                            "name": "fav",
                            "title": "你最喜欢的栏目？",
                            "isRequired": True,
                            "choices": ["新闻", "活动", "教程"],
                        },
                        {"type": "text", "name": "comment", "title": "留言（选填）"},
                    ],
                }
            ],
        }
        survey_q = Questionnaire.objects.create(kind="survey", schema=survey_schema)
        survey_act, _ = Activity.objects.get_or_create(
            title="E2E 调研活动",
            defaults={
                "type": "survey",
                "status": "open",
                "audience": "public",
                "body": "<p>E2E 调研活动正文。</p>",
                "creator": info,
                "questionnaire": survey_q,
            },
        )
        Review.objects.update_or_create(activity=survey_act, defaults={"status": Review.STATUS_APPROVED})

        # ── 教程（文档型） ─────────────────────────────────────────────
        tut, _ = Tutorial.objects.get_or_create(
            title="E2E 教程：投稿指南",
            defaults={
                "description": "E2E 教程描述：如何向传媒社投稿。",
                "file_type": "document",
                "file_name": "e2e-guide.md",
                "file_size": 0,
                "uploader": info,
            },
        )
        if not tut.file:
            body = "# E2E 教程\n\n这是种子教程文件。\n".encode()
            tut.file.save("e2e-guide.md", ContentFile(body), save=False)
            tut.file_size = len(body)
            tut.save(update_fields=["file", "file_size"])
        Review.objects.update_or_create(tutorial=tut, defaults={"status": Review.STATUS_APPROVED})

        # ── 任务 ───────────────────────────────────────────────────────
        task, _ = Task.objects.get_or_create(
            title="E2E 任务：整理素材库",
            defaults={
                "description": "E2E 任务描述：整理本学期素材。",
                "status": "pending",
                "priority": "high",
                "creator": info,
                "assignee": plain,
            },
        )
        task.tags.set([tag_event])

        # ── 反馈（匿名） + 举报 ────────────────────────────────────────
        feedback, _ = Feedback.objects.get_or_create(
            title="E2E 反馈条目",
            defaults={
                "category": "suggestion",
                "description": "E2E 反馈描述：建议增加暗色模式。",
                "creator": None,
                "contact": "",
            },
        )
        report_case, _ = ReportCase.objects.get_or_create(news=news, defaults={})
        ReportFiling.objects.get_or_create(
            case=report_case, reporter=plain,
            defaults={"reason": "E2E 举报理由：内容存疑。"},
        )

        # ── 认证：e2e_plain 待审人工认证 + 证明材料 ────────────────────
        Verification.objects.get_or_create(
            user=plain, channel="manual", status="pending",
            defaults={"identifier": "E2E 人工认证"},
        )
        if not IdentityProof.objects.filter(user=plain).exists():
            IdentityProof.objects.create(user=plain, file=ContentFile(_make_png(), name="proof.png"))

        # ── 通知 + 私信 ────────────────────────────────────────────────
        Notification.objects.get_or_create(
            recipient=info, category="review", event="approved",
            defaults={"payload": {"news_id": news.pk}},
        )
        conversation, _ = Conversation.objects.get_or_create(title="E2E 会话")
        conversation.participants.set([info, plain])
        Message.objects.get_or_create(
            conversation=conversation, sender=plain,
            content="E2E 私信：你好，这是种子消息。",
        )

        # ── 招生：公告 + 自我介绍问卷 Schema ───────────────────────────
        RecruitmentNotice.objects.update_or_create(
            pk=1,
            defaults={"content": "<p>欢迎加入南汇一中传媒社（E2E 招生公告）。</p>"},
        )
        join_q = Questionnaire.objects.filter(kind="join").first()
        if join_q is None:
            Questionnaire.objects.create(kind="join", schema=default_join_schema())
        else:
            pages = (join_q.schema or {}).get("pages") or []
            if not pages or not pages[0].get("elements"):
                join_q.schema = default_join_schema()
                join_q.save(update_fields=["schema"])

        # ── 考试板：当天日期的一场考试 ─────────────────────────────────
        today = timezone.localdate()
        exam, _ = Exam.objects.get_or_create(title="E2E 期中考试", defaults={"updated_by": info})
        batch, _ = ExamBatch.objects.get_or_create(exam=exam, name="高一", defaults={"sort_order": 0})
        for order, (subject, start, end) in enumerate(
            (("语文", dtime(9, 0), dtime(11, 30)), ("数学", dtime(14, 0), dtime(16, 0)))
        ):
            ExamSubject.objects.get_or_create(
                batch=batch, name=subject,
                defaults={"exam_date": today, "start_time": start, "end_time": end, "sort_order": order},
            )

        # ── 关于页（有内容可断言） ─────────────────────────────────────
        AboutPage.objects.get_or_create(
            pk=1,
            defaults={"content": "<p>E2E 关于我们正文。</p>", "intro": "南汇一中传媒社（E2E）"},
        )
        AboutBlock.objects.get_or_create(
            key="intro",
            defaults={"title": "社团简介", "content": "<p>E2E 社团简介正文。</p>", "order": 0},
        )

        self.stdout.write(self.style.SUCCESS(
            f"seed_e2e 完成：账号 {'/'.join(E2E_USERS)}（密码 {password}）"
            f" + 新闻 #{news.pk} + 待审×2 + 活动×2 + 教程 #{tut.pk} + 任务 #{task.pk}"
            f" + 反馈 #{feedback.pk} + 举报 #{report_case.pk} + 通知 + 私信 #{conversation.pk}"
            f" + 考试 #{exam.pk} + 招生公告"
        ))
