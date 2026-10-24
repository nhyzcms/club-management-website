# 账号与认证 API

账号体系：注册 / 登录 / 登出 / 会话记录、认证通道（邮箱、人工审批、后台委任）、密码重置、资料与头像、能力投影（`can_*`）、用户检索，以及人工身份审核队列与待办收件箱。端点全部由 `accounts/urls.py` 暴露（前缀 `/auth/`，其中 `identity-reviews` 由 `DefaultRouter` 注册）。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0005](../adr/0005-access-control-principle.md)、[ADR-0006](../adr/0006-verification-model.md)、[ADR-0008](../adr/0008-list-pagination.md)、[ADR-0010](../adr/0010-runtime-site-policy.md)、[ADR-0013](../adr/0013-appointment-verification-channel.md)、[ADR-0023](../adr/0023-email-domain-allowlist.md)、[ADR-0025](../adr/0025-member-identity.md)

## 模块约定

- **路径前缀**：`config/urls.py` 把本 app 挂在 `/auth/`，故端点形如 `/auth/login/`。
- **认证口径**（本文件「认证」列）：公开 = 匿名可用；登录 = 仅要求已登录；已认证 = 登录且 `is_verified`（任一认证通道 `approved` 且未过期，[ADR-0006](../adr/0006-verification-model.md)）。
- **未登录行为分两类**：`@login_required` 的函数视图未登录时 302 重定向到 `/login/`；DRF 端点（`identity-reviews`、`inbox`）会话认证无跳转，未登录 / 无权限均返回 403 JSON（`{"detail": …}`）。
- **错误体形状**：函数视图为 `{"error": "…"}`（多条校验错误时 `error` 为字符串数组）；DRF 端点为 `{"detail": "…"}`。部分错误带 `reason` 供前端分支：`account_disabled` / `login_protection` / `login_throttled` / `registration_closed` / `verification_closed` / `email_domain_not_allowed` / `account_expired_unverified` / `step_up_required`。
- **Session + CSRF**：登录态走 Django Session cookie；非 GET 请求须带 `X-CSRFToken`（可先 `GET /auth/csrf/` 取 cookie）。
- **单会话与挤号**（`accounts.middleware.SingleSessionMiddleware`）：同一账号仅一个当前会话；他设备登录成功后旧会话的下一次请求返回 401 `{"detail": "您的账号在其他设备登录，您已被迫下线。", "reason": "session_superseded", "takeover": {"device_name": …, "device_type": …, "ip": …, "time": …}}`（浏览器导航 Accept 含 `text/html` 时改返 401 HTML 下线页）。
- **登录保护与限流**：账号已有未满 10 分钟的当前会话、且本次非同一会话再认证 → 409 `login_protection`；登录失败按 IP（`login_per_ip_per_hour`）与按用户名 / 邮箱（`login_per_username_per_hour`）双维度计数（只计失败），命中返回 429 `login_throttled` + `Retry-After` 头。
- **站点策略门禁**：`verification_enabled=false` 时新开 / 完成通道的端点返回 403 `verification_closed`（已通过者仍算已认证）；`registration_enabled=false` 时注册 403 `registration_closed`。旋钮见[公共 API](common.md)。
- **邮箱后缀白名单**（[ADR-0023](../adr/0023-email-domain-allowlist.md)）：仅注册带邮箱与邮箱绑定 / 换绑判定；不在白名单（`accounts/email_domains.py`）→ 400 `{"error": "该邮箱后缀暂不可用，请换用其他邮箱。详询社长或服务器管理员", "reason": "email_domain_not_allowed", "domain": "<命中的域名>"}`。不回溯既有地址、重发与认证链接落地。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| POST | `/auth/login/` | 公开 | — | 登录（用户名或绑定邮箱 + 密码） |
| POST | `/auth/logout/` | 登录 | — | 登出并清当前会话标记 |
| GET | `/auth/csrf/` | 公开 | — | 下发 `csrftoken` cookie |
| POST | `/auth/register/` | 公开 | — | 自助注册（multipart） |
| GET | `/auth/verify-email/` | 公开 | — | 邮箱认证链接落地 |
| POST | `/auth/resend-verification/` | 公开 | — | 重发认证邮件 |
| GET | `/auth/me/` | 登录 | — | 当前用户（资料 + 能力投影） |
| GET | `/auth/profile/` | 登录 | — | 同上（同一响应，历史别名） |
| POST | `/auth/profile/update/` | 登录 | — | 更新资料 / 头像（multipart） |
| POST | `/auth/profile/change-password/` | 登录 | — | 修改密码（需 Step-up） |
| POST | `/auth/account/delete/` | 登录 | — | 注销账号（软删除 + 敏感信息清除，[ADR-0027](../adr/0027-account-deletion.md)） |
| GET | `/auth/sessions/` | 登录 | — | 本人最近登录记录 |
| POST | `/auth/password-reset/` | 公开 | — | 发起密码重置 |
| POST | `/auth/password-reset/confirm/` | 公开 | — | 确认新密码 |
| GET | `/auth/verification/` | 登录 | — | 账号认证状态总览 |
| GET | `/auth/validity/` | 登录 | — | 账号有效期快照（状态 / 到期时间 / 剩余天数 / 提示键） |
| POST | `/auth/validity/ack/` | 登录 | — | 标记「账号有效期」弹窗已读（写回快照键） |
| POST | `/auth/verification/email/bind/` | 登录 | — | 绑定 / 换邮 / 重发邮箱认证 |
| POST | `/auth/verification/manual/submit/` | 登录 | — | 提交人工通道身份证明（multipart） |
| POST | `/auth/verification/authcode/redeem/` | 登录 | — | 兑换认证码（即时通过） |
| GET | `/auth/member/` | 登录 | — | 本人社员身份 + 可认领候选（[ADR-0025](../adr/0025-member-identity.md)） |
| POST | `/auth/member/claim/` | 登录 | — | 自助认领（身份 + 手机号后四位） |
| GET | `/auth/member/check/` | 公开 | — | 扫码校验（签名；最小公开字段） |
| GET | `/auth/stepup/` | 登录 | — | 安全验证方式总览（[ADR-0026](../adr/0026-stepup-verification.md)） |
| POST | `/auth/stepup/email/send/` | 登录 | — | 发送邮箱验证码（60s 冷却 / 小时限） |
| POST | `/auth/stepup/verify/` | 登录 | — | 验证并签发 grant（10 分钟） |
| GET/POST | `/auth/stepup/questions/` | 登录 | — | 题库 / 设置与更换安全问题 |
| GET | `/auth/stepup/events/` | 登录 | — | 本人最近验证记录 |
| GET | `/auth/identity-proof/{pk}/` | 登录 | 本人或 `accounts.can_review_identity` | 身份证明文件（鉴权下载） |
| GET | `/auth/identity-reviews/` | 登录 | `accounts.can_review_identity` | 人工身份审核队列 |
| GET | `/auth/identity-reviews/{pk}/` | 登录 | `accounts.can_review_identity` | 单条审核记录 |
| POST | `/auth/identity-reviews/{pk}/approve/` | 登录 | `accounts.can_review_identity` | 通过身份审核 |
| POST | `/auth/identity-reviews/{pk}/reject/` | 登录 | `accounts.can_review_identity` | 驳回身份审核 |
| POST | `/auth/identity-reviews/{pk}/disable/` | 登录 | `accounts.can_review_identity` | 停用账号 |
| GET | `/auth/inbox/` | 已认证 | — | 待办收件箱（活动债 + 任务债） |
| GET | `/auth/users/` | 登录 | — | 用户列表（`?search=` 搜人） |
| GET | `/auth/users/{id}/profile/` | 登录 | — | 他人主页资料（按查看者身份裁剪） |
| GET | `/auth/users/{id}/content/` | 登录 | — | 用户内容 tab（按查看者身份裁剪） |
| GET | `/auth/` | 登录 | — | DRF 路由根（仅罗列 identity-reviews 链接，无业务语义） |

