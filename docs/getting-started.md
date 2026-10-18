# 快速开始

面向第一次接手本仓库的开发者：把项目跑起来、跑测试、找到要改的文件。
逐项配置说明见 [配置参考](configuration.md)。

## 项目是什么

南汇一中传媒社的内部协作平台。它是一个 **Django 单体应用**：DRF 提供 JSON API，Django admin 提供后台管理，前端是一个 **React 单页应用（SPA）**，构建产物由 Django 直接托管（不需要单独部署前端服务）。功能覆盖账号与认证、任务协作、活动（众议 / 征集 / 展示 / 调研）、新闻与教程发布、发布审核与意见反馈、评论与私信、通知与横幅公告、考试看板等社团日常运营场景。

## 技术栈

| 层 | 选型 | 位置 |
|---|---|---|
| 后端 | Python 3.14 + Django 6.0 + Django REST Framework | 仓库根目录 |
| 依赖管理（后端） | uv（`pyproject.toml` + `uv.lock`） | 仓库根目录 |
| 前端 | React 19 + TypeScript + Webpack 5 | `frontend/` |
| 依赖管理（前端） | npm（`frontend/package-lock.json`） | `frontend/` |
| 数据库 | SQLite 缺省（`db.sqlite3`）；可选 PostgreSQL（`DB_ENGINE=postgresql`） | `config/settings.py` |
| 实时推送 | Django Channels（缺省 `InMemoryChannelLayer`；配 `REDIS_URL` 用 Redis 频道层） | `config/asgi.py` |
| 前端路由 | hash 路由（应用内 URL 形如 `/#/route`） | `frontend/src/App.tsx` |
| 生产运行 | Nginx + Gunicorn `UvicornWorker`（**1 worker**，无 Redis） | `start.sh` |

后端运行时依赖（`pyproject.toml`）：`django`、`djangorestframework`、`django-cors-headers`、`django-filter`、`channels[daphne]`、`drf-tus`、`bleach`、`pillow`、`python-dotenv`、`gunicorn`、`uvicorn[standard]`。
前端运行时依赖（`frontend/package.json`）：`react` 19、`react-router-dom` 7、Tiptap 3、SurveyJS 3（`survey-core` / `survey-react-ui` / `survey-creator-*` / `survey-analytics`）、`chart.js`、`frappe-gantt`、`docx-preview`、`mammoth`、`lowlight`、`tus-js-client`、`l2d`。

## 前置要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.14 | `pyproject.toml` 声明 `requires-python = ">=3.14"`；`.python-version` 写死 `3.14`，`uv sync` 会自动准备解释器 |
| uv | 0.11 及以上 | 后端唯一的依赖管理工具；仓库内没有 `uv.toml`，索引配置随环境 |
| Node.js | 22（CI 固定值） | `.github/workflows/ci.yml` 用 `actions/setup-node` 固定 `node-version: "22"`；`frontend/package.json` 未声明 `engines`，本地比 22 略新/略旧通常也可用 |
| npm | 随 Node 附带 | 前端依赖用 `npm ci` 按 lockfile 安装 |

不需要预先准备 `.env`：`config/settings.py` 自带本地默认值（`DEBUG` 默认开、`SECRET_KEY` 回退公开占位、邮件走 console 后端），开箱即可跑起来。生产必填项见 [配置参考](configuration.md)。

## 快速开始

### 后端

```bash
# 1. 安装 Python 依赖（uv 会自行准备 Python 3.14）
uv sync

# 2. 创建本地数据库（SQLite 文件 db.sqlite3，已 gitignore）
uv run python manage.py migrate

# 3. 可选：创建超级管理员（用于登录 Django admin）
uv run python manage.py createsuperuser

# 4. 启动开发服务器 → http://localhost:8000
uv run python manage.py runserver
```

### 前端

```bash
cd frontend

# 1. 按 lockfile 安装依赖
npm ci

# 2. 启动开发服务器 → http://localhost:3000
npm run dev
```

`npm run dev` 等价于 `node scripts/copy-surveyjs.js && webpack serve`：先把 SurveyJS 的未哈希 min 文件拷进 `static/surveyjs/`（供 Django admin 模板引用），再起 webpack-dev-server（HMR）。

生产构建：

```bash
cd frontend
npm run build
```

