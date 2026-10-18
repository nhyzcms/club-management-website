# 账号验证模型（统一「已验证」+ 多通道 + 注册/验证分离）

日期：2026-08-04 · 与 jinha 协作

> 术语注记（2026-10-18）：本文件写作于「验证系统」年代，该体系现已更名「**认证系统**」（账号认证 / 认证通道 / 已认证）；代码标识（`Verification` 模型、`/auth/verification/*`、`is_verified`）冻结不改。2026-10 起「验证」一词专指新增的**安全验证**（敏感操作前的本人确认，见后续 ADR）。

## 目标与动机

需求：

- 邮箱注册可选 → **分离注册与验证**。
- 重置密码、账号需**绑定邮箱**；邮箱验证通过即算验证（跳过人工审批）。
- 未验证账号等级为**访客**，功能受限。
- 验证**多通道**：邮箱验证、人工审批，二者独立、任一通过即算验证；后续还会增加更多方式。
- 个人中心开**验证板块**：查各通道状态、绑定并验证邮箱。
- **未验证账号也能登录**；**绑定邮箱后**才能用邮箱登录。

现状（2026-08-04）的矛盾：验证拆在 Profile 两个布尔上，各管各的——`email_verified` 卡**登录**、`identity_verified` 卡**写操作 + 徽章**。两个独立布尔管不同东西，自相矛盾、不可扩展、与新需求拧着。

## 核心模型：统一「已验证」+ `Verification` 通道

**账号「已验证」⇔ 至少一条验证通道通过（任一，any-of）。** 通道是一等公民，独立、可增量。邮箱、人工审批是通道；以后加通道是增量，不动核心判定。

### `Verification` 模型

```python
class Verification(models.Model):
    CHANNEL = [("appointment", "后台委任"), ("email", "邮箱"), ("manual", "人工审批")]  # 以后加 phone / sso / ...
    STATUS  = [("pending", "待验证"), ("approved", "已通过"), ("rejected", "已驳回")]
    user        = FK(User, related_name="verifications")
    channel     = CharField(choices=CHANNEL)
    status      = CharField(choices=STATUS, default="pending")
    identifier  = CharField(blank=True)   # 邮箱=待验地址；人工=空；后台委任=staff/superuser
    verified_at = DateTimeField(null=True)
    verified_by = FK(User, null=True)     # 人工=admin；邮箱/委任=空
    unique_together = ("user", "channel") # 每(user,channel)一行，当前状态 in-place
```

- **`is_verified`** = `user.verifications.filter(status="approved").exists()`——**单一计算源**，驱动 登录门禁 / 操作门禁 / 徽章 / 面板。
- **`IdentityProof`** 保留（FK→user），人工通道的**证据**（永久留底，审核通过后亦不删）。
- 删除 Profile 的 `email_verified` / `identity_verified` / `verified_at` / `verified_by` 四字段——单一事实源，杜绝双源漂移。

## 十四条决策

1. **统一「已验证」**（任一通道通过），取代 `email_verified` 管登录、`identity_verified` 管操作的双布尔拆分。两布尔降级为通道状态记录，用来*计算*那一个「已验证」。
2. **注册↔验证分离**：注册只建号；邮箱绑定、身份证明提交都挪到验证面板；证明仍是人工通道证据；面板里自选走哪条通道。
3. **注册必填** = 用户名 + 密码 + Turnstile；邮箱**可选**；`real_name` / `identity` 降为可选资料（`real_name` 改在提交证明时收）。
   > **2026-09 修订**：`real_name` / `identity` 回到注册必填（注册页收集、写入 `Profile`）；邮箱与身份证明仍留在验证面板。
4. **通道状态用 `Verification` 模型存**（非 Profile 布尔）。
5. **模型形状**：每 `(user, channel)` 一行、in-place 更新（不留尝试历史，审计走 `IdentityProof`）；枚举 `{pending, approved, rejected}`；`IdentityProof` 为人工通道证据。
6. **登录与验证解耦**：未验证可登（访客），只 `is_active` 拒停用；移除 `email_verified` 登录卡点。
7. **操作门禁** `IsIdentityVerified` → `IsVerified`，改读 `is_verified`；徽章 `_role_for` 同步改读 `is_verified`；作用域不变（只挂写动作）；取消「无 profile 视为已审核」后备。
8. **迁移**：布尔 1:1 → `Verification` 行（无存量用户，退化为给现有用户造 approved 行 = 信任态）；**删 Profile 四字段**；单一事实源。
9. **密码重置需已验证（绑定）邮箱**；无绑定 → 信息组人工。
10. **`User.email` 永远已验证（或空）**；待验邮箱住 `Verification.identifier`；验证通过才晋升写入 `User.email`。**邮箱登录只认 `User.email`**（已绑定），待验邮箱登不进。
11. **验证面板**（个人中心新 tab）：总览 + 每通道状态卡（状态→动作矩阵），仅本人可见，证明上传内嵌人工卡。
12. **人工审核三动作**：通过 / 驳回 / 停用账号。驳回触发邮件 + 允许重交；重交 = manual 行回 pending + 新证明累加。
13. **无存量用户**；任何已存在用户默认为真（信任态）。
14. **扩展性**：加通道 = 加 `CHANNEL` choices + 实现该通道流程；`is_verified` 自动纳入；面板数据驱动按通道铺卡。

