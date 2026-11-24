# legacy — 旧浏览器只读版

服务端直出的纯 HTML 页面（`/legacy/`），给不支持现代 JS/CSS 的浏览器（设计基线 IE8）看
"新闻 / 活动 / 教程 / 关于"。不是第二套前端，**不复制数据、不写库、不碰账号**。

## 红线（改这个 app 前先读）

1. **只读**：视图只接 `GET`/`HEAD`，不读 session、不写 Cookie、不写任何表。
   新增视图必须套 `@readonly`（限流）+ `@require_http_methods(["GET", "HEAD"])`。
2. **可见性不自己发明**：一律复用 `reviews.visibility.public_q()`，
   活动再加 `audience="public"` 与类型白名单（征集不出现）。
   抄别的条件 = 迟早把草稿/待审/仅成员内容漏给游客。
3. **不用前端那套东西**：零 `<script>`，CSS 不用变量 / flex / grid / 圆角 / 阴影 /
   双冒号伪元素，HTML 4.01 Transitional，全 px。改样式先看 `static/legacy/legacy.css` 头注释。
4. **富文本走 `legacy/sanitize.py`**，不要用 `common/rich_text.sanitize_html()`
   （那个白名单放行 iframe/video/style，旧浏览器用不上还扩大攻击面）。
5. **图片按四种情况处理**（见 `legacy/sanitize.py`）：同源（含写成
   `http://<本站>/media/…` 的绝对地址，会改写成路径）原样内嵌；跨域换成
   "未自动加载 + 新窗口打开"的占位块，服务端不代理；同源但 IE 全系解不了的
   格式（WebP/AVIF）包成 `<picture><source type=…><img 兜底>` —— 能解的浏览器
   看原图，解不了的看 `/legacy/img/<token>.jpg` 兜底（见 `legacy/images.py`），
   **不要一刀切成文字说明**，那会把现代浏览器也一起降级；连兜底都转不了的
   （SVG/HEIC）才换成文字说明。
   封面/展品/教程封面同样走 `queries.image_box()`，判断口径只有这一份。
6. **兜底图是缓存文件，不是站点数据**：存在 `CLUB_DATA_DIR/legacy-cache/`，
   token 带源图 mtime+size，源图换了 URL 就换；别把它挪进 MEDIA_ROOT 当内容发。

## 2026-11 安全审计后的约定

审计报告打的是线上 1.2.1。下面每一条都配了回归测试，改这些代码前先看测试名。

1. **`<img>` 必须按属性解析，不能按正则改字符串**（`sanitize.py`）。
   旧实现用 `<img[^>]*>` 切出整段、再用第一个 `src=` 拼回去：属性值里出现
   `src=`（例如 title/alt 里）就会提前闭合属性，`onerror` 变成真事件属性 ——
   存进正文即可对全部匿名访客触发（CSP 在 IE9/10/11 也不强制 `script-src`，而
   legacy 的读者正是这批浏览器）。现在用 `html.parser.HTMLParser` 取属性，
   只替换 `<img>` 自己那一段字节，属性值一律转义后重写。
2. **写回地址前先验原始值**（`_unsafe_url` / `_safe_path`）：反斜杠、制表符/回车、
   `//host` 这几种在浏览器里都会被解释成「去别的站取图」，只看 `urlsplit` 的
   netloc 会漏。任何含控制字符、引号、尖括号或反斜杠的地址一律不给链接。
3. **搜索词里的控制字符直接 400**：线上 PG 的文本字段不收 NUL，`?q=%00`
   会在 `ILIKE` 处抛 `ValueError` → 匿名 500。视图层先拒（`_CONTROL_CHARS`），
   别指望数据库兜。
4. **缓存头按状态给**：只有 200/404 用 `public, max-age=60`；429/400 是
   「本次请求」的结果，必须 `no-store`，否则限流页会被缓存分发给别的访客。
   兜底图端点（`/legacy/img/<token>.jpg`）单独计额度（`LegacyImageThrottle`，
   1200/min）：一页十几张图，跟页面共用 300/min 会把正常浏览打成 429，
   但也不能完全不限流（那是无上限的磁盘读 + 首次同步转码入口）。

