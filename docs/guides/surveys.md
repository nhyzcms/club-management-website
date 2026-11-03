# 问卷系统指南

本指南讲**问卷**这一子系统怎么运转：它由哪些实体组成、调研互动与它是什么关系、作答规则是什么、编辑与统计从哪里进。接口字段级细节见 [互动 API](../api/activities.md) 与 [招生与加入 API](../api/recruitment.md)；本页只讲概念、流程与操作建议。

相关设计记录：[ADR-0011：调研作为第四种活动类型](../adr/0011-survey-activity-type.md)、[ADR-0014：问卷与问卷结果从活动表拆出](../adr/0014-questionnaire-independent.md)、[ADR-0009：门户重构（加入问卷 = 嵌入式 SurveyJS）](../adr/0009-portal-review-about-tutorials.md)、[ADR-0005：访问控制原则](../adr/0005-access-control-principle.md)。

## 一、问卷是什么

**问卷 (Questionnaire)** 是一份独立的 SurveyJS Schema 实体，住在 `activities` app（`activities/models.py`），**不挂在互动表上**。它只有三个字段：`kind`（用途）、`schema`（SurveyJS JSON）、时间戳。

`kind` 有两个取值，对应两件不同的事：

| `kind` | 中文 | 数量 | 谁指向它 |
|---|---|---|---|
| `survey` | 调研 | 每场调研一份 | 调研互动 `OneToOne` 指向 |
| `join` | 自我介绍 | **全站单例** | 加入流程（`Questionnaire.get_join()`） |

- **`kind=survey`**：一场调研互动创建时自动生成一份，互动与问卷为 `SET_NULL` 关联——**删除互动不会删除问卷，也不会删除任何作答**（问卷变无互动引用的孤儿行，可在后台问卷列表按「调研互动」为空识别、人工处置；历史作答按提交时的 schema 快照解释）。
- **`kind=join`**：自我介绍问卷，全站唯一，由数据库部分唯一约束 `unique_join_questionnaire` 兜底；后台**不允许删除**（`QuestionnaireAdmin.has_delete_permission` 对 join 恒假）。

Schema 形状与校验：必须是含 `pages` 的 JSON 对象（`common/survey_schema.py:validate_schema_dict`），否则写入被拒（`Schema 须包含 pages`）。更深一层（审计 S-4）：**禁止 `type: "html"` 题**（无正当用途、是直接 HTML 注入面）；`html` 题的 `html` 属性与根 / 页级的 `completedHtml` / `completedBeforeHtml` / `loadingHtml` / `emptySurveyText` 会过 `sanitize_html`；递归深度 > 16 或节点数 > 4000 直接拒绝（`问卷结构嵌套过深 / 过大`）。默认调研 Schema 是一页空问卷；默认加入 Schema 含 `grade` / `skills` / `source` / `other_source` / `intro` 五个元素与一条跳题 trigger。

> 术语提醒：**问卷**是 Schema 实体，**调研**是互动类型，**问卷结果**是一次作答。三者不要混用；「复审」是征集作品的录用/退稿，与问卷无关。

## 二、调研互动与问卷的关系

**调研 (Survey)** 是互动的第四种类型（`Activity.type="survey"`），与**众议 / 征集 / 展示**并列。它管的是**窗口**：排期、受众、审核、列表可见性；**表单与结果**则完全交给问卷。

```
Activity(type=survey)  ──OneToOne──▶  Questionnaire(kind=survey)
   │ 窗口语义                              │ 表单 + 结果
   ├─ status: scheduled → open → closed    ├─ schema（SurveyJS JSON）
   ├─ audience: public / members           └─ responses（QuestionnaireResponse）
   ├─ start_at / end_at
   └─ Review（经 ContentTarget 锚定，见 ADR-0045）
```

拆分的理由（ADR-0014）：窗口（排期 / 受众 / 审核 / 列表）是互动该管的；拆的是表单与结果，不是窗口。因此：

- 互动侧提供**投影**：`Activity.schema` 属性读关联问卷的 Schema（无问卷时给默认空表），写回也落到问卷上。
- 门户**只填、不看结果**：详情只给 `schema` / `my_response` / `response_count`，不给作答列表（ADR-0011 决策 6）。
- 加入流程**不**并入互动表：它是招生单例，不是可排期、可审核公开的调研窗口。

### 状态机与受众

调研的状态机与众议相同（判定真源 `activities/state.py::calc_state`，惰性流转、无定时任务）：

- `scheduled`（待开始）→ 到 `start_at` 自动 `open`（征答中）→ 到 `end_at` 自动 `closed`（已结束）。
- 不填 `start_at` 则创建即 `open`；发起人或持 `activities.manage_activity` 者可**提前结束征答**（`POST /activities/activities/{id}/close/`，仅 `open` 可关）。

