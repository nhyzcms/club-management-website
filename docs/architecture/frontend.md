# 前端架构

> 后端架构见 [架构总览](overview.md)；构建与运行见 [快速开始](../getting-started.md)。

`frontend/` 是本项目的全部前端代码：一个 React 19 单页应用（SPA），由 Webpack 打包、产物交给 Django 直接服务。应用内所有 URL 均为 **hash 路由**（`/#/route`），Django 侧对非后端路径统一返回 `index.html`，进入应用后的路由由前端接管。

## 技术栈

| 层 | 选型 | 说明 |
|---|------|------|
| UI 框架 | React 19.2 + react-dom 19.2 | 函数组件 + Hooks；无 Redux/MobX 等状态库，状态靠组件本地 state、Context 与模块级单例 |
| 语言 | TypeScript 6（`strict: true`） | ts-loader 经 webpack 编译，`target ES2020` |
| 路由 | react-router-dom 7（`HashRouter`） | 全部路由集中在 `src/App.tsx` |
| 构建 | Webpack 5 + ts-loader + css-loader/style-loader | 入口 `src/index.tsx`，产物 `frontend/dist/` |
| 样式 | 手写 CSS | 全站设计层 `src/styles/cobalt.css`（钴蓝校徽主题，token 来源 DESIGN.md）+ 组件/页面就近 CSS |
| 富文本 | Tiptap 3 | starter-kit、table、mention、image、link、code-block-lowlight、highlight、text-style、text-align、character-count、bubble/floating menu 等；自定义节点见 `components/rte/` |
| 问卷 | SurveyJS 3（survey-core / react-ui / creator-* / analytics） | 调研填写、问卷编辑器、答复与统计 |
| 其他依赖 | chart.js、frappe-gantt、docx-preview、mammoth、lowlight、tus-js-client、l2d | 见「静态资源与第三方库」 |
| 包管理 | npm（`package-lock.json`） | 后端为 uv，前端独立 |

运行形态：无 SSR、无服务端模板变量（唯一的模板层交互是 Django 渲染 `index.html` 下发 Cookie），环境差异全部通过相对路径 + `/static/`、`/media/` 前缀与 dev server 代理抹平。设计约定：页面组件默认套 `AppShell`（顶栏 + 用户菜单 + 页脚），社区视觉走 `.cs` 作用域与 `--brand-*` 等 token；不引入 UI 组件库。

## 构建与产物

`package.json` 脚本（`frontend/`）：

```bash
npm run dev     # node scripts/copy-surveyjs.js && webpack serve
npm run build   # webpack --mode production && copy-surveyjs && assert-live2d-dist && assert-surveyjs-dist
npm run copy-surveyjs
```

- **开发**：webpack-dev-server 监听 3000 端口，热更新，`historyApiFallback` 指向 `/static/index.html`；`webpack.config.js` 的 `devServer.proxy` 将 `/ws/messaging`、`/ws/exam-board`（WebSocket）与 `/auth`、`/tasks`、`/news`、`/messaging`、`/activities`、`/reviews`、`/about`、`/exam_board`、`/tutorials`、`/recruitment`、`/attachments`、`/uploads`、`/site-policy`、`/panorama`、`/media`、`/admin`（HTTP）全部代理到 `http://localhost:8000`。
- **构建**：webpack 输出 `frontend/dist/`，JS 文件名带 `contenthash`，`publicPath` 为 `/static/`（与 Django `STATIC_URL` 对齐）；`splitChunks` 分层拆包：首屏同步库合成 `vendor` chunk（**排除 `l2d`**，看板娘运行时单独成块）、异步页面共享的第三方库（≥2 个页面用到）抽成按需加载的独立 chunk（`defaultVendors` 关闭、`minSize` 20KB）；`CopyWebpackPlugin` 把 `vendor/live2d/` 整目录拷入 `dist/live2d`；`HtmlWebpackPlugin` 以 `template.html` 生成 `index.html`。

请求链路（两种模式）：

```
开发:  浏览器 → webpack-dev-server :3000（/static/* 由 dist 服务）
        ├── 前端 hash 路由      → index.html（模板直接返回，不经 Django）
        └── /auth、/tasks、/ws… → 代理 → Django :8000
生产:  浏览器 → Django（或前置 nginx）
        ├── /static/*         → dist 产物（collectstatic 后由静态服务托管）
        ├── /auth|/tasks|…    → DRF / Admin / Channels
        └── 其余所有路径      → TemplateView 渲染 dist/index.html
```

`frontend/dist/` 内容大致为：`index.html`、入口与懒加载的 `*.chunk.js`、`vendor.*.js`、`live2d/`（看板娘资源）、`surveyjs/`（admin 用未哈希 min 文件）、`favicon.ico`。该目录 gitignored，由 Django 的 `TEMPLATES["DIRS"]` 与 `STATICFILES_DIRS` 引用（目录缺失时安全跳过，保证全新 clone 跑测试不报静态文件警告）——细节见 `config/settings.py`。

**构建接缝校验**：`copy-surveyjs.js` 把 SurveyJS 未哈希 min 文件（survey-core、creator、analytics、chart.js、中文 i18n）同时拷入仓库根 `static/surveyjs/`（本地 runserver 供 Django admin 模板 `{% static 'surveyjs/...' %}` 引用）与 `frontend/dist/surveyjs/`（生产 collectstatic / 发布包）；随后 `assert-live2d-dist.js` 与 `assert-surveyjs-dist.js` 逐文件断言产物齐全并校验 `catalog.json`，缺一即构建失败。前端另有单元（Vitest）/ E2E（Playwright）测试（见「已知边界」）；升级 survey-* / Chart.js 后需重跑 `npm run copy-surveyjs`。

**CSRF 初始化**：应用启动时（`App.tsx` 的 `useEffect`）显式 `api.getCsrf()` 调 `GET /auth/csrf/` 拉一次 `csrftoken` Cookie，同时 `fetchSitePolicy()` 拉取站点策略。开发态 webpack 直接服务模板、不经 Django 渲染，无法依赖 `{% csrf_token %}` 下发，故走显式端点。

## 目录结构

