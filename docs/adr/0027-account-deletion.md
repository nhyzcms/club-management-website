# 账号注销：软删除 + 敏感信息清除

日期：2026-10-18

成员可以离开社团，但**账号不能带着邮箱、身份证明与登录设备记录一直留在库里**。同时，社团又必须保住历史内容归属、社员名册与后台审计——直接删 `User` 行会连带毁掉私信、评论、任务、名册绑定，并让「这个 id 以前是谁」永远查不到。本记录定义「注销」的语义与数据边界。

## 决策

1. **软删除，永不物理删除 `User` / `Profile`**。`Profile.deleted_at` 非空即「已注销」，是所有注销态判定的**唯一真源**（`accounts.models.is_deleted_user`）。
2. **必须保留**：
   - `User.id`（账户唯一编码）、`username`、`date_joined`；
   - `Profile.real_name`（真实姓名，审计与名册核对需要）、`nickname`、`identity`；
   - `MemberIdentity` 整行（社员编号 `code`、学号、届数、绑定关系、`phone` 等名册快照）——名册是社团档案，不随账号注销而删；
   - 历史内容与其作者外键：私信、评论、新闻、任务、活动、投票、兑换记录等。
3. **必须清除**：
   - 登录邮箱 `User.email`（同时释放该邮箱的绑定唯一性）；
   - 全部 `Verification` 行（邮箱 / 认证码 `identifier` 等随身标识，`ValidityNotice` 级联）；
   - `IdentityProof` 行 + `PRIVATE_MEDIA_ROOT` 里的证明文件；头像文件；
   - `Profile` 的 `bio` / `birthday` / `gender` / `avatar`；
   - `UserSession`（IP / UA / 设备）与 Django `Session`（强制下线）；
   - 密码置为不可用（`set_unusable_password`），此后登录一律 401；
   - 站内通知、通知偏好、消息已读状态；
   - 安全验证残留：`SecurityQuestion`（答案哈希）、`StepUpEmailCode`（含邮箱原文）、`StepUpEvent`（含 IP）。
4. **展示口径**：`SimpleUserSerializer` 对已注销账号输出 `is_deleted=true`、`username=""`、`avatar=null`、`nickname="该用户已注销"`——一处收口所有历史内容（私信发送者、评论作者、新闻作者、提及列表）。个人主页返回墓碑响应（`deleted: true`，只给 id 与注册时间），前端渲染「该用户已注销」。用户搜索（含 @ 提及 / 发私信选人）走 `is_active=True`，已注销账号不再出现。
5. **私信**：历史会话只读——`send_dm` 检测到对方已注销 → 403「该用户已注销，无法继续发送私信」；`start_private` 同样拒绝。前端在会话顶部显示提示并禁用输入。
6. **入口与确认**：个人中心新增「注销账号」面板。三重确认由后端复核：勾选知悉 + 逐字输入「注销账号」+ 当前密码；账号配置了可用安全验证方式（认证邮箱 / 安全问题）时**另需 Step-up grant**（scope `delete_account`），没有可用方式时退回密码确认，避免把未认证用户永久挡在门外。
7. **管理员保护**：`is_staff` / `is_superuser` 账号不允许自助注销（403 `account_deletion_protected`），避免社团误失后台；离任应先调整角色。
8. **幂等**：重复注销返回 409 `account_already_deleted`，不伪装成功。

## 被否的方案

- **物理删除 `User`**：`Message.sender` / `Comment.author` / `News.author` 等 CASCADE 会连带删除历史内容；`MemberIdentity.user` 变 `NULL` 丢失绑定；且 id 复用会让后台审计与兼容性排查彻底失真。否。
- **注销时改写 `username`（如 `deleted_123`）**：用户名是账号唯一编码与历史 @ 文本的锚点，改名会让旧提及、日志、名册对不上。否（只做展示层遮蔽）。
- **删除该用户的私信**：对方机器上的历史会凭空消失，且破坏会话一致性；只读保留 + 墓碑展示足够。否。
- **注销时清空 `MemberIdentity`（含社员编号）**：名册是社团档案、且 `code` 全库唯一，用于扫码校验与后续核对。否。
- **只靠 `is_active=False`**：停用账号仍保留邮箱、身份证明与设备记录，不满足个人信息清除要求。否（注销 = 停用 + 清除 + 标记）。

## 兼容与迁移

- 迁移 `accounts/0019_profile_deleted_at`：`Profile` 增加 `deleted_at`（可空），无数据回填。
- 新增 Step-up scope `delete_account`；后端 `accounts.stepup.SCOPES` 与前端 `STEPUP_SCOPE_LABELS` 同步。
- 后台：用户列表 / 资料列表新增「已注销」列与筛选；`deleted_at` 只读（系统维护）。已注销账号仍可在后台搜索、查看真实姓名与名册绑定。
- 相关：[API · accounts](../api/accounts.md)、[ADR-0026](0026-stepup-verification.md)、[ADR-0025](0025-member-identity.md)。
