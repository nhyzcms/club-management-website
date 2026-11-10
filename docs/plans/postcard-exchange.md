# 明信片互寄 · 实施方案与交接文档

> 状态：**已完成**（2026-11-08，批次 1–4 全部合并）；交付后的增量见 §10「交付记录」，模拟环境（管理员演练 / 新功能验收）见 §11。本文是唯一权威方案落点：任何开发者 / agent 读本文即可接手。
> 需求提出：2026-11-07（用户）；方案批准：2026-11-07（用户逐条认可，含第五节 4 处解释）。

## 0. 进度看板

| PR | 分支 | 内容 | 状态 |
|---|---|---|---|
| #1 后端核心 | `feature/postcard-backend-core` | 模型 + 5 阶段状态机 + 条码生成/PDF + 登记 CRUD/搜索/导出 + 统计 + 权限 + 限流 + 审计 + 照片安全管线 + 测试 | ✅ #292 已合并 |
| #2 AI 与复核 | `feature/postcard-ai-review`（stacked on #1） | AI 客户端(OpenAI 兼容) + 配置/样例 + AI 审核流 + 人工复核台 + 照片自动删除 + 管理员邮件告警 + 测试 | ✅ #293 已合并（经 #295/#297 合流回 main） |
| #3 前端用户侧 | `feature/postcard-portal`（stacked on #2） | 主页按钮(新标签页) + `/#/postcard` 独立页 5 状态 + 登记表单(扫码/照片/下拉) + 历史 + **查询入口(登记码/姓名)** + 建议 + 深色纯黑适配 | ✅ #294 已合并（经 #295/#297 合流回 main） |
| #4 前端管理侧 | `feature/postcard-admin`（stacked on #3） | 活动配置 + 条码导出 UI + AI 配置/样例 + 记录管理/导出 + 统计图表 + 签收扫码页 + 截图 + README | ✅ #296 已合并（经 #297 合流回 main） |
| 批次 1 · 登记码体系 | `feature/postcard-shared-code` | 同一发件人共用登记码 + 服务端发码门禁（`access_token`）+ 截止后仍可改 + `/my/` 收紧 + 管理端 by-id | ✅ #298 已合并 |
| 批次 2 · 审核台/站内信/测试 | `feature/postcard-review-desk` | AI 连通性测试 + 复核并入 `/#/reviews`「明信片」桌 + 新待复核站内信（同码未读合并） | ✅ #300 已合并 |
| 批次 3 · 多届活动与健壮性 | `feature/postcard-next-season` | 归档 + 开启新一届 + IP 限流 60/h + 条码并发 400 + 配置缺省不变 + PDF 无孤儿 + GC timer | ✅ #301 已合并 |
| 批次 4 · 口径收尾 | `feature/postcard-polish` | 统计排除已取消 + 重试 1+5 / 超时 20s + 条码 PDF 打印提示 + docs-guard 收窄 | ✅ #302 已合并 |

stacked PR 约定：后一个 base 指前一个；前一个合并后 GitHub 自动改指 main。
2026-11-08 起改为**一批一个 PR、base 直接指 main**（避免再次出现合到旧分支的问题）。

## 1. 架构落点

- **后端**：`events/modules/postcard/`（modules 框架预留位，见 `events/modules/__init__.py`）。
  模型 `app_label="events"`，迁移集中在 `events/migrations/`，不动 `INSTALLED_APPS`。
  模型注册：`events/apps.py` 的 `ready()` 导入模块 models。
- **前端**：独立路由 `/#/postcard`；主页（桌面 + 手机）加单独按钮，`window.open` 新标签页。
- **活动壳**：复用 `Event`（标题 / 公告正文 / 时间窗 / 可见性 + `lifecycle.touch()` 硬关门）。
  `Event.start_at` = 登记开始，`Event.end_at` = 活动结束；模块配置补寄出 / 下发两个节点时间。
- **零新依赖**：Python 与 npm 均不新增。复用清单见 §6。

## 2. 状态机

### 活动 5 阶段（时间惰性推导，管理员改时间即改阶段）

```
未开始 ──start_at──> 登记中 ──ship_at──> 已寄出 ──distribute_at──> 下发中 ──end_at──> 已结束
```

