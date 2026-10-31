# 门户重构：统一审核轴 · 关于多区块 · 教程原文件直播 · SurveyJS

日期：2026-08-21 · 落地 #69 / T01–T11

> **补充（2026-10-30）：审核行的挂载方式已由 [ADR-0045](0045-content-target.md) 取代。**
> `Review` 不再有 `news` / `activity` / `tutorial` 三条可空 OneToOne 与 XOR 约束，
> 改为通过 `ContentTarget` 锚定；`publication_review` 这个 `related_name` 也已随列删除。
> 本文其余决策——统一审核是正交可见性轴、不改对象生命周期——仍然有效。

## 背景

门户原是单例 `AboutPage` + 新闻/活动直接公开；教程、考试写权限、加入流程缺失。#69 要把对外可见性收成一条横切审核轴，并把关于页、教程集锦、考试看板、加入问卷做成可独立交付的切面。

## 决策

1. **统一审核是正交可见性轴，不是对象生命周期。** `Review` 挂在新闻 / 活动 / 教程上（三条可空 OneToOne + XOR 约束，不用 GenericForeignKey）。状态 `pending → approved / rejected`，通过后可 `removed`。公开 queryset 只放行已通过；对象自身状态机（活动 scheduled/open、教程入库）不改。活动侧 related_name 为 `publication_review`，以免和征集作品「复审」撞名。
2. **两套命名工作流权限，不按类型拆。** `reviews.force_publish`（创建即公开）与 `reviews.moderate`（通过/驳回/下架）正交、可分别分配。社长组默认获 `moderate`；`force_publish` 不默认授予。前端能力键 `can_review_content` / `can_force_publish`。
3. **关于页：单例正文拆成 `AboutBlock`。** 固定 key（club / school / site / contact / campus-overview），同一权限 `about.change_aboutpage` 覆盖全部区块与首页概览静态行，不按块拆权限。校园全景图是 `panorama_url` 外链，按钮 `target=_blank`。
4. **文档保真：原件嵌入，不解析成富文本。** PDF 用浏览器 iframe；`.docx` 用前端 `docx-preview` 渲染；原件始终可下载。上传覆盖该区块附件。
5. **教程视频不转码。** 原文件 `<video>` 直播；解码失败则给下载件。交互只做收藏 + 去重播放量。
6. **加入问卷 = 嵌入式 SurveyJS，Schema/作答落本库。** 无第二套服务。公告确认（`notice_acknowledged`）是提交门槛。问卷编辑复用 `about.change_aboutpage`（同一批门户管理员）。
7. **考试看板写权限用 Django 白送的 `exam_board.add_exam`。** 读匿名开放。能力键 `can_manage_exam`。课表形状与公开误刊 socket 见 [ADR 0018](0018-exam-board-batch-and-public-ws.md)（本条原写 `add_examdata` / 扁平科目串，已 superseded）。

## 被否的方案

- **GenericForeignKey 挂审核目标**：能少几列，但破坏 XOR 约束与 admin 可发现性；三条 OneToOne 更贴「恰好一类」。
- **按新闻/活动/教程拆审核权限**：PRD 明确持有者同一批；ADR-0005 第三条触发都不满足。
- **把文档解析进 `content` HTML**：保真需求（分页/字体/图表）与现有富文本通道冲突。
- **视频转码 / 多清晰度**：本迭代明确不做。
- **问卷编辑另造权限**：与关于页同一批管理员，不满足拆权三条。

## 后果

- 公开读过滤条件成为「`review.status=approved`」（活动另允许尚无审核行的历史夹具，回填后新创建必有行）。
- 信息组获 `about.change_aboutpage` 与 `exam_board.add_exam`；审核仍走社长的 `reviews.moderate`。
- 后续若某类型审核持有者真的不同，再按 ADR-0005 拆权，而不是先预留。
