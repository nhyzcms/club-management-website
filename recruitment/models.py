from django.conf import settings
from django.db import models


class SingletonManager(models.Manager):
    def get_solo(self):
        obj, _ = self.get_or_create(pk=1)
        return obj


class RecruitmentNotice(models.Model):
    """本年度招生公告（单例）：加入落地页展示，须勾选已知晓后才能进入问卷。"""

    content = models.TextField("公告正文（HTML）", blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    objects = SingletonManager()

    class Meta:
        verbose_name = verbose_name_plural = "招生公告"

    def save(self, *args, **kwargs):
        self.pk = 1
        if self._state.adding and RecruitmentNotice.objects.filter(pk=1).exists():
            self._state.adding = False
            kwargs.pop("force_insert", None)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    def __str__(self):
        return "招生公告"


def default_schema():
    """历史迁移 / 种子仍引用此形状；运行时代码走 activities.models.default_join_schema。"""
    return {
        "title": "自我介绍问卷",
        "pages": [
            {
                "name": "page1",
                "elements": [
                    {
                        "type": "radiogroup",
                        "name": "grade",
                        "title": "年级",
                        "isRequired": True,
                        "choices": ["高一", "高二", "高三"],
                    },
                    {
                        "type": "checkbox",
                        "name": "skills",
                        "title": "擅长方向（可多选）",
                        "choices": ["摄影", "剪辑", "平面设计", "撰稿"],
                    },
                    {
                        "type": "dropdown",
                        "name": "source",
                        "title": "你如何得知本社团？",
                        "choices": ["同学介绍", "海报", "其他"],
                    },
                    {
                        "type": "text",
                        "name": "other_source",
                        "title": "其他来源",
                        "visibleIf": "{source} = '其他'",
                    },
                    {
                        "type": "comment",
                        "name": "intro",
                        "title": "自我介绍",
                        "isRequired": True,
                    },
                ],
            }
        ],
        "triggers": [
            {
                "type": "skip",
                "expression": "{grade} = '高三'",
                "gotoName": "intro",
            }
        ],
    }