- `ship_at` / `distribute_at` 可空 = 跳过该阶段；
- Event 处于 draft / archived 一律视为「未开始 / 已结束」语义（见 `state.py`）；
- **仅「登记中」开放登记**；其余阶段用户侧只显示公告 + 进度条（或全屏「本年度活动未开始」/「活动已结束」）。

### 登记记录 3 态

`已登记(registered) → 已报寄(reported) / 已取消(cancelled)`。
签收按 7 位条码定位到具体某张（`PostcardItem`），该张及其所属登记单状态联动
（登记单全部条码已报寄 → 登记单已报寄）。

## 3. 数据模型（`events/modules/postcard/models.py`）

| 模型 | 要点 |
|---|---|
| `PostcardConfig` | Event 一对一。可参与年级、寄达校清单、`ship_at`/`distribute_at` 节点、公告附件(PDF)。`Meta.permissions` 声明 `manage_postcard` / `review_postcard` 两个命名工作流权限。**寄达区下拉 = `REGION_CHOICES` 写死的上海市 16 区固定清单（顺序固定，2026-11-08 用户指定）**；寄达校下拉按所选区从清单过滤，登记校验要求 (区, 校) 配对命中 |
| `PostcardBarcode` | event + 7 位随机数字，`(event, code)` 唯一（单活动内不重复，跨活动可复用） |
| `PostcardRegistration` | 一次**提交**（同一发件人可多次提交）。6 位登记码：**同一发件人（姓名 + 年级 + 班级，2026-11-08 用户指定）在活动内共用**、`(event, reg_code)` 只建索引不唯一；`access_token` = 单次提交的轮询凭证（审核未过时不发码）。姓名、年级、班级、寄达区、寄达校、状态、`device_id`（`club_device` cookie）/ `fingerprint_hash` / 登录用户 三轨归属 |
| `PostcardItem` | 登记单内每张明信片，绑条码（`(event, barcode)` 唯一 → 一条码一明信片）；一次登记可多张；同寄出人自动聚合展示 |
| `PostcardPhoto` | 正/反面照片，私有存储，审核状态机（PR2 起 AI 用） |
| `PostcardAIConfig` | base_url / api_key(写后不可读) / model / 自定义请求头 JSON / 超时（PR2） |
| `PostcardAISample` | 管理员上传样例照片 + 说明；**活动开始前必须配置**，否则登记接口拒绝开放（PR2） |
| `PostcardSuggestion` | 用户建议（内容 + 可选联系方式） |
| `PostcardAuditLog` | 管理员操作全留痕：配置变更 / 导出 / 删除 / 签收 / 复核 |

## 4. 条码规格

- 7 位纯随机数字（`secrets`），Code128（reportlab 编码，几何同 `accounts/member_barcode.py`）；
- 生成数量：**1500 ~ 10000，步进 500，默认 6000**（服务端强校验）；
- PDF 整版导出：A4，条码规格 40×20mm（条 + 下方 7 位人眼可读数字），间隙 2mm，
  每页 5 列 × 13 行 = 65 枚；6000 张 ≈ 93 页；reportlab 流式输出（2C2G 服务器实测无压力）；
- 中文字体：`activities/fonts/NotoSansSC.ttf`（页眉/页脚用；缺失时退化 Helvetica，条码数字为 ASCII 不受影响）；
- 版面边距：5 列 × 40mm + 4 × 2mm = 208mm，横向仅约 1mm 余量——**PDF 每页页脚提示「请选实际大小 /
  100%，勿缩放」**，否则打印机缩放会把条码裁掉或压窄导致扫不出。

## 5. 网安设计对照（需求 → 实现）

