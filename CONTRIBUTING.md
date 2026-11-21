# 参与开发

南汇一中传媒社 · 社团管理系统。本文件是**唯一**的协作约定来源；与其它文档冲突时以本文件为准。

仓库是公开的，任何人可以 fork、提 PR。校内成员通常没有自己的电脑，因此**不要求 fork**：直接在仓库内开分支是允许的（见下方「两条路径」）。

---

## 两条路径

| 你是谁 | 怎么做 |
|---|---|
| 有仓库写权限（校内维护者） | 在仓库内开分支 → 推分支 → 开 PR |
| 没有写权限（外部贡献者 / 同学） | fork → 在自己的 fork 开分支 → 向上游开 PR |

两条路径的评审标准完全一样。**没有任何一条路径允许直接 push 到 `main`。**

---

## 分支

格式：`<类型>/<短横线描述>`，全小写，不用中文、不用空格。

```
feature/postcard-barcode-autofocus
hotfix/login-scrim-drag
release/v1.2.0
chore/ci-concurrency
```

- **一个分支只做一件事。** 顺手改的无关文件请单独开分支。
- 短命分支生命周期目标 ≤ 1 周，超过两周要么拆、要么合。
- 合并后分支**自动删除**（仓库已开启 `delete_branch_on_merge`）。
  长期分支只有四条：`main`、`develop`、`documentation`、`assets/pr-previews`。

## 分支模型（Git Flow）

```
main        ●───────────────●───────────────●      只接受 release/* 与 hotfix/*
             ╲             ╱ ╲             ╱
release/v1.2.0 ●───●───●        release/v1.3.0 …  冻结窗口，只修 bug
               ╱         ╲      ╱
develop    ●──●─────●─────●────●                   下一个版本的集成点
            ╲    ╱   ╲    ╱
feature/*    ●──●      ●──●                        单个功能，合完即删
```

| 分支 | 从哪来 | 合到哪 | 谁可以往里写 |
|---|---|---|---|
| `main` | — | — | 只有 `release/*`、`hotfix/*` 的 PR |
| `develop` | 由 `main` 初始化 | — | `feature/*` 的 PR；`release/*`、`hotfix/*` 回流 |
| `release/*` | `develop` | `main` + `develop` | 发布负责人可直接提交（冻结期修 bug） |
| `feature/*` | `develop` | `develop` | 作者本人 |
| `hotfix/*` | `main` | `main` + `develop` | 值班人 |

### 五条硬规矩

1. **`main` 只认两个来源。** `release/*` 或 `hotfix/*`，其它分支的 PR 会被 `source-guard`
   拦截。生产分支不接受「顺手改一下」——任何改动都得先落到 `develop`。
2. **`develop` 不要求 review。** 三个人的改动先汇到一起让 CI 跑一遍，
   真正的评审发生在合进 `main` 的那一次，一次审完全部。
   给 `develop` 也加 review 只会让评审人变成瓶颈。
3. **`release/*` 是冻结窗口，不是长期分支。** 切出来之后只允许修 bug，
   不允许把 `develop` 上的新功能再合进来。发版完成当天删除。
4. **`hotfix/*` 必须回流。** 合进 `main` 之后如果不合回 `develop`，
   下一个 `release/*` 会把修好的 bug 原样带回来——这是 Git Flow 最常见的翻车方式。
   回流 PR 由 Release workflow 自动开，别忽略它。
5. **测试文件跟功能代码一起进 `main`。** 不要为测试单开分支——
   `main` 上没有测试文件时，CI 会跑空集并报绿，这是最坏的一种失败。

### 版本号：谁都不用手改

```
pyproject.toml 的 version   ← 只由 release/* 分支改（Release workflow 自动 bump）
build_info.json             ← 只由 CI 在构建镜像前生成，不进仓库
GET /version/               ← 程序自报：version / channel / commit / 构建时间
```

- **不要手改 `pyproject.toml` 的版本号。** 它由 `release.yml` 在切 `release/*` 时改，
  于是「版本号变了的那个提交」就是发布提交本身——构建侧据此判断 release / dev，
  不需要等 tag（tag 由另一个 job 并发创建，等它会有竞态）。
- **`build_info.json` 不要提交。** 它在 `.gitignore` 里，由 `scripts/gen-build-info.sh`
  在 `docker build` 前写入构建上下文。提交它就意味着每条分支都要处理一次冲突。