## 端点详情

### 登录

`POST /auth/login/`

**认证**：公开；**权限**：—。请求体 JSON：`username` / `email`（二选一；`email` 仅匹配**已绑定**邮箱 `User.email`，待认证邮箱登不进）、`password`（必填）。

**响应 `200 OK`**

```json
{"user": {"id": 7, "username": "zhangsan", "email": "zs@example.com"}}
```

`email` 未绑定时为空字符串。未认证账号照常登录（登录与认证解耦）；停用账号被拒，普通停用与「超期未认证被系统停用」返回不同的错误提示（见下表）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | JSON 非法；`username` / `email` 均缺；`password` 缺失 |
| 401 | 账号不存在或密码错误（统一 `{"error": "Invalid credentials"}`，不泄露账号是否存在） |
| 403 | 账号已停用：`{"error": "账号已停用，请联系信息组。", "reason": "account_disabled"}` |
| 403 | 超期未认证被系统停用：`{"error": "本账户超过 60 日未认证，已被系统停用。请联系社长或服务器管理员处理。", "reason": "account_expired_unverified"}` |
| 409 | 登录保护窗口：`{"reason": "login_protection", "retry_after": <秒>}` |
| 429 | 失败次数超限：`{"reason": "login_throttled", "retry_after": <秒>}` |

### 登出 / CSRF / 路由根

`POST /auth/logout/`：**认证**登录；**权限**—。注销 Session，并把本人 `UserSession.is_current` 置 `false`。响应 `200`：`{"message": "Logged out"}`。

`GET /auth/csrf/`：**认证**公开；**权限**—。`@ensure_csrf_cookie` 下发 `csrftoken` cookie（与 HTML 渲染解耦，SPA 启动时请求一次）；视图不限方法（实际按 GET 调用）。响应 `200`：`{"detail": "CSRF cookie set"}`。

`GET /auth/`：**认证**登录（`DefaultRouter` 的 API 根视图继承全局 `IsAuthenticated`，匿名 403）；**权限**—。仅罗列 `identity-reviews` 链接，无业务语义。

### 注册

`POST /auth/register/`