```
frontend/
├── src/
│   ├── index.tsx          # 入口：挂载 <App />，引入 cobalt.css
│   ├── App.tsx            # HashRouter、全部路由、全局 Provider 装配
│   ├── embed.ts           # ?embed=1 判定（useEmbedMode）
│   ├── turnstile.ts       # Cloudflare Turnstile 按需加载与 useTurnstile
│   ├── pages/             # 路由页面（PascalCase，*Page.tsx）
│   │   ├── activity/      # 活动详情壳与面板：Collection/Exhibition/Deliberation/Survey
│   │   └── review/        # 审核预览组件（ReviewPreview）
│   ├── components/        # 跨页共享组件（布局、守卫、评论、消息、编辑器…）
│   │   ├── profile/       # 个人中心面板（资料/密码/会话/认证/权限/禁言…）
│   │   ├── security/      # 安全中心面板（设备 / 登录记录 / 地图 / 滚动密钥）
│   │   ├── mascot/        # 看板娘 host、惰性加载、气泡喊话
│   │   ├── rte/           # Tiptap 自定义原子节点（Video、Iframe）
│   │   └── feed/          # 首页社团动态卡片
│   ├── api/               # API 客户端（按后端前缀拆分）+ WebSocket 客户端
│   ├── types/             # 按域的类型定义（news/tasks/activities/messaging…）
│   ├── hooks/             # usePagedList（分页列表钩子）
│   ├── utils/             # device、deviceId、survey、surveyLocale、iframeEmbed、marzipano
│   ├── examBoard/         # 考试看板纯逻辑：prefs、audio、validate
│   └── styles/            # 共享样式：cobalt 主题 + 各域页面样式
├── scripts/               # copy-surveyjs / assert-* 构建钩子
├── e2e/                   # 浏览器 E2E 用例（Playwright；配置见 playwright.config.ts）
├── vendor/live2d/         # 看板娘静态资源（构建时拷贝，引用一律走 /static/live2d/）
├── template.html          # HtmlWebpackPlugin 模板
├── public/                # favicon.ico、wave-mark.svg
└── dist/                  # webpack 产物（gitignored，由 Django 服务）
```

`components/` 分组职责（不逐个穷举）：

- **布局与守卫**：`AppShell`（全站顶栏/移动抽屉/用户菜单/未认证提醒/横幅公告/回顶/页脚）、`UserMenu`（顶栏头像菜单：`个人中心 / 私信 / 通知 / 待办 / 任务 / 活动 / 反馈 / 审核队列` 按能力裁剪，**「后台管理」只在 `utils/roles.ts::canAccessAdmin(role.variant)` 为真时出现**，即 `admin` / `superadmin` 两种 `is_staff` 徽章）、`PageChrome`（AppShell 的 embed 变体）、`ProtectedRoute`、`SessionGuard`、`LoginModal` + `LoginModalProvider`、`SessionSupersedeModal`、`AnnouncementHost`（全站弹窗公告宿主：进入站点后拉 `/announcements/active/` 逐条弹，关闭即记已读）。
- **内容与互动**：`CommentSection`（评论树，含协管 UI）、`MessageThread`（私信/任务讨论线程）、`Avatar`、`ReportButton`、`AuthorReviewBanner`（作者视角审核状态横幅）、`Pagination`、`ArticleToc`（正文目录）、`ClubFeed` + `feed/FeedCards`（首页动态流）。
- **表单与编辑器**：`RichTextEditor`（Tiptap 封装）、`DocxPreview`、`UserSearchSelect`（用户搜索选择器）、`MentionField`（@ 提及）、`CommentThreadStatusField`（评论线程开关）、`PasswordInput`、`SurveyFill`。
- **视图部件**：`TaskGantt`（frappe-gantt 甘特）、`TaskTimeline`（任务时间线）。
- **看板娘**：`mascot/MascotHost`、`mascot/loadWidget`（懒加载 chunk）、`mascot/speak`（气泡喊话）。

页面级样式有两种归属：组件专属的与组件同目录（如 `components/AppShell.css`、`pages/TaskFormPage.css`），跨页复用的域样式集中放 `styles/`（`home/list/detail/news/comments/messages/profile/form/about/survey/panorama/announcement/mobile/exam-board.css`）。

## 样式与主题

全站视觉建立在 `styles/cobalt.css`（钴蓝校徽主题，token 取自设计文档 DESIGN.md）之上，文件内部分层：① Reset ② Tokens ③ 排版 ④ 布局 ⑤ 顶栏 ⑥ 组件 ⑦ 动效 ⑧ 响应式。

- **作用域**：所有业务内容挂在 `.cs` 之下（reset 也以 `.cs` 为前缀，避免污染 Django admin 等外站页面）；body 级样式与 `:focus-visible` 焦点环在文件顶部单独声明。
- **token**：颜色（`--brand-*`、`--ink-*`、`--bg/--fg`、状态色）、圆角、阴影、动效（`--ease`、`--dur-*`）等均为 CSS 变量；图表/画布类库颜色也回读 token（如 `TaskGantt` 用 `getComputedStyle` 读 `--brand-600`/`--warning` 生成甘特条配色），保证不脱离主题。
- **状态类**：`AppShell` 在 body 上切换 `is-authed`，cobalt 的 `.act-guest` / `.act-user` 由此控制登录前后两套界面显隐；考试看板另有 `exam-board-*` 系列类名（`examBoard/prefs.ts` 同步切换）。
- **字体**：Sora + Noto Sans SC，Google Fonts `@import` 引入，中文正文 15px / line-height 1.6。
- **域样式**：各域 CSS 与页面就近 import；移动版共享 `mobile.css` 并以 `m-` 前缀隔离。
- **写入习惯**：新域样式尽量用 `var(--token, 兜底值)` 写法（token 改名时不会整块“无样式”，深色模式下也不会突然不可读）。
- **深色模式**：全局主题系统（`theme.ts`）支持浅色 / 深色 / 跟随系统三态，偏好按设备存 localStorage（`cobalt:theme`）；解析结果写入 `<html data-theme>` 并同步 `color-scheme` 与页面 `<meta name="theme-color">`（地址栏配色），同时镜像到 Django admin 约定的 `theme` 键（`auto/light/dark`），使后台自动跟随。切换入口为顶栏 `ThemeToggle`（`AppShell`）；`template.html` 内联脚本在首屏前预应用主题、避免闪白；深色配色在 `styles/theme-dark.css`（覆盖 cobalt token）。App 壳内（`device.ts::isAppShell`）无存储偏好时默认「跟随系统」，并对旧版壳存下的「浅色」做一次性迁移；该逻辑在 `template.html` 与 `theme.ts` 各有一份，改动需两处同步。