`npm run build` 依次执行 `webpack --mode production`（产物写入 `frontend/dist/`）→ `node scripts/copy-surveyjs.js`（拷 SurveyJS 未哈希 min 文件）→ `node scripts/assert-live2d-dist.js` → `node scripts/assert-surveyjs-dist.js`（两个产物断言，缺文件即失败）。

### 端口约定

| 服务 | 地址 | 说明 |
|---|---|---|
| 后端（`manage.py runserver`） | `http://localhost:8000` | DRF API、Django admin（`/admin/`） |
| 前端（`npm run dev`） | `http://localhost:3000` | webpack-dev-server，热更新 |
| 生产（Nginx + Gunicorn） | `https://<域名>` | Gunicorn 只监听 unix socket `run/gunicorn.sock`，对外由 Nginx 反代 |

开发态跨端口访问不需要额外配置：`frontend/webpack.config.js` 的 `devServer.proxy` 把 `/auth`、`/admin`、`/media`、`/tasks`、`/messaging`、`/news`、`/attachments`、`/uploads`、`/activities`、`/reviews`、`/about`、`/exam_board`、`/tutorials`、`/recruitment`、`/site-policy` 与 WebSocket `/ws/messaging`、`/ws/exam-board` 全部代理到 `http://localhost:8000`。

### 第一次跑起来后的检查

| 检查 | 预期 |
|---|---|
| 浏览器打开 `http://localhost:8000/` | 返回 SPA 入口页（Django 渲染 `frontend/dist/index.html`）；未构建前端时该模板不存在，需先 `npm run build` |
| 打开 `http://localhost:8000/admin/` | Django admin 登录页（用 `createsuperuser` 建的账号） |
| `curl http://localhost:8000/site-policy/` | 返回站点策略 JSON 快照（含 `turnstile_enabled` 等字段） |
| `uv run python manage.py check` | 无错误输出 |
| `uv run python manage.py test` | 全套通过（Django runner 打印 `Ran N tests ... OK`） |

## 运行测试

```bash
uv run python manage.py test                            # 全套
uv run python manage.py test accounts                   # 单个 app
uv run python manage.py test accounts.tests_site_policy # 单个测试模块
uv run python manage.py check                           # 项目配置自检
```

测试期有两项专门的提速设置（仅 `TESTING=True` 生效，零生产影响）：密码哈希切 MD5、邮件走内存后端。详见 [配置参考 §2.8](configuration.md)。

浏览器 E2E（Playwright，chromium）是「真实浏览器里的整栈冒烟」，现已覆盖前端全部模块与关键路由：登录 / 新闻（含封面上传、编辑器插图）/ 活动 / 考试看板 / 问卷 / 审核台 / 消息 / 反馈 / 个人中心 / 移动版 / 未知路由重定向等。

```bash
cd frontend
npm run build                                    # 首次需要：Django 直接托管 frontend/dist
npx playwright install chromium --with-deps      # 首次需要：安装浏览器（国内网络可加 PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright 走镜像）
npx playwright test                              # 自动：独立库 run/e2e.sqlite3 → migrate → seed_e2e → 起服务（:8010）→ 跑用例
```

测试数据由 `uv run python manage.py seed_e2e` 生成（幂等；账号 `e2e_info`（管理权限）、`e2e_plain`（普通），密码 `e2e-pass-123`）。失败产物在 `frontend/playwright-report/`（`npx playwright show-report` 查看，含 trace 回放）。

前端单元 / 组件测试（Vitest + React Testing Library + jsdom，测试文件在 `src/**/__tests__/*.test.ts(x)`）：

```bash
cd frontend
npm test            # 一次性运行（vitest run）
npm run test:watch  # 监视模式
```
CI 配置见 `.github/workflows/ci.yml`，触发条件为 push 到 `main` 或任意 PR；四个必跑 job 加一个发布 job：

