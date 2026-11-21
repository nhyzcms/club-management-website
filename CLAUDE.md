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
- **分支模型：Git Flow**（2026-11-20 起）。五条分支、四种流向，不要自创：

  ```
  main        ← 生产。只接受 release/* 与 hotfix/* 的 PR。每次合并都打 tag。
  develop     ← 下一个版本的集成点。feature/* 合进来，不要求 review。
  feature/*   ← 从 develop 拉，回 develop，合完即删。
  release/*   ← 从 develop 拉，合到 main + develop，发版当天删（冻结窗口，只修 bug）。
  hotfix/*    ← 从 main 拉，合到 main + develop，合完即删。
  ```

  - **`main` 只认两个来源**：`release/*` 或 `hotfix/*`。其它分支的 PR 会被 `source-guard`
    检查拦下——生产分支不接受"顺手改一下"，一切改动先落到 `develop`。
  - **评审只发生在合进 `main` 的那一次**，一次审完整批。`develop` 不设 review，
    否则评审人成瓶颈（3 人开发 1 人 review）。
  - **`hotfix/*` 必须回流 `develop`**，否则下一个 `release/*` 会把 bug 原样带回来。
    Release workflow 会自动开回流 PR，别忽略它。
  - **`release/*` 是冻结窗口**：切出后只修 bug，不再合入 `develop` 的新功能。
  - **测试文件必须跟功能代码一起进 `main`**。给测试单开分支会让 `main` 上的测试为空，
    CI 跑空集并报绿——最坏的一种失败（静默通过）。
  - **不要建 `test` 分支**，需要预演用容器化环境（见下）。
  - 各分支保护规则见 `CONTRIBUTING.md` 的「各分支的保护规则」表。
- **不要在生产服务器上跑测试或构建**：该机为 **2 核 / 2 GB 内存 / 3 MB 带宽**，跑测试会拖垮在线服务。
  测试交 CI（四个作业：backend / frontend / frontend-test / e2e）；需要本机验证时用 SQLite 跑 `manage.py test`。
- **生产机没有代码树**（2026-11-20 起容器化）：`/opt/club` 只剩 `.env` / `docker-compose.yml` /
  `data` / `staticfiles` / `run` / `backups` / `scripts/{deploy.sh,deploy-wrapper.sh}`。
  没有 `.git`、没有 `.venv`、没有 `frontend/`。不要在它上面切分支、装依赖或改代码。
  `club.service` 已删除，容器是 `club-app`（`restart: unless-stopped`），`docker logs club-app` 看日志。
- **前端在镜像里构建**：`Image` workflow 跑 `npm ci && npm run build`，产物进镜像；
  生产机永远不构建。改前端后等 Image/Deploy 走完即可，不需要在服务器上重建 `frontend/dist`。
- **上线路径**：合并 `main` → CI → Image（推 ghcr）→ Deploy（只登记）→ `club-deploy.timer` 在
  01:00–03:00 窗口内切容器。状态唯一真源是 `sudo -u clubdeploy /opt/club/scripts/deploy.sh status`。
- **发布流程**（人点两下，其余全自动；细则见 `CONTRIBUTING.md` 的「发布流程」）：

  ```bash
  gh workflow run release.yml --ref develop -f bump=patch     # 或 -f version_override=X.Y.Z
  ```

  1. 从 **`develop`**（不是 main）切 `release/vX.Y.Z`，bump `pyproject.toml` + 写 `CHANGELOG.md`，
     推分支并对 `main` 开 PR。
  2. PR 过 `source-guard` + 1 review + `backend`/`frontend`/`frontend-test`/`e2e`。
  3. 合并后自动：打 tag `vX.Y.Z` → 建 Release → 关旧 Milestone/开新 → `ci.yml` 的 `release` job
     打包 `club-<sha>.tar.gz` 挂到该 Release → `back-merge` job 开「main → develop」回流 PR →
     Image 构建 → Deploy 登记待发布。
  4. **回流 PR 必须合**：不合回 `develop`，下一个 `release/*` 会把已修好的问题原样带回来。
  5. 验证线上：`curl https://<站点>/version/`，`channel=release` 且版本号与刚发的一致才算切上去。

  - **不要手改版本号、不要手写 CHANGELOG**：前者由 `bump_version.py` 算，后者由
    `release_notes.py` 按 Conventional Commits 分类生成。提交信息不规范，发布说明就不像话。
  - **发布说明只发一份**：挂在该版本 Release 的资产里，不恢复「每提交一个 `club-<sha>` Release」。
  - **卡点**：① Actions 建 PR 需要组织/仓库打开 `can_approve_pull_request_reviews`（该开关同时
    允许 workflow 审批 PR）；② `GITHUB_TOKEN` 建的 PR 触发的 run 可能是 `action_required`，
    去 Actions 页面点一次 Approve；③ `main` 要 1 个 review，不能自批。