## 路由与页面

全部在 `src/App.tsx` 声明（`HashRouter`）。所有页面组件一律 `React.lazy(() => import(...))` 懒加载，统一 `Suspense` 兜底（渲染「加载中...」）。「登录守卫」列 ✅ 表示路由元素外包 `ProtectedRoute`（未登录时打开登录弹窗并渲染空）。绝大多数页面经 `AppShell`（详情页经等价的 `PageChrome`，embed 模式下跳过全站外壳）包裹。

| 路径 | 页面（文件） | 登录守卫 | 说明 |
|------|--------------|:---:|------|
| `/` | `HomePage` |  | 首页；`HomeRoute` 对手机 UA 渲染 `<Navigate to="/m" replace />` |
| `/m` | `MobileHomePage` |  | 手机版首页 |
| `/m/news` | `MobileNewsPage` |  | 手机版新闻列表 |
| `/m/news/:id` | `MobileNewsDetailPage` |  | 手机版新闻详情 |
| `/m/activity` | `MobileActivityPage` |  | 手机版活动列表 |
| `/m/activity/:id` | `MobileActivityDetailPage` |  | 手机版活动详情（众议投票 / 调研作答 / 展示画廊） |
| `/m/tutorials` | `MobileTutorialsPage` |  | 手机版教程列表 |
| `/m/tutorials/:id` | `MobileTutorialDetailPage` |  | 手机版教程详情（视频 / 文档 / 收藏） |
| `/m/join` | `MobileJoinPage` |  | 手机版加入（公告 + 阅读确认） |
| `/m/join/form` | `MobileJoinFormPage` |  | 手机版加入问卷 |
| `/m/me` | `MobileMePage` |  | 手机版「我的」（工作 / 常用分组，含外观切换） |
| `/m/review` | `MobileReviewPage` | ✅ | 手机版审核台（身份 / 内容 / 意见反馈 / 举报案，权限按能力键派生） |
| `/m/inbox` | `MobileInboxPage` | ✅ | 手机版待办（需已认证） |
| `/m/notifications` | `MobileNotificationsPage` | ✅ | 手机版通知中心（「加载更多」分页） |
| `/m/tasks` | `MobileTaskListPage` | ✅ | 手机版任务列表（状态 / 优先级 / 搜索） |
| `/m/tasks/:id` | `MobileTaskDetailPage` | ✅ | 手机版任务详情（认领 / 验收 / 打回 / 附件 / 评论） |
| `/about` | `AboutPage` |  | 关于我们 |
| `/announcements/:id` | `AnnouncementPage` |  | 全站弹窗公告回看页（站内通知点入；按受众鉴权，无权限 404） |
| `/panorama` | `PanoramaPage` |  | 校园全景浏览（`?id=N` 选场景；Marzipano 多级层级图 + 首层常驻） |
| `/panorama/manage` | `PanoramaManagePage` | ✅ | 全景图管理（导入 / 编辑 / 重切 / 删除），需 `can_manage_panoramas` |
| `/news` | `NewsListPage` |  | 新闻列表 |
| `/news/new` | `NewsFormPage` | ✅ | 新建/编辑共用表单 |
| `/news/:id` | `NewsDetailPage` |  | 新闻详情（正文 + 评论 + 附件） |
| `/news/:id/edit` | `NewsFormPage` | ✅ | 编辑新闻 |
| `/activity` | `ActivityListPage` |  | 活动列表 |
| `/activity/new` | `ActivityFormPage` | ✅ | 新建/编辑共用表单 |
| `/activity/:id` | `ActivityDetailPage` |  | 活动详情（内部壳 `ActivityDetailShell`，按类型挂面板） |
| `/activity/:id/edit` | `ActivityFormPage` | ✅ | 编辑活动 |
| `/activity/:id/survey-edit` | `SurveyEditorPage` | ✅ | 问卷编辑（复用 `SurveyCreatorPage`） |
| `/activity/:id/survey-responses` | `SurveyResponsesPage` | ✅ | 答复列表 |
| `/activity/:id/survey-stats` | `SurveyStatsPage` | ✅ | 答复统计（survey-analytics 仪表盘） |
| `/tasks` | `TaskListPage` | ✅ | 任务列表（列表/时间线/甘特视图切换）；手机 UA 由 `MobileAware` 改道到对应 `/m` 页面 |
| `/tasks/new` | `TaskFormPage` | ✅ | 新建任务（独立布局，不含全站外壳） |
| `/tasks/:id` | `TaskDetailPage` | ✅ | 任务详情（动作按钮由 `available_actions` 驱动）；手机 UA 由 `MobileAware` 改道到对应 `/m` 页面 |
| `/tasks/:id/edit` | `TaskFormPage` | ✅ | 编辑任务 |
| `/messages` | `MessagePage` | ✅ | 私信（无选中会话） |
| `/messages/:id` | `MessagePage` | ✅ | 私信（指定会话） |
| `/notifications` | `NotificationsPage` | ✅ | 通知中心；手机 UA 由 `MobileAware` 改道到对应 `/m` 页面 |
| `/inbox` | `InboxPage` | ✅ | 「待办」聚合（任务/活动/私信等 kind 合并）；手机 UA 由 `MobileAware` 改道到对应 `/m` 页面 |
| `/feedback` | `FeedbackPage` |  | 意见反馈（匿名可提交） |
| `/feedback/:id` | `FeedbackDetailPage` | ✅ | 反馈详情与处理 |
| `/reviews` | `ReviewQueuePage` | ✅ | 审核队列（内容/身份/反馈/举报分栏）；手机 UA 由 `MobileAware` 改道到对应 `/m` 页面 |
| `/exam` | `ExamBoardPage` |  | 考试看板（访客可看，独立全屏布局） |
| `/schedule` | `SchedulePage` |  | 课表下载 |
| `/tutorials` | `TutorialListPage` |  | 教程列表 |
| `/tutorials/new` | `TutorialFormPage` | ✅ | 新建/编辑教程 |
| `/tutorials/:id` | `TutorialDetailPage` |  | 教程详情 |
| `/join` | `JoinPage` |  | 加入社团（自我介绍问卷入口） |
| `/join/form` | `JoinFormPage` |  | 填写自我介绍问卷（`SurveyFill`） |
| `/join/editor` | `JoinEditorPage` | ✅ | 编辑自我介绍问卷（复用 `SurveyCreatorPage`） |
| `/register` | `RegisterPage` |  | 自助注册（用户名 + 双密码 + 真实姓名 / 身份 + Turnstile；成功即登录、进入社员认领阶段） |
| `/verify-email` | `VerifyEmailPage` |  | 邮箱认证落地页（邮件链接带 `?uid=&token=`） |
| `/verify-email-pending` | `VerifyEmailPendingPage` |  | 重发认证邮件（`?email=` 可预填） |
| `/v/:code` | `MemberVerifyPage` |  | 社员识别码公开校验页（`?s=` 签名；只出最小公开字段） |
| `/verify` | `StepUpPage` | ✅ | 安全验证（Step-up）：`?action=&next=`，完成回跳原操作 |
| `/security` | `SecurityCenterPage` | ✅ | 账号与安全中心：登录方式、设备、登录记录、滚动密钥、恢复代码；旧 `?tab=security/password/sessions` 会 `replace` 到这里 |
| `/forgot-password` | `ForgotPasswordPage` |  | 忘记密码 |
| `/reset-password` | `ResetPasswordPage` |  | 重置密码落地页 |
| `/profile` | `ProfileRedirect` |  | 取 `me.id` 后 `replace` 到 `/u/<id>` |
| `/u/:id` | `UserProfile` |  | 用户主页（资料卡 + 内容列表 + 私信/禁言入口） |
| `*` | — |  | `<Navigate to="/" replace />` 兜底 |