5. **清洗是纯 CPU，正文必须有上限、结果必须复用**（`sanitize.py`）。
   2026-11 二审（artex 复测）指出：含表格/列表的真实排版清洗耗时超线性
   （256KB 0.5s、512KB 1.8s、1MB 8s），而每个请求都要重跑一遍 bleach + 属性改写；
   仓库默认单 worker 且 ASGI 下同步视图串行，一篇长稿被几个读者同时打开就能顶死整站。
   现在入口先按 `MAX_HTML_CHARS = 256KB` 在标签边界截断（末尾补
   `.legacy-truncated` 说明），4KB 以上的结果按「正文 + 本站主机名」的哈希
   存进 Django cache（7 天）。**改清洗逻辑时把 `CACHE_TAG` 一起改**，否则旧结果还会被命中。
   生产用 Redis 时给 `maxmemory-policy` 设 `allkeys-lru`：缓存键是正文哈希，理论上
   有发稿权的人可以塞很多长文把内存顶起来，TTL + LRU 是兜底。
6. **清洗前的整块删除要线性扫描**（`_strip_blocks` / `_strip_comments`）。
   原来的 `<(script|style|…).*?</\1>` 正则遇到成堆未闭合的开始标签是
   O(N × 文长)（275KB 实测 21 秒）。现在找开始标签 → 找对应结束标签，一次扫完。
   写入侧 bleach 本来就会把 `<script` 转义，这道闸是防历史脏数据与其它写入路径。
7. **兜底图先看像素再看字节**（`legacy/images.py`）。`MAX_SOURCE_BYTES` 只挡体积：
   12000×12000 的 WebP 只有几百 KB，解码要 ~2.3GB（实测），而转码发生在请求线程。
   现在 `MAX_PIXELS = 40MP`（与 `news.thumbnails.MAX_COVER_PIXELS` 对齐），
   `Image.open()` 之后、`load()` 之前就判掉。临时文件用 `tempfile.mkstemp`
   生成唯一名字：多 worker 会对同一张源图同时首次转码，固定 `<token>.tmp` 会互相覆写。

## IE8 兼容性核对（2026-11，按官方文档逐项对过）

基线不是"看着能跑"：下面每行都有出处，改样式/模板前对照着看。出处只有两份——
微软官方的 CSS 兼容表（MSDN *CSS Compatibility and Internet Explorer*，`cc351024`，
IE8 时代原文，现站已下架，存档：
`https://web.archive.org/web/20120101000000id_/http://msdn.microsoft.com/en-us/library/cc351024(v=vs.85).aspx`）
和 caniuse 的 `css-sel3` / `css-mediaqueries` / `html5semantic` / `picture` 数据集。

| 我们用到的 | IE8 | 依据 | 本仓库的处理 |
| --- | --- | --- | --- |
| CSS 2.1 全部（float / inline-block / position / line-height / 表格 / `zoom:1`） | 支持 | 官方表开头：IE8 "fully compliant with the CSS 2.1 specification" | 样式基本只用这一层 |
| `display: inline-block` | 支持 | 官方表 `display` 行：IE8 = Yes（IE7 及以下 Partial） | 分页、徽标、chip 都用它 |
| `min/max-width`、`min/max-height`、`overflow-x` | 支持 | 官方表：IE7 起 Yes | 图片缩放全靠 `max-width/max-height + width/height:auto`（没有 `object-fit`） |
| `inherit` 关键字 | 支持（IE8 起） | 官方表：IE5–7 = No，IE8 = Yes | `.btn-mini` 的 `font-family: inherit` |
| 媒体查询 `@media screen and (max-width:…)` | **不支持** | 官方表 "Media Queries … supported in Internet Explorer 9"；caniuse `css-mediaqueries` IF8 = partial | 窄屏样式写在文件末尾两个 `@media only screen and (…)` 里，带 `only` 让 IE8 整块丢弃 |
| `:last-child` / `:nth-child` / `:not()` 等 CSS3 选择器 | **不支持** | 官方表：IE5–8 全 No，IE9 起 Yes；caniuse `css-sel3`：IE7/8 只有 `~` 和 `[attr^=]` 系 | 列表末项一律有 `.last` 兜底类；**兜底类不能和 `:last-child` 写在同一个选择器列表里**——IE8 遇到不合法选择器会丢弃整条规则，`.last` 会跟着失效（`legacy.css` 里已拆成两条） |
| `border-radius` / `box-shadow` / `text-shadow` / `opacity` / `rgba()` / `transform` / flex / grid / `rem` / `calc` / `::before` | 不支持 | 官方表对应行 IE8 = No（CSS3 部分才支持） | 一条都没用；圆角/阴影一律用边框和底色代替 |
| `<picture>` + `<source srcset>` | **全系 IE 不支持** | caniuse `picture`：IE6–11 全部 `n`；caniuse `html5semantic`：IE8 把新元素当 unknown element（partial，缺默认样式） | 只当"能解的浏览器多拿一张原图"的渐进增强：IE8 把 `picture`/`source` 当未知元素、忽略 `srcset`，内层 `<img>` 照常显示 → 图的兜底必须永远写在 `<img src>` 上 |
| `<figure>` / `<figcaption>` | 未知元素，无默认 display | caniuse `html5semantic` note：partial 指缺默认样式，"manually setting the default `display` value" 即可 | `.prose figure`/`.prose figcaption` 显式写 `display: block`，否则图注会并到图片右边 |
| `placeholder` / `required` / `type=search` 等 HTML5 表单 | 不支持 | caniuse `forms` | 一个没用；搜索框靠 `.search-input` 的 `padding` |
| 文档模式 | — | IE8 按 doctype 选模式 | `base.html` 用 HTML 4.01 Transitional **带 system identifier**（进标准模式），另加 `X-UA-Compatible: IE=edge`（在 IE8 上等价于 IE8 标准模式） |