| 要求 | 实现 |
|---|---|
| CSRF | DRF SessionAuthentication 自带校验（全站现状） |
| SQL 注入 | 全程 Django ORM 参数化，零裸 SQL |
| 越权 IDOR | 历史列表按 ncdid + 指纹哈希 + 登录用户归集，**指纹必须与设备/登录同时命中**（单轨指纹可被复制，2026-11-08 收紧）；**登记码即能力凭证**（任何设备凭 6 位码可查/改/取消/申请复核，码不对一律 404）；**未达发放条件时服务端只回掩码 + `access_token`**，不提前泄露能力凭证；姓名查询只回掩码码；双轨限流防枚举（查询 20/min·设备 + 300/h·IP，凭证端点 30/min·设备 + 120/h·IP）；管理端命名权限，多份同码时管理端只接受按提交 id 操作 |
| 文件上传 | 魔数校验 → Pillow 重编码（**压缩至最长边 1280 / 质量 80**，EXIF 自动剥离）→ `PRIVATE_MEDIA_ROOT` 私有存储 → 短期签名 URL 仅审核台可达 |
| 速率限制 | 登记 / 照片 / 建议 按 IP + 设备双轨限流（复用 `common/throttles.py`） |
| 人机验证 | 登记提交挂 Turnstile（复用 `turnstile.ts`） |
| CSP | 公告渲染走 `common/rich_text.sanitize_html` 白名单净化；PDF 公告经独立视图输出，强制 `CSP: sandbox` + `nosniff`，PDF 内嵌 JS 不可能执行 |
| Cookie | 全站已 HttpOnly + Secure + SameSite（settings 现状，不动） |
| 审计日志 | `PostcardAuditLog`：配置变更 / 导出 / 删除 / 签收 / 复核全记录 |
| 错误信息 | AI 失败只回「哪一项不匹配」，不回显内部异常 / 堆栈 |
| Excel 公式注入 | `= + - @ \t \r` 开头单元格前置 `'`（同 `activities/survey_export.py` 审计 M-5 手法） |
| PDF 中文字体 | NotoSansSC 注册进 reportlab |
| XSS | 公告 word 导入：前端 mammoth 转 HTML → **服务端 bleach 白名单净化**后入库；表单字段纯文本转义渲染 |
| 备份加密 / HTTPS | 站点既有措施（ZeroSSL + nginx TLS），本功能不新增面 |

## 6. 复用清单（零新依赖）

Code128=`reportlab`（`accounts/member_barcode.py`）；中文字体=`activities/fonts/NotoSansSC.ttf`；
Excel=`openpyxl`；净化=`bleach`（`common/rich_text.py`）；摄像头扫码=`barcode-detector`（支持 code_128）；
Word 导入=`mammoth`；图表=`chart.js`；人机验证=Turnstile；限流=`common/throttles.py`；
设备 Cookie=`club_device`（`accounts/utils.py`，ADR-0028 多端登录复用）；私有存储=`PRIVATE_MEDIA_ROOT`；缓存=Redis；邮件=`EMAIL_BACKEND`。

## 7. AI 管线（PR2）

- OpenAI 兼容协议，**urllib 零依赖**实现（JSON + base64 图片，带超时）；
- 判定输入：用户照片 + 管理员样例 + 规则文本 + **动漫黑名单 IP 清单**（预置广电网络动漫黑名单条目，管理员可编辑）；
- 输出强制严格 JSON（匹配与否 + 不匹配项 + 黑名单判定）；解析失败视为本次失败；
- **5 次重试机会 = 1 次初始 + 5 次退避重试（共 6 次尝试，退避 1/2/4/8/16s）** → 全败自动转人工复核队列；
- 单次调用超时默认 **20s**（管理端可调 5–120s）；另有「测试连接」端点用已保存配置发一次最小文本请求，
  回 `{ok, latency_ms, model, reply}`，错误按 HTTP 状态收敛成人话、绝不回显 api_key；
- Redis 计数器跟踪**连续 5 个用户失败** → `send_mail` 通知所有绑定邮箱的管理员；
- 照片生命周期：AI/人工通过 → 立即删；复核失败 → 用户关标签页 `sendBeacon` 删 + 24h TTL 兜底；
  活动结束 → 全量清除（状态翻转触发 + 周期兜底）。登记数据永久保留，除非管理员手动删。

### 7.1 管理端前端（PR4）

- 路由：`/#/postcard/admin`（六个分区：配置 / 条码 / AI / 记录 / 统计 / 建议与审计）、
  `/#/postcard/receive`（签收扫码）——两者均挂 `ProtectedRoute`，权限真源在服务端命名权限，
  前端只做「403 → 无权限提示」，不复制一套权限判定；人工复核不在管理端，见 §7.3。