**认证**：公开；**权限**：—。请求体 `multipart/form-data`（视图读 `request.POST`）；启用 Turnstile 时须带 token。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 站点内唯一（大小写不敏感） |
| password / password2 | string | 是 | 密码（走 Django 密码校验器）与确认密码，须一致 |
| email | string | 否 | 提供则建 `email` 通道 `pending`（`identifier`=待认证地址，归一化小写）并发认证信；**后缀须在白名单内**（[ADR-0023](../adr/0023-email-domain-allowlist.md)） |
| real_name | string | 是 | 真实姓名，写入 `Profile.real_name`（不公开展示） |
| identity | string | 是 | 身份，写入 `Profile.identity`；∈ `student` / `external` / `graduate` / `parent` / `teacher` |
| card_no | string | 否 | **校牌号**（≤20 字符）。仅 `student` / `graduate` 登记，其余身份传了也忽略；写入 `Profile.card_no`（与名册行 `MemberIdentity.card_no` 是同一个值）。见下方「校牌号与自动绑定」 |
| turnstile_token | string | 条件 | Turnstile 启用时必填 |

**响应 `201 Created`**

```json
{"message": "注册成功。请查收邮件完成邮箱认证。", "user": {"id": 8, "username": "newuser"}}
```

`User.email` 保持空（待认证邮箱住通道 `identifier`，认证通过才晋升）；未提供邮箱或认证通道关闭时 `message` 为 `"注册成功。"` 且不建通道。**注册成功即建立登录会话（自动登录）**；若名册存在姓名匹配的未绑定行，前端随后进入社员身份认领阶段（可跳过，见 `/auth/member/`）。

**校牌号与自动绑定**（2026-10-23）：带 `card_no` 注册时，若名册中存在**姓名（归一）+ 校牌号（归一：去空白、大小写不敏感）都一致**且未绑定的**唯一**一行 → 直接绑定（`bind_method=register`），前端无需再走手机号后四位。没命中（名册未导入 / 校牌号不同 / 同名多行）**不报错**：`Profile.card_no` 先保存，名册导入或「重新运行自动匹配」时按姓名写回名册行（`sync_card_numbers`）；名册有值时以名册为准，两边始终对齐。

**错误**：400 字段校验（用户名 / 邮箱占用、两次密码不一致、密码强度、真实姓名缺失、身份缺失或枚举非法、邮箱格式，单条或数组）、邮箱后缀不在白名单 `{"error": "该邮箱后缀暂不可用，请换用其他邮箱。详询社长或服务器管理员", "reason": "email_domain_not_allowed", "domain": "gmail.com"}`，或 Turnstile 未通过 `{"error": "人机校验失败，请刷新后重试。"}`；403 `{"error": "当前未开放注册。", "reason": "registration_closed"}`；429 每 IP 每日注册次数超限；500 `{"error": "注册失败，请稍后重试。"}`。

### 邮箱认证与重发

`GET /auth/verify-email/?uid=<uid>&token=<token>`

**认证**：公开；**权限**：—。`uid` 为 urlsafe base64 的用户 pk；`token` 绑 email 通道 `identifier` + `status`（改待认证邮箱或认证通过后旧令牌立即失效，不可重放）。不校验后缀白名单（令牌已限定既有待认证地址）。

**响应 `200 OK`**：`{"message": "邮箱认证成功。"}`。通过后：email 通道置 `approved` 并记 `verified_at`（`verified_by` 空），`identifier` 晋升写入 `User.email`——绑定邮箱生效，可用于邮箱登录与密码重置。

**错误**：400 `{"error": "认证链接无效或已过期。", "reason": "invalid"}`；403 `{"error": "认证通道已关闭", "reason": "verification_closed"}`。

`POST /auth/resend-verification/`

**认证**：公开；**权限**：—。请求体 JSON：`email`（是）、`turnstile_token`（条件）。**响应 `200 OK`**：`{"message": "如果该邮箱正在认证中，认证邮件已重发。"}`。

不泄露邮箱是否存在 / 是否在验；仅「存在 `email` 通道 `pending` 且账号启用」的账号真正发信（发往待验 `identifier`）；不校验后缀白名单（只重发既有地址）。**错误**：403 `verification_closed`；429 每 IP 每小时重发次数超限；400 邮箱缺失（`{"error": "请输入邮箱。"}`）/ JSON 非法 / Turnstile 失败。

### 当前用户（`/auth/me/` 与 `/auth/profile/`）

`GET /auth/me/`、`GET /auth/profile/`

**认证**：登录；**权限**：—。两视图输出完全一致（同一 `_profile_response`）；均未限制方法（实际按 GET 调用）。

**响应 `200 OK`**

```json
{
  "user": {"id": 7, "username": "zhangsan", "email": "zs@example.com",
    "permissions": {
      "can_manage_news": false, "can_manage_tasks": false, "can_assign_task": false, "can_manage_tags": false,
      "can_change_activity": false, "can_view_feedback": false, "can_handle_reports": false, "can_review_collections": false,
      "can_edit_about": false, "can_manage_panoramas": false, "can_manage_exam": false, "can_review_content": false,
      "can_review_identity": false, "can_force_publish": false, "can_manage_comment_thread": false, "can_mute_user": false,
      "can_manage_announcement": false, "can_manage_announcements": false
    }},
  "role": {"label": "用户", "variant": "user"},
  "profile": {"avatar": "/media/avatars/user_7.png", "nickname": "张三", "birthday": "2007-05-01",
    "gender": "M", "bio": "摄影部部长", "is_verified": true}
}
```