- **预演环境**：`sudo scripts/test-env.sh up sha-<submit>`，只绑 `127.0.0.1:8080`，用
  `ssh -N -L 8080:127.0.0.1:8080 nhyz-prod` 访问。数据库 `club_test`、Redis db 1、独立媒体/静态目录，
  与生产完全隔离。验完 `down`，需要清数据用 `reset --yes`。详见 `deploy/README.md`。
- **版本号不要手改**：`pyproject.toml` 的 `version` 只由 `release.yml` 在切 `release/*` 时 bump；
  `build_info.json` 由 `scripts/gen-build-info.sh` 在 `docker build` 前生成，**在 `.gitignore` 里，不进仓库**。
  构建侧靠「提交是否改了 pyproject 的 version」判断 release / dev，因此不需要等 tag（tag job 是并发跑的）。
  线上版本：`curl https://<站点>/version/`，或 `docker exec club-app .venv/bin/python manage.py version`。
  `channel=dev` 的版本号形如 `1.0.1-dev.<距上个 tag 的提交数>.g<sha7>`。
  **弹窗文案**：`CHANGELOG.md` 版本小节标题下的 `> …` 引用块会成为弹窗第一句；没写就只剩
  自动生成的 commit 条目。`ci/test/chore/build` 类型不进弹窗（留给 git log）。
  **前端**：页脚显示版本号（`/version/`），发版后版本变化弹一次「这次的更新」——内容来自
  `/changelog/`，由 `scripts/gen_changelog.py` 把 CHANGELOG.md 的当节转成 `changelog.json` 带进镜像。
  弹窗只在 `channel=release`、且用户见过旧版本、且确有说明时才弹（首次访问只记录不打扰）。
- **数据库迁移**：新增 `Meta.permissions` 等模型选项时**必须**同时生成 `AlterModelOptions` 迁移，
  否则权限不落库（历史踩坑）。
- **推送后自检**：CI 状态 + 关键接口/页面人工确认；涉及前端构建的改动，确认 Image workflow 真的重建了镜像。

### 移动端与 App 契约

- **手机版与桌面版是两套页面**：`/m` 页面不用 `AppShell`，二级页统一走 `components/MobilePage.tsx`。
  新增桌面工作流页面时，若该功能对手机用户必要，同时补一个 `/m` 实现，并在 `App.tsx` 的
  `MobileAware` 里登记改道；审核台的取数规则在 `frontend/src/utils/reviewDesk.ts`（两端共用，勿复制）。
- **入口不重复**：首页九宫格或「关于我们」里已有的功能，不在「我的」再列一次；
  手机版考试看板只保留管理员的「考试日程编辑」，不渲染看板本体。
- **未读红点**的数据源在 `frontend/src/api/unreadBadges.ts`：30 s 轮询 + 窗口可见/聚焦刷新，
  并监听 App 壳派发的 `club:unread` 常量事件。`/m` 页面不用 `AppShell`，桌面顶栏那套徽标与它们无关。
- **App 壳 UA 契约**：`NhyzClubApp/<versionName> (Android; <versionCode>)`。改壳的 UA 必须同步
  `frontend/src/utils/device.ts`，否则「App 内默认跟随系统深色」等 App 专属行为会静默失效。
- **`MIN_SHELL_VERSION_CODE` 慎动**：提高它等于把老壳用户挡在门外（只留「暂时继续」），
  只有老壳真的会让网站出错时才动；改完同步 app 仓库的 `docs/FEATURE-MATRIX.md`。

### 数据删除

- **账号注销是软删除**（[ADR-0027](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/adr/0027-account-deletion.md)）：
  `Profile.deleted_at` 标记，只清邮箱 / 头像 / 身份证明材料 / 会话等敏感信息；
  `User`、`Profile`、`MemberIdentity`（社员编号）行永不删除。新增「删除用户」类功能时先读该 ADR，不要物理删账号。

### Issue tracker

Issues and PRDs live as GitHub issues in `nanhui-no1-media/club-management-website`, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles; the label string equals the role name (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.
