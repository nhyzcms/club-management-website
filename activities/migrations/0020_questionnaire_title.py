"""给 Questionnaire 加冗余列 ``title``，从 ``schema["title"]`` 回填（B8）。

## 为什么需要这一列

`Questionnaire.schema` 是 JSONField，标题存在 `schema["title"]` 里。JSON 里的值
在 SQL 层没法建索引、没法排序、也没法用 `search_fields` 搜——admin 列表里只能
显示 `__str__` 拼出来的字符串，点不了列头。

## 为什么是冗余而不是搬家

`schema` 是 SurveyJS 的完整定义，前端直接吃它。把 title 从 schema 里挪走意味着
前端要改、导入导出格式要变。留一份冗余、由 `save()` 保证一致，代价最小。

## 回填

存量行的 `title` 会是空字符串（`default=""`），这里从 schema 抄一遍。
反向不需要写：`title` 是派生值，删列不丢信息（schema 还在）。
"""
from django.db import migrations, models


def backfill(apps, schema_editor):
    Questionnaire = apps.get_model("activities", "Questionnaire")
    filled = 0
    for row in Questionnaire.objects.all().only("pk", "schema").iterator():
        title = ((row.schema or {}).get("title") or "")[:200]
        if title:
            Questionnaire.objects.filter(pk=row.pk).update(title=title)
            filled += 1
    if filled:
        print(f"[activities.0020] 回填 {filled} 份问卷标题")


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0019_rename_submission_audit_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionnaire",
            name="title",
            field=models.CharField(
                blank=True, default="", max_length=200, verbose_name="标题",
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