布局例外（不套全站外壳）：`/tasks/new`、`/tasks/:id/edit`（`TaskFormPage` 自带 `.task-page` 布局）、`/exam`（考试看板全屏）；移动版页面自持 `.m-app` 外壳；`ProfileRedirect` 只做跳转不渲染。`/panorama` 仍套 `AppShell`，但舞台区自带暗底容器与全屏按钮（不另开布局变体）。

### 手机版工作台（2026-10-18）

手机版不再是「只能看新闻/活动」的只读站点：审核台、待办、通知、任务列表与详情都有 `/m` 专属实现。

- **入口**：`MobileMePage` 按权限分组渲染「工作 / 常用」；首页九宫格对登录用户追加「任务」「待办」。
- **改道**：`App.tsx` 的 `MobileAware` 在手机 UA 下把 `/reviews`、`/inbox`、`/notifications`、`/tasks`、`/tasks/:id`
  `replace` 到对应 `/m` 页面（保留深链接语义，桌面 UA 完全不受影响）。改道发生在 `ProtectedRoute` 外层，
  未登录用户不会先触发一次 `/auth/me/` 再跳转。
- **刷新改道**：`utils/uaSwitch.ts` 的 `TO_MOBILE` / `TO_DESKTOP` 也登记了这批页面
  （含 `/tasks/:id` 的数字 id 特判），否则切换 UA 类别刷新时会掉回 `/m` 首页。
- **共用逻辑**：审核台的取数与「跳过已浏览条目」规则抽到 `src/utils/reviewDesk.ts`，桌面 `ReviewQueuePage`
  与手机 `MobileReviewPage` 共用 `deskTabs()` / `firstIdentity()` / `firstContent()` / `firstFeedback()` / `firstReport()`。
  新增审核桌时必须改这一处，否则两端会漂移（`src/utils/__tests__/reviewDesk.test.ts` 锁定顺序与可见性）。
- **页面框架**：二级页统一用 `components/MobilePage.tsx`（返回 + 标题 + 右侧操作 + 底部 tab）；
  样式在 `styles/mobile-work.css`（`mw-` 前缀），审核内容预览直接复用 `ReviewPreview`，
  只用 `.m-review` 作用域覆盖排版，不复制正文渲染逻辑。
- **尚未手机化**（仍会打开桌面页）：私信、意见反馈提交、个人资料/认证、各类发布表单、考试看板、
  课表下载、全景管理。这些页面在 390px 下可用但不适合单手操作，后续按需迁移。


页面内的重要子组件（非路由）：

| 场景 | 组件 |
|------|------|
| 活动详情（`ActivityDetailShell` 按活动类型挂面板） | `activity/CollectionPanel`（征集）、`activity/ExhibitionPanel`（展览）、`activity/DeliberationPanel`（审议）、`activity/SurveyPanel`（调研问卷） |
| 审核队列预览 | `pages/review/ReviewPreview` |
| 个人中心（`UserProfile` 的 tab 面板） | `profile/ProfileHero`、`ProfileSideNav`、`ProfileTabs`、`ProfileEditPanel`、`VerificationPanel`、`PasswordPanel`、`SessionsPanel`、`ContentListPanel`、`PermissionsPanel`、`MuteUserPanel` |
| 账号与安全中心（`/#/security`） | `pages/SecurityCenterPage` + `security/DeviceListPanel`、`security/LoginEventsPanel`、`security/LoginMap`、`security/TotpPanel`（改密 / 安全问题复用 `profile/PasswordPanel`、`profile/SecurityPanel`） |

URL 查询参数约定（hash 部分之后）：tab 状态用查询参数（如 `/u/3?tab=verification`、`/profile?tab=verification`）并由页面用 `URLSearchParams` 读写（`PanoramaPage` 的 `?id=` 选场景同理）；邮件链接参数（`uid`/`token`/`email`）；嵌入参数 `embed=1`（见「嵌入模式」）。

## API 客户端约定

`src/api/` 按后端 URL 前缀拆分，每个模块导出一个 `xxxApi` 对象（个别模块导出若干函数）。所有模块共用 `shared.ts` 里的 `createRequest(base)`：

