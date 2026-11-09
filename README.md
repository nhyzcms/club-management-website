# 南汇一中传媒社 · 社团管理系统

校内社团的**自托管运营平台**：入社与身份、活动与内容发布、审核、通知与私信、考试看板，一套 Django 单体 + React SPA 全包。

- 线上：<https://8.153.145.175/>
- 形态：Django 6（DRF + Channels）后端 + React 19 SPA 前端，前端产物由 Django 直接托管
- 客户端：桌面网页 · 独立手机版 `/#/m` · Android 系统 WebView 壳
- 许可：BSD 3-Clause

## 亮点

- **社员身份有「证」**：名册导入 → 自助认领 → 唯一识别码 → 工牌二维码 / 条形码，扫码即可校验；公开查询按查询者身份分档限次。
- **活动是星形收集，重大活动单开入口**：活动（`activities`）含众议投选票 / 征集收作品 / 展示布展点赞 / 调研收问卷；**重大活动**放独立入口，首个形态是**明信片互寄**（Code128 条码登记 + AI 审图 + 签收 + 全量审计；寄达校清单可上传活动海报由 AI 识别导入，登记时按区内编号排序与检索）。
- **账号安全按「丢了手机」的真实场景设计**：3 设备并发登录、陌生设备二次验证（TOTP / 邮箱码 / 安全问题 / 恢复码）、账号与安全中心、有效期与软删除注销。
- **审核是一条流水线，不是一个弹窗**：身份、密码重置、内容、意见反馈、举报、明信片复核统一进「审核台」，桌面与手机版各有工作台。
- **重大活动可以「先演练再上线」**：明信片管理端一键进入**模拟环境**（`?sim=1`，红底白字标注），管理端 6 个 tab + 用户端登记页 + 审核台 + 签收页全部走同一份内存沙箱，界面与正式版完全一致；在用户页 / 管理端 / 审核台 / 签收页之间来回切换都不会丢测试数据，点「退出模拟」（会二次确认）或离开这几个页面即清空——管理员可以完整走一遍「配活动 → 发条码 → 登记 → 复核 → 签收」，全程不碰正式数据。
- **三端一套代码、一套数据**：UA 自动改道到对应版式，深色模式覆盖（OLED 纯黑），App 壳有最低版本闸门。
- **2 核 2 GB 的小机器就能跑**：单 ASGI worker、PG / Redis 全部可选，一键安装脚本 + GitHub Release 自动更新与回滚。

## 功能一览

| 业务域 | 主要能力 |
|---|---|
| 账号与安全 | 多渠道认证、注册查重、多端登录、陌生设备验证、安全中心、记住登录、有效期、注销 |
| 社员身份 | 名册导入、自助认领、识别码、工牌导出、扫码校验、社员查询 |
| 活动 | 众议 / 征集 / 展示 / 调研、排期与期限、受众、秘密投票、展品与点赞、征集复审 |
| 重大活动 | 明信片互寄（条码增量/覆盖生成、AI 审图与样例解读、**DeepSeek / OpenCode-GO 预设 + 从服务商 /models 实时取模型清单**、**全局前置提示词**、海报导入寄达校、复核台、签收、多届、**模拟环境**演练；开新一届继承 AI 配置但不继承 API Key，Django 后台可按年度整批删除） |
| 问卷 | SurveyJS 设计、作答、检索、统计与导出（含 panel 与子题） |
| 内容 | 新闻、教程、关于页、校园全景图（瓦片化）、站点政策 |
| 协作 | 任务与标签、评论区（三态 / 撤回 / 墓碑）、私信、意见反馈 |
| 通知与运营 | 站内通知、横幅、全站禁言、全站弹窗公告（PDF / Word 原版渲染 + 已读台账） |
| 考试看板 | 批次课表、题目误刊 WebSocket 广播、大屏授时 |
| 后台与运维 | Django Admin、一键部署、Release 自动更新与回滚、维护模式、运行时策略旋钮 |

