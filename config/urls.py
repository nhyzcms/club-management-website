"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os
import re
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import path, include, re_path
from django.views.decorators.cache import never_cache
from django.views.generic import RedirectView, TemplateView
from django.views.static import serve

from common.views import ChangelogView, SitePolicyView, VersionView, healthz

#: 站内一级路由（HashRouter 里 `#` 后的第一段）。
#:
#: 服务端的职责只是「把干净链接翻译成 hash 链接」：`/news/123` → `/#/news/123`。
#: 只有这些前缀会被翻译，其余未知路径仍然是 404——不恢复 catch-all，
#: 否则拼错的 URL 又会变成 200 + 首页（软 404）。
#: 新增站内一级页面时，这里和 `frontend/src/App.tsx` 的 Route 一起加。
SPA_PATH_PREFIXES = frozenset({
    "forgot-password",
    "change-password-required",
    "reset-password",
    "register",
    "verify-email",
    "verify-email-pending",
    "v",
    "verify",
    "security",
    "profile",
    "u",
    "tasks",
    "messages",
    "notifications",
    "announcements",
    "activity",
    "inbox",
    "feedback",
    "news",
    "reviews",
    "about",
    "panorama",
    "exam",
    "postcard",
    "schedule",
    "tutorials",
    "join",
    "m",
})


def spa_deep_link(request, path):
    """把干净链接 302 到 HashRouter 的等价地址（query 原样保留）。

    `/news/123?from=share` → `/#/news/123?from=share`
    路由层已经用白名单正则限定了前缀，不会接住 `/admin` 这类路径——它们仍走
    Django 的 APPEND_SLASH / 404，不受深链接翻译影响。
    """
    clean = path.rstrip("/")
    target = "/#/" + clean
    query = request.META.get("QUERY_STRING", "")
    if query:
        target += "?" + query
    return HttpResponseRedirect(target)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', healthz, name='healthz'),
    path('site-policy/', SitePolicyView.as_view(), name='site-policy'),
    path('version/', VersionView.as_view(), name='version'),
    path('changelog/', ChangelogView.as_view(), name='changelog'),
    path('auth/', include('accounts.urls')),
    path('tasks/', include('tasks.urls')),
    path('messaging/', include('messaging.urls')),
    path('activities/', include('activities.urls')),
    path('events/', include('events.urls')),
    path('exam_board/', include('exam_board.urls')),
    path('news/', include('news.urls')),
    path('reviews/', include('reviews.urls')),
    path('about/', include('about.urls')),
    path('panorama/', include('panorama.urls')),
    path('announcements/', include('announcements.urls')),
    path('tutorials/', include('tutorials.urls')),
    path('recruitment/', include('recruitment.urls')),
    path('attachments/', include('attachments.urls')),
    path('uploads/', include('attachments.tus_urls')),
    re_path(r'^file/(?P<path>.*)$', serve, {'document_root': os.path.join(settings.BASE_DIR, 'media', 'file')}),

    # 旧浏览器只读版：服务端直出的纯 HTML（无 JS、无 CSS 变量），不经过 SPA。
    # 必须排在下面两条 SPA 入口之前，否则 /legacy/ 会被兜底路由吃掉。
    path('legacy/', include('legacy.urls')),
    # 少了斜杠也必须到得了：否则 /legacy 会落进下面的 SPA 兜底，
    # 旧浏览器看到的又是白屏——正是本功能要解决的问题本身。
    path('legacy', RedirectView.as_view(pattern_name='legacy:home', permanent=True)),
    
    # SPA 入口：**只有这四个路径**是网站入口，其余一律交给 Django 的 404。
    #
    # 这里曾经有一条 catch-all（任何未匹配路径都返回 index.html）。对 HashRouter
    # 的 SPA 来说它没有带来任何东西——所有站内路由都在 `#` 之后，服务端看到的
    # 永远只有 `/`——却把所有拼错的 URL、失效的外链、探测请求全变成
    # 「200 + 首页」（软 404）。监控与搜索引擎会把它当成真实存在的页面。
    # SPA 入口**必须**不可缓存：L0 热更新（网站改完重开 App 就生效）全靠这一步。
    # index.html 只有 2.5 KB，而它引用的静态资源文件名带 contenthash，
    # 一旦 HTML 被 WebView 缓存，就会拿着旧哈希去请求已被删除的 chunk → 白屏。
    path('', never_cache(TemplateView.as_view(template_name='index.html')), name='home'),
    # 旧入口：书签 / 部署平台探活常打这两个路径，统一 302 回 `/`。
    # 用 302 而不是 301：/index.html 是历史产物，不该被浏览器永久缓存成重定向。
    path('index', RedirectView.as_view(pattern_name='home', permanent=False, query_string=True)),
    path('index.html', RedirectView.as_view(pattern_name='home', permanent=False, query_string=True)),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 深链接翻译必须排在 static()/media() 之后：否则 `/static/...` 会先撞到这里，
# 被当成「未知路径」404，DEBUG 下连页面都加载不出来。
# 正则只匹配白名单前缀——`/admin` 这类路径不匹配，仍能走 APPEND_SLASH。
_SPA_PREFIX_PATTERN = "|".join(re.escape(p) for p in sorted(SPA_PATH_PREFIXES))
urlpatterns += [
    re_path(rf"^(?P<path>(?:{_SPA_PREFIX_PATTERN})(?:/.*)?)$", spa_deep_link),
]
 