- **判断线上跑的是哪一版**：`curl https://<站点>/version/`，或在服务器上
  `docker exec club-app .venv/bin/python manage.py version`。
  返回里的 `channel=dev` 说明这是分支构建（版本号带 `-dev.<n>.g<sha>`），
  `channel=release` 才是打过 tag 的发布版本。

### 各分支的保护规则

| 分支 | 保护规则 |
|---|---|
| `main` | PR + 1 人 review + `source-guard` + `backend`/`frontend`/`frontend-test`/`e2e`；禁强推、禁删除 |
| `develop` | PR + `backend`/`frontend`/`frontend-test`；禁强推、禁删除（不要求 review） |
| `release/*` | 禁强推（冻结期不许重写历史）；push 即跑 CI |
| `hotfix/*` | 禁强推；push 即跑 CI |
| `feature/*` | 无 |

`feature/*` 不给保护是有意的：它通常一天就没了，加规则只会在删除分支时添麻烦。

### 两条特例分支

- **`documentation`** —— 文档站点。`main` 上不允许出现 `docs/`，`docs-guard` 会拦下。
  改文档对该分支开 PR。禁强推、禁删除。
- **`assets/pr-previews`** —— PR 预览图床。只放图片，不放代码。禁强推、禁删除。

### 预演环境

想在合并进 `main` 之前点一遍真实页面，用**容器化预演环境**，不要另开分支：

```bash
sudo scripts/test-env.sh up sha-<develop 的提交>
ssh -N -L 8080:127.0.0.1:8080 nhyz-prod     # 另开一个终端
# 浏览器 http://127.0.0.1:8080/
sudo scripts/test-env.sh down                # 验完就关
```

它跑的是 `develop` 的镜像，但数据库（`club_test`）、媒体目录、静态目录、Redis db 序号
全部独立，停掉或清空都碰不到生产。不需要开安全组、不需要域名证书。

---

## 提交信息

```
<类型>(<范围>): <中文摘要>

<为什么这么改，而不是改了什么——diff 已经说明改了什么>
```

- 类型同上表；范围是模块名（`news` / `accounts` / `ci` …），可省略。
- 摘要用中文，不超过 60 字，不加句号。
- 一次提交一件事。格式化与逻辑修改不要混在一个提交里。

---

## Pull Request

### 必须满足

1. **base 是 `main`**（文档改动 base 是 `documentation`）。
2. **CI 必须绿**：`backend` / `frontend` / `frontend-test` / `e2e` 四个检查。
   - `e2e` 在 PR 上默认是**跳过**的（省 5–20 分钟）。跳过也报 success，不阻塞合并。
   - 改了登录、路由、上传、审核台、问卷这类跨页流程时，给 PR 打 **`ci:full`** 标签，re-run workflow 跑全套浏览器测试。
3. **至少 1 人 review 通过。** 不能自己批自己——你的 PR 必须由另一个人点 Approve。
4. **分支与 `main` 无冲突。** 冲突自行 rebase，不要用 merge commit 把 `main` 拉进功能分支。

### 描述写什么

用 `.github/PULL_REQUEST_TEMPLATE.md`。三件事必须写清楚：

- **为什么改** —— 关联 issue（写 `Refs #123`；确实要关闭才写 `Closes #123`）
- **怎么验证** —— 可执行的命令或可点的路径，不要写「应该没问题」
- **影响面与回滚** —— 涉及迁移、权限、配置键、上传路径时必填

### 不要

- 不要一个 PR 混多个不相关主题
- 不要把 review 意见的讨论塞进 commit 历史（讨论留在 PR 里）
- 不要为了让 CI 变绿而跳过或删除测试
- 不要在没有迁移文件的情况下改模型（CI 会以 `no such column` 大面积报错）

---

## 本地开发

```bash
uv sync                                   # 装依赖（Python 3.14）
.venv/bin/python manage.py test           # 全量后端测试，约 140s
.venv/bin/python manage.py test news      # 定向测试，迭代时用这个
DJANGO_DEBUG=1 .venv/bin/python manage.py makemigrations <app>   # 非 test 子命令必须带 DEBUG

cd frontend && npm ci && npm run build    # 前端构建
cd frontend && npm test                   # Vitest 单测
cd frontend && npx playwright test        # 浏览器 E2E（首次需装 chromium）
```

跑测试用 `.venv/bin/python` 直调，不要用 `uv run`——`uv run` 每次都会重写 `uv.lock`，给 diff 添噪音。