每项的规则细节、代码落点与入口见 **[功能总览](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/features.md)**。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.14 · Django 6 · Django REST Framework · Channels（ASGI） |
| 前端 | React 19 · TypeScript · Webpack 5，hash 路由 SPA（`/#/route`） |
| 数据 | SQLite（缺省，开发 / 裸机开箱可用）或 PostgreSQL（`DB_ENGINE=postgresql`）；Redis 可选，配 `REDIS_URL` 后兼任缓存与 Channels 频道层 |
| 依赖管理 | uv（Python） · npm（前端） |
| 生产运行 | Nginx + Gunicorn `UvicornWorker`；worker 数由 `GUNICORN_WORKERS` 控制（默认 1，未配 Redis 时不得 >1） |

## 快速开始

```bash
# 后端 → http://localhost:8000
uv sync
uv run python manage.py migrate
uv run python manage.py runserver

# 前端开发服务器 → http://localhost:3000（HMR）
cd frontend && npm ci && npm run dev
```

生产构建：`cd frontend && npm run build` → 产物在 `frontend/dist/`，由 Django 直接托管，不需要单独部署前端服务。
完整环境要求、测试与 CI、目录结构见 [快速开始文档](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/getting-started.md)。

## 文档

代码在 `main`（每次推送都会触发一次 release），**文档在 [`documentation` 分支](https://github.com/nhyzcms/club-management-website/tree/documentation/docs)**，不占用发布通道。

| 我想…… | 读这里 |
|---|---|
| 知道每个功能到底怎么用 | [功能总览](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/features.md) |
| 把项目跑起来 | [快速开始](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/getting-started.md) · [配置参考](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/configuration.md) |
| 了解架构与前端结构 | [架构总览](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/architecture/overview.md) · [前端架构](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/architecture/frontend.md) |
| 调接口 | [API 总览](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/api/README.md) |
| 部署 / 备份 / 排障 | [部署与运维](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/operations/deployment.md) · [统一数据根](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/operations/data-root.md) |
| 在后台发布与审核 | [管理后台指南](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/operations/admin-guide.md) · [审核系统](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/guides/moderation.md) |
| 弄清权限模型 | [访问控制](https://github.com/nhyzcms/club-management-website/blob/documentation/docs/guides/access-control.md) |
| 看当初为什么这么设计 | [ADR](https://github.com/nhyzcms/club-management-website/tree/documentation/docs/adr) · [领域术语](CONTEXT.md) |
| 参与开发 / 让 AI 接手 | [CLAUDE.md](CLAUDE.md)（分支 + PR、CI 四作业、生产机不跑测试） |

对外入口另有 [GitHub Wiki](https://github.com/nhyzcms/club-management-website/wiki)。

## 开发约定

- **改动一律走分支 + PR**（`feature/…` / `fix/…` / `docs/…`），不直推 `main`。
- **测试与构建一律交 CI**（`backend` / `frontend` / `frontend-test` / `e2e`）：生产机只有 2 核 2 GB / 3 MB 带宽，跑测试会拖垮线上。
- **升级不要在服务器上 `git pull`**：走 GitHub Release + 更新守护进程（或 `scripts/updater.py --apply-now <sha>`），失败自动回滚。
- 更多协作细节见 [CLAUDE.md](CLAUDE.md)。

## 许可证

代码采用 **BSD 3-Clause License**，全文见 [LICENSE](LICENSE)：可自由使用、修改、再分发（含商用），但须保留版权声明与免责声明，且不得用本社团或贡献者名义为衍生品背书。软件按「现状」提供，不附带担保。

第三方素材各自保留原许可：Live2D 运行时与模型（`frontend/vendor/live2d/`）、Noto Sans SC 字体（`activities/fonts/OFL.txt`，SIL OFL 1.1）。站内内容（新闻、作品、照片、全景图、社徽等）著作权归原作者或社团，不在代码许可范围内。

---

维护：**Echo**
