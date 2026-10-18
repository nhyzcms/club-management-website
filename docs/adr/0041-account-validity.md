# 账号身份有效期：认证 / 管理员 / 注册宽限三档（补档）

日期：2026-10-18（**补档**：决策实际落地于 2026-10 早段批次，代码先行为「ADR-0041」编号，本文按现行代码行为回写）

代码多处引用「ADR-0041（身份有效期）」而仓库 ADR 缺档（止于 0024）。本文件沿用代码引用编号补档，不改引用号。

## 背景

认证引入「有效期」概念前，通过记录永不过期：管理员权限与「已认证」永不回收，未认证账号则永远滞留。三档期限（站点策略可调，默认值见 `common/policy.py`）：

- **认证有效期** `verification_valid_days`（默认 365）：普通认证通道（email / manual / authcode）通过 → `expires_at = 通过日 + N`；过期后需重新认证（认证码通道据此**放宽约束为「每 (账号, 码) 一条」**，允许重新兑换不同码）。
- **管理员有效期** `admin_valid_days`（默认 730）：委任通道到期 → 自动撤销 `is_staff`（回落普通用户，需重新授予）；超管永远豁免。
- **注册宽限** `registration_verify_days`（默认 60）：从未认证账号，`date_joined + N`（或 `Profile.registration_deadline` 显式覆盖）到期 → 停用账号（`is_active=False`）并标记 `expiry_disabled_at`（登录时给专属提示）；持 `manage_validity` 的管理员可手动调整有效期（`can_manage_validity_for` 权限层级门控）。

## 决策

1. **单一计算源**：`is_verified` 即含有效期判定（未过期才算认证），账号「已验证」判定与接口契约（如 `me` 键集）均以它为准；`has_ever_verified` 另供「是否曾通过」判断。
2. **执行器双入口、单实现**：惰性（请求 / 登录时 middleware，带会话级节流）+ 定时（management command，支持 `--dry-run`）共用 `accounts/validity.py`；幂等——已处理账号重复执行 no-op；管理员过期优先于未认证停用判定。
3. **豁免与边界**：超管直接 no-op；已手动停用账号不再改提示语义（避免覆盖人工处置）。

## 兼容与迁移

- 迁移 `accounts/0013`：`Verification.expires_at`、`Profile.registration_deadline`、`Profile.expiry_disabled_at` 三字段 + 存量回填（存量认证记录 = 迁移时刻 + 365 天；委任 = +730 天；超管 = 永久）+ 新增并授予 `manage_validity` 权限（社长 / 信息组）。
- 相关：`accounts/middleware.py`、`accounts/validity.py`、`accounts/identity_review.py`、`common/policy.py`。
