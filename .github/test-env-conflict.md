自动同步 `develop → test-env` 时发生合并冲突，test 环境本轮未构建 / 未部署。

## 处理方式（本地）

```bash
git fetch origin
git checkout -B test-env origin/test-env
git merge origin/develop     # 解决冲突
git push origin test-env
```

推送合并结果后，到 Actions 手动跑一次 `Test Env`，或等下一次 `develop` 推送。

## 常见冲突面

- `deploy/test/` 下的文件通常只由 test-env 维护，develop 不应触碰；若两侧都改了，**以 test-env 侧为准**（它就是这套环境的唯一真源）。
- 其他路径按正常 Git Flow 处理，解决后必须回到 develop 同步改一遍，否则下次还会冲突。

> 本 issue 由 `.github/workflows/test-env.yml` 自动创建，冲突解决后可关闭。