**受众 (`audience`)** 是调研专属字段，**创建后不可改**（与展示的 `voting_enabled` 同思路）：

- `public`（公开）：访客可列表、可打开、可作答；未登录的列表查询范围也被收窄为「`type=survey` 且 `audience=public` 且审核轴公开」。
- `members`（仅成员，默认）：须登录才能作答；门户仍仅成员可见。

其他互动类型 `audience` 恒为 `members`，字段无实际作用。

### 审核轴怎么作用在调研上

调研照常受统一审核轴门控（见 [审核系统指南](moderation.md)）：互动创建时自动开一条 `Review`，通过 `ContentTarget`（`kind="activity"`）锚定互动，只有**公开展示**受它门控，**不阻断状态机**——到点照常 `open` / `closed`，只是审核通过前访客/成员看不到、也作答不了。

- 作答入口额外判一次：审核状态非 `approved`（且非「无审核行」）时返回 400「调研尚未公开」。
- 发起人自己能看到待审/驳回/下架的互动（`GET /activities/activities/mine/`），并看到审核评语。

## 三、SurveyJS 集成：四块

前端与后台都用开源 **SurveyJS**（`survey-core` / `survey-react-ui` / `survey-creator-*` / `survey-analytics`，见 `frontend/package.json`），locale 统一 `zh-cn`（`frontend/src/utils/surveyLocale.ts`）。共四块能力：

| 块 | 位置 | 用途 |
|---|---|---|
| **编辑器** | 门户 `SurveyCreatorPage.tsx`（详情页「编辑问卷」）与 `components/SurveyDesignerModal.tsx`（互动发起 / 编辑表单里的弹层）；后台 `common/surveyjs_admin.py` + `editor.html` | 拖拽编辑 Schema（含逻辑页签） |
| **渲染（作答）** | `components/SurveyFill.tsx` | 门户填问卷（调研详情 + 加入页共用） |
| **结果（单份）** | `SurveyResponsesPage.tsx`；后台 `response.html` + `response.js` | display 模式只读阅读一份作答 |
| **统计（聚合）** | `SurveyStatsPage.tsx`；后台 `results.html` + `results.js` | 图表看板（survey-analytics Dashboard） |

要点：

- **设计入口**：`/#/activity/new`（发起互动）与 `/#/activity/{id}/edit`（待开始）表单里就有「设计问卷 / 编辑问卷」——SurveyJS Creator 以**弹层**加载（`components/SurveyDesignerModal.tsx`，portal 到 `body`，避免 Creator 的输入控件误触发表单提交；编辑器的 chunk 按需下载）。点「完成」只回填到表单状态，创建时随 `POST /activities/activities/` 的 `schema` 一起落库，编辑时随「保存修改」提交。创建后仍可从详情页「编辑问卷」（`SurveyEditorPage`，待开始或开放且零作答时可用）。
- **作答模型**由 `frontend/src/utils/survey.ts:createSurveyModel` 统一构造：`widthMode="responsive"` + `onComplete` 回调；`SurveyFill` 把提交错误就地显示在问卷上方。
- **只读阅读**统一用 display 模式：`mode="display"`、`questionsOnPageMode="singlePage"`、`showCompletedPage=false`、`widthMode="responsive"`（门户与后台同款）。
- **统计看板**用 `survey-analytics` 的 `Dashboard`，`allowHideQuestions: true`（可隐藏不关心的题）；无作答时不渲染图表，只给空态文案。
- **后台静态资源**是 SurveyJS 的 vanilla min 文件，由 `frontend/scripts/copy-surveyjs.js` 复制到 `static/surveyjs/`（本地 runserver）与 `frontend/dist/surveyjs/`（生产 collectstatic）。**忘了跑 `npm run copy-surveyjs` 时，后台编辑器/看板会提示「SurveyJS 静态资源未复制」**——这是最常见的后台问卷故障。
- 后台与门户共用同一份 Schema JSON 字段，不存在第二套服务（ADR-0009 决策 6）。

## 四、作答规则

**调研问卷上，一个身份只能提交一次**（加入 / 自我介绍问卷例外：同一人最多 5 次，且不写判重键）。身份分两种：

| 身份 | 判重键 `dedupe_key` | 约束 |
|---|---|---|
| 已登录用户 | `q<问卷id>:u<用户id>` | 列级 `unique=True`（nullable：历史行 / 加入问卷留 `NULL`） |
| 访客 | `q<问卷id>:d<设备id>` | 同上；`user` 为空且 `device_id` 非空时写入 |

