"""问卷作答检索测试：``GET .../responses/?q=`` + ``activities/survey_search.py`` 纯函数。

关注两件事：
1. 匹配口径（选择题按选项文本、文件题按文件名、全角/大小写归一化、只搜作答内容）；
2. 响应契约（``total`` 保留未过滤份数、``query`` 回显、``matches`` 只含命中字段），
   以及权限边界不因检索而放宽（普通成员仍只能搜自己那一份）。
"""
import json

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from reviews.test_helpers import approve_activity

from . import survey_search
from .models import Activity, Questionnaire

SCHEMA = {
    "title": "检索测试问卷",
    "pages": [{
        "name": "page1",
        "elements": [
            {
                "type": "radiogroup",
                "name": "fav",
                "title": "最喜欢的栏目",
                # value 与 text 不同：库里存 news，用户看到「新闻」
                "choices": [
                    {"value": "news", "text": "新闻"},
                    {"value": "act", "text": "活动"},
                ],
            },
            {"type": "checkbox", "name": "skills", "title": "擅长方向", "choices": ["摄影", "剪辑"]},
            {"type": "comment", "name": "intro", "title": "自我介绍"},
            {"type": "rating", "name": "score", "title": "评分"},
            {"type": "file", "name": "attach", "title": "作品附件"},
        ],
    }],
}


def _answers(**overrides):
    base = {
        "fav": "news",
        "skills": ["摄影"],
        "intro": "我是高一新生，喜欢摄影和剪辑。",
        "score": 5,
    }
    base.update(overrides)
    return base


class SurveySearchTextTest(SimpleTestCase):
    """纯函数：归一化、取值摊平、命中片段。"""

    def test_clean_query_strips_and_caps(self):
        self.assertEqual(survey_search.clean_query(None), "")
        self.assertEqual(survey_search.clean_query(["x"]), "")
        self.assertEqual(survey_search.clean_query("  新闻   活动 "), "新闻 活动")
        self.assertEqual(len(survey_search.clean_query("字" * 300)), survey_search.MAX_QUERY_LEN)
        self.assertNotIn("\x00", survey_search.clean_query("a\x00b"))

    def test_normalize_is_fullwidth_and_case_insensitive(self):
        self.assertEqual(
            survey_search.normalize_text("  ＮＥＷＳ\t 编辑部 "),
            survey_search.normalize_text("news 编辑部"),
        )

    def test_matches_choice_label_not_just_stored_value(self):
        hit, matches = survey_search.search_answers(SCHEMA, _answers(), "新闻")
        self.assertTrue(hit)
        self.assertEqual(matches[0]["title"], "最喜欢的栏目")
        self.assertEqual(matches[0]["name"], "fav")

    def test_matches_multi_choice_item(self):
        hit, _ = survey_search.search_answers(SCHEMA, _answers(), "剪辑")
        self.assertTrue(hit)

    def test_matches_number_answer(self):
        hit, _ = survey_search.search_answers(SCHEMA, _answers(score=4), "4")
        self.assertTrue(hit)

    def test_matches_file_name(self):
        answers = _answers(attach=[{"name": "海报终稿.png", "content": "https://x/a.png"}])
        hit, matches = survey_search.search_answers(SCHEMA, answers, "海报")
        self.assertTrue(hit)
        self.assertEqual(matches[0]["title"], "作品附件")

    def test_does_not_match_respondent_identity(self):
        # 只搜用户填写的内容；username / 设备标识不参与
        hit, _ = survey_search.search_answers(SCHEMA, _answers(), "zhangsan")
        self.assertFalse(hit)

    def test_unknown_answer_key_is_searchable(self):
        # Schema 已删掉的题目：历史作答仍可被搜到，标题退回键名
        hit, matches = survey_search.search_answers(SCHEMA, {"legacy_note": "旧题目答案"}, "旧题目")
        self.assertTrue(hit)
        self.assertEqual(matches[0]["title"], "legacy_note")

    def test_blank_query_matches_everything(self):
        hit, matches = survey_search.search_answers(SCHEMA, _answers(), "   ")
        self.assertTrue(hit)
        self.assertEqual(matches, [])

    def test_snippet_keeps_context_around_hit(self):
        long_text = "开头" + "填充" * 40 + "关键线索" + "结尾" * 40
        _, matches = survey_search.search_answers(
            SCHEMA, _answers(intro=long_text), "关键线索")
        snippet = matches[0]["snippet"]
        self.assertIn("关键线索", snippet)
        self.assertLess(len(snippet), len(long_text))
        self.assertTrue(snippet.startswith("…"))
        self.assertTrue(snippet.endswith("…"))

    def test_matches_capped_per_response(self):
        answers = {f"q{i}": "同一个词" for i in range(6)}
        _, matches = survey_search.search_answers({}, answers, "同一个词")
        self.assertEqual(len(matches), survey_search.MAX_MATCHES_PER_RESPONSE)