`avatar` 无头像时为 `null`；`birthday` 未填为 `null`；`gender` 可为 `""` / `M` / `F` / `O`（男 / 女 / 其他）。`profile.is_verified` 为账号总认证态（任一通道 `approved` 且未过期）。`role` 四档：`superadmin` 超级管理员（`is_superuser`）＞ `admin` 管理员（`is_staff`，仅徽章展示）＞ `user` 用户（`is_verified`，后台委任通道计入）＞ `visitor` 访客（匿名或已登录未认证）。

### 能力投影（`permissions.can_*`）

由 `has_perm` 派生的语义化布尔（[ADR-0005](../adr/0005-access-control-principle.md) 决策 3/4）：前端不接触权限代号；键集恒为全量（true / false 都在，与前端契约测试对齐）。超管 `has_perm` 恒真，故全部为 true。

| 字段 | 源权限代号 | 字段 | 源权限代号 |
|---|---|---|---|
| can_manage_news | `news.manage_news` | can_manage_tasks | `tasks.manage_tasks` |
| can_assign_task | `tasks.assign_task` | can_manage_tags | `tasks.manage_tags` |
| can_change_activity | `activities.manage_activity` | can_view_feedback | `reviews.read_feedback` |
| can_handle_reports | `reviews.handle_report` | can_review_collections | `activities.review_collection` |
| can_edit_about | `about.manage_aboutpage` | can_manage_panoramas | `panorama.manage_panoramas` |
| can_manage_exam | `exam_board.manage_exams` | can_review_content | `reviews.moderate` |
| can_review_identity | `accounts.can_review_identity` | can_force_publish | `reviews.force_publish` |
| can_manage_comment_thread | `messaging.manage_comment_thread` | can_mute_user | `messaging.mute_user` |
| can_manage_announcement | `messaging.manage_announcement` | can_manage_announcements | `announcements.manage_announcements` |

### 更新资料 / 修改密码

`POST /auth/profile/update/`

**认证**：登录；**权限**：—。请求体 `multipart/form-data`；成功返回与 `/auth/me/` 相同的完整对象。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| avatar | file | 否 | ≤2MB；仅 JPG / PNG / GIF / WebP |
| nickname / bio | string | 否 | 昵称 ≤50 字符；简介 ≤500 字符 |
| birthday / gender | string | 否 | 生日 `YYYY-MM-DD`；性别 `""` / `M` / `F` / `O` |
通知订阅（站内 / 邮件等通道开关）已迁至通知框架：见 `/messaging/notification-preferences/`（详见 messaging.md）。**错误**：400 `{"error": "头像文件不能超过 2MB"}`、`{"error": "仅支持 JPG、PNG、GIF、WebP 格式"}` 或表单校验消息。

`POST /auth/profile/change-password/`

**认证**：登录；**权限**：—。请求体 JSON：`old_password`（是）、`new_password`（是，≥8 字符）。**响应 `200 OK`**：`{"message": "密码修改成功"}`；**错误**：400 `{"error": "原密码不正确"}` 或表单校验消息。

### 注销账号

`POST /auth/account/delete/`

**认证**：登录；**权限**：—。请求体 JSON：`password`（是）、`confirm`（是，必须逐字等于 `注销账号`）。账号配置了可用安全验证方式（认证邮箱 / 安全问题）时另需 `X-StepUp-Grant` 头（scope `delete_account`），缺 grant → 403 `{"error": "需要先完成安全验证。", "reason": "step_up_required", "scope": "delete_account"}`；两种方式都没有的账号退回「密码 + 逐字确认」。

**响应 `200 OK`**：`{"message": "账号已注销"}`，同时当前会话被清空（需重新登录，但账号已停用）。

**错误**：

- 400 `confirmation_required` / `password_required` / `password_incorrect`；
- 403 `account_deletion_protected`（管理员 / 超管账号不允许自助注销）；
- 409 `account_already_deleted`（重复注销）。

注销语义见 [ADR-0027](../adr/0027-account-deletion.md)：`User` / `Profile` 行保留（`Profile.deleted_at` 标记），邮箱、头像、身份证明材料、验证通道、登录设备、通知与安全验证残留删除；真实姓名、账号唯一编码与社员编号（`MemberIdentity`）保留。

> 前端（`AccountDeletionPanel`）在表单填对后**不会直接调本端点**：先弹一次二次确认弹窗，点「确认注销」才发请求；取消 / Esc / 点遮罩都不发。这是纯前端防误触，后端的三重校验不变。

### 登录记录（会话列表）

`GET /auth/sessions/`

**认证**：登录；**权限**：—。按 `-created_at` 倒序；存储层按 `SESSION_HISTORY_LIMIT = 20` 裁剪，分页按同上限做单页，返回完整 DRF 信封。

**响应 `200 OK`**

```json
{
  "count": 2, "next": null, "previous": null,
  "results": [
    {"id": 5, "device_name": "Chrome · Windows", "device_type": "Desktop", "ip_address": "127.0.0.1",
     "created_at": "2026-09-19T02:00:00+00:00", "is_current": true}
  ]
}
```