| 模块 | 前缀 | 覆盖 |
|------|------|------|
| `api/client.ts` | `/auth` | 登录/登出/`me`/资料/改密/密码重置/注册/邮箱认证/会话列表/用户检索/收件箱；`api/security.ts` 另封装安全中心（设备 / 登录记录 / TOTP / 恢复代码） |
| `api/news.ts` | `/news` | 列表/详情/我的/增删改/图片上传/featured/hot/tags/overview/feed |
| `api/tasks.ts` | `/tasks` | 任务 CRUD、认领/审批/完成/指派等动作、标签 |
| `api/activities.ts` | `/activities` | 活动 CRUD、生命周期动作、问卷 schema、征集/展品 |
| `api/messaging.ts` | `/messaging` | 私信会话、通知、评论线程、未读数、横幅公告 |
| `api/reviews.ts` / `api/feedback.ts` / `api/reports.ts` | `/reviews` | 发布审核、意见反馈、举报案 |
| `api/identityReviews.ts` | `/auth` | 身份审核（预约认证、证明投递） |
| `api/about.ts` | `/about` | 关于页读写 |
| `api/panorama.ts` | `/panorama` | 全景图列表/详情、导入（multipart）、改/删/重切片；`listAll()` 逐页拉全 |
| `api/announcements.ts` | `/announcements` | 未读在线公告、详情、标已读、原件 URL |
| `api/tutorials.ts` | `/tutorials` | 教程 CRUD |
| `api/recruitment.ts` | `/recruitment` | 自我介绍问卷 schema |
| `api/exam.ts` | `/exam_board` | 考试/课表/题目误刊 |
| `api/attachments.ts` | `/attachments` | 统一附件上传/删除 + tus 大文件续传（`/uploads/files/`） |
| `api/sitePolicy.ts` | `""` | 公开站点策略 `GET /site-policy/` |
| `api/shared.ts` | — | 请求适配器与错误契约（无业务端点） |

`shared.ts` 是唯一的 HTTP 适配器（组件不直接 `fetch`），约定：

1. **fetch 出口唯一**：`createRequest(base)` 返回的 `request(path, options)` 统一 `credentials: "include"`；非 `FormData` 请求默认 `Content-Type: application/json`；每个请求带 `X-CSRFToken`（读 `csrftoken` Cookie）与 `X-Device-Id`（`utils/deviceId.ts` 的 localStorage UUID，供访客问卷去重与统计）。
2. **响应 → 类型化结果**：`readResponse` 解析响应体，`classifyHttpResponse(status, data)` 把后端 `reason` 串/状态码映射为判别联合 `ApiError`：`session_superseded`（含 `takeover` 载荷）、`login_protection`、`login_throttled`、`account_disabled`、`email_not_verified`、`network`（断网或响应非 JSON）、`auth`(401)、`forbidden`(403)、`not_found`(404)、`http`（其余非 2xx）。`reason → kind` 的映射只发生在这一处，后端改字段名只改这一个函数。
3. **抛错约定**：失败时抛 `Error`，并挂载 `err.status` 与 `err.apiError`（类型化）；调用方按 `apiError.kind` 分支而不是匹配中文字符串。`humanizeApiError` 用穷尽 switch 做 kind → 中文文案映射（新增 kind 时 TS 在 default 报错，强制补分支）。
4. **挤号回调**：`session_superseded` 结果先交给注册的 `supersedeHandler`（由 `SessionGuard` 注册），再照常抛错。
5. **列表分页**：DRF 信封 `{count, next, previous, results}`（类型 `types/pagination.ts::Paginated<T>`）。页面列表统一用 `hooks/usePagedList(fetcher, pageSize, filters, enabled)`：filter 变化自动回第 1 页、`refetch()` 强制重拉、`enabled=false` 时不发请求（等待身份解析等场景）；filters 经 ref 调用避免内联 fetcher 身份变化导致重复请求。非分页接口（如 `/auth/users/`）单独处理；需要「一次拉全」的少数据列表（如全景图库）在 api 模块里自行逐页拉全。
6. **WebSocket 只做提示**：`api/messagingSocket.ts`（`/ws/messaging/`，已登录可连；`dm / notification / comment / unread` 事件，指数退避重连）与 `api/examSocket.ts`（`/ws/exam-board/`，访客可连；课表与题目误刊广播）都遵循「HTTP 是事实源、socket 只提示刷新」；断线不影响页面功能，重连成功后重新订阅当前评论区。

典型调用与错误分支（页面里的惯用形状）：

```tsx
try {
  const d = await newsApi.get(id);
  setNews(d);
} catch (err: any) {
  const apiError = err?.apiError as ApiError | undefined;
  setError(apiError ? humanizeApiError(apiError) : "加载失败");
}
```

站点策略 `sitePolicy.ts` 是模块级单例：`fetchSitePolicy()` 在 App 启动时拉取并合并 `DEFAULTS`，`useSitePolicy()` / `useSitePolicyReady()` 订阅快照。`turnstile_enabled`、`dms_enabled`、`comments_enabled`、`verification_enabled`、`registration_enabled` 等开关据此驱动前端显隐（如关闭私信时导航与收件箱相应收敛）；拉取失败静默回退默认值（默认与后端一致，均为开启）。

`src/types/` 按域放纯类型（`news / tasks / activities / messaging / profile / inbox / feed / feedback / reports / reviews / identityReviews / panorama / announcements / pagination`），并含少量展示常量（状态中文标签、配色映射等），不 import React。

## 身份与会话

会话基于 Django Session + CSRF（无 JWT）。`App.tsx` 的组件树：

```tsx
<HashRouter>
  <LoginModalProvider>        {/* 全局登录弹窗 + authNonce */}
    <SessionGuard>            {/* 多端登录轮询 + 下线弹窗 */}
      <Suspense fallback={<Loading />}>
        <Routes>…</Routes>
      </Suspense>
    </SessionGuard>
    <ValidityNoticeHost />     {/* 账号有效期弹窗（ADR-0041）：桌面 / 手机版共用一份快照 */}
  </LoginModalProvider>
  <MaybeMascot />             {/* embed 模式不渲染看板娘 */}
</HashRouter>
```

