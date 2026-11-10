"""数据库不变量测试（B0）。

这些不是业务行为测试，而是「DB 层必须守住的结构契约」——

1. 删活动不删问卷与作答（历史资产，不可逆丢失）；
2. 长期活动不能同时有截止时间（DB 级，不只是表单校验）；
3. 问卷作答带 schema 快照（改题不改史）；
4. 设备 ID 长度两处一致（UserSession / AccountDevice 都是 64）。

每一条都对应一个曾经只能靠应用层代码维护、或根本无法维护的约束。
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import AccountDevice, UserSession
from django.contrib.auth.models import User

from .models import Activity, Questionnaire, QuestionnaireResponse, default_survey_schema
from .testing import make_survey_activity


class ActivityDeleteKeepsQuestionnaireTest(TestCase):
    """删活动是删「入口」，不是删「数据」。

    回归的是这么一条链：Activity post_delete → 手动删 Questionnaire
    → QuestionnaireResponse.questionnaire 是 CASCADE → 全部作答蒸发。
    生产上已经发生过一次（问卷 id=1 已不存在），所以这不是假想风险。
    """

    def setUp(self):
        self.activity = make_survey_activity(
            status="open", title="社团现状调研", audience="members",
        )
        self.questionnaire = self.activity.questionnaire
        self.assertIsNotNone(self.questionnaire, "调研活动应在保存时自动获得问卷")

    def test_questionnaire_survives_activity_delete(self):
        qid = self.questionnaire.pk
        self.activity.delete()
        self.assertTrue(
            Questionnaire.objects.filter(pk=qid).exists(),
            "删活动不应删除问卷——问卷是独立的历史资产",
        )

    def test_responses_survive_activity_delete(self):
        user = User.objects.create_user(username="respondent", password="x")
        QuestionnaireResponse.objects.create(
            questionnaire=self.questionnaire, user=user, answers={"grade": "高一"},
        )
        rid = self.questionnaire.responses.get().pk

        self.activity.delete()

        self.assertTrue(
            QuestionnaireResponse.objects.filter(pk=rid).exists(),
            "删活动不应删除任何人已提交的作答",
        )
        # 问卷变孤儿：没有 activity 引用它，但作答完整保留（B8 的后台筛选依赖这一形态）
        self.assertIsNone(
            Activity.objects.filter(questionnaire_id=self.questionnaire.pk).first(),
        )

    def test_join_questionnaire_unaffected(self):
        """加入问卷不挂 activity，从来不受影响——顺带钉住这个前提。"""
        join = Questionnaire.get_join()
        self.activity.delete()
        self.assertTrue(Questionnaire.objects.filter(pk=join.pk).exists())


class PermanentActivityConstraintTest(TestCase):
    """长期有效与截止时间互斥——DB 层兜底。

    此前只有 ``Activity.clean()`` 和序列化器在拦；admin、shell、未来新写路径
    都能写进「is_permanent=True 且有 end_at」的行，之后 lifecycle 的惰性结算
    和 is_permanent 语义就会互相打架。
    """

    def test_permanent_with_end_at_is_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Activity.objects.create(
                    type="deliberation", status="open", title="矛盾活动",
                    is_permanent=True, end_at=timezone.now() + timedelta(days=7),
                )

    def test_permanent_without_end_at_is_allowed(self):
        activity = Activity.objects.create(
            type="deliberation", status="open", title="长期活动", is_permanent=True,
        )
        self.assertIsNone(activity.end_at)

    def test_scheduled_with_end_at_is_allowed(self):
        activity = Activity.objects.create(
            type="deliberation", status="open", title="有截止的活动",
            is_permanent=False, end_at=timezone.now() + timedelta(days=7),
        )
        self.assertIsNotNone(activity.end_at)

    def test_clean_still_reports_friendly_error(self):
        """DB 约束是兜底，用户可见的仍然是 clean() 的中文字段错误。"""
        from django.core.exceptions import ValidationError

        activity = Activity(
            type="deliberation", status="open", title="x",
            is_permanent=True, end_at=timezone.now(),
        )
        with self.assertRaises(ValidationError) as ctx:
            activity.clean()
        self.assertIn("end_at", ctx.exception.message_dict)


class QuestionnaireResponseSnapshotTest(TestCase):
    """作答要带「它当时看到的题目」。

    没有快照时：改一次题（element 改名 / 删题），历史作答就按新 schema 解释——
    统计错位、已删题目凭空消失，且无痕。
    """

    def setUp(self):
        self.activity = make_survey_activity(
            status="open", title="快照测试", audience="members",
        )
        self.questionnaire = self.activity.questionnaire
        self.schema_v1 = {
            "title": "第一版",
            "pages": [{"name": "p1", "elements": [{"type": "text", "name": "q1", "title": "题一"}]}],
        }
        self.questionnaire.schema = self.schema_v1
        self.questionnaire.save(update_fields=["schema", "updated_at"])

    def test_new_response_snapshots_schema(self):
        resp = QuestionnaireResponse.objects.create(
            questionnaire=self.questionnaire, answers={"q1": "答"},
        )
        self.assertEqual(resp.schema_snapshot, self.schema_v1)

    def test_old_response_keeps_snapshot_after_schema_edit(self):
        resp = QuestionnaireResponse.objects.create(
            questionnaire=self.questionnaire, answers={"q1": "答"},
        )
        self.questionnaire.schema = {
            "title": "第二版",
            "pages": [{"name": "p1", "elements": [{"type": "text", "name": "q2", "title": "改名了"}]}],
        }
        self.questionnaire.save(update_fields=["schema", "updated_at"])

        resp.refresh_from_db()
        self.assertEqual(resp.schema_snapshot, self.schema_v1, "历史作答必须仍由旧 schema 解释")

    def test_explicit_snapshot_is_not_overwritten(self):
        explicit = {"title": "调用方指定", "pages": []}
        resp = QuestionnaireResponse.objects.create(
            questionnaire=self.questionnaire, answers={}, schema_snapshot=explicit,
        )
        self.assertEqual(resp.schema_snapshot, explicit)

    def test_updating_existing_response_does_not_rewrite_snapshot(self):
        resp = QuestionnaireResponse.objects.create(
            questionnaire=self.questionnaire, answers={"q1": "答"},
        )
        old = resp.schema_snapshot
        self.questionnaire.schema = {"title": "被改过", "pages": []}
        self.questionnaire.save(update_fields=["schema", "updated_at"])

        resp.answers = {"q1": "改了答案"}
        resp.save()
        resp.refresh_from_db()
        self.assertEqual(resp.schema_snapshot, old, "更新作答不应顺带刷新快照")

    def test_recruitment_style_create_also_snapshots(self):
        """加入问卷走 serializer.save(questionnaire=...) 这条路径，也要有快照。"""
        join = Questionnaire.get_join()
        join.schema = {"title": "招生", "pages": [{"name": "p", "elements": []}]}
        join.save(update_fields=["schema", "updated_at"])

        resp = QuestionnaireResponse(answers={"grade": "高一"})
        resp.questionnaire = join
        resp.save()

        self.assertEqual(resp.schema_snapshot, join.schema)

    def test_default_schema_still_usable(self):
        """没有内容的默认问卷也要能正常快照（不能因为空 dict 判断而漏写）。"""
        fresh = make_survey_activity(
            status="open", title="默认问卷", audience="members",
        )
        resp = QuestionnaireResponse.objects.create(
            questionnaire=fresh.questionnaire, answers={},
        )
        self.assertEqual(resp.schema_snapshot, default_survey_schema())


class DeviceIdLengthTest(TestCase):
    """设备 ID 在两张表里必须同宽。

    现值由 ``secrets.token_hex(16)`` 生成（32 位），两处分别是 40 / 64 时没触雷；
    但一旦换生成算法或接原生端，一处截断、另一处完整 → 认不出是同一台设备。
    """

    def test_user_session_accepts_64_chars(self):
        user = User.objects.create_user(username="dev", password="x")
        long_id = "a" * 64
        session = UserSession.objects.create(user=user, session_key="k" * 40, device_id=long_id)
        session.refresh_from_db()
        self.assertEqual(session.device_id, long_id)

    def test_length_matches_account_device(self):
        session_max = UserSession._meta.get_field("device_id").max_length
        device_max = AccountDevice._meta.get_field("device_id").max_length
        self.assertEqual(session_max, device_max)