`device_type` ∈ `Desktop` / `Mobile` / `Tablet` / `Bot` / `Unknown`；`device_name` 由 UA 解析（浏览器 · 系统），可为空串；`ip_address` 可为 `null`。

### 密码重置（发起 / 确认）

`POST /auth/password-reset/`

**认证**：公开；**权限**：—。请求体 JSON：`email`（是，格式校验）、`turnstile_token`（条件）。对每个 `User.email` 匹配的账号（不假设唯一）发送重置链接 `{FRONTEND_URL}/#/reset-password?uid=<uid>&token=<token>`（Django `default_token_generator`，默认 7 天有效）；**无论邮箱是否存在都返回同一提示**（防账号探测）。响应 `200`：`{"message": "If an account with that email exists, a reset link has been sent."}`；错误：400 邮箱缺失 / 格式非法 / JSON 非法 / Turnstile 失败。

`POST /auth/password-reset/confirm/`

**认证**：公开；**权限**：—。请求体 JSON：`uid`（string，是）、`token`（string，是）、`new_password`（string，是）。校验 `default_token_generator.check_token`；`new_password` 仅必填校验（不走密码强度校验器）。响应 `200`：`{"message": "Password has been reset successfully."}`；错误：400 `{"error": "Invalid reset link"}`（`uid` 无法解出用户）或 `{"error": "Invalid or expired token"}`。

### 认证状态

`GET /auth/verification/`

**认证**：登录；**权限**：—。总认证态 + 各通道当前状态（数据驱动面板铺卡），每通道一卡、按 `CHANNELS` 序（`appointment` → `email` → `manual` → `authcode`），无记录行的通道 `status="none"`。

**响应 `200 OK`**

```json
{
  "is_verified": true,
  "channels": [
    {"channel": "appointment", "status": "approved", "identifier": "staff", "verified_at": "2026-09-19T02:00:00+00:00"},
    {"channel": "email", "status": "not_required", "identifier": "zs@example.com", "verified_at": null},
    {"channel": "manual", "status": "not_required", "identifier": "", "verified_at": null},
    {"channel": "authcode", "status": "not_required", "identifier": "", "verified_at": null}
  ]
}
```

`status` ∈ `none` / `pending` / `approved` / `rejected` / `not_required`；`identifier`：email = 待认证地址（认证通过后即提升为 `User.email`）、manual = 空、appointment = `staff` / `superuser`、authcode = 码原文（后台可读，供追溯）。

`not_required`（「无需再次认证」）是**派生态**，不落库：账号已认证（存在未过期 `approved` 通道）时，除该通道外的其余通道一律返回 `not_required`，前端据此收起表单；认证过期后自动消失、恢复真实状态。响应示例里若 `is_verified=true`，`status` 为 `pending`/`none`/`rejected` 的通道会显示成 `not_required`。

### 账号有效期（快照 / 弹窗已读）

`GET /auth/validity/`

**认证**：登录；**权限**：—。只读快照，口径见 `accounts/validity_summary.py`（与执行模块 `accounts/validity.py`、到期前提醒 `accounts/validity_notices.py` 分工不同）。前端用它渲染「账号有效期」弹窗（注册成功 / 认证通过后各弹一次）与认证面板上的到期提示；字段与 `frontend/src/utils/validity.ts` 一一对应。**匿名访问返回 401 JSON**（`{"error": "未登录。"}`，不跳转），便于匿名页面静默处理。

```json
{
  "status": "verified",
  "status_label": "已认证用户",
  "expires_at": "2027-10-18T20:00:00+08:00",
  "remaining_days": 365,
  "registration_deadline": null,
  "channels": [
    {"channel": "email", "label": "邮箱认证", "expires_at": "2027-10-18T20:00:00+08:00", "remaining_days": 365}
  ],
  "policy": {"verification_valid_days": 365, "admin_valid_days": 730, "registration_verify_days": 60},
  "key": "verified:2027-10-18T20:00:00+08:00",
  "notice_pending": true
}
```

- `status`：`permanent`（超级管理员） / `admin`（委任管理员，取委任到期） / `verified`（取仍在有效期内、到期最晚的通道；任一通道永久则 `expires_at=null`） / `expired`（曾认证但已全部到期，需重新认证） / `unverified`（从未认证，取注册宽限截止）。
- `expires_at` / `remaining_days`：`null` = 永久；`remaining_days` 向下取整，`0` = 不足 24 小时，负数 = 已到期。
- `key`：状态快照键（`<status>:<到期时间>`），状态或到期时间变化即换键；`notice_pending` = 该键 ≠ `Profile.validity_notice_ack`。
- `channels`：未过期的 approved 通道（含通道短名与各自到期），供多通道并列展示。

`POST /auth/validity/ack/`

**认证**：登录；**权限**：—。请求体 JSON：`key`（是，取自上面响应的 `key`）。仅当 `key` 等于**当前**快照键时才写回（防止用旧键吞掉新状态）；响应 `200`：`{"acknowledged": true}`，键已过期 / 不匹配返回 `{"acknowledged": false}`；缺 `key` → 400。已读标记存服务端（跨设备一致），续期 / 重新认证后键变化，弹窗会再次出现。