- **登录弹窗**：`LoginModalProvider` 提供 `openLogin(redirectTo?)` / `closeLogin` / `authNonce` / `notifyAuthChange`。`LoginModal` 由 Provider 常驻渲染，用户名/邮箱两种方式（`api.login` / `api.loginWithEmail`；手机号 tab 置灰「即将上线」）。登录成功后先自检一次 `api.me()`（防「假登录」：刚建会话即被挤下线时不进入已登录假态），成功则 `authNonce++` 并跳转 `redirectTo`；失败按类型化错误分支展示：登录保护期（含重试 ETA）、限流、账号停用、「邮箱未认证」（附「重发认证邮件」入口直达 `/verify-email-pending`）。
- **受保护路由**：`ProtectedRoute` 在挂载与每次 `authNonce` 变化后调 `api.me()` 校验；未登录时 `openLogin(location.pathname + location.search)` 记录回跳地址并渲染空（弹窗遮罩在前）。弹窗带 `redirectTo` 时关闭会先回首页，避免用户停在空白受保护页。
- **下线提示（多端登录 / 挤号）**：`SessionGuard` 注册回调并在已登录时每 15s 轮询 `api.me()`；被下线的响应（类型化 `session_superseded`，含 `revokedReason` + 接管设备名/IP/时间）触发 `SessionSupersedeModal`（幂等展示，已显示则不覆盖），文案按 `sessionEndedMessage()` 区分「名额已满被替换 / 在个人中心被下线 / 设备重登 / 安全吊销」，确认后重新打开登录弹窗。未登录则不轮询。
- **登录态变化广播**：登录（`LoginModal` 的 `onLoggedIn`）与登出（`AppShell` 用户菜单的 `api.logout()`）都自增 `authNonce`；`AppShell`、受保护路由、`SessionGuard` 据此重新拉取身份，避免同页登出后本地 `user` 状态过期。
- **陌生设备挑战**：`api.login()` 收到 202 + `reason: "new_device"` 时，`LoginModal` 原地切到二次验证界面（TOTP / 邮箱码 / 安全问题 / 恢复代码），验证通过后再走 `onLoggedIn`；无 2FA 豁免（`must_bind_2fa`）则跳 `/#/security?bind=1`。不要在别处复制这套状态机。
- **注册与认证链路**：`/register` 建登录身份（用户名 + 双密码 + 真实姓名 / 身份 + Turnstile），**注册成功即登录**；若名册存在匹配的未绑定行，进入**社员身份认领**阶段（可跳过、之后在个人中心「社员身份」补办——[ADR-0025](../adr/0025-member-identity.md)）。邮箱绑定与身份证明在登录后的「账号认证」面板（`components/profile/VerificationPanel`）；邮箱认证走邮件链接到 `/verify-email`，未认证登录被拒时跳 `/verify-email-pending` 重发。身份状态徽章由 `me.role` 驱动（见「能力投影」）。

## 能力投影（permissions → UI）

后端把当前用户权限投影为 `/auth/me/` 响应里的 `user.permissions`（`can_*` 语义布尔，后端由命名工作流权限派生）。前端用它**预判 UI 显隐**，不做安全边界——实际操作仍由后端权限类校验并可能 403。

| 能力字段 | 前端用途（位置） |
|----------|------------------|
| `can_manage_news` | 新闻列表的新建/编辑入口；`NewsFormPage` 打开前预检 |
| `can_review_content` / `can_review_identity` | 审核队列入口（`AppShell`）；新闻列表的审核入口；`ReviewQueuePage` 分栏 |
| `can_view_feedback` / `can_handle_reports` | 反馈详情可见性；审核队列入口与反馈/举报分栏 |
| `can_change_activity` | 活动详情管理动作（编辑/生命周期）；`SurveyEditorPage` 编辑权限（或本人创建） |
| `can_review_collections` | 活动征集复审（`CollectionPanel` 的 isReviewer） |
| `can_edit_about` | 关于页/首页编辑入口；`JoinEditorPage` 问卷编辑权限 |
| `can_manage_panoramas` | 全景游览页的「管理全景图」入口与全景图管理页（导入/编辑/删除/重切） |
| `can_manage_exam` | 考试看板管理态（编辑考试/批次） |
| `can_mute_user` | 用户主页「全站禁言」入口（`MuteUserPanel`） |
| `can_manage_tasks` / `can_assign_task` / `can_manage_tags` / `can_force_publish` / `can_manage_comment_thread` / `can_manage_announcement` / `can_manage_announcements` / `can_review_password_reset` | 主要在个人中心「权限」面板（`PermissionsPanel`）中展示说明；相关操作由后端校验。`can_review_password_reset` 另决定审核台「密码重置」桌与「审核台」入口显隐 |

- `components/profile/PermissionsPanel.tsx` 集中维护全部 `can_*` 的中文标签与说明（新增能力字段时在此补一行）。
- 另一类投影是**资源随附的服务器计算标志**：任务详情的 `available_actions` 决定操作按钮（`TaskDetailPage`——按钮显隐完全由后端给出，前端不自行推导生命周期）；活动详情的 `schema_editable` 决定问卷是否可编辑（叠加 `canManage`）；评论线程的 `can_manage` 决定协管按钮（`CommentSection`）。
- 身份徽章：`me.role.variant/label`（`visitor/user/admin/superadmin`）驱动「未认证」提醒条（`visitor` 时显示，点击跳 `/profile?tab=verification`）与后台入口（见「移动版」）；`profile.is_verified` 门禁私信/待办入口的可见性。
- 用户渲染：共享用户形状（`SimpleUserSerializer` 语义——`avatar` 相对路径、显示名 `nickname || username`）由 `components/Avatar.tsx` 落实：`avatar` 为空时渲染首字符默认头像；`user.permissions` 只出现在当前用户接口，其它用户的引用对象不含 `can_*`。

## 移动版

「手机版」是一套**独立的移动布局站点**（非桌面端响应式变体），入口 `/#/m` 系列，路由与桌面路由并列声明在 `App.tsx`：

| 路由 | 页面 | 内容 |
|------|------|------|
| `/m` | `MobileHomePage` | 顶栏 + hero + 四宫格快捷入口 + 新闻/活动卡片流 |
| `/m/news` · `/m/news/:id` | `MobileNewsPage` · `MobileNewsDetailPage` | 新闻列表与详情（头图 / 正文 / 相关阅读 / 图片大图） |
| `/m/activity` · `/m/activity/:id` | `MobileActivityPage` · `MobileActivityDetailPage` | 活动列表与详情（信息徽章 / 众议投票 / 调研作答 / 展示画廊；受限活动给登录入口） |
| `/m/tutorials` · `/m/tutorials/:id` | `MobileTutorialsPage` · `MobileTutorialDetailPage` | 教程列表与详情（视频播放 / 文档下载 / 收藏） |
| `/m/join` · `/m/join/form` | `MobileJoinPage` · `MobileJoinFormPage` | 加入公告（阅读确认）与自我介绍问卷（SurveyJS） |
| `/m/me` | `MobileMePage` | 「我的」：资料卡 + 工作 / 常用服务入口 + 外观切换 + 登录/退出 |
| `/m/review` · `/m/inbox` · `/m/notifications` · `/m/tasks` · `/m/tasks/:id` | `MobileReviewPage` 等 | 工作台：审核台 / 待办 / 通知 / 任务列表与详情（见「手机版工作台」） |