- 配置提交固定走 **multipart**：公告 PDF 只能走文件上传，而 HTML 表单承载不了对象数组，
  所以 `destination_schools` 以 JSON 串提交，后端 `JSONListField` 只在 html 输入且值以 `[`
  开头时解码（JSON 请求行为不变，非法 JSON 仍按字段错误返回）。
- 性能：`chart.js`（统计页）与 `zxing-wasm`（扫码）全部动态 `import()`，普通用户首屏零增量；
  管理端样式复用 `cobalt.css` 设计令牌，深色模式随 `data-theme` 自动接管。

### 7.2 共用登记码（批次 1，2026-11-08）

- **同一发件人 = 姓名 + 年级 + 班级**（用户指定 B 方案）：再次提交复用首份的 6 位码，每次提交仍是独立行（各自的寄达校 / 审核状态）。跨设备/跨账号复用同码会写一条 `code_reused_cross_track` 审计（冒名追查）。
- **发码门禁落在服务端**：存在失败条目 → 掩码；已转人工 / 全部通过 → 真码；仍在 AI 审核 → 掩码 + 下发 `access_token`。前端审核中轮询 `/my/token/<token>/`，不再提前拿码。
- 用户侧操作：`/my/<code>/` 支持 `?id=` 指定单份；取消支持 `scope=one|all`，整批取消前端需重新输入 6 位码（不可逆二次验证）。
- 管理端：记录行带 `registration_id`，改/删走 `admin/registrations/by-id/<id>/`；按码操作在多份提交时返回 400。
- 登记截止后 portal 仍下发年级 / 16 区 / 学校清单（历史「修改」可用）；用户改登记与登记同一套区校校验；已取消条目不再阻塞登记单状态联动。

### 7.3 审核台集成 + 站内信 + 连通性测试（批次 2，2026-11-08）

- **不单开复核台**：管理端删除「复核台」tab，人工复核并入全站审核台 `/#/reviews` 的「明信片」桌
  （桌面 `ReviewQueuePage` 与手机 `MobileReviewPage` 共用 `PostcardReviewPane`，沿用 `reviewDesk.ts`
  的取数与「下一条」语义）；队列接口补通用 `id` 与 `state=manual_pending|ai_failed` 过滤；
  `/auth/me` 增 `can_review_postcard`（manage 隐含），能力标签表同步（契约测试钉死）。
- **站内信**：`ReviewSource` 新增事件 `postcard_submitted`（「新明信片待复核」），
  `notify_perm("review", ..., "events.review_postcard", extra_recipients=manage 持有者)` 投递；
  订阅开关 / 未读 / 推送 / 外发规则与「新内容送审」完全一致；**同登记码未读合并**
  （`ReviewSource.dedup_identity`）防刷屏。触发点：AI 未配置或不可用转人工、AI 重试耗尽转人工、
  用户主动申请人工复核。
- **AI 连通性测试**：`POST /admin/ai/test/`（manage）用已保存配置发一次最小文本请求，
  返回 `{ok, latency_ms, model, reply}` 或 `{ok:false, error}`；401/403/404/429/5xx 收敛成中文，
  写审计 `ai_test`；管理端 AI 页有「测试连接」按钮。

### 7.4 多届活动与健壮性（批次 3/4，2026-11-08）

- **多届活动**：`POST /admin/new-season/` 归档当前活动 + 新建草稿（复制年级与寄达校清单）；
  `POST /admin/archive/` 单独归档。管理端配置页「开启新一届（归档当前）」按钮，二次确认。
  归档活动对公众仍显示「活动已结束」（`current_event` 回退语义保留），旧登记数据不动。
- **限流**：登记 IP 轨 10/h → **60/h**（学校 NAT 整层楼共出口），设备轨维持 10/h。
- **并发**：条码预检通过后被另一请求抢占时，捕获唯一约束冲突返回友好 400（不再 500）。
- **配置 PUT**：节点 / 年级 / 清单 / 公告正文缺省 = 保持不变；公告 PDF 替换前删旧文件。
- **周期清理**：`install.sh` 安装 `${SERVICE}-postcard-gc.timer`（每小时 + 随机延迟），
  活动结束后的照片清除不再依赖「有人访问页面」。
- **统计口径**：已取消条目不计入「明信片总数 / 按校 / 按年级 / 按日」，取消数单独给出。