### 邮箱通道：绑定 / 换邮 / 重发

`POST /auth/verification/email/bind/`

**认证**：登录；**权限**：—。请求体 JSON：`email`（是）。统一置 email 通道 `pending` + `identifier`=新地址并发信，`User.email` 不动，认证通过才晋升。首次绑定 / 重发同邮箱 → 建或刷新 `pending` 行；换邮箱（含已认证旧邮箱）→ 回 `pending` 且旧 `verified_at` 失效；已认证同邮箱再绑 → no-op：`{"message": "该邮箱已认证。"}`。**后缀须在白名单内**；与既有 `identifier` 相同的重发 / 复绑不重复判定（不回溯旧地址）。

**响应 `200 OK`**：`{"message": "认证邮件已发送，请查收。"}`；**错误**：400 邮箱缺失 / 格式非法 / 后缀不在白名单（`{"error": "该邮箱后缀暂不可用，请换用其他邮箱。详询社长或服务器管理员", "reason": "email_domain_not_allowed", "domain": "gmail.com"}`）/ 已被占用（`{"error": "该邮箱已被占用"}`，含他人 `pending`）/ JSON 非法；403 `verification_closed`；429 每 IP 每小时重发次数超限。

### 人工通道：提交身份证明

`POST /auth/verification/manual/submit/`

**认证**：登录；**权限**：—。请求体 `multipart/form-data`；把 `manual` 通道置 `pending`，并把证明照片累加进 `IdentityProof`（**永久留底**，审核通过后也不删）。仅当前 `none` / `rejected` 可提交（`pending` 审核中、已通过不可重复）。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| real_name | string | 是 | 写入 `Profile.real_name` |
| identity | string | 是 | `student` / `external` / `graduate` / `parent` / `teacher` |
| proof_files | file[] | 是 | 1–3 张；单张 ≤5MB；仅 `image/jpeg` / `image/png` / `image/webp` |

**响应 `200 OK`**：`{"message": "身份证明已提交，等待管理员审核。"}`；**错误**：403 `verification_closed`；400 校验消息（可数组）或 `{"error": "当前不可提交（审核中或已通过）"}`。

### 认证码通道：兑换

`POST /auth/verification/authcode/redeem/`

**认证**：登录；**权限**：—。请求体 JSON：`code`（是）。码经归一化（去空格 / 连字符、转大写）后按序校验：无效 / 已吊销 / 已过期 / 已用尽 / 同一码每账号至多兑一次；通过即写 `authcode` 通道 `approved`（`identifier` = 码原文，`verified_by` = 发码人）、`used_count + 1` 并落兑换记录（审计留底），认证有效期 = 兑换日 + `verification_valid_days`（默认 365 天）。**已通过且未过期**（任一通道）的账号再兑换 → 400 `{"error": "账号已完成认证，无需使用认证码。"}` 且不消耗任何码；认证过期后可用新码重新兑换。

**响应 `200 OK`**：`{"message": "认证码认证通过，账号已完成认证。"}`；**错误**：403 `verification_closed`；429 `{"error": "请求过于频繁，请稍后再试。"}`（每账号每小时失败次数超限，**只计失败**、成功不占额度）；400 `{"error": "…"}`（无效 / 已吊销 / 已过期 / 已用尽 / 账号已完成认证 / 空码 / JSON 非法）。

码的生成与吊销**只在 Django 后台**（`账户 → 认证码`），前端无生成入口；过期 / 吊销只停后续兑换，不回溯已通过者。

### 人工身份审核（证明下载 / 队列 / 动作）

`GET /auth/identity-proof/{pk}/`

**认证**：登录；**权限**：本人或 `accounts.can_review_identity`。文件存 `PRIVATE_MEDIA_ROOT` 私有存储，不经公开 `MEDIA_URL` 暴露，仅经本端点鉴权下载。**响应 `200 OK`**：二进制图片流（`FileResponse`，`Content-Type` 按文件后缀推断，默认 `image/jpeg`）；**错误**：403 非本人且无审核权限；404 记录或磁盘文件不存在。

`GET /auth/identity-reviews/`、`GET /auth/identity-reviews/{pk}/`

**认证**：登录；**权限**：`accounts.can_review_identity`。`pk` 是人工通道 `Verification` 行的 id（非 `user.id`）。DRF `ReadOnlyModelViewSet`，列表分页（默认页大小 20）；查询参数（仅列表）：`status`（否，`pending` 默认 / `approved` / `rejected`；传空串返回全部）、`page`（否）。

**响应 `200 OK`**

```json
{
  "count": 1, "next": null, "previous": null,
  "results": [
    {"id": 9, "user_id": 42, "username": "lisi", "real_name": "李四", "identity": "student",
     "status": "pending", "verified_at": null, "verified_by": null,
     "proofs": [{"id": 3, "uploaded_at": "2026-09-19T03:00:00+00:00", "url": "/auth/identity-proof/3/"}]}
  ]
}
```

`verified_by` 为 `{"id", "username"}` 或 `null`；`real_name` / `identity` 取自该用户 `Profile`（缺 profile 时为空串）；`proofs` 为该用户全部证明材料（倒序）。

`POST /auth/identity-reviews/{pk}/approve/`、`POST …/reject/`、`POST …/disable/`