- 手机版内闭环：首页快捷格、列表卡片与「更多」一律指向 `/m/*`——列表进详情、教程、加入都不跳出手机版。
- 共享外壳：样式 `styles/mobile.css`（`.m-app` 作用域：topbar / 渐变 hero / 四宫格快捷入口 / 卡片流 / 固定底部 tab），每个页面自渲染 `<MobileTabBar />`（`components/MobileTabBar.tsx`，四个 tab：首页/活动/新闻/我的，`NavLink` 指向 `/m/*`，首页用 `end` 精确匹配）。
- 未读红点：底部 tab、首页铃铛与「我的」入口的未读数字（私信 + 通知）来自 `api/unreadBadges.ts` 的模块级 store（30 s 轮询 + 窗口可见 / 聚焦刷新 + App 壳 `club:unread` 事件）。
- 自动改道：`HomeRoute` 在根路径用 `utils/device.ts::isMobileDevice()`（UA 正则命中 iPhone/Android/Windows Phone 等）判断手机浏览器，渲染 `<Navigate to="/m" replace />`；深链接、桌面端与「请求桌面站点」模式不受影响。
- UA 变化改道：`index.tsx` 在 React 渲染前调用 `utils/uaSwitch.ts::applyUaSwitch()`，把当前 UA 归为三档（`app` / `mobile` / `desktop`，见 `device.ts::classifyUserAgent`）并与 `localStorage` 里的上一次类别比较。**只在跨「移动侧 / 桌面侧」变化时**跳一次：变成移动侧 → 手机版等价页（`/news/:id` → `/m/news/:id`，无对应页面则 `/m`），变成桌面侧 → 桌面版等价页（`/m/me` → `/profile`，其余回落 `/`）。只比类别不比字符串，浏览器版本号升级、壳版本升级都不会误跳；类别不变时深链接保持原样。跳转用 `history.replaceState` 改 hash，不新增历史记录、不产生闪屏。
- `/m/me` 按真实契约 `{user, role, profile}` 渲染：显示名与头像取 `profile`、身份徽章取 `role.label`；`role.variant ∈ {admin, superadmin}` 时显示「进入后台管理」行（`window.location.href = "/admin/"`，判定走 `utils/roles.ts::canAccessAdmin`，与桌面顶栏同一函数）；匿名显示登录 CTA；退出登录 = `api.logout()` + 刷新。
- 加固点：网格用 `repeat(4, minmax(0, 1fr))` 防溢出、`.m-app` 上 `overflow-x: hidden`、固定条带 `env(safe-area-inset-*)` 安全区 padding。

## 嵌入模式（`?embed=1`）

Django admin 用 iframe 内嵌 SPA 页面（如审核对象预览 `/#/news/5?embed=1`）时，URL 带 `embed=1`。判定集中在 `src/embed.ts::useEmbedMode()`（读 hash 路由的 query）：

- `PageChrome` 在 embed 时返回 `<div className="cs embed-root">`，跳过 `AppShell` 的顶栏/菜单/页脚——详情类页面（新闻/教程/活动）因此可在 iframe 中干净渲染；
- `App.tsx` 的 `MaybeMascot` 在 embed 时不渲染看板娘；`AppShell` 自身也有 embed 早退分支兜底。

服务端配合 `X_FRAME_OPTIONS = "SAMEORIGIN"`（`config/settings.py`）：允许同站 iframe 嵌入，同时保持对第三方点击劫持的防护。

## 静态资源与第三方库

- **SurveyJS 全家桶**（survey-core / survey-react-ui / survey-creator-core / survey-creator-react / survey-analytics + chart.js）：SPA 内 `SurveyFill`（填写，`utils/survey.ts` 统一响应式宽度与 `onComplete` 接后端，`utils/surveyLocale.ts` 中文 locale）、`SurveyCreatorPage`（编辑器，`saveSurveyFunc` 直连后端保存）、`SurveyResponsesPage` / `SurveyStatsPage`（答复与 analytics 仪表盘）。构建时另将未哈希 min 文件拷到 `static/surveyjs/` 与 `dist/surveyjs/`，专供 Django admin 的问卷编辑器/结果页模板使用——升级 survey-* 后必须重跑 `npm run copy-surveyjs`。
- **看板娘（Live2D）**：`vendor/live2d/`（runtime + widget + 模型 + `catalog.json`）构建时拷到 `/static/live2d/`，运行时经 `l2d` npm 包渲染 Cubism 2/6 模型。`MascotHost` 分三态：`widget`（完整挂件，独立懒加载 chunk `mascot/loadWidget`）/ `chip`（「看板娘」小按钮）/ `none`（窄屏 ≤1024px、系统 `prefers-reduced-motion`、考试看板且关闭偏好）。开关存 localStorage（`mascot.enabled`）；考试看板经 `examBoard/prefs.ts` 与 `mascot/speak.ts` 让看板娘播报考试提示与倒计时语音。
- **Marzipano（校园全景）**：**不是 npm 依赖**——它是服务端多级分层方案（[ADR-0022](../adr/0022-campus-panorama-library.md)）的渲染端，运行时由 `utils/marzipano.ts::loadMarzipano()` 从自托管静态资源 `/static/panorama/marzipano.js` 注入脚本（幂等、失败可重试、不发任何第三方请求）。该文件与旧静态全景页共用，并已被 `scripts/pack-release.sh` 与 `scripts/check_panorama_static.py` 纳入发布完整性校验；**退役 `static/panorama/` 前必须先把 `marzipano.js` 迁到新位置并同步 `constants.ts::PANORAMA_RENDERER_URL`**。
- **Cloudflare Turnstile**：`turnstile.ts` 在注册/找回密码/重发认证邮件/匿名反馈处按需注入脚本（未启用时零请求）；`turnstile_enabled` 与 sitekey 由 `/site-policy/` 下发，`useTurnstile` 负责渲染、重置与卸载组件。
- **富文本**：Tiptap 3 编辑器（`RichTextEditor.tsx`），自定义原子节点 `rte/VideoNode.ts`（本地上传视频）与 `rte/IframeNode.ts`（仅 https iframe 嵌入，sandbox 属性与后端 `common/rich_text.py` 保持一致）；`utils/iframeEmbed.ts` 解析用户粘贴的 embed HTML（仅取首个 iframe 的 src/title，安全边界仍在服务端 sanitize）。工具栏扩展高亮 / 文字颜色 / 对齐 / 上下标 / 字数统计与选区气泡菜单、空行浮动菜单；新闻编辑页（`NewsFormPage`）为文档式布局，编辑内容自动保存至服务端草稿区（已发布稿存 `draft_*`，未发布稿直写正文；读写弃均须 `news.manage_news`），详情页提供「编辑 / 继续编辑」入口。
- **文档处理**：`DocxPreview`（docx-preview 保真渲染 Word 原件）与 mammoth（Word 导入转富文本）；全站弹窗公告的 PDF 原件用内置 **pdf.js**（`vendor/pdfjs/`：解析器 + worker + CJK CMap，构建时直拷到 `/static/pdfjs/`，不进 bundle——`PdfPreview` 按页懒渲染，页数封顶）。
- **其他**：`frappe-gantt`（任务甘特，`TaskGantt`，配色映射 cobalt token）；`tus-js-client`（超过同步上限的大文件走 tus 可续传上传，端点 `/uploads/files/`，完成后后端自动挂为统一附件）；字体 Sora / Noto Sans SC 由 `cobalt.css` 以 Google Fonts `@import` 引入。