结论：`/legacy/` 在 IE8 上是"CSS 2.1 + 未知元素降级"，不会白屏，也不用 polyfill；
真正的红线只有两条 —— **别用 CSS3 选择器兜底列表**、**别把图片的兜底从 `<img>` 挪走**。

## 新增一个页面（4 步）

1. `legacy/queries.py` 加查询（复用 `public_*()` 的过滤链，别新写 `filter()`）。
2. `legacy/views.py` 加视图（`@readonly` + `@require_http_methods` + `_render()`）。
3. `legacy/templates/legacy/<name>.html` + `legacy/urls.py` 加一行；导航在 `base.html`。
4. `legacy/tests.py` 至少三条：公开内容出现 / 非公开内容不出现 / 响应头与无 Cookie。

## 自测

```
SECRET_KEY=dev DJANGO_DEBUG=1 python manage.py test legacy
```

页面之外的验证（真机/生产形态）看仓库根目录的 `legacy-精简版-PR说明.md`。

## 常见坑

- **改了模板看不到变化**：本地 `runserver` 会缓存编译后的模板，重启服务再试。
- **`/legacy` 少了尾斜杠**：`config/urls.py` 里有一条显式 301；删了它就会掉进 SPA 兜底变白屏。
- **CSS 改了没生效**：链接带内容指纹 `?v=<md5 前 8 位>`（nginx 对 `/static/` 给 7 天缓存）；
  指纹由 `views._asset_version()` 在进程启动时算一次 —— 改了 CSS 要**重启进程**才换指纹（发版天然满足）。
- **`/legacy` 这一跳也要算只读路径**：`accounts/middleware.py` 的
  `is_legacy_readonly_path()` 同时认 `/legacy` 与 `/legacy/**`；只写前缀会让 301
  响应带上设备 Cookie 与 `Vary: Cookie`，共享缓存再也命中不了这一跳。
- **`/legacy/` 下任何没匹配上的路径**：走 `urls.py` 末尾的兜底路由，回 legacy 自己的中文 404 页。
- **改了 WebP 处理逻辑后现代浏览器也看不到图**：说明兜底被写成了唯一路径。检查模板是否
  还在用 `<picture>`、`cover_mime` 是否为空（空 `type` 会让浏览器跳过 `<source>`）。
- **图片被压扁**：容器给了固定高度时，图片只能用 `width/height:auto + max-width/max-height`
  （IE8 没有 `object-fit`，同时写死宽高必然变形），垂直居中靠容器的 `line-height` + `vertical-align:middle`。
- **把站内图判成外链**：`_own_hosts()` 决定哪些主机名算自己（请求 Host / ALLOWED_HOSTS /
  FRONTEND_URL）；换域名或改用 IP 访问时，新主机名要能被这三处之一覆盖，否则正文里的绝对地址会被拦。
- **手机窄屏样式**：只写在 `legacy.css` 末尾的 `@media only screen and (...)` 里。必须带 `only`：
  不认识媒体查询的老浏览器会把整块丢掉，桌面 IE8 的渲染因此完全不受影响（`MobileLayoutTest` 守着这条）。
  窄屏适配是实验性的，没有真机矩阵，别把它当"已验证支持手机"。
