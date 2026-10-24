# ADR-0028：多端登录（最多 3 台设备同时保持登录态）

- 状态：已采纳（2026-10-24）
- 相关：[ADR-0027](0027-account-deletion.md)（注销时清除登录设备）、[ADR-0026](0026-stepup-verification.md)（改密轮换 session key）

## 背景

上线以来会话是**单会话**模型（`SingleSessionMiddleware`）：`UserSession.is_current` 只有一个
`True`，任何新登录都把旧会话挤下线，且 10 分钟内他方登录直接 409 `login_protection`。

站点现在有三类客户端同时使用同一账号：桌面网页、手机浏览器、Android 壳（App）。单会话
模型下三者互斥，用户每切换一端就要重新登录、还会把另一端踢掉；「登录保护」又让「三端
依次登录」在 10 分钟内根本不可能完成。同时，账号密码在同学之间共享时，单会话也无法让
本人察觉「有别人在用」。

产品决定：**同一账号最多 3 台设备同时保持登录态**，并由用户在个人中心自行管理（下线任意
设备 / 下线其他所有设备）。3 是**全局名额**，不按端配额——网页、手机浏览器、App 各登录
一次正好占满，多开第二个浏览器标签页不会额外占名额（同一 Cookie 会话）。

## 决策

### 1. `UserSession` 的单一真源是 `revoked_at`

删除 `is_current`，新增：

| 字段 | 含义 |
|---|---|
| `revoked_at` | `NULL` = 仍保持登录态；非空 = 已下线（只留历史） |
| `revoked_reason` | `limit` / `manual` / `logout` / `replaced` / `security` |
| `replaced_by_session_key` | 顶替本会话的那台设备（用于「接管设备」提示） |
| `last_seen_at` | 最后活跃时间（顶替排序 + 个人中心展示），按会话节流写库（120s） |
| `device_id` | 设备标识（`club_device` Cookie，HttpOnly / 2 年），同一设备重登复用名额 |
| `client_kind` | `web` / `mobile` / `app`（App 壳 UA 含 `NhyzClubApp/`） |

迁移 `accounts/0027_session_multi_device` 带数据迁移：旧 `is_current=False` 的历史行统一写成
`revoked_at=now, revoked_reason=replaced`，避免迁移后一次性冒出 20 台「在线设备」。

### 2. 顶替规则：自动顶掉「最久未活动」的那台

`accounts.utils.record_user_session` 在每次登录时：

1. 同一 `device_id` 的旧会话先让位（`replaced`）——同一台手机重登不额外占名额；
2. 在线设备仍超过 3 台 → 按 `last_seen_at`（缺省回退 `created_at`）升序顶掉，写
   `revoked_reason=limit` + `replaced_by_session_key`；
3. **不删 Django Session**：被顶设备的下一次请求由中间件判 401（`session_superseded` +
   `revoked_reason` + 接管设备四字段），前端弹「设备名额已满」并引导重新登录。
   安全事件（停用 / 重置密码 / 撤销认证 / 注销）仍走 `revoke_user_sessions`：直接删
   Django Session 行，立即断线，不给提示页。

### 3. 「登录保护」改为同账号 10 分钟内最多 5 次成功登录

单会话时代的「他方 10 分钟内不许登录」与三端登录直接冲突，已取消。保留一个更宽的滑动
窗口节流（`LOGIN_PROTECTION_MAX_LOGINS = 5`）以抑制账号密码共享式的反复登录 / 挤号，
超出仍返回 409 `login_protection` + `retry_after`（前端契约不变）。

### 4. 个人中心「登录设备」

`GET /auth/sessions/` 返回在线设备 + 历史记录，信封补 `max_active` / `active_count`，
每行补 `client_kind` / `last_seen_at` / `is_active` / `is_this_device` / `revoked_at` /
`revoked_reason`。新增：

- `POST /auth/sessions/<id>/revoke/` —— 下线指定设备（仅本人记录；下线本机等价于退出登录）；
- `POST /auth/sessions/revoke-others/` —— 下线其他所有设备。

前端把「个人中心 → 登录记录」升级为「登录设备」（`SessionsPanel`），手机版「我的」也加入口。

## 后果

- 三端可以同时在线；第 4 台登录立即生效（顶替最久未用的那台），不需要等待。
- 密码泄露时攻击者登录会占一个名额，本人能在「登录设备」里看到并一键下线 / 改密。
- 每个已登录请求最多多一次 `UserSession` 读取（与旧的单会话判定等价），
  `last_seen_at` 写库按会话 120s 节流。
- `club_device` Cookie 是 HttpOnly、`SameSite=Lax`、HTTPS 下带 `Secure`；它只用于名额复用，
  不参与鉴权（删掉它不会掉登录态，只是下次登录会多占一个名额）。
- 旧会话迁移后保持「在线」的只有原先 `is_current=True` 的那一条，其余进入下线历史。

## 不采用

- **按端配额（网页 1 + 手机 1 + App 1）**：端类型由 UA 判定，UA 可伪造、桌面浏览器
  也可能被识别成 mobile；用户明确选择「全局任意 3 台」。
- **拒绝第 4 台登录**：体验差（要先在另一台设备上操作），且用户明确选择自动顶替。
- **持久化设备名 / 让用户给设备起名**：当前 `device_name` 由 UA 解析已足够辨识。
