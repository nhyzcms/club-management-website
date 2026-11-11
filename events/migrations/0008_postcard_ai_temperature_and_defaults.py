"""明信片 AI 配置：新增「温度」+ 黑名单/前置提示词换新默认值。

数据迁移按管理员口径 **全部覆盖**：已存配置的 ``ip_blacklist`` 与
``prompt_prefix`` 一律改写为新的默认值（旧默认清单是早期摘录，名单与口径
都已更新，留旧值等于线上还在用过期清单）。
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models

NEW_BLACKLIST = [
    "东京残响", "blood-c", "学园默示录", "死亡代理人", "寄生兽", "骷髅人",
    "another（替身）", "地狱刑警", "爆炸头武士", "东京食尸鬼第二季",
    "刀剑神域第二季", "东京ESP", "东京暗鸦", "鬼泣", "记忆女神的女儿们",
    "新妹魔王的契约者", "进击的巨人", "尸体派对", "噬血狂袭", "死亡笔记",
    "亡灵幻境（死囚乐园）", "约会大作战第二季", "心理测量者", "女恶魔人",
    "日在校园(school days)", "妖精狩猎者", "妖精的旋律", "high school（恶魔高校）",
    "百花缭乱 武士少女", "美少女死神 还我H之魂！", "女生万岁第二季",
    "我的狐仙女友", "无赖勇者的鬼畜美学", "樱通信", "暗杀教室", "黑执事3",
    "大剑", "吸血鬼同盟",
]

NEW_PROMPT_PREFIX = (
    "你是明信片审核员。你应当将用户上传的明信片与已有模板和参与表相对比，"
    "确保用户书写的格式正确，寄达校存在于参与校名单中。"
    "如不符合要求，应当简明扼要地告知用户"
)


def overwrite_defaults(apps, schema_editor):
    """全部覆盖：黑名单与前置提示词都换成新默认值。"""
    cfg_model = apps.get_model("events", "PostcardAIConfig")
    cfg_model.objects.update(ip_blacklist=list(NEW_BLACKLIST), prompt_prefix=NEW_PROMPT_PREFIX)


def noop(apps, schema_editor):
    """回滚不还原旧值（旧清单已过期，回退只会让线上用回错名单）。"""


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0007_postcard_ai_prompt_prefix"),
    ]

    operations = [
        migrations.AddField(
            model_name="postcardaiconfig",
            name="temperature",
            field=models.DecimalField(
                decimal_places=1,
                default=Decimal("0.0"),
                max_digits=3,
                validators=[
                    MinValueValidator(Decimal("0")),
                    MaxValueValidator(Decimal("2")),
                ],
                verbose_name="温度",
            ),
        ),
        migrations.AlterField(
            model_name="postcardaiconfig",
            name="prompt_prefix",
            field=models.TextField(
                blank=True, default=NEW_PROMPT_PREFIX, verbose_name="前置提示词"
            ),
        ),
        migrations.RunPython(overwrite_defaults, noop),
    ]