| Job | 触发 | 步骤 |
|---|---|---|
| `backend` | push 到 `main` / 任意 PR | `astral-sh/setup-uv`（python 3.14）→ `uv sync --frozen` → `uv run python manage.py test` |
| `frontend` | 同上 | Node 22 → `npm ci && npm run build`（工作目录 `frontend`）→ 断言 `frontend/dist/surveyjs/survey.core.min.js` 存在 → 上传 `frontend-dist` artifact（保留 1 天） |
| `frontend-test` | 同上 | Node 22 → `npm ci` → `npm test`（Vitest 单元 / 组件测试，工作目录 `frontend`） |
| `e2e` | 同上 | 复用 `frontend-dist` artifact + `uv sync` → `npx playwright install --with-deps chromium` → `npx playwright test`（自动起独立库与服务）；上传 `playwright-report`（含 trace 回放，保留 7 天） |
| `release` | 仅 push 到 `main` 且前四个 job 通过 | `bash scripts/pack-release.sh` 打包 → 创建 GitHub Release（标签 `club-<sha>`，资产为 tarball + `.sha256` + `install.sh`，附上一个 Release 以来的 changelog） |

各 job 会把关键结果（测试统计、构建摘要等）写入运行页的 Step Summary，便于快速浏览。

本地跑 CI 的等价命令：

```bash
uv sync --frozen && uv run python manage.py test          # backend job
cd frontend && npm ci && npm run build                    # frontend job
cd frontend && npm test                                   # frontend-test job
cd frontend && npx playwright test                        # e2e job（需已装浏览器与前端产物，见上）
```

前端单元测试用 Vitest（`src/**/__tests__/*.test.ts(x)`，`cd frontend && npm test`）；浏览器 E2E 用 Playwright（`frontend/e2e/`，chromium，CI job `e2e`）；自动质量关口另有构建断言脚本（`assert-live2d-dist.js` / `assert-surveyjs-dist.js`）与 TypeScript 编译，页面质量仍依赖人工验收。

## 常用命令速查

| 命令 | 作用 |
|---|---|
| `uv sync` | 安装 / 同步 Python 依赖 |
| `uv add <package>` | 新增 Python 依赖 |
| `uv run python manage.py runserver` | 启动后端开发服务器（:8000） |
| `uv run python manage.py migrate` | 应用数据库迁移 |
| `uv run python manage.py makemigrations [app]` | 生成迁移文件 |
| `uv run python manage.py test [app \| 模块]` | 运行测试 |
| `uv run python manage.py check` | 校验项目配置 |
| `uv run python manage.py createsuperuser` | 创建超级管理员 |
| `uv run python manage.py startapp <name>` | 新建 Django app（之后要注册进 `INSTALLED_APPS`） |
| `uv run python manage.py collectstatic --noinput` | 收集静态文件（生产） |
| `uv run python manage.py maintenance on / off / status` | 全站维护拦截旗标（写 `run/MAINTENANCE`，`on` 可加 `--message`） |
| `cd frontend && npm ci` | 按 lockfile 安装前端依赖 |
| `cd frontend && npm run dev` | 前端开发服务器（:3000，HMR） |
| `cd frontend && npm run build` | 生产构建 → `frontend/dist/` |
| `cd frontend && npm test` | 前端单元测试（Vitest，一次性运行） |
| `cd frontend && npx playwright test` | 浏览器 E2E（自动起独立库与服务；详见「运行测试」） |
| `uv run python manage.py seed_e2e` | 生成 E2E 种子数据（幂等；仅测试环境） |
| `cd frontend && npm run copy-surveyjs` | 单独重跑 SurveyJS 静态文件拷贝（升级 survey-* / Chart.js 后需要） |
| `./start.sh` | 前台启动生产 ASGI（Gunicorn + `UvicornWorker`，1 worker）+ 更新守护进程 |

## 目录结构速览

```text
club-management-website/
├── config/            # Django 项目配置：settings.py / urls.py / asgi.py / wsgi.py
├── accounts/          # 账号、登录、邮箱认证、身份审核、会话、能力投影
├── about/             # 关于页内容
├── activities/        # 活动（众议 / 征集 / 展示 / 调研）与问卷
├── attachments/       # 统一附件与 tus 可续传上传
├── common/            # 站点策略、维护模式、富文本清洗、更新守护进程
├── exam_board/        # 考试看板（批次课表 + 题目误刊广播）
├── messaging/         # 评论区 / 私信 / 通知 / 横幅公告
├── news/              # 新闻
├── recruitment/       # 招聘（自我介绍问卷）
├── reviews/           # 发布审核 / 意见反馈 / 举报案
├── tasks/             # 任务与标签
├── tutorials/         # 教程
├── frontend/          # React SPA：src/ 源码、scripts/ 构建钩子、e2e/ 浏览器 E2E、dist/ 产物（gitignore）
├── scripts/           # 运维脚本：install.sh / pack-release.sh / updater.py
├── static/            # 静态资源（surveyjs/ 未哈希 min 文件、maintenance.html 等）
├── docs/              # 项目文档
├── manage.py          # Django 入口
├── start.sh           # 生产启动脚本（Gunicorn ASGI）
├── pyproject.toml     # Python 依赖与项目元数据
├── uv.lock            # uv 锁文件
├── .env.example       # 环境变量模板（复制为 .env）
├── CLAUDE.md          # 协作约定（命令节、访问控制原则）
├── CONTEXT.md         # 领域术语表
└── README.md
```

