"""B8 之后的测试夹具。

## 为什么需要

`Activity.save()` 不再为 survey 类型自动建问卷——那属于 service 层的职责
（`activities/serializers.py` 的 `create()`）。model 层做跨表创建会让 admin、
shell、任何新建入口都意外多出一份问卷。

代价是测试里直接 `Activity.objects.create(type="survey")` 拿到的是**没有问卷**
的活动，访问 `activity.questionnaire` 得到 None。

`make_survey_activity()` 补上这一步，让测试保留原来的写法。
"""
from .models import Activity, Questionnaire, default_survey_schema


def make_survey_activity(**fields):
    """建调研活动并挂上问卷，返回活动（``activity.questionnaire`` 已可用）。

    调用方显式传了 ``questionnaire=`` 时不新建——那是「我要挂这份特定问卷」的
    意思，覆盖掉会让调用方拿到的 schema 不是自己给的那份。
    """
    fields.setdefault("type", "survey")
    if fields.get("questionnaire") is not None:
        return Activity.objects.create(**fields)

    activity = Activity.objects.create(**fields)
    questionnaire = Questionnaire.objects.create(
        kind=Questionnaire.KIND_SURVEY, schema=default_survey_schema(),
    )
    Activity.objects.filter(pk=activity.pk).update(questionnaire=questionnaire)
    activity.questionnaire = questionnaire
    return activity