## 关键流程

### 邮箱通道

- **绑定**：填邮箱 → `Verification(email, pending, identifier=邮箱)` → 发信（令牌绑 `identifier`）。`User.email` **不动**（保持空或旧验证邮箱）。
- **验证**（点链接）：email 行 `approved` → `identifier` 晋升写入 `User.email`。绑定生效。
- **改邮箱** = 重新绑：email 行回 pending + 新 identifier；未验证前 `User.email` 保留旧值；验证后才换。
- **唯一性**：绑定时校验该邮箱未被他账号有效持有。

### 后台委任通道

- **委任**：后台将账号标为管理员或超级管理员 → `appointment` 行 `approved`（`identifier`=`staff` / `superuser`）。只读，无自助申请。
- **撤销委任**：删 `appointment` 行；若无其它 approved 通道则回到未验证。与站点「验证通道开/关」无关（不是用户走通道，是委任副作用）。见 ADR-0013。

### 人工通道

- **提交**：上传证明（+ `real_name`） → manual 行 `pending` + `IdentityProof` 累加。
- **admin**：通过 → `approved`（+ `verified_at` / `verified_by`）+ 邮件；驳回 → `rejected` + 邮件；停用账号 → `is_active=False` + 吊销会话（账号级，与通道无关）。
- **驳回后重交**：manual 行回 pending + 新证明（旧行永久留底）。

### 登录

- **用户名登录**：任何活跃账号（无邮箱的账号照常登，落地访客）。
- **邮箱登录**：只匹配 `User.email`（已验证）；待验邮箱登不进（回退「凭据无效」）。

### 密码重置

- 按 `User.email`（已验证）发链接；无绑定邮箱 → 信息组人工。

## 被否方案

- **双布尔保留**（`email_verified` 管登录、`identity_verified` 管操作）：自相矛盾、不可扩展、与新需求拧着。否。
- **Profile 上累加通道布尔**（email/identity/phone/...）：any-of 逻辑散、`verified_at` / `verified_by` 归属歧义、加通道要改判定。否（改 `Verification` 模型）。
- **`User.email` 装待验邮箱 + status 标记**：`User.email` 语义糊（可能是未验证地址），且会让**未绑定邮箱也能邮箱登录**——直接违反需求。否（待验邮箱住 `Verification.identifier`）。
- **保留 Profile 四字段作反范式缓存**：双源必然漂移，违背单一事实源。否。
- **面板硬编码每通道卡**：加通道要改组件。否（改数据驱动）。
- **登录强制跳转验证面板**：访客看只读内容合理，提示用横幅即可。否。

## 待办（实现清单）

1. 建 `Verification` 模型 + 迁移（无存量用户；现有用户默认信任造 approved 行）；**删 Profile 四字段**（`email_verified` / `identity_verified` / `verified_at` / `verified_by`）。
2. `is_verified` 计算（`User` 属性或 helper，单一源）。
3. 改 `register_view`：邮箱可选、去 `real_name` / `identity` / 证明必填；注册**不**造 Verification 行（未验证 = 访客）。
4. 邮箱绑定 / 验证 / 重发 / 改邮：`Verification(email)` + `identifier` + 令牌绑 `identifier` + 验证通过晋升 `User.email`；绑定时校验唯一。
5. 改 `login_view`：去 `email_verified` 卡点；邮箱登录查 `User.email`。
6. 改 `password_reset`：查 `User.email`（已验证）。
7. `IsIdentityVerified` → `IsVerified`（改读 `is_verified`）；徽章 `_role_for` 改读 `is_verified`。
8. admin：`approve` / `reject` / `disable` 改操作 `Verification` 行；`ProfileAdmin` 过滤改走 Verification；加 reject 动作。
9. 验证面板（前端）：新 tab，总览 + 数据驱动通道卡 + 证明上传 + 绑邮箱/重发/换邮。
10. 测试：任一通道通过即验证、登录（用户名/邮箱）、重置、操作门禁、徽章、面板状态矩阵、驳回重交各路径。