后端 URL 前缀（`config/urls.py`）：`/admin/`、`/site-policy/`、`/auth/`、`/tasks/`、`/messaging/`、`/activities/`、`/exam_board/`、`/news/`、`/reviews/`、`/about/`、`/tutorials/`、`/recruitment/`、`/attachments/`、`/uploads/`，其余路径统一回落到 SPA 入口 `index.html`。

## 常见改动怎么做

| 任务 | 步骤 |
|---|---|
| 新增 Django app | `uv run python manage.py startapp <name>` → 注册进 `config/settings.py` 的 `INSTALLED_APPS` → 在 `config/urls.py` 挂载前缀，并把该前缀加进 catch-all 的排除清单 |
| 新增前端可访问的 API 前缀 | 同步两处：`config/urls.py` 的排除清单 + `frontend/webpack.config.js` 的 `devServer.proxy`（漏一处，开发态请求会被 SPA 或 dev server 吞掉） |
| 新增前端页面 | 在 `frontend/src/App.tsx` 声明路由并 `React.lazy` 懒加载；需登录的包 `ProtectedRoute`；随后 `npm run build` 验证 |
| 新增后端配置项 | 密钥 / 基础设施 → `.env` + `.env.example` + `config/settings.py`；运营旋钮 → `common/models.py::SiteSettings` + 迁移 + `common/policy.py` 快照 + admin `fieldsets` |
| 改模型字段 | `uv run python manage.py makemigrations <app>` → `uv run python manage.py migrate` |
| 改接口 | 保持 DRF API 与前端能力一致：后端改字段名时同步 `frontend/src/api/` 与 `frontend/src/types/` |

## 注意事项

- `uv` 的任意命令都可能重写 `uv.lock`（镜像 URL 噪音）；提交前用 `git checkout uv.lock` 还原，别把锁文件噪音混进改动。
- 构建前端时若 webpack 报内存不足（`ERR_WORKER_OUT_OF_MEMORY`），用 `NODE_OPTIONS="--max-old-space-size=4096" npm run build` 重试——这是机器内存压力，不是代码问题。
- **未配 Redis 时不要把生产 ASGI worker 调到 1 以上**：内存 channel layer 无法跨进程扇出（`docs/adr/0015-channels-without-redis.md`）；配置 `REDIS_URL` 后由 `GUNICORN_WORKERS` 控制（`docs/adr/0021-postgresql-redis-and-multiworker.md`）。
- 生产升级走 GitHub Release + 更新守护进程，不要在服务器上 `git pull` 再手工构建。
- `frontend/dist/`、`media/`、`private_media/`、`data/`、`db.sqlite3`、`.env` 均不入库，全新 clone 缺这些是正常的。

## 进一步阅读（仓库内已有文档）

| 文档 | 内容 |
|---|---|
| `CONTEXT.md` | 领域术语表（任务、活动、众议、征集、展示、调研、作品……） |
| `CLAUDE.md` | 命令速查与访问控制原则（权限词汇、能力投影） |
| `docs/architecture/frontend.md` | SPA 的路由表、API 客户端约定、构建与产物细节 |
| `docs/api/` | 各 app 的接口文档 |
| `docs/operations/admin-guide.md` | 后台使用手册 |
| `docs/operations/deployment.md` | 运维与部署指南 |
| `docs/adr/` | 架构决策记录 |

## 下一步

- [架构总览](architecture/overview.md) —— 后端分层、请求链路、关键设计决策
- [API 总览](api/README.md) —— 各 app 的端点、认证与错误契约
- [部署](operations/deployment.md) —— 生产安装、升级、备份与回滚
- [配置参考](configuration.md) —— 环境变量、Django settings、站点策略、前端构建配置
