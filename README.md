# 南汇一中传媒社 · 社团管理系统

这是一个以 Django 为核心、React 前端为展示层的社团内部管理系统。当前代码结构已经覆盖了用户认证、任务管理、活动/众议/征集/展示、新闻发布、提案/反馈、教程、招聘、评论与私信、通知、横幅公告和站点策略等核心场景，适用于校内社团的日常运营和后台管理。

## 1. 当前项目状况

项目当前已经具备以下模块：

- 认证与账号：登录、注册、邮箱验证、人工审核、认证码、密码重置、用户资料、会话管理；
  个人中心支持**账号注销**（软删除：邮箱 / 头像 / 身份证明材料 / 登录设备记录即刻清除，
  账号编码、真实姓名与社员编号保留在后台；历史私信与评论展示为「该用户已注销」）
- 内容管理：新闻、教程、关于页、站点政策
- 协作管理：任务、标签、评论区、私信、提案/反馈
- 提醒与运营：站内通知（可按来源开关）、横幅公告、全站禁言
- 活动管理：活动、众议、征集、展示、公开投票、审核；期限可设截止时间，也可勾选「长期有效」（不设截止、不会因时间自动结束，只能由发起人或管理员手动终结）
- 问卷系统：SurveyJS 问卷（编辑 / 作答 / 按作答内容检索 / 统计与导出）
- 招聘与审批：招聘信息、面试/审核流程
- 移动端：独立的手机版站点（`/#/m`）。底部 tab 与首页铃铛带未读数字红点（私信 + 通知），
  「我的」页列出带未读数的私信/通知入口，并提供**外观**切换（浅色 / 深色 / 跟随系统）；
  Android 壳内默认跟随系统深色（壳的 UA 标记见 `frontend/src/utils/device.ts` 的 `isAppShell`）；
  每次刷新都会对比 UA 类别，移动侧（手机浏览器 / App 壳）与桌面侧切换后自动落到对应版本的等价页面
  （`frontend/src/utils/uaSwitch.ts`，类别不变时深链接不动）
- 手机版工作台（2026-10-18）：审核台 `/#/m/review`（身份 / 内容 / 意见反馈 / 举报案）、
  待办 `/#/m/inbox`、通知 `/#/m/notifications`、任务列表与详情 `/#/m/tasks`；
  「我的」按权限分「工作 / 常用」两组，首页九宫格对登录用户追加「任务」「待办」；
  手机 UA 打开桌面路径（如 `/#/reviews`）会自动改道到对应手机版页面
- 后台管理：Django Admin + 自定义视图 + 前端 SPA
- 运维能力：一键部署脚本（`scripts/install.sh`）、GitHub Release 自动更新（维护页 / 回滚）、systemd + Nginx + Gunicorn（ASGI / 单 worker），适合内部低门槛生产环境

## 2. 技术栈

- 后端：Python 3.14 / Django 6.0
- 前端：React 19 / TypeScript / Webpack 5
- 数据库：SQLite（默认开发/生产都可用）
- 依赖管理：uv（Python） + npm（前端）
- 运行方式：Django 直接托管前端产物；生产为 Nginx + Gunicorn ASGI（`UvicornWorker`，**1 worker**，无 Redis；见 [ADR 0015](docs/adr/0015-channels-without-redis.md)）

## 3. 快速开始

### 3.1 本地开发

```bash
# 安装 Python 依赖
uv sync

# 创建本地数据库
uv run python manage.py migrate

# 可选：创建超级管理员
uv run python manage.py createsuperuser

# 启动后端
uv run python manage.py runserver
```

前端开发：

```bash
cd frontend
npm install
npm run dev
```

默认前端开发地址通常为 `http://localhost:3000`，后端默认 `http://localhost:8000`。

### 3.2 生产构建

```bash
cd frontend
npm run build
```

构建产物写入 `frontend/dist/`（含 Django admin 用的 SurveyJS 静态文件），Django 会直接托管 SPA 页面与静态资源，无需额外部署独立前端服务。

## 4. 目录结构

