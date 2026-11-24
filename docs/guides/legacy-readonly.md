# 旧浏览器精简版（`/legacy/`）

> 代码在仓库根目录 `legacy/`（Django app，服务端模板直出）。本文描述它对外的行为与改动时必须守住的约束。

## 是什么

给不支持现代 JS / CSS 的浏览器（设计基线 IE8）留一个**只读**入口：首页、关于、新闻、活动、教程。

- 主站 SPA 在旧浏览器上会落到「请更换浏览器」提示页，提示下方新增「仍然进入精简版（只读，排版从简）」链接（`frontend/template.html`）；也可以直接访问 `/legacy/`。
- 不是第二套前端：不复制数据、不建缓存表、不写库、不碰账号。每个请求直接查主站同一个数据库，内容永远是活的。
- `/legacy` 少尾斜杠会 **301** 到 `/legacy/`（少了这条会掉进 SPA 兜底变成白屏）；`/legacy/` 下未匹配的路径回 legacy 自己的中文 404 页。
- 只接受 `GET` / `HEAD`，其余方法 405；浏览器直接 POST 还会先被 CSRF 中间件挡成 403。
- 站点维护模式（`run/MAINTENANCE`）期间与其他路径一样回 503。

## 页面

| 路径 | 内容 |
|---|---|
| `/legacy/` | 首页：站点简介 + 最新新闻 / 活动 |
| `/legacy/about/` | 关于页五个区块；全景块以文字说明代替（WebGL 在旧浏览器无解） |
| `/legacy/news/` · `/legacy/news/<id>/` | 新闻列表（搜索 `?q=`、分页 `?page=`）与详情 |
| `/legacy/activities/` · `/legacy/activities/<id>/` | 活动列表（`?type=deliberation|exhibition|survey`）与详情（展示选项与作品，不提供投票 / 投稿） |
| `/legacy/tutorials/` · `/legacy/tutorials/<id>/` | 教程列表与详情（文档下载走同源链接，不做内嵌预览） |

## 硬约束（改这个 app 前先读）

1. **只读、无状态**：不读 session、不写 Cookie、不写任何表。`MultiDeviceSessionMiddleware`、`PasswordChangeRequiredMiddleware`、`ValidityEnforcementMiddleware` 对 `/legacy/` 前缀整段豁免；响应不带 `Set-Cookie`，`Vary` 里也不出现 Cookie / User-Agent——否则共享缓存无法命中。
2. **可见性不自己发明**：一律复用 `reviews.visibility.public_q()`。活动另加 `audience="public"` 与类型白名单（`deliberation` / `exhibition` / `survey`）——**征集（collection）匿名永远不出现**。自己抄一份过滤条件，迟早把草稿 / 待审 / 仅成员内容漏给游客。
3. **不用前端那套东西**：零 `<script>`、无 CSS 变量 / flex / grid / 圆角 / 阴影 / 双冒号伪元素；HTML 4.01 Transitional、全 px。样式集中在 `static/legacy/legacy.css`。
4. **富文本走 `legacy/sanitize.py`**：不要换成主站的 `common.rich_text.sanitize_html()`——那个白名单放行 iframe / video / style，旧浏览器用不上还扩大攻击面。`style` / `script` / `iframe` / `object` / `embed` / `video` / `audio` / `canvas` / `svg` / `noscript` 整块删除；外链图片替换为「未自动加载 + 新窗口打开」的占位块，服务端不代理图片。
5. **响应头固定**：CSP `default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`，外加 `X-Robots-Tag: noindex, nofollow`、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`、`Cache-Control: public, max-age=60`。
6. **限流**：所有页面先过 `common.throttles.PublicReadThrottle`，与 `/about/`、`/panorama/` **共用同一份按 IP 的读额度**（300 次/分）；超出回 legacy 自己的 429 提示页并带 `Retry-After`。

## 样式与缓存

- CSS 链接带内容指纹 `?v=<md5 前 8 位>`，由 `legacy/views.py:_asset_version()` 在进程启动时算一次。nginx 对 `/static/` 下非哈希文件给 7 天缓存，所以**改 CSS 要重启进程**（发版天然满足）才会换指纹；本地 `runserver` 也会缓存编译后的模板，看不到变化先重启。
- 手机窄屏适配只写在 CSS 末尾的 `@media only screen and (...)` 里。`only` 不能省：不认识媒体查询的旧浏览器会把整块丢掉，桌面 IE8 的渲染因此完全不受影响。这部分是**实验性**的，没有真机矩阵，别写成「已验证支持手机」。

## 测试与新增页面

```bash
uv run python manage.py test legacy
```

新增一个页面四步：

1. `legacy/queries.py` 加查询（复用 `public_*()` 的过滤链，别新写 `filter()`）。
2. `legacy/views.py` 加视图：`@readonly`（限流）+ `@require_http_methods(["GET", "HEAD"])` + `_render()`（用 `render_to_string`，不要用 `render(request, ...)`——后者会跑 context processors，可能给访客种下 session）。
3. 模板 `legacy/templates/legacy/<name>.html` + `legacy/urls.py` 加一行；导航在 `base.html`。
4. `legacy/tests.py` 至少三条：公开内容出现 / 非公开内容不出现 / 响应头与无 Cookie。

`legacy` app 没有模型与迁移，注册只需 `INSTALLED_APPS` 加 `legacy` 与 `config/urls.py` 挂载；它不能漏进 SPA catch-all 的排除清单。仓库内的实现笔记见 [legacy/README.md](https://github.com/nhyzcms/club-management-website/blob/main/legacy/README.md)。