## 开发惯例

从现有代码归纳的约定（新代码请保持）：

- **命名与组织**：页面 `pages/*Page.tsx`（PascalCase 组件）；共享组件 `components/`（按域分子目录）；API 模块导出 `xxxApi` 对象、端点路径带尾斜杠；类型集中在 `types/<domain>.ts`；纯逻辑放 `utils/` 或域目录（如 `examBoard/validate.ts`、`examBoard/prefs.ts` 独立于 React，便于单测与复用）。
- **样式**：不用 CSS 框架；共享设计层 `cobalt.css` 提供 `.cs` reset 与 token，业务样式就近 import（组件专属 CSS 与组件同目录；跨页域样式放 `styles/`）。移动版样式类前缀 `m-`，移动页统一 `import "../styles/mobile.css"`。
- **数据访问**：组件不直接 `fetch`，一律经 `api/` 模块；错误展示优先按 `err.apiError.kind` 分支 + `humanizeApiError`（登录弹窗内的登录专用英文串例外，走 `LOGIN_ERROR_ZH` 映射）。
- **路由**：新页面在 `App.tsx` 声明并 lazily import；需要登录的包 `ProtectedRoute`；新增后端 API 前缀时同步在 `config/urls.py` 的 catch-all 排除清单与 `webpack.config.js` 的 `devServer.proxy` 两处登记（否则前端路径会被 SPA 捕获 / 开发态 404）。站内导航用 `navigate`/`NavLink`/`Link`，跳 `/admin/` 或外链用 `window.location.href`。
- **页面元信息**：各页在 `useEffect` 里设置 `document.title`（如「待办 · 传媒社」）；列表页优先 `Pagination` + `usePagedList`（数据量小、需一次拉全的列表在 api 模块里逐页拉全亦可）。
- **组件外壳**：页面默认套 `AppShell`（详情页用 `PageChrome`，等价但在 `?embed=1` 时跳过）；确需独立布局的页面（任务表单、考试看板、移动版）自持布局根类，并在本文件「路由与页面」的布局例外中登记。
- **兼容与类型**：`strict` TypeScript；跨模块的响应形状允许先 `as Promise<T>` 收口，再在 `types/` 中补精确类型；不新增未使用的依赖，第三方库的使用方式（懒加载、按需注入）以现有模块为范本。
- **可访问性与语义**：交互元素用真实 `<button>/<a>`（`role`/`aria-*` 标注到位：导航 `aria-current`、弹窗 `aria-modal`、徽标计数 `aria-label`、提醒条与横幅 `role="status"`），图标统一收在 `components/icons.tsx`（内联 SVG、无图标库；24px 视框线性 / `stroke=currentColor`，实际尺寸由外层 `.ico` 控制）；键盘可达性以 `:focus-visible` 焦点环兜底。
- **文案与注释**：UI 文案为内联中文（无 i18n 框架），代码注释以中文说明设计意图；日期时间展示用 `toLocaleString/toLocaleDateString("zh-CN")` 或手写「x月x日」格式。

## 已知边界

- 前端测试：单元 / 组件测试用 Vitest + React Testing Library（测试文件在 `src/**/__tests__/*.test.ts(x)`，`cd frontend && npm test`）；浏览器 E2E 用 Playwright（chromium，用例在 `frontend/e2e/`，`cd frontend && npx playwright test` 自动起独立测试库与服务）。E2E 登录态 setup 按可访问名「打开用户菜单」断言顶栏用户菜单触发器——修改 `UserMenu.tsx` 的 `aria-label` 时需同步 `e2e/auth.setup.ts` 与 `e2e/login.spec.ts`；自动化关口另有构建断言脚本（`assert-*-dist.js`）与 TypeScript 编译；页面质量仍依赖逐页预览与人工验收。
- `user.permissions` 与 `available_actions` 等能力投影是 **UI 预判**，不是安全边界：任何被隐藏的操作在后端仍会做权限校验（403 已由类型化错误统一接住）。
- **全景浏览页依赖自托管渲染器**：Marzipano 走 `/static/panorama/marzipano.js`（非 npm 包），故「静态资源缺失 / 改名」会让全景页报「全景渲染器加载失败」；两者必须同步变更（见「静态资源与第三方库」）。全景层级图走 `/media/panorama/...`，开发态由 `devServer.proxy` 的 `/media` 代理覆盖。
- 移动版是独立布局站点：`/m` 页面与桌面页面**不共享**同一组件实现（共享的只有 `api/`、`types/`、`utils/`），桌面端的改动不会自动出现在手机版，反之亦然。
- 路由采用 hash 模式（`/#/...`）的代价：URL 中可见 `#`、SEO 不友好、`?embed=1` 等查询参数必须写在 `#` 之后；换来的是 Django 端无需任何 rewrite 配置即可服务 SPA。
- 开发态依赖 `devServer.proxy` 的前缀清单与后端 `config/urls.py` 双向保持同步；新增 API 前缀时两处都要登记。
