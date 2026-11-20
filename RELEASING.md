# 发布流程

版本号遵循 **SemVer 2.0.0**：`MAJOR.MINOR.PATCH`，git tag 形如 `v1.2.3`。
变更记录遵循 **Keep a Changelog**（`CHANGELOG.md`）。

## 三个数字什么时候动

| 位置 | 什么时候 +1 | 本站的判据 |
|---|---|---|
| **MAJOR** | 不兼容变更 | 公开 API 字段 / 路由 / 配置键 / 环境变量被删除或改名；前端持久化数据结构不兼容旧版本 |
| **MINOR** | 向后兼容的新功能 | 新增业务模块、新增页面、新增权限、新增配置项（带默认值） |
| **PATCH** | 向后兼容的修复 | 修 bug、改文案、调样式、补测试、内部重构（行为不变） |

判不准时按「**往大里算**」：一个该升 MINOR 却发了 PATCH 的版本，
会让使用者以为升级无风险，实际会撞到新行为。

`0.y.z` 的语义是「公开接口随时会变」。本站已有生产用户，**从 1.0.0 起**
不再回到 0.x。

## 一次发布怎么做

### 1. 攒够内容

合并进 `main` 的 PR 会自动挂到「当前开放的版本 Milestone」
（`.github/workflows/milestone.yml`，取编号最小的开放 `v*` Milestone）。
这个 Milestone 就是「本次要发的东西」。

```bash
gh api "repos/nhyzcms/club-management-website/milestones?state=open" \
  --jq '.[] | "\(.title)　open=\(.open_issues) closed=\(.closed_issues)"'
```

### 2. 触发发布（二选一）

```bash
# 自动递增
gh workflow run release.yml --ref main -f bump=minor

# 直接指定（首个版本或需要跳号时）
gh workflow run release.yml --ref main -f version_override=1.2.0
```

Workflow 会算出版本号、改 `pyproject.toml` 的 `version`、往 `CHANGELOG.md`
插一个新小节，然后开一个 `release/vX.Y.Z` 的 PR。

### 3. 评审并合并那个 PR

它和普通 PR 走同样的闸门（四个 CI 检查 + 1 人 review）。
**这一步就是「发布审批」**——你批准的是「本次发布的变更集与版本位」。

### 4. 合入后自动完成剩下的事

`main` 上 `pyproject.toml` 的版本一变，Release workflow 立刻：

1. 打 annotated tag `vX.Y.Z`
2. 建 GitHub Release（正文是上一个 `v*` tag 到本次之间的分类变更记录）
3. 给容器镜像补一个可读 tag `ghcr.io/nhyzcms/club-management-website:vX.Y.Z`
4. 关闭 `vX.Y.Z` 这个 Milestone，并开出下一个 MINOR 的 Milestone

生产切换仍按容器部署那套走（`deploy/README.md`）：Deploy workflow 只登记，
窗口内由服务器上的 timer 切换。

## 变更记录怎么生成

`scripts/release_notes.py` 读 `git log` 的首行前缀，按 Conventional Commits 分类：

```
feat(scope): 摘要      → Added
fix(scope): 摘要       → Fixed
perf / refactor        → Performance / Changed
docs / test / ci       → 对应小节
feat!: 或 BREAKING CHANGE: 脚注 → Breaking（置顶）
```

为什么读 commit 而不是 PR 标签：本仓库有直推 main 的提交，PR 标签覆盖不全，
commit 前缀才是全量。

手工核对：

```bash
python3 scripts/release_notes.py --since v1.0.0 --until HEAD
```

## 回滚

```bash
# 代码回滚到上一个版本镜像（数据库迁移不回退）
sudo -u clubdeploy /opt/club/scripts/deploy.sh rollback

# 回到指定版本
sudo -u clubdeploy /opt/club/scripts/deploy.sh now v1.2.2
```

`deploy.sh` 的 tag 白名单只认 `sha-<hex>`。用版本 tag 回滚要先在服务器上
解析成 sha：

```bash
docker image inspect ghcr.io/nhyzcms/club-management-website:v1.2.2 \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

然后把得到的 sha 传给 `deploy.sh now sha-<sha>`。

## 常见问题

**发布 PR 一直没合，会不会重复触发？** 不会——Workflow 只在手动 dispatch 时开 PR，
同一个 `release/vX.Y.Z` 分支重复推送会更新同一个 PR。

**能不能直接推 main 再打 tag？** 不能。`main` 有分支保护。发布也必须是 PR。

**Milestone 空了但还想发？** 可以，Milestone 只用于规划，不是发布的前置条件。

**patch 版本要不要单开 Milestone？** 不要。patch 不改变规划范围，
挂在当前 MINOR 的 Milestone 下即可。
