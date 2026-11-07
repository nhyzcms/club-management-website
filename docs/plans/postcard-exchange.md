# 明信片互寄 · 实施方案与交接文档

> 状态：**开发中**。本文是唯一权威方案落点：任何开发者 / agent 读本文即可接手。
> 需求提出：2026-11-07（用户）；方案批准：2026-11-07（用户逐条认可，含第五节 4 处解释）。

## 0. 进度看板

| PR | 分支 | 内容 | 状态 |
|---|---|---|---|
| #1 后端核心 | `feature/postcard-backend-core` | 模型 + 5 阶段状态机 + 条码生成/PDF + 登记 CRUD/搜索/导出 + 统计 + 权限 + 限流 + 审计 + 照片安全管线 + 测试 | 已完成（63 测试全绿，待 CI） |
| #2 AI 与复核 | （stacked on #1） | AI 客户端(OpenAI 兼容) + 配置/样例 + AI 审核流 + 人工复核台 + 照片自动删除 + 管理员邮件告警 + 测试 | 未开始 |
| #3 前端用户侧 | （stacked on #2） | 主页按钮(新标签页) + `/#/postcard` 独立页 5 状态 + 登记表单(扫码/照片/下拉) + 历史 + 建议 + 深色纯黑适配 | 未开始 |
| #4 前端管理侧 | （stacked on #3） | 活动配置 + 条码导出 UI + AI 配置/样例 + 复核台 + 记录管理/导出 + 统计图表 + 签收扫码页 + 截图 + README | 未开始 |

stacked PR 约定：后一个 base 指前一个；前一个合并后 GitHub 自动改指 main。

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
| `PostcardRegistration` | 6 位随机登记码（单活动唯一，**防 IDOR 的能力凭证**）、姓名、年级(高一~高三)、班级(1-8)、寄达区、寄达校、状态、`device_id`(ncdid) / `fingerprint_hash` / 登录用户 三轨归属 |
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
- 中文字体：`activities/fonts/NotoSansSC.ttf`（页眉用；缺失时退化 Helvetica，条码数字为 ASCII 不受影响）。

## 5. 网安设计对照（需求 → 实现）

| 要求 | 实现 |
|---|---|
| CSRF | DRF SessionAuthentication 自带校验（全站现状） |
| SQL 注入 | 全程 Django ORM 参数化，零裸 SQL |
| 越权 IDOR | 历史/修改按 ncdid + 指纹哈希 + 登录用户过滤；**改记录必须出示 6 位登记码**；管理端命名权限 |
| 文件上传 | 魔数校验 → Pillow 重编码（EXIF 自动剥离）→ 像素上限 2048 → `PRIVATE_MEDIA_ROOT` 私有存储 → 短期签名 URL 仅审核台可达 |
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
设备 Cookie=`ncdid`（`DeviceIDMiddleware`）；私有存储=`PRIVATE_MEDIA_ROOT`；缓存=Redis；邮件=`EMAIL_BACKEND`。

## 7. AI 管线（PR2）

- OpenAI 兼容协议，**urllib 零依赖**实现（JSON + base64 图片，带超时）；
- 判定输入：用户照片 + 管理员样例 + 规则文本 + **动漫黑名单 IP 清单**（预置广电网络动漫黑名单条目，管理员可编辑）；
- 输出强制严格 JSON（匹配与否 + 不匹配项 + 黑名单判定）；解析失败视为本次失败；
- **5 次重试**（指数退避）→ 全败自动转人工复核队列；
- Redis 计数器跟踪**连续 5 个用户失败** → `send_mail` 通知所有绑定邮箱的管理员；
- 照片生命周期：AI/人工通过 → 立即删；复核失败 → 用户关标签页 `sendBeacon` 删 + 24h TTL 兜底；
  活动结束 → 全量清除（状态翻转触发 + 周期兜底）。登记数据永久保留，除非管理员手动删。

## 8. 需求解释（已获用户认可，勿再改动）

1. 「只有登记中的时候开放登录」= **开放登记**：非登记中只显示公告 + 进度条（或未开始 / 已结束全屏提示）。
2. 「后台自动整个同一寄出人的明信片」= 自动**整合**（聚合展示）。
3. 签收页扫**明信片上的 7 位条码**，命中展示所属登记单信息，确认后置「已报寄」；
   未命中提示「明信片未登记，请先登记！」。
4. 指纹 = 轻量 JS 指纹（canvas / 屏幕 / UA / 时区哈希），与 ncdid Cookie 双轨并用，服务端只存哈希。

## 9. 服务器约束（2C / 2G / 3M）

- 条码 PDF 流式生成，不落盘缓存全量；
- 照片重编码像素上限 2048、单张 ≤5MB、单次登记 ≤5 张明信片（10 张照片）；
- AI 调用带超时（默认 30s）+ 重试上限，绝不挂起 worker；
- 导出接口仅管理员 + 限流；
- 不在生产服务器跑测试 / 构建（CI 四路：backend / frontend / frontend-test / e2e）。