## 8. 需求解释（已获用户认可，勿再改动）

1. 「只有登记中的时候开放登录」= **开放登记**：非登记中只显示公告 + 进度条（或未开始 / 已结束全屏提示）。
2. 「后台自动整个同一寄出人的明信片」= 自动**整合**（聚合展示）。
3. 签收页扫**明信片上的 7 位条码**，命中展示所属登记单信息，确认后置「已报寄」；
   未命中提示「明信片未登记，请先登记！」。
4. 指纹 = 轻量 JS 指纹（canvas / 屏幕 / UA / 时区哈希），与 `club_device` Cookie 双轨并用，服务端只存哈希。
5. **登记码发放时机（2026-11-08 用户指定）**：AI 审核通过后才在「登记成功」弹窗亮码；
   AI 不可用转人工复核 → 立即发码（不等人工结果）；AI 判不匹配 → 不发码、告知具体错项，
   用户申请人工复核转人工后立即发码。审核中弹窗显示「审核中」，前端 2s 轮询、40s 封顶。

## 9. 服务器约束（2C / 2G / 3M）

- 条码 PDF 流式生成，不落盘缓存全量；
- 照片重编码压缩至最长边 1280（质量 80；审核用途足够，省存储与 AI 上行载荷）、单张 ≤5MB、单次登记 ≤5 张明信片（10 张照片）；
- AI 调用带超时（默认 20s）+ 重试上限（1+5），绝不挂起 worker；
- 导出接口仅管理员 + 限流；
- 不在生产服务器跑测试 / 构建（CI：docs-guard / backend / frontend / frontend-test / e2e）。

## 10. 交付记录（批次之后）

| PR | 内容 |
|---|---|
| #305 | README 精简为定位 + 亮点 + 入口 |
| #306 | 撤销「互动」改名、恢复单一「活动」入口、下线通用 `events` CRUD；`Event` 只作明信片壳 |
| #307 | 补齐 `ContentTarget.kind` 与 `Notification.category` 的 choices 迁移 |
| #309 | 海报 AI 导入寄达校 + 区内编号排序与检索 |
| #310 → #311 | 管理端「模拟活动」模拟环境（PR1）合入后整体回滚，未保留 |
| #312 | 模拟环境 PR1 重建（撤销回滚）：内存沙箱 + 管理端 6 个 tab，见 §11 |
| #313 | 模拟环境 PR2：用户端登记 / 查询 / 历史 + 审核台 + 签收接同一沙箱 |
| #314 | 模拟环境修复：退出后残留数据、复核「不通过」误取消、照片压缩 |
| #315 | 模拟环境口径对齐：壳锁含简介、登记单状态联动、提交粒度、改单校验 |
| #317 | 模拟环境 AI 演练 `dry_run`：不写正式审计 |
| #318 | AI 端点限流：测试连接 60/h、读样例 10/h |
| #319 | 模拟环境登记**真跑 AI 判定**（`admin/ai/preview/`，不落库），见 §11.3 |
| #321 | 退出模拟前二次确认（误点退出会清空演练数据） |
| #322 | AI 配置预设（DeepSeek / OpenCode-GO）+ 从服务商 `/models` 拉取模型清单（不内置写死列表） |

运维增量：`scripts/install.sh` 新增 `club-postcard-gc.timer`（每小时跑 `postcard_photo_gc`，做活动结束全清 / 失败照片 24h TTL / 卡死 pending 转人工）。文档增量：新增 [明信片互寄 API](../api/postcard.md) 与 [明信片互寄指南](../guides/postcard.md)，`events` 通用模块文档改为壳说明。

## 11. 模拟环境（2026-11-09）

> 目的：管理员**教学演练**、开发者**验收新功能**——界面与正式版完全一致，数据只在浏览器内存里，退出即清空（PR #312 / #313，修复 #314 / #315 / #317）。

### 11.1 入口与生命周期