- **设备标识 (Device ID)**：门户在 localStorage 生成 UUID（`frontend/src/utils/deviceId.ts`），每个请求带 `X-Device-Id` 头；后端按标准 UUID 正则校验（`activities/device.py`），**缺失或格式非法一律视为未提供**，访客作答会被 400「缺少设备标识」拒绝。
- 已登录用户作答时 `device_id` 落空串，不参与设备去重。
- 重复提交：视图先查一次，落库时再由 `dedupe_key` 唯一约束兜底（`IntegrityError` → 400「你已经提交过了」）。判重键只由调研 `respond` 写入；**加入（自我介绍）问卷允许同一人最多 5 次、不写该键**（多个 `NULL` 不冲突）。
- **设备标识不是硬件 ID**：清 localStorage 或换浏览器仍可再交——这是 Web 侧去重能做到的上限（ADR-0014 决策 3），不要把它当防刷的强保证。

作答入口的完整前置条件（`SurveyPanel.tsx` 的 `canFillSurvey`）：

1. 互动 `status === "open"`（未开始 / 已结束都不行）；
2. 审核轴 `approved` 或无审核行；
3. 当前身份尚未提交过；
4. `audience === "public"` 或已登录。

`answers` 的键名与 SurveyJS 元素 `name` 一一对应，落库前必须过 `common/survey_answers.validate_answers()`（审计 M-2）：`answers` 须为 JSON 对象且 ≤ 64KB；题目名必须在 Schema 中存在（未知题名 400）；必填题不得为空；`checkbox` / `tagbox` 必须是数组、选项须属于该题；`radiogroup` / `dropdown` 须是单值且选项合法；`boolean` 必须是布尔；文本单值 ≤ 20000 字；矩阵题须为对象 / 数组；文件题项须是字符串或对象。**不解释表达式**：`visibleIf` 隐藏的必填题允许为空（前端按同一 Schema 跳过），空 Schema 的历史问卷直接放行。需要更强的业务约束时，仍应在 Schema 之外另设校验或人工核查。

**历史作答按提交时的 Schema 解释**：新建作答时自动快照当时的问卷 Schema（`QuestionnaireResponse.schema_snapshot`），之后改题 / 删题不会让旧作答错位——统计、只读查看与导出都按提交时的题目结构读取（快照为空的历史行回退当前 Schema）。

## 五、结果与统计入口

### 门户（发起人 / 管理）

调研详情页的「问卷」面板（`SurveyPanel.tsx`）对 `canManage`（发起人 或 `activities.manage_activity`）显示两个按钮：

| 入口 | 路由 | 内容 |
|---|---|---|
| 查看结果 | `/activity/{id}/survey-responses` | 逐份作答列表（可按作答内容检索），展开即 display 模式阅读 |
| 查看统计 | `/activity/{id}/survey-stats` | survey-analytics 图表看板 + 份数 |

两者都走 `GET /activities/activities/{id}/responses/`，返回 `{schema, is_manager, total, query, results[]}`：

- `is_manager`（发起人 或 `activities.manage_activity`）→ 看**全部**作答；
- 其他登录用户 → 只看**自己**的那一份（页面文案相应变成「你可见自己的作答」）。

**结果页支持按作答内容检索**（`?q=`）：输入框在份数说明下方，停止输入 300 ms 后生效（防抖），命中项会标出「哪道题命中了」的片段，份数变成「匹配 N / 共 M 份」。

- 匹配范围是**用户填写的值**，不含作答者用户名 / 提交时间；
- 选择题按**选项展示文本**匹配（SurveyJS 的 `value` 与 `text` 可以不同，库里存 `item1`、界面写「新闻」，用户搜「新闻」必须命中）；
- 文件题匹配文件名与链接，多选逐项匹配，评分 / 数字按字符串匹配；
- 归一化：NFKC（全角「ＮＥＷＳ」= `news`）+ 折叠空白 + 大小写不敏感；
- 过滤在服务端 Python 侧做（`activities/survey_search.py`）：`answers` 是 JSONField，Django 写 SQLite 时中文会被 `ensure_ascii` 成 `\uXXXX`，直接 `icontains` 搜不到中文；该端点本来就要下发整份作答，逐行扫描不额外增加查询。数据量到万份级再考虑落检索列。

门户**没有**「谁答了什么」的公开列表，也不给未登录者看结果。

### 后台（Django admin）

问卷后台是编辑与统计的**权威入口**（ADR-0014 决策 2：编辑问卷与查看统计只挂问卷后台）：

