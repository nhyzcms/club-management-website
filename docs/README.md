# 项目文档

南汇一中传媒社社团管理系统的文档中心。

本仓库的 `main` 分支只放代码（每次推送都会触发一次 release），**文档统一在本分支（`documentation`）维护**。文档与代码同步演进——以代码为准，发现出入请提 Issue。

## 按目的找入口

| 我想…… | 从这里开始 |
|---|---|
| 先知道这系统能干什么、有什么亮点 | [功能总览](features.md) |
| 把项目跑起来、跑测试 | [快速开始](getting-started.md) |
| 改代码前了解系统结构 | [架构总览](architecture/overview.md) → [前端架构](architecture/frontend.md) |
| 调接口、对接前端 | [API 总览](api/README.md)（全局约定）+ 下方模块分册 |
| 配环境变量 / 部署参数 | [配置参考](configuration.md) |
| 安装、升级、备份、排障 | [部署与运维](operations/deployment.md) |
| 在后台发布内容、处理审核 | [管理后台指南](operations/admin-guide.md) |
| 弄懂谁能看到什么、谁能改什么 | [访问控制](guides/access-control.md) → [身份认证](guides/certification.md) |
| 弄懂登录安全（设备 / 二次验证） | [账号与安全](guides/account-security.md) · [安全验证](guides/security-verification.md) |
| 弄懂审核队列怎么走 | [审核系统](guides/moderation.md) |
| 设计或修改问卷 | [问卷系统](guides/surveys.md) |
| 知道当初为什么这么设计 | [ADR](adr/) |
| 接手大功能的权威方案 | [实施方案](plans/)（进度看板 + 交接） |
| 让 AI 助手接手改代码 | [CLAUDE.md](https://github.com/nhyzcms/club-management-website/blob/main/CLAUDE.md) · [协作约定](agents/) |

> 术语以 [CONTEXT.md](https://github.com/nhyzcms/club-management-website/blob/main/CONTEXT.md) 为准（任务、互动、活动、众议、征集、展示、调研、作品……）。新概念先查这里，别自己造词。

## 全部文档

### 入门与功能

- [功能总览](features.md) —— 按业务域列全部能力与规则落点
- [快速开始](getting-started.md) —— 技术栈、环境搭建、测试与 CI、目录结构、常见改动
- [配置参考](configuration.md) —— 环境变量与设置项

### 架构

- [架构总览](architecture/overview.md) —— 系统结构、请求生命周期、模块地图
- [前端架构](architecture/frontend.md) —— React 应用结构、路由、开发惯例

### API 参考

[API 总览](api/README.md) 约定认证 / CSRF / 分页 / 错误；模块分册：

| 模块 | 文档 | 模块 | 文档 |
|---|---|---|---|
| 账号与认证 | [accounts](api/accounts.md) | 消息与评论 | [messaging](api/messaging.md) |
| 新闻 | [news](api/news.md) | 审核系统 | [reviews](api/reviews.md) |
| 互动 | [activities](api/activities.md) | 招聘与加入 | [recruitment](api/recruitment.md) |
| 活动（限时） | [events](api/events.md) | 考试看板 | [exam-board](api/exam-board.md) |
| 任务 | [tasks](api/tasks.md) | 关于页 | [about](api/about.md) |
| 教程 | [tutorials](api/tutorials.md) | 公共（站点策略） | [common](api/common.md) |
| 附件与上传 | [attachments](api/attachments.md) | 全站弹窗公告 | [announcements](api/announcements.md) |
| 校园全景图 | [panorama](api/panorama.md) | | |

### 指南

- [访问控制](guides/access-control.md) —— 身份、权限与可见性模型
- [身份认证](guides/certification.md) —— 认证通道与流程
- [安全验证](guides/security-verification.md) —— 敏感操作的本人确认（Step-up）
- [账号与安全](guides/account-security.md) —— 登录方式、设备与陌生设备验证、滚动密钥、登录记录
- [审核系统](guides/moderation.md) —— 六张桌与处理流程
- [问卷系统](guides/surveys.md) —— SurveyJS 问卷与作答规则

### 运维

- [部署与运维](operations/deployment.md) —— 安装、更新、备份、回滚、排障
- [统一数据根](operations/data-root.md) —— 数据目录结构、开目录规则与换根剧本
- [管理后台指南](operations/admin-guide.md) —— Django Admin 使用

### 设计记录与方案

- [ADR（架构决策记录）](adr/) —— 0001–0029、0041–0046，重要决策的来龙去脉
- [实施方案（plans）](plans/) —— 大功能的权威方案与交接文档（含进度看板）；当前：[明信片互寄](plans/postcard-exchange.md)
- [AI 协作约定](agents/) —— issue 流程、triage 标签、领域文档约定
- 领域术语：[CONTEXT.md](https://github.com/nhyzcms/club-management-website/blob/main/CONTEXT.md)
- GitHub Wiki（对外入口）：<https://github.com/nhyzcms/club-management-website/wiki>

---

维护：**Echo**