```text
club-management-website/
├── accounts/             # 账号、验证、资料、权限相关
├── activities/           # 活动与活动类型（众议/征集/展示）
├── about/                # 关于页内容管理
├── attachments/          # 附件和上传处理
├── common/               # 公共组件、站点策略等
├── config/               # Django settings / urls / ASGI/WSGI
├── docs/                 # 项目文档
├── exam_board/           # 考试看板（批次课表 + 题目误刊广播）
├── frontend/             # React 前端源代码与构建输出
├── messaging/            # 评论区 / 私信 / 通知 / 横幅公告
├── news/                 # 新闻模块
├── recruitment/          # 招聘模块
├── reviews/              # 发布审核 / 意见反馈 / 举报案
├── scripts/              # 运维脚本（install.sh、更新/回滚）
├── static/               # 静态资源
├── tasks/                # 任务与标签模块
├── tutorials/            # 教程上传与审核模块
├── .env.example          # 环境变量模板
├── start.sh              # 运行/重启脚本
├── manage.py             # Django 启动入口
├── pyproject.toml        # Python 项目配置
├── uv.lock               # uv 锁文件
└── README.md             # 项目入口文档
```

## 5. 文档导航

- 完整文档索引：[`docs/README.md`](docs/README.md)
- 协作者 / AI 助手指引：[`CLAUDE.md`](CLAUDE.md)（改动流程、环境限制、工具链）
- 快速开始：[`docs/getting-started.md`](docs/getting-started.md) · 配置参考：[`docs/configuration.md`](docs/configuration.md)
- API 参考：[`docs/api/README.md`](docs/api/README.md)（各模块分册见 `docs/api/`）
- 架构：[`docs/architecture/overview.md`](docs/architecture/overview.md) · [`docs/architecture/frontend.md`](docs/architecture/frontend.md)
- 指南：`docs/guides/`（访问控制 / 身份认证 / 安全验证 / 审核系统 / 问卷）
- 运维：[`docs/operations/deployment.md`](docs/operations/deployment.md) · [`docs/operations/data-root.md`](docs/operations/data-root.md) · [`docs/operations/admin-guide.md`](docs/operations/admin-guide.md)
- ADR 设计记录：[`docs/adr/`](docs/adr/)
- GitHub Wiki（对外入口）：<https://github.com/nhyzcms/club-management-website/wiki>

## 6. 主要入口和 URL

- 后台管理：`/admin/`
- 认证：`/auth/`
- 任务：`/tasks/`
- 新闻：`/news/`
- 活动：`/activities/`
- 审核（发布审核 / 意见反馈 / 举报）：`/reviews/`
- 教程：`/tutorials/`
- 招聘：`/recruitment/`
- 消息（评论区 / 私信 / 通知 / 横幅）：`/messaging/`
- 实时推送（已登录）：`/ws/messaging/`
- 考试看板：`/exam_board/`，广播 `/ws/exam-board/`
- 附件上传：`/uploads/`
- 站点政策：`/site-policy/`
- 手机版（移动端站点）：`/#/m`
  - 工作台：`/#/m/review`（审核台）、`/#/m/inbox`（待办）、`/#/m/notifications`（通知）、
    `/#/m/tasks` 与 `/#/m/tasks/:id`（任务）
  - 手机 UA 访问 `/reviews`、`/inbox`、`/notifications`、`/tasks`、`/tasks/:id` 会自动 `replace`
    到对应的 `/#/m/...`（桌面 UA 不受影响）

注意：本项目使用 Django + React 的单页架构，前端路由需要由 Django 回落到 `index.html`，非 API 路径都会进入 SPA 入口。

## 7. 常用命令

```bash
uv run python manage.py runserver        # 启动开发服务器
uv run python manage.py migrate          # 执行数据库迁移
uv run python manage.py makemigrations  # 生成迁移文件
uv run python manage.py test             # 运行测试
uv run python manage.py check            # 检查项目配置

cd frontend && npm run dev               # 启动前端开发服务器
cd frontend && npm run build             # 构建生产资源
cd frontend && npm test                  # 前端单元测试（Vitest）
cd frontend && npx playwright test       # 浏览器 E2E（Playwright）

sudo ./scripts/install.sh                # 一键部署生产环境
./start.sh                              # 启动生产服务
```

