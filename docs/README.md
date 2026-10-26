# 项目文档

南汇一中传媒社社团管理系统的文档中心。文档与代码同步演进——以代码为准，发现出入请提 Issue。

## 入门

- [快速开始](getting-started.md) —— 技术栈、环境搭建、常用命令
- [配置参考](configuration.md) —— 环境变量与设置项

## 架构

- [架构总览](architecture/overview.md) —— 系统结构、请求生命周期、模块地图
- [前端架构](architecture/frontend.md) —— React 应用结构、路由、开发惯例

## API 参考

[API 总览](api/README.md) —— 认证 / CSRF / 分页 / 错误等全局约定；模块分册：

| 模块 | 文档 | 模块 | 文档 |
|---|---|---|---|
| 账号与认证 | [accounts](api/accounts.md) | 消息与评论 | [messaging](api/messaging.md) |
| 新闻 | [news](api/news.md) | 审核系统 | [reviews](api/reviews.md) |
| 活动 | [activities](api/activities.md) | 招聘与加入 | [recruitment](api/recruitment.md) |
| 任务 | [tasks](api/tasks.md) | 考试看板 | [exam-board](api/exam-board.md) |
| 教程 | [tutorials](api/tutorials.md) | 关于页 | [about](api/about.md) |
| 附件与上传 | [attachments](api/attachments.md) | 公共 | [common](api/common.md) |
| 校园全景图 | [panorama](api/panorama.md) | 全站弹窗公告 | [announcements](api/announcements.md) |

## 指南

- [访问控制](guides/access-control.md) —— 身份、权限与可见性模型
- [身份认证](guides/certification.md) —— 认证通道与流程
- [安全验证](guides/security-verification.md) —— 敏感操作的本人确认（Step-up）
- [账号与安全](guides/account-security.md) —— 登录方式、设备与陌生设备验证、滚动密钥、登录记录
- [审核系统](guides/moderation.md) —— 五张桌与处理流程
- [问卷系统](guides/surveys.md) —— SurveyJS 问卷与作答规则

## 运维

- [部署与运维](operations/deployment.md) —— 安装、更新、备份、排障
- [统一数据根](operations/data-root.md) —— 数据目录结构、开目录规则与换根剧本
- [管理后台指南](operations/admin-guide.md) —— Django Admin 使用

## 设计记录

- [ADR（架构决策记录）](adr/) —— 0001–0029、0041–0043（补档），重要决策的来龙去脉
- 领域术语与项目概览：[CONTEXT.md](../CONTEXT.md)
- AI 协作流程约定：[docs/agents/](agents/)
- GitHub Wiki（对外入口）：<https://github.com/nhyzcms/club-management-website/wiki>

---

维护：**Echo**