---

## 发布流程

一次发布只需要人点两下，其余全是自动的。**不要手改版本号，也不要手写 CHANGELOG。**

### 1. 发起

```bash
gh workflow run release.yml --ref develop -f bump=patch   # patch | minor | major
# 版本号算不准时可以直说：
gh workflow run release.yml --ref develop -f version_override=2.0.0
```

workflow 会从 `develop`（不是 `main`——`main` 上可能还缺已集成的改动）切出
`release/vX.Y.Z`，把 `pyproject.toml` 的 version 和 `CHANGELOG.md` 的新小节一起提交，
推上去并对 `main` 开 PR。

CHANGELOG 的分类来自 commit message 的 Conventional Commits 前缀，区间是上一个
`v*` tag 到本次提交。所以**提交信息写规范**，发布说明才像话。

**但自动生成的只是草稿。** 它给的是 `**ci**: 恢复打包 job` 这种原文，而看这个弹窗的是社员。
发版 PR 合并前，在该节标题下补一行引用块，它会作为弹窗最上面那句话：

```markdown
## [1.1.0] - 2026-11-22

> 页面底部现在能看到版本号，发版后会告诉你这次改了什么。

### Added
```

`ci` / `test` / `chore` / `build` 这几类改动**不会**进给社员的那份（git log 里一条不少），
流水线怎么排队跟社员没有关系。

### 2. 看 PR

`release/*` → `main` 的 PR 会跑全套：`source-guard`（来源必须是 `release/*` 或
`hotfix/*`）+ 1 人 review + `backend` / `frontend` / `frontend-test` / `e2e`。

`release/*` 是**冻结窗口**：这个分支上只修 bug，不要再把 `develop` 的新功能合进来。

### 3. 合并后自动发生的事

```
合并进 main
  ├─ release.yml  tag   → 打 vX.Y.Z、建 Release、关旧 Milestone、开下一版 Milestone
  ├─ release.yml  back-merge → 自动开「main → develop 回流 PR」，务必合并
  ├─ ci.yml       release → 打包 club-<sha>.tar.gz，作为资产挂到该版本的 Release
  ├─ image.yml    image  → 构建并推 ghcr.io/nhyzcms/club-management-website:sha-<sha>
  └─ deploy.yml   deploy → 登记「待发布」，等夜间窗口切容器
```

**回流 PR 不能忽略。** 不合回 `develop`，下一个 `release/*` 会把已修好的问题原样带回来。

**发布包只发一份。** 资产挂在 Releases 页面对应版本下（`club-<sha>.tar.gz` + `.sha256`），
不再每次提交都建一个 Release。

### 4. 验证线上

```bash
curl -s https://<站点>/version/ | python3 -m json.tool
```

`channel=release` 且版本号就是刚发的那个，说明镜像已经切过去了。
`channel=dev` 说明还在跑分支构建。

### 5. 常见卡点

| 现象 | 原因 | 处理 |
|---|---|---|
| `GitHub Actions is not permitted to create or approve pull requests` | 组织/仓库关了 Actions 建 PR | 设置里打开 `can_approve_pull_request_reviews`（同时也会放开 Actions 审批 PR） |
| PR 的 CI 停在 `action_required` | `GITHUB_TOKEN` 建的 PR 触发的 workflow 要人工放行 | 在 Actions 页面点一次 Approve；通常几十秒内会自行开始 |
| `source-guard` 红 | PR 的 head 不是 `release/*` 或 `hotfix/*` | 改动先落 `develop`，别直接对 `main` 开 PR |
| 合并被拒 `At least 1 approving review is required` | `main` 需要 1 个 review，且不能自批 | 找另一位维护者审；不要用 admin 绕过 |

---

## 合并与上线

- 合并用 **merge commit**，不用 squash（保留每个提交的上下文）。
- **合并 ≠ 上线。** 生产部署由维护者执行，卡在夜间窗口内自动进行；合并后不会立刻影响线上。
- 紧急修复也走 PR。确实需要绕过 CI 时，由维护者临时调整分支保护并记录原因——不要靠「某个账号能直推」当通道。

---

## 报告问题

用 `.github/ISSUE_TEMPLATE/` 里的模板。安全漏洞**不要**开 issue，直接私下联系维护者。

提 issue 前先搜一遍已有关闭的 issue——很多问题已经修过了。