**权限**同队列；请求体可为空（`{}`）；成功返回刷新后的审核记录对象（结构同上）。

| 动作 | 效果 |
|---|---|
| approve | `manual` 通道置 `approved`（记 `verified_at` / `verified_by`），向用户邮箱发通过邮件 |
| reject | `manual` 通道置 `rejected`，清 `verified_at`，向用户邮箱发驳回邮件（可在面板重交） |
| disable | 停用账号：`is_active = False` + 立即吊销既有会话（删 Django `Session` 行 + 清 `UserSession.is_current`），发通知邮件 |

`approve` / `reject` 在 `verification_enabled=false` 时返回 403 `verification_closed`；`disable` 是账号级动作，通道关闭时仍可执行。

### 待办收件箱

`GET /auth/inbox/`

**认证**：已认证（DRF `IsVerified`，未登录 / 未认证 403）；**权限**：—。混合时间线：48 小时内截止的活动债置顶（`end_at` 升序），其余按 `updated_at` 降序；不分页（直接返回全量信封）。私信未读不进待办。

**响应 `200 OK`**

```json
{
  "count": 1, "next": null, "previous": null,
  "results": [
    {"kind": "activity", "reason": "vote", "pinned": true,
     "updated_at": "2026-09-19T02:00:00+00:00", "end_at": "2026-09-20T12:00:00+00:00",
     "activity": {"id": 12, "type": "deliberation", "status": "open", "title": "运动会口号征集"},
     "task": null, "conversation": null}
  ]
}
```

`kind` ∈ `activity` / `task`；`reason` ∈ `vote`（待投票）/ `submit`（待投稿）/ `complete`（待完成）/ `approve_completion`（待验收）/ `approve_claim`（待批认领），判定见 `activities/debt.py` 与 `tasks/debt.py`。`activity` / `task` 为对应模块列表序列化器的完整对象（此处摘录关键字段）：见[活动 API](activities.md)、[任务 API](tasks.md)；`conversation` 恒为 `null`（预留形状）。

### 用户列表

`GET /auth/users/`

**认证**：登录；**权限**：—。供任务表单选人：DRF 分页（页大小 20）+ 可选搜索。查询参数：`search`（否，对 `username` / `profile.nickname` 模糊匹配；空则返回全部激活用户第一页）、`page`（否，越界返回空 `results` 的完整信封）。

**响应 `200 OK`**

```json
{
  "count": 2, "next": null, "previous": null,
  "results": [
    {"id": 7, "username": "zhangsan", "nickname": "张三", "avatar": "/media/avatars/user_7.png"},
    {"id": 8, "username": "lisi", "nickname": "", "avatar": null}
  ]
}
```

仅 `is_active=True` 用户；按 `username, id` 排序。

### 他人主页资料

`GET /auth/users/{id}/profile/`

**认证**：登录；**权限**：—（按查看者身份裁剪字段）。`id` 不存在或账号停用 → 404 `{"error": "用户不存在"}`。

已注销账号（`Profile.deleted_at` 非空）例外返回**墓碑响应**：`{"deleted": true, "user": {"id", "username": ""}, "profile": {"avatar": null, "nickname": "", "bio": ""}, "role": {"label": "已注销"}, "viewer": {...}}`，不含权限 / 组 / 私密字段（[ADR-0027](../adr/0027-account-deletion.md)）。

**响应 `200 OK`**（本人查看自己的示例；他人查看时省略 ★ 字段）

```json
{
  "user": {"id": 7, "username": "zhangsan", "date_joined": "2026-09-01T01:00:00+00:00", "email": "zs@example.com"},
  "profile": {"avatar": "/media/avatars/user_7.png", "nickname": "张三", "bio": "摄影部部长",
              "birthday": "2007-05-01", "gender": "M"},
  "role": {"label": "用户", "variant": "user"},
  "viewer": {"is_owner": true, "is_admin": false},
  "permissions": {"can_manage_news": false, "can_manage_tasks": false, "can_assign_task": false, "can_manage_tags": false,
                  "can_change_activity": false, "can_view_feedback": false, "can_handle_reports": false, "can_review_collections": false,
                  "can_edit_about": false, "can_manage_panoramas": false, "can_manage_exam": false, "can_review_content": false,
                  "can_review_identity": false, "can_force_publish": false, "can_manage_comment_thread": false, "can_mute_user": false,
                  "can_manage_announcement": false, "can_manage_announcements": false},
  "groups": ["信息组"]
}
```

字段可见性（`accounts/visibility.py`）：

- 公开（始终输出）：`user.id` / `username` / `date_joined`、`profile.avatar` / `nickname` / `bio`、`role`、`viewer`。
- ★ 私密（仅本人，`can_see_private`）：`user.email`、`profile.birthday`、`profile.gender`。
- ★ 敏感（本人或管理员视角，`can_see_sensitive`）：`permissions`、`groups`（组名列表）。管理员视角 = 超管或持 `news.manage_news`。

### 用户内容 tab

`GET /auth/users/{id}/content/`