- 入口：明信片管理端「去审核台复核」后面的**模拟活动**按钮 → 弹「是否进入模拟操作」→ `#/postcard/admin?sim=1`。
- 标识：管理端标题后**红底白字**「模拟环境」（URL 带参或沙箱已装载都会显示）；用户页 / 审核台 / 签收页右下角固定浮标「模拟环境 · 退出模拟」。
- 生命周期：
  - 进入：URL 带 `sim=1`；
  - **保持**：在明信片这条链（`#/postcard`、`/postcard/admin`、`/postcard/receive`、`#/reviews`、`#/m/review`）之间切换**不卸载**，URL 没带参数也继续用沙箱——用户页 ↔ 管理端来回跳不丢测试数据（用户 2026-11-09 要求）；
  - 退出：点「退出模拟」→ **二次确认**（#321）→ 卸载沙箱并 `reload` 回正式环境（不 reload 的话已渲染页面会残留模拟数据）；离开这条链同样卸载；刷新 / 关标签页天然清空。

### 11.2 实现方式（页面零改动）

- `api/postcardAdmin.ts` / `api/postcard.ts` 出口是 `Proxy`：真实现常规直通，装上模拟实现时整体路由 → **页面组件一行不改**，这是「界面一模一样」的结构保证。
- `frontend/src/postcardSim/`：
  - `state.ts` 内存数据模型 + 与后端对齐的口径（阶段推导 / 条码 / 校验 / 状态联动 / 统计）；
  - `api.ts` 管理端、`apiUser.ts` 用户端（形状与真实 API 完全一致）；
  - `files.ts` 浏览器现造 PDF / xlsx（不新增依赖），导出文件名自动加「-仅限模拟环境使用」；
  - `session.ts` 装卸与路由判定，`SimHost.tsx` 全局宿主 + 浮标。

### 11.3 隔离边界

- 活动 / 条码 / 登记 / 统计 / 建议 / 审计：**全部内存**，不发任何写请求。
- 导出：浏览器生成文件，不请求后端。
- AI 相关（用户 2026-11-09 要求「模拟流程与正式一模一样」）：四处真调后端，**都不落库、不写审计**：
  - **登记判定** `admin/ai/preview/`：表单 + 正反照片 → 跑一次真实判定（同一套 prompt / 解析，见 §7），返回 verdict；不建登记单、不存照片、无审计，限流 120/h；
  - 测试连接 `admin/ai/test/`：可带临时参数（只用于本次请求），并带 `dry_run`，限流 60/h；
  - 导入海报 `admin/schools/import/`：`dry_run=1`，识别结果只进内存表单，限流 10/h；
  - 读样例 `admin/ai/explain/`：一次性上传解读，不落库、不留文件、无审计，限流 10/h。

### 11.4 与正式口径对齐的规则（模拟里必须一致，否则会教错人）

| 规则 | 说明 |
|---|---|
| 5 阶段推导 | 节点可空跳过；draft / archived 语义同 `state.py` |
| 条码 | 7 位唯一、1500~10000 / 步进 500、被占用不能覆盖重建 |
| 登记判定 | 真跑 AI：通过 → `ai_passed` + 删照片 + 亮码；不匹配 / 黑名单 → `ai_failed` + 掩码 + 列错项，可申请人工复核（转人工后立即发码）；AI 不可用 → `manual_pending` 但**立即发码** |
| 壳锁 | 活动开始后锁「标题 / **简介** / 起止时间」，节点 / 学校 / 公告仍可改 |
| 提交粒度 | 同一发件人（姓名 + 年级 + 班级）复用同码，每次提交是独立登记单；取消一份提交整条作废 |
| 状态联动 | 全部未取消条目都报寄 → 登记单「已报寄」；已取消条目禁止签收 |
| 复核 | 「人工不通过」只改复核态（`manual_failed`），**不取消登记单**；通过即删照片 |
| 照片 | 上传即压到最长边 1280 / JPEG 0.8（同正式管线），SVG 等无法重编码时回退原图 |

以上每一条都有对应前端用例钉住（`frontend/src/__tests__/postcard-sim*.test.tsx`）。

### 11.5 已知限制（刻意不做）

- 判定请求是**同步**的一次调用（正式环境是后台队列 + 5 次重试）；失败直接按「转人工」降级，不会重试；
- 演练会消耗真实 AI 额度（每张明信片一次调用，限流 120/h）；
- 无 Turnstile、无登记侧限流 / 并发保护、无站内信（这些是防御设施，不是教学重点）；
- 导出文件是**浏览器现造**的示意件（条码 PDF 只列前 100 个码），只用于验证流程。
