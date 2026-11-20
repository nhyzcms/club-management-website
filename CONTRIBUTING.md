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
feat/postcard-barcode-autofocus
fix/login-scrim-drag
chore/ci-concurrency
docs/api-events
```

- 类型只用：`feat` / `fix` / `chore` / `docs` / `refactor` / `test` / `ci`
- **一个分支只做一件事。** 顺手改的无关文件请单独开分支。
- 分支生命周期目标 ≤ 1 周。超过两周的分支要么拆、要么合，不要长期悬空。
- 合并后分支**自动删除**（仓库已开启 `delete_branch_on_merge`）。需要保留的长期分支只有四个：`main`、`develop`、`documentation`、`assets/pr-previews`。

### 分支模型

```
main        ← 生产。PR + 1 人 review + 四道必需检查，只接受 develop / fix 的合并
develop     ← 集成。feat/* 合进来的地方，只要求 CI 绿，不要求 review
feat/* fix/* ← 短命，从 develop 拉，合完即删
```

- **`develop` 不需要 review。** 集成分支的作用是把三个人各自的改动汇到一起，
  让 CI 先跑一遍。真正的评审发生在 `develop` → `main`，**一次审完全部**。
  给 `develop` 也加 review 只会让评审人变成瓶颈。
- **`fix/*` 急用时可以从 `main` 拉**，直接对 `main` 开 PR。仍然要过完整 CI + review
  ——"急"省掉的是绕经 develop 那一跳，不是省掉验证。**对 `main` 的 PR 一律跑全套 e2e**，
  不因为在急修就跳过。
- **发版后把 `main` 合回 `develop`**（`git checkout develop && git merge main`），
  否则两条线会越走越远，最后合并时冲突集中爆发。
- 测试文件**跟功能代码一起进 `main`**。不要为测试单独开分支：`main` 上没有测试文件时，
  CI 会静默跑空集并报绿，这是最坏的一种失败。

### 三个特殊分支

- **`documentation`** —— 文档站点。`main` 上不允许出现 `docs/` 目录，`docs-guard` 检查会拦下。改文档请对该分支开 PR。
- **`assets/pr-previews`** —— PR 预览图床。只放图片，不放代码；不要为每个 PR 新建一条 assets 分支。
- **`develop`** —— 集成缓冲。见上。

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

## 合并与上线

- 合并用 **merge commit**，不用 squash（保留每个提交的上下文）。
- **合并 ≠ 上线。** 生产部署由维护者执行，卡在夜间窗口内自动进行；合并后不会立刻影响线上。
- 紧急修复也走 PR。确实需要绕过 CI 时，由维护者临时调整分支保护并记录原因——不要靠「某个账号能直推」当通道。

---

## 报告问题

用 `.github/ISSUE_TEMPLATE/` 里的模板。安全漏洞**不要**开 issue，直接私下联系维护者。

提 issue 前先搜一遍已有关闭的 issue——很多问题已经修过了。