**认证**：登录；**权限**：—（按查看者身份裁剪可见性）。`id` 不存在或停用 → 404；`type` 非法 → 400 `{"error": "无效的 type"}`。查询参数：`type`（是，`news` / `feedback` / `tasks` / `activities` / `tutorials`）、`page`（否，页大小 15（`CONTENT_LIMIT`）；越界返回空 `results` 的完整信封）。

**响应 `200 OK`**：`{"count": …, "next": …, "previous": …, "results": [ … ]}`（倒序，按类字段如下）

| type | results 单项字段 |
|---|---|
| news | `id` / `title` / `cover_image` / `is_published` / `review_status` / `published_at` |
| feedback | `id` / `title` / `category` / `status` / `created_at` |
| activities | `id` / `title` / `type` / `status` / `review_status` / `created_at` |
| tutorials | `id` / `title` / `review_status` / `created_at` |
| tasks | `id` / `title` / `status` / `priority` / `created_at` |

可见范围：本人全部；他人仅公开项（`news` 还需 `is_published=true`；`feedback` 恒为空；`activities` / `tutorials` 按审核轴公开）。**查看他人任务返回 403** `{"error": "无权查看他人任务"}`。`review_status` 可为 `null`（尚无审核行）。

### 社员身份（[ADR-0025](../adr/0025-member-identity.md)）

`GET /auth/member/`：**认证**登录。本人绑定状态 + 可认领候选。未绑定且认领开关开启时，候选 = 「未绑定且姓名（归一化）与本人 `real_name` 一致」的名册行，仅含 `id` / `name` / `cohort`（**电话、校牌号绝不下发**）；绑定后 `bound` 含 `code`（识别码）/ `card_no`（校牌号，仅本人可见）/ `status`（`active` / `graduated` / `left`）。

**响应 `200 OK`**

```json
{"enabled": true, "bound": null, "candidates": [{"id": 3, "name": "张三", "cohort": 2}]}
```

`POST /auth/member/claim/`：**认证**登录。JSON `{"identity_id": <候选 id>, "phone_last4": "9198"}`。服务端强制「账号 `real_name` == 名册行姓名（归一）」并以**手机号后四位**校验；成功 `200`：`{"message": "认领成功。", "member": {…}}`。

| 状态码 | 场景 |
|---|---|
| 400 | 后四位不匹配 / 姓名不匹配 / 名册行或账号已在别处绑定 / 名册行无电话 |
| 403 | 认领开关关闭：`{"reason": "claim_closed"}` |
| 429 | 失败超限（账号 5 次/时、IP 20 次/天，**只计失败**） |

`GET /auth/member/check/`：**认证**公开。`?c=<识别码>&s=<签名>`。签名不符或码不存在一律 `404 {"found": false}`（语义不可区分，防枚举）；命中返回：

```json
{"found": true, "name": "张三", "cohort": 2, "code": "26020542", "status": "active", "avatar": null}
```

**绝不含**电话 / 学号 / 邮箱；按 IP 限流（60 次/时，计全部请求）→ `429`。签名 = HMAC-SHA256（密钥默认由 `SECRET_KEY` 派生，`MEMBER_QR_SECRET` 可覆盖）截断 16 位 hex——二维码内容如 `https://<站点>/#/v/26020542?s=b7951a1f144d7be0`。

### 安全验证（Step-up，[ADR-0026](../adr/0026-stepup-verification.md)）

`GET /auth/stepup/`：**认证**登录。方式总览：`email`（可用性 / 打码地址 / 冷却剩余秒）、`questions`（已设否 / 题数）、`scopes`（作用域 → 名称）、`grant_ttl`。

`POST /auth/stepup/email/send/`：**认证**登录。发 6 位验证码到**已认证邮箱**。`400 email_unavailable`（无已认证邮箱）；`429`：60 秒冷却（`reason: cooldown` + `retry_after`）或账号 / IP 小时上限；成功 `{"message": "验证码已发送，请查收邮件。"}`。

`POST /auth/stepup/verify/`：**认证**登录。`{"method": "email"|"question", "scope", "code"? | "question_id" + "answer"?}` → `{"grant", "expires_in": 600, "message"}`；错误统一 `400`（「验证码错误或已过期。」；答案错为「答案不正确。」）。grant 是签名令牌（账号 + scope + 时间戳、10 分钟）；**受保护端点**凭请求头 `X-StepUp-Grant` 复用。

`GET/POST /auth/stepup/questions/`：**认证**登录。GET 返回 `{bank, mine}`（题库 + 本人已设，只出题干）；POST `{"items": [{"key","answer"}], "password"?}`：**首次设置需 `password`（登录密码）**，之后更换 / 清除（`items: []`）需 grant（缺 → `403 step_up_required`）。

`GET /auth/stepup/events/`：**认证**登录。本人最近 20 条验证记录（`scope` / `scope_label` / `method` / `result` / `ip` / `created_at`）。

**受保护端点契约**：`POST /auth/profile/change-password/`（原密码 ＋ grant `change_password`）与 `POST /auth/verification/email/bind/`（换绑 grant `change_email`；**首次绑定不拦**）缺令牌时返回 `403 {"error": "需要先完成安全验证。", "reason": "step_up_required", "scope": …}`——前端按 reason 跳 `/#/verify?action=<scope>&next=…`，完成后回跳重试。