## 8. 维护建议

- 生产环境用 `scripts/install.sh`：它会生成 SECRET_KEY、写入 FRONTEND_URL、创建超级用户。邮箱 / Turnstile / GitHub token 仍按需补进 `.env`。
- 如果你需要给别人上手使用，优先为管理员配一份后台操作手册和一份运维手册，避免直接让运维/运营人员碰源码。
- 日常更新走 GitHub Release + 更新守护进程（或 `scripts/updater.py --apply-now`），不要在生产机 `git pull` 再手工构建。
- 代码需保持 DRF API 与前端能力一致，改动接口时同步更新文档和前端调用逻辑。
- **协作者 / AI 助手请先读 [`CLAUDE.md`](CLAUDE.md)**：里面写了改动流程（分支 + PR）、
  环境限制（生产机 2 核 2 GB，**不要在生产服务器跑测试或构建**、前端无法在服务器构建），
  以及"写入与推送的载荷上限已解除（大文件/长文档不必再拆片）"这条工具链事实。
- **不要在生产服务器上跑测试或构建**：生产机只有 2 核 / 2 GB 内存 / 3 MB 带宽，
  测试与构建一律交 CI（`backend` / `frontend` / `frontend-test` / `e2e` 四个作业）。
- **手机版与桌面版是两套页面**：`/m` 页面不用 `AppShell`，二级页统一走 `components/MobilePage.tsx`。
  新增桌面工作流页面时，若该功能对手机用户必要，同时补一个 `/m` 实现并在 `App.tsx` 的 `MobileAware`
  里登记改道；审核台的取数规则在 `frontend/src/utils/reviewDesk.ts`（两端共用，勿复制）。
- 手机版未读红点的数据源在 `frontend/src/api/unreadBadges.ts`：30 s 轮询 + 窗口可见/聚焦时刷新，
  并监听 App 壳派发的 `club:unread` 事件（壳在原生的 WS 收到新消息时发一个**不带数据**的常量事件）。
  改这条链路时注意：/m 页面**不用** `AppShell`，桌面顶栏那套徽标与它们无关。
- App 壳与网站的契约：UA 标记 `NhyzClubApp/<versionName> (Android; <versionCode>)`。
  修改壳的 UA 必须同步 `frontend/src/utils/device.ts`，否则「App 内默认跟随系统深色」等
  App 专属行为会静默失效。
- **账号注销是软删除**（[ADR-0027](docs/adr/0027-account-deletion.md)）：`Profile.deleted_at` 标记，
  只清邮箱 / 头像 / 身份证明材料 / 会话等敏感信息；`User`、`Profile`、`MemberIdentity`（社员编号）
  行永不删除。新增「删除用户」类功能时先读该 ADR，不要物理删账号。

如果你是第一次接手这个项目，建议先读：

1. [docs/getting-started.md](docs/getting-started.md)
2. [docs/architecture/overview.md](docs/architecture/overview.md)
3. [docs/api/README.md](docs/api/README.md)
4. [docs/operations/deployment.md](docs/operations/deployment.md)
5. [docs/operations/admin-guide.md](docs/operations/admin-guide.md)

## 9. 许可证

本项目代码采用 **BSD 3-Clause License**（三条款 BSD 许可证），全文见 [LICENSE](LICENSE)。

简单说：你可以自由使用、修改、再分发，包括商用，但必须

1. 在源码中保留版权声明、条款与免责声明；
2. 在二进制分发时于文档或其他材料中复现上述内容；
3. **不得**用本社团或贡献者的名义为你的衍生品背书（未经书面许可）。

软件按「现状」提供，不附带任何担保。

**第三方素材不受本许可证覆盖**，它们各自保留原许可，再分发时请遵守对应条款：

- Live2D 运行时与模型：`frontend/vendor/live2d/runtime/LICENSE.txt`、`frontend/vendor/live2d/models/*/LICENSE`
- Noto Sans SC 字体：`activities/fonts/OFL.txt`（SIL Open Font License 1.1）
- 站内内容（新闻、活动作品、照片、全景图、社徽等）的著作权归原作者或社团所有，不属于代码许可的授权范围。

---

维护：**Echo**
