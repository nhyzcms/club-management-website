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

1. **只读、无状态**：不读 session、不写 Cookie、不写任何表。`MultiDeviceSessionMiddleware`、`PasswordChangeRequiredMiddleware`、`ValidityEnforcementMiddleware` 对 `/legacy` 与 `/legacy/**` 整段豁免（`accounts/middleware.py:is_legacy_readonly_path()`）；响应不带 `Set-Cookie`，`Vary` 里也不出现 Cookie / User-Agent——否则共享缓存无法命中。**无尾斜杠的 `/legacy` 也算只读路径**：漏掉这一跳，301 响应会带上设备 Cookie 与 `Vary: Cookie`，共享缓存从此命中不了首页入口。
2. **可见性不自己发明**：一律复用 `reviews.visibility.public_q()`。活动另加 `audience="public"` 与类型白名单（`deliberation` / `exhibition` / `survey`）——**征集（collection）匿名永远不出现**。自己抄一份过滤条件，迟早把草稿 / 待审 / 仅成员内容漏给游客。
3. **不用前端那套东西**：零 `<script>`、无 CSS 变量 / flex / grid / 圆角 / 阴影 / 双冒号伪元素；HTML 4.01 Transitional、全 px。样式集中在 `static/legacy/legacy.css`。
4. **富文本走 `legacy/sanitize.py`**：不要换成主站的 `common.rich_text.sanitize_html()`——那个白名单放行 iframe / video / style，旧浏览器用不上还扩大攻击面。`style` / `script` / `iframe` / `object` / `embed` / `video` / `audio` / `canvas` / `svg` / `noscript` 整块删除。图片按四种情况处理（富文本正文见 `legacy/sanitize.py`；封面 / 展品 / 教程封面同样走 `legacy/queries.py:image_box()`，判断口径只有这一份）：
   - 同源（相对路径，或主机名属于 `_own_hosts()` 的绝对地址）→ 原样内嵌，绝对地址归一成路径，老浏览器少做一次 DNS / 连接；
   - 跨域 → 「未自动加载 + 新窗口打开」的占位块，服务端不代理，也不泄露访客 IP；
   - 同源 WebP / AVIF → `<picture><source>` + `/legacy/img/<token>.jpg` JPEG 兜底：现代浏览器看原图，IE 全系落到兜底图（`legacy/images.py`）；
   - 同源 SVG / HEIC 等连兜底都转不了的格式 → 文字说明，不输出破图标。
5. **响应头固定**：CSP `default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`，外加 `X-Robots-Tag: noindex, nofollow`、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`。`Cache-Control` **按状态给**：200 / 404 是 `public, max-age=60`；**400 / 429 必须 `no-store`**——否则限流页 / 错误页会被缓存分发给别的访客。兜底图端点单独设头：200 是 `public, max-age=604800`（7 天），404 是 `no-store` + `noindex`。
6. **限流分两条额度**：所有页面先过 `common.throttles.PublicReadThrottle`，与 `/about/`、`/panorama/` **共用同一份按 IP 的读额度**（300 次/分）；超出回 legacy 自己的 429 提示页并带 `Retry-After`。兜底图按 `LegacyImageThrottle` 独立计额度（1200 次/分）——一页可能十几张图，与页面共用 300 次/分会把正常浏览打成 429；但也不能不限（那是无上限的磁盘读 + 首次同步转码入口）。

## 2026-11 安全加固（改代码前先读）

线上 v1.2.1 经过两轮审计；下面的约定改动前先对照 `legacy/tests.py` 里的回归测试。

1. **`<img>` 必须按属性解析，不能按正则改字符串**：`legacy/sanitize.py` 用标准库 `html.parser` 取属性、只替换 `<img>` 自己的字节。旧实现用正则截整段再拼 `src`，属性值里出现 `src=` 会提前闭合属性，把 `onerror` 变成真事件属性——存进正文即可对匿名访客触发存储型 XSS。
2. **写回地址前先验原始值**（`_unsafe_url` / `_safe_path`）：反斜杠、控制字符、`//host`、userinfo、同源双斜杠一律不给链接，降级为占位块。只看 `urlsplit().netloc` 挡不住这些。
3. **搜索词含控制字符直接 400**：线上 PG 的文本字段不收 NUL，`?q=%00` 会在 `ILIKE` 处抛 `ValueError` → 匿名 500；视图层先拒，别指望数据库兜。
4. **正文清洗有 CPU 上限、结果复用**：入口按 `MAX_HTML_CHARS`（256KB）在标签边界截断并补一行说明；4KB 以上的结果按「正文 + 本站主机名」哈希缓存 7 天。**改清洗逻辑时把 `CACHE_TAG` 一起改**，否则旧结果还会被命中。整块删除（script / style / …）是线性扫描，不是可能超线性的正则。
5. **兜底图先判像素再解码**：`MAX_PIXELS`（40MP）在 `Image.open()` 之后、`load()` 之前判掉——12000×12000 的 WebP 只有几百 KB，解码却要 GB 级内存，而转码发生在请求线程；`MAX_SOURCE_BYTES`（24MB）只挡体积。临时文件用 `tempfile.mkstemp` 唯一名，多 worker 并发转码不会互相覆写。

缓存文件在 `CLUB_DATA_DIR/legacy-cache/`：token 含源图 mtime + size（源图换了 URL 就换），目录超过 400 张按最旧清理。**它是可重建缓存，不是站点数据**——别挪进 `MEDIA_ROOT` 当内容发；生产用 Redis 时给缓存后端设 `allkeys-lru`，避免正文缓存把内存顶死。

## IE8 兼容性基线

- 服务端**不按 UA 分流**：IE8 与现代浏览器拿到同一份字节；兼容靠「CSS 2.1 + 未知元素降级」，不用 polyfill。
- 媒体查询只写在 `legacy.css` 末尾，且必须带 `only`（`@media only screen and (...)`）——IE8 不认识媒体查询，会把整块丢弃，桌面渲染因此不受影响。
- 列表末项用 `.last` 兜底类，且**不能与 `:last-child` 写在同一个选择器列表**：IE8 遇到不认识的选择器会丢弃整条规则，兜底类会一起失效（`legacy.css` 里已拆成两条）。
- `<picture>` 只是渐进增强：图片的兜底必须永远写在 `<img src>` 上（IE8 把 `picture` / `source` 当未知元素、忽略 `srcset`）。
- `<figure>` / `<figcaption>` 必须显式 `display: block`，否则图注会并到图片右边。

完整逐项核对表（含微软 CSS 兼容文档与 caniuse 出处）在仓库 `legacy/README.md` 的「IE8 兼容性核对」一节。

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
