# 账号拆表：`Profile` 拆成身份、生命周期两张表

日期：2026-10-30
状态：已实施（PR #218–#223、#237）
相关：ADR-0025（社员身份编号）、ADR-0027（账号注销）、ADR-0041（账号有效期）

## 背景

`accounts.Profile` 是 `User` 的 `OneToOne`，长期承担了四种互不相关的事情：

| 关心的事 | 字段 |
|---|---|
| 我是谁（名册身份） | `real_name`、`identity`（识别码）、`card_no`（校牌号） |
| 这个账号还能不能用 | `expiry_disabled_at`、`deleted_at`、`validity_notice_ack`、`must_change_password` |
| 注册时填的 | `registration_deadline` |
| 展示用的 | `avatar`、`bio`、`nickname` |

这带来的具体问题是：

1. **查询要 JOIN 一张宽表**。判断「这个用户是否已注销」要 `user__profile__deleted_at__isnull=True`，
   而这个条件散落在 20 多个 queryset 里；每加一处就多一次漏写的风险。
2. **写冲突**。用户改昵称会 `profile.save()`，而 `save()` 会连带的把生命周期字段一起写回——
   并发下「改昵称」和「管理员停用」互相覆盖。
3. **语义混淆**。「名册里有这个人」和「这个账号能登录」是两件事，但存在同一行里，
   导致「注销用户是否还占名册」这类问题没有唯一答案。

## 决定

拆成两张表，各自单一职责：

- **`AccountIdentity`**：名册身份。`real_name`、`identity`、`pending_card_no`、`registration_deadline`。
  由名册导入与身份审核维护，与账号能否登录无关。
- **`AccountLifecycle`**：账号状态。`deleted_at`、`expiry_disabled_at`、`validity_notice_ack`、
  `must_change_password`。

`Profile` 保留展示字段（`avatar`、`bio`、`nickname`），不再是「什么都有」的垃圾桶。

状态判定收敛到 `accounts/status.py` 的 `account_state(user)`，返回四态：

| 状态 | 含义 | 优先级 |
|---|---|---|
| `deleted` | 已注销 | 1（最高） |
| `admin_expired` | 管理员停用 | 2 |
| `unverified_expired` | 超期未验证 | 3 |
| `active` | 可用 | 4 |

优先级顺序有生产数据支撑：37 个用户里 1 个 `is_active=False` 且 `deleted_at` 非空——
如果「停用」优先于「注销」，这个用户会显示成「管理员停用」而不是「已注销」，
与实际操作历史不符。

**没有 `inactive` 这个状态。** 计划里列了第五态，但查遍生产数据与代码路径都不可达。

## 迁移怎么做的

分五个 PR，不是一次性切换：

1. **建表 + 双写**（#218/#219）：`Profile.save()` 里 `ensure_split_rows()` 补行。
   覆盖 `save()` 而不是挂 `post_save` 信号，因为信号会在 `Profile` 未保存时也触发。
   **不包 `atomic`**——否则「影子表写失败」会升级成「用户改资料失败」。
2. **切读**（#220）：`accounts/queries.py` 提供 `not_deleted_q()` 等，queryset 改成
   「新表优先 + 缺行回落旧列」。
3. **校验命令**（#221）：`check_profile_sync` 比对两边，部署前必须 `exit=0`。
4. **权威归一**（#222/#223）：校牌号归到 `MemberIdentity.card_no`，`Profile.card_no` → `pending_card_no`。
5. **删旧列**（#237）：8 个字段从 `Profile` 移除。

## 踩到的三个坑

### 1. 「新表优先 + 缺行回落」不能写成 INNER JOIN

直觉写法是：

```python
User.objects.filter(user__lifecycle__deleted_at__isnull=True)
```

这是 INNER JOIN——**新表里没有行的用户会被整个排除**，包括所有新注册用户。
正确写法必须显式走 LEFT JOIN（`isnull=True` 在 Django 里会被翻成 LEFT JOIN），
并且保留对旧列的回落。

### 2. `not_deleted_q()` 包含缺行用户不是 bug

同上：`isnull=True` 走 LEFT JOIN，缺行的用户会被包含进来。这是**安全方向**——
宁可让一个本该注销的用户多显示一会儿，也不要把一个可用用户藏起来。改测试断言，不改代码。

### 3. `Profile.save()` 钩子在删列之后仍然不能删

3b2 之后新表是唯一真源，但注册流程仍然**先建 `Profile`**（`create_user` 的连带写入）。
删掉钩子会让新注册用户没有 lifecycle 行，然后被 INNER JOIN 全部漏掉。

所以钩子改成只补行、不写数据：`ensure_split_rows()`。

## 保险写进迁移，不写进流程

`0035_drop_profile_legacy_columns.py` 里有一个 `ensure_split_complete()`：删列之前先
给所有缺行的用户补上 lifecycle 行。

**流程会被跳过，迁移不会。** 依赖「部署时记得先跑校验命令」是靠不住的；
依赖「迁移执行到这个点，数据一定齐」是可靠的。

## 后果

- `account_state(user)` 成为唯一的状态判定入口，20 多处 `profile__deleted_at` 条件全部收敛。
- 改昵称不再可能覆盖生命周期字段（不同表）。
- 名册导入与账号状态解耦：注销的用户仍留在名册里，只是不能登录。
- 代价：读一个用户的完整信息需要两次 JOIN（identity + lifecycle），
  比原来一张宽表慢。但生产用户表 37 行，这个代价可以忽略——**这批改造的理由不是性能，
  是「下次加功能的摩擦」和「不可逆的数据丢失风险」**。
