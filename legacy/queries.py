"""只读查询层。

legacy 不复制数据、不建缓存表：每个请求都直接查主站同一个数据库，
并把「什么算公开」交给主站同一段代码判定（reviews.visibility.public_q）。
结构层（模板 / CSS / 路由）才需要发版，内容层永远是活的。
"""

from news.models import News
from reviews.visibility import public_q

# 保守分页：旧浏览器一次请求过多条目容易超时，也给数据库留余量。
NEWS_PAGE_SIZE = 20


def public_news():
    """主站公开新闻：已发布 且 审核已通过（与 news/views.py 的匿名口径一致）。"""
    return (
        News.objects.filter(is_published=True)
        .filter(public_q("news"))
        .order_by("-published_at", "-created_at")
    )


def latest_news(limit=5):
    return list(public_news()[:limit])
