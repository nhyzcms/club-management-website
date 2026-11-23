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
5. **外链图片不自动加载**：清洗时换成"未自动加载 + 新窗口打开"的占位块；服务端不代理图片。

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
- **`/legacy/` 下任何没匹配上的路径**：走 `urls.py` 末尾的兜底路由，回 legacy 自己的中文 404 页。
