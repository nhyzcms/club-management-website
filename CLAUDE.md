# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Django)

```bash
uv run python manage.py runserver          # Start dev server
uv run python manage.py migrate            # Apply migrations
uv run python manage.py makemigrations     # Generate migrations
uv run python manage.py check              # Validate project config
uv run python manage.py test               # Run tests
uv run python manage.py test <app>         # Run tests for a single app
uv add <package>                           # Add a Python dependency
```

### Frontend (React)

```bash
cd frontend
npm run dev                                # Start dev server (localhost:3000, HMR); copies SurveyJS for Django admin
npm run build                              # Production build → frontend/dist/ (+ SurveyJS admin assets)
npx playwright test                        # Browser E2E: auto-starts Django (:8010) with a fresh DB + seed data
```

## Architecture

- **Python 3.14** + **Django 6.0** backend, managed with **uv** (`pyproject.toml` + `uv.lock`)
- **React 19** + **TypeScript** + **Webpack 5** frontend in `frontend/`, managed with **npm**
- Django settings module: `config/` (ROOT_URLCONF = `config.urls`)
- Frontend entry: `frontend/src/index.tsx` → built to `frontend/dist/`
- Database: SQLite (default, dev only)
- New Django apps: `uv run python manage.py startapp <name>` → add to `INSTALLED_APPS` in `config/settings.py`

## Access control

**控制访问 = 定义一个权限，用 `has_perm` 判定；绝不检查组名。** 权限由组分配、组决定身份、组由人手动管。四个正交轴各管一摊：

| 轴 | 来源 | 用途 |
|---|---|---|
| 身份徽章 | 登录态 + `is_superuser`/`is_staff`/`identity_verified` | 展示（访客/用户/管理员/超级管理员） |
| 角色能力 | `has_perm(...)` | **全部访问控制** |
| 组成员身份 | `user.groups` | 仅作「所属组」纯文本展示 |
| 对象所有权 | `creator==user` | 每行组合规则 |

硬规则：

- 权限词汇用 Django 默认 CRUD（`view`/`add`/`change`/`delete`，免费）+ 命名工作流权限（`Meta.permissions`，如 `approve_proposal`）；不造 `create_news` 这种重复。
- 访问控制走**命名 DRF `BasePermission` 子类**（挂 `permission_classes`）；状态机守卫（"pending 才能改"）不是访问控制，放 `lifecycle.py`。视图 `permission_classes` 应能独立说明"谁能访问"。
- 前端吃**语义化 `can_*` 能力布尔**（`accounts/views.py:_capabilities`），不吃原始权限代号；能力是纯角色投影，对象级"能不能动这条"由前端拿 `is_owner`/对象字段另行组合。
- 读默认走「身份 + 可见性」（`accounts/visibility.py`），不查 `view` 权限；仅敏感读（如 `view_feedback`）用专门 `view_*` 权限。
- 组**名**只作惰性展示文本，**绝不**进分支条件（含徽章——徽章按身份态四档派生，不从组名）。
- `is_superuser` 是唯一应用访问逃生舱；`is_staff` 在应用访问里零权限（只登 Django admin + 触发「管理员」徽章）。
- 拆新权限三条触发：持有者可能不同 / 前端门禁独立 affordance / 需独立审计；否则用最粗的已有权限。

详见 `docs/adr/0005-access-control-principle.md`。

## 工具链与改动流程（助手 / 新人必读）

- **写入与推送的载荷上限已解除**（2026-10-14 实测，见 `nhyzcms/app` 的 `docs/ENGINEERING-ENV.md`）：
  2 MiB 二进制文件可以**一次 `git push`** 落地；单次写入调用可以生成 1.1 万+ 字符的文档且逐字节无损。
  → 大文件、长文档**直接整文件写、直接推**；**不要**再为了体积拆片，**不要**再使用"补丁分片 + 一次性工作流"之类的临时通道。
- **改动一律走分支 + PR**（`feature/…` / `fix/…` / `docs/…`），不要直推 `main`；PR 被合并后若还要继续改，**另开分支/PR**。
- **不要在生产服务器上跑测试或构建**：该机为 **2 核 / 2 GB 内存 / 3 MB 带宽**，跑测试会拖垮在线服务。
  测试交 CI（四个作业：backend / frontend / frontend-test / e2e）；需要本机验证时用 SQLite 跑 `manage.py test`。
  生产应用目录 `/opt/club` 是**发布包解压目录、不是 git 仓库**，不要在它上面切分支。
- **前端无法在服务器构建**：本机与生产服务器都**没有 node/npm**，`npm run build` 只能在 CI 或你自己的机器上跑；
  改前端后不重建 `frontend/dist`，线上不会生效。
- **数据库迁移**：新增 `Meta.permissions` 等模型选项时**必须**同时生成 `AlterModelOptions` 迁移，
  否则权限不落库（历史踩坑）。
- **推送后自检**：CI 状态 + 关键接口/页面人工确认；涉及前端构建的改动，确认 `frontend/dist` 真的重建了。

### Issue tracker

Issues and PRDs live as GitHub issues in `nanhui-no1-media/club-management-website`, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles; the label string equals the role name (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.