- `Questionnaire` 后台（`QuestionnaireAdmin`）：
  - 列表显示 `kind` / Schema 标题 / 关联调研互动 / 更新时间，可按 `kind` 过滤；
  - change form 右上角 object-tools 给「编辑问卷」「统计」两个链接（由 `SurveyJSAdminMixin.change_view` 注入）；
  - 编辑问卷页 `…/survey-editor/`：SurveyJS Creator，保存走 `POST` 同一 URL（JSON `{schema}`），成功返回 `{"ok": true}`；
  - 统计页 `…/survey-results/`：图表看板 + 作答列表（作答者 / 提交时间 / 「查看作答」链接）。
- `QuestionnaireResponse` 后台（`SurveyJSResponseViewMixin`）：
  - 列表可按 `questionnaire__kind` 过滤、按用户名或设备标识搜索；
  - 「查看作答」进 `…/survey-view/`：display 模式只读阅读，作答者标签为用户名或「访客 · 前 8 位设备标识」；
  - 「统计」链回该问卷的统计页。
- `Activity` 后台的「问卷」列直接链到对应问卷 change form，方便从互动跳到问卷。

## 六、后台编辑入口与锁定规则

**Schema 可改窗口**（`activities/lifecycle.py:can_edit_schema`，单一事实源）：

| 情形 | 能否改 Schema |
|---|---|
| 待开始（`scheduled`） | ✅ |
| 开放中（`open`）且该问卷**尚无任何作答** | ✅ |
| 开放中但已有作答 | ❌ 锁定 |
| 已结束（`closed`） | ❌ 锁定 |
| `kind=join` 单例 | ✅ 始终可改 |

注意与「互动可编辑窗口」的区别：**标题 / 正文 / 时间**只在待开始可改（`can_edit`）；**Schema** 多一条「开放且零作答」的宽限。受众 `audience` 创建后任何阶段都不可改。

锁定是**生命周期判断，不是权限**（ADR-0005 执行纪律）：`schema_editable` 由后端算好下发，前端据此显隐「编辑问卷」按钮；后台 `QuestionnaireAdmin.survey_can_save_schema` 复用同一谓词，锁定时保存被拒并提示「已有作答或已截止，问卷 Schema 已锁定。」。

### 门户编辑（调研）

- 入口：互动详情页右上角「编辑问卷」按钮 → `/activity/{id}/survey-edit`（`SurveyEditorPage.tsx`）。
- 显示条件：`canManage && a.schema_editable`（发起人 或 `activities.manage_activity`，且未锁定）。
- 保存走 `PATCH /activities/activities/{id}/`（body `{schema}`），后端 `perform_update` 对 `schema` 单独走 `can_edit_schema`，不满足返回 403「当前不可修改问卷」。
- 锁定后页面顶部给红条「问卷已锁定，无法保存。」，Creator 仍可查看但不能落库。

### 门户编辑（自我介绍问卷）

- 入口：`/join/editor`（`JoinEditorPage.tsx`），权限复用门户管理员 `about.manage_aboutpage`（`can_edit_about`）——与关于页同一批人，不另造权限（ADR-0009 决策 6）。
- 读写走 `GET` / `PUT|PATCH /recruitment/schema/`；作答入口是 `/join/form`（须先在落地页勾选公告确认）。
- 加入问卷**不受**互动锁定规则约束，随时可改。

### 操作建议

- **先定稿再开放**：Schema 一旦有第一份作答就锁死。开放前把题目、选项、跳题逻辑在 Creator 里过一遍，用「查看问卷」只读预览确认渲染效果。
- **别用后台直接改 Schema JSON**：`Questionnaire` change form 的 `schema` 字段可编辑，但容易写坏结构；统一走 Creator 编辑器（门户或后台）更安全。
- **改完立刻验证**：以访客身份（无痕窗口）打开一次调研，确认跳题与必填符合预期；`audience=public` 时这一步尤其重要。
- **结果看板不是导出工具**：统计页只做图表与逐份阅读；要 CSV / PDF 走后台「互动 → 问卷」列表的导出动作（见[后台管理指南](../operations/admin-guide.md) §5.2）。
- **加入问卷与调研问卷分开维护**：两者共用模型但用途不同，改一个不会影响另一个。

## 七、相关文档

- [互动 API](../api/activities.md) — `respond` / `responses` 端点、`schema` / `my_response` / `response_count` / `schema_editable` 字段
- [招生与加入 API](../api/recruitment.md) — 自我介绍问卷 Schema 端点与报名作答
- [审核系统指南](moderation.md) — 调研互动的发布审核
- [审核系统 API](../api/reviews.md) — 审核队列与通过 / 驳回 / 下架
- [ADR-0011](../adr/0011-survey-activity-type.md) / [ADR-0014](../adr/0014-questionnaire-independent.md) / [ADR-0009](../adr/0009-portal-review-about-tutorials.md)
