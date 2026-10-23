# 全站弹窗公告：原件保真 + 已读台账

日期：2026-10-24

社团需要一个**能把通知直接推到每个人眼前**的渠道：横幅会被忽略、站内通知要自己点铃铛、
微信群又覆盖不到已毕业的成员。本记录定义「全站弹窗公告」的形态、文档保真方案与已读口径。

## 决策

1. **一条 `Announcement` = 一次弹窗 + 一条站内通知 +（可选）一封邮件**。发布是后台动作，
   前台没有任何写接口；`status`（草稿 / 已发布 / 已下线）+ `published_at` 决定「在线」，
   `expires_at` 可限定自动停止弹出的时间（到点后不再弹，但通知与回看页仍可访问）。
2. **文档只存原件，浏览器端保真渲染**。
   - PDF → **pdf.js**（逐页画到 canvas）：Android WebView / 手机 Chrome 不渲染内嵌 PDF
     （`<iframe src="x.pdf">` 在 App 壳里是空白），pdf.js 两端一致。
   - `.docx` → **docx-preview**（与关于页文档保真导入同一套组件与判断）。
   - 都提供「下载原件」。**不做服务端转换**（LibreOffice 在 2C2G 机型上太重、
     且发布包更新不会安装系统包），也**不转站内富文本**（mammoth 会丢分页 / 字体 / 边框）。
   - 上限 20MB，与关于页文档导入一致；pdf.js 页数封顶 40 页并提示下载原件。
3. **受众四档**：`all`（含未登录访客）/ `registered` / `verified` / `admin`。
   `verified`、`admin` 的判定与 `accounts.models.is_verified` / `admin_identity_valid`
   **逐条等价**（同一批 status + 有效期条件），不另立口径；SQL 版写成
   `Q(verifications__… )` 且**必须在同一个 `filter()` 内**，否则两次 join 会出现
   「一行过期 + 一行未过期」的假阳性。
4. **已读 = 关闭弹窗**。`AnnouncementRead(announcement, user)` 唯一约束，一人一行、
   跨设备一次性。匿名访客没有行可写，用 `localStorage["cobalt:announcement-seen"]`
   记住，刷新不再弹；因此后台的「阅读量」只统计登录用户。
5. **通知与邮件复用既有通知框架**：`notify_many("announcement", "published", …)` 落站内
   通知并实时推送；`send_email=True` 时再为每位收件人补一条 `NotificationDelivery`
   （`channel_key="email"`），走异步投递队列（失败退避重试）。**邮件只发已认证邮箱**，
   避免把公告发到拼写错误的未验证地址。
6. **权限单点**：`announcements.manage_announcements` 一个命名工作流权限收口整个后台模块
   （`AnnouncementAdmin` 覆写 `has_*_permission`），迁移默认授予「社长」「信息组」。
   前端能力键 `can_manage_announcements`（与 `can_manage_announcement`＝横幅公告区分）。
7. **超管不外显**：全站广播文案与前端有效期规则里不再出现「超级管理员永久有效」；
   公共用户主页的徽章把 `superadmin` 一律显示为「管理员」（`account_validity` 快照仍只
   返回本人，`/admin/` 也只有职员能进）。

## 被否的方案

- **服务端把 WORD 转 HTML / 抽取文字**：版式丢失（分页、缩进、表格边框、页眉页脚），
  与「保持原格式 / 排版不变」直接冲突。否。
- **服务端装 LibreOffice 转 PDF**：2 核 2G 机器上一次转换就会吃掉几百 MB 内存，且
  `scripts/install.sh` 之外还得手工装系统包，更新器不会补。否。
- **PDF 用 iframe 直出**：桌面可用、**App 壳（WebView）与手机浏览器不可用**，等于对一半
  用户不可见。否（pdf.js 按需懒加载，代价只有一个 ~1MB 的 worker）。
- **每次打开页面都弹（不记已读）**：会变成打扰，且后台没有「阅读量」可言。否。
- **把公告塞进私信（Conversation/Message）**：会给每个人留下一堆无法归档的会话，
  且私信的历史噪音与通知语义不同。否（用 `Notification` + 独立回看页）。
- **匿名访客也计入阅读量**：需要设备指纹 / IP 去重，涉及隐私且不准确。否（明示只统计登录用户）。

## 迁移与兼容

- 新 app `announcements`：`0001_initial`（两张表 + 唯一约束 + 索引）、
  `0002_grant_manage_permission`（社长 / 信息组授权）。
- 通知源 `announcement` 早已注册（原「横幅广播」），本次把名称改为「全站公告」并补邮件文案；
  前端 `NotificationCategory` 补 `announcement` / `activity` 两个一直缺失的分支。
- 邮件链接修复：`messaging.notifications.channels._absolute_url` 之前拼成
  `https://站点/news/42`（HashRouter 打开会落到首页），改为 `https://站点/#/news/42`——
  影响所有源的邮件链接，属顺带修正。
- 无破坏性数据迁移；`/announcements/` 是新增 URL 前缀，nginx 无需改动（走 Django）。