class SurveyResponsesSearchViewTest(TestCase):
    """HTTP：检索词过滤、total 保留、权限边界不变。"""

    def setUp(self):
        self.author = grant_verification(User.objects.create_user(username="sauthor", password="x"))
        self.m1 = grant_verification(User.objects.create_user(username="sm1", password="x"))
        self.m2 = grant_verification(User.objects.create_user(username="sm2", password="x"))
        self.q = Questionnaire.objects.create(kind=Questionnaire.KIND_SURVEY, schema=SCHEMA)
        self.act = Activity.objects.create(
            type="survey", status="open", audience="public",
            title="检索调研", body="<p>x</p>", creator=self.author,
            questionnaire=self.q,
        )
        approve_activity(self.act)
        self.client = APIClient()

    def _respond(self, user, answers):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/activities/activities/{self.act.pk}/respond/",
            data=json.dumps({"answers": answers}),
            content_type="application/json",
        )

    def _responses(self, user, query=None):
        self.client.force_authenticate(user)
        path = f"/activities/activities/{self.act.pk}/responses/"
        return self.client.get(path, {"q": query} if query is not None else {})

    def test_filters_by_text_answer_and_keeps_total(self):
        self._respond(self.m1, _answers(intro="我喜欢摄影"))
        self._respond(self.m2, _answers(intro="我只写稿子", skills=["剪辑"]))
        resp = self._responses(self.author, "摄影")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["query"], "摄影")
        self.assertEqual(resp.data["total"], 2)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["user_label"], "sm1")

    def test_matches_choice_label(self):
        self._respond(self.m1, _answers(fav="act"))
        self._respond(self.m2, _answers(fav="news"))
        resp = self._responses(self.author, "活动")
        self.assertEqual([r["user_label"] for r in resp.data["results"]], ["sm1"])
        self.assertEqual(resp.data["results"][0]["matches"][0]["title"], "最喜欢的栏目")

    def test_no_match_returns_empty_results_with_total(self):
        self._respond(self.m1, _answers())
        resp = self._responses(self.author, "绝对搜不到的词")
        self.assertEqual(resp.data["results"], [])
        self.assertEqual(resp.data["total"], 1)

    def test_blank_query_returns_all(self):
        self._respond(self.m1, _answers())
        self._respond(self.m2, _answers())
        resp = self._responses(self.author, "   ")
        self.assertEqual(resp.data["query"], "")
        self.assertEqual(len(resp.data["results"]), 2)
        self.assertEqual(resp.data["results"][0]["matches"], [])

    def test_member_scope_not_widened_by_search(self):
        # m2 的作答不该被 m1 搜出来；total 也只算 m1 自己那一份
        self._respond(self.m1, _answers(intro="我的答案"))
        self._respond(self.m2, _answers(intro="别人的答案"))
        own = self._responses(self.m1, "别人")
        self.assertEqual(own.data["results"], [])
        self.assertEqual(own.data["total"], 1)
        mine = self._responses(self.m1, "我的")
        self.assertEqual(len(mine.data["results"]), 1)
        self.assertFalse(mine.data["is_manager"])
