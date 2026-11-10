from common.targets import target_of
from reviews.models import Review


def approve_news(news):
    """测试辅助：给已有新闻补一条「通过」审核，使其公开可见。"""
    Review.objects.update_or_create(
        target=target_of(news),
        defaults={"status": Review.STATUS_APPROVED},
    )
    return news


def approve_activity(activity):
    """测试辅助：给已有活动补一条「通过」审核，使其对成员公开可见。"""
    Review.objects.update_or_create(
        target=target_of(activity),
        defaults={"status": Review.STATUS_APPROVED},
    )
    return activity


def approve_tutorial(tutorial):
    """测试辅助：给已有教程补一条「通过」审核，使其在公共库可见。"""
    Review.objects.update_or_create(
        target=target_of(tutorial),
        defaults={"status": Review.STATUS_APPROVED},
    )
    return tutorial
