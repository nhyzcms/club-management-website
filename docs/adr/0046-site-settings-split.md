# 站点策略：`SiteSettings` 拆成五张领域表

日期：2026-10-30
状态：已实施（PR #249）
相关：ADR-0044（账号拆表，同一套思路）

## 背景

`common.SiteSettings` 是一个 33 字段的单例表，装着五类完全不相干的配置：

| 领域 | 字段数 | 例子 |
|---|---|---|
| 认证 | 6 | `verification_enabled`、`admin_valid_days`、`member_claim_enabled` |
| 频控 | 13 | `login_per_ip_per_hour`、`reports_per_user_per_day`、`stepup_email_per_user_per_hour` |
| 上传 | 2 | `sync_upload_max_bytes`、`tus_media_max_bytes` |
| 自动更新 | 8 | `auto_update_enabled`、`update_window_start`、`update_release_keep` |
| 内容 | 4 | `comment_max_depth` 等 |

问题不在字段数量，在于：

1. **改一处要写整行**。管理员改「评论最大嵌套层数」，`save()` 会把 33 个字段一起写回。
   两个管理员同时改不同领域，后者覆盖前者。
2. **缓存失效粒度粗**。任何字段变化都 `invalidate_policy_cache()`，整份 `SitePolicy` 重建。
3. **admin 是一个 33 字段的长表单**，没有领域分组，改错了很难发现。
4. **权限没法分**。理论上「谁能改频控」和「谁能改更新窗口」是不同的人，但同表同权限。

## 决定

拆成五张 singleton 表，各管一域：`AuthPolicy` / `RateLimitPolicy` / `UploadPolicy` /
`UpdaterPolicy` / `ContentPolicy`。

**`get_policy()` 的返回值一个字段都没改。** 它仍然返回同一个 `SitePolicy` dataclass，
33 个字段、名字、默认值全部不变。这是这批改造零风险的前提——**所有调用方一行都不用动**。

`_snapshot(rows)` 改成吃五行，用 `pick(row, name, default)` **逐字段**回落默认值：

```python
def _snapshot(rows):
    return SitePolicy(
        login_per_ip_per_hour=pick(rows["rate"], "login_per_ip_per_hour", 10),
        ...
    )
```

逐字段而不是整份回落，是因为某张表还没建行时只应该影响它自己的字段，
不能让整份策略回到默认值。

## singleton 怎么保证

`_SingletonPolicy` 抽象基类：

- `save()` 强制 `pk=1`，然后 `invalidate_policy_cache()`
- `delete()` 永远返回 `(0, {})` —— **拒绝删除**

`delete()` 为什么拒绝：删掉一行之后 `_snapshot` 会让那张表的所有字段静默回落默认值。
频控默认值比线上配置**松**，所以「删了一行」等于「悄悄放开了限流」，而且没有任何报错。
这种失败模式比崩溃难查得多。

## admin 必须同批改

旧 `SiteSettings` 从 admin 撤下，换成五个 `_SingletonPolicyAdmin`（禁止新增、禁止删除、
changelist 重定向到 change 页）。

**这一步不能拆到后面做。** `get_policy()` 改读新表之后，旧 admin 还在的话，管理员
「改了设置但没效果」——这比报错更糟，因为它看起来成功了。

## 测试怎么改的

36 个测试失败，全是同一个模式：造一个旧 `SiteSettings` 行，然后断言 `get_policy()` 的值。

这些测试在旧表已经没人读之后**仍然通过**——因为 `get_policy()` 那时还在读旧表。
换句话说，它们测的是「我写进去的东西能读出来」，而不是「策略生效」。拆表后它们集体失败，
暴露了这层耦合。

改法：新增 `common/testing.py` 的 `set_policy(**fields)`，**按字段名查表**：

```python
set_policy(comment_max_depth=1)   # 不关心它住哪张表
```

这样 5 个模型名不会泄漏到 36 个测试里。测试关心的是「把 `comment_max_depth` 设成 1」，
不是「`ContentPolicy.comment_max_depth = 1`」。

`test_policy.py` 重写了 admin 断言（从「一个 33 字段 fieldsets」改成「五张表各管各的」），
但**默认值断言一字未改**——那是 `SitePolicy` 的契约，不是实现的细节。
另外加了一条 `test_all_thirty_three_fields_are_covered_once`：总数 33 且无重复，
防止以后加字段时漏进某张表。

## 迁移

`common/0018_split_site_settings.py`：

- `GROUP_FIELDS` 把 33 个字段映射到 5 个模型
- `copy_from_settings` / `copy_back` 双向搬运
- `RunPython` 必须排在 `CreateModel` **之后**

第三点踩了两次：`makemigrations` 自动生成的顺序把 `RunPython` 放在了 `CreateModel`
前面，迁移直接 `LookupError: App 'common' doesn't have a 'AuthPolicy' model`——那时表还不存在。
第二次生成还是错，所以改成手写并显式排序。

往返实测：0017 造 `login_per_ip_per_hour=42` / `comment_max_depth=7` /
`update_release_keep=9` / `sync_upload_max_bytes=123456` → 升 0018 五表全对 →
回滚 0017 四个值原样回来。

## 后果

- 改一个领域的配置只写那一行，不再覆盖其他领域。
- admin 分成五个页面，每个页面的字段都在同一语义下。
- 代价：`get_policy()` 每次要查 5 张表而不是 1 张。有缓存（`load_policy` + `invalidate_policy_cache`），
  冷启动时 5 次单行查询，可忽略。
- 旧的 `SiteSettings` 表**还在**（存量数据已搬走，回滚路径已验证）。删表留给后续批次——
  本批的目标是「建新表 + 切读 + 撤 admin」，不把删表和切读绑在一起。
