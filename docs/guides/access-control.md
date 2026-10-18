# 访问控制

> 相关：[账号 API](../api/accounts.md) · [身份认证](certification.md) · [ADR-0005](../adr/0005-access-control-principle.md)

## 一句话原则

**控制任何东西的访问时，直接定义一个权限，用 `has_perm` 判定——绝不检查组名或别的什么。** 权限由组分配，组决定身份，组由人手动管理；前端根据服务端算好的能力布尔做对应限制（禁用 / 隐藏按钮等）。

## 四个正交轴

| 轴 | 来源 | 用途 |
|---|---|---|
| **身份徽章** | 登录态 + `is_superuser` / `is_staff` / 已认证 | 展示（访客 / 用户 / 管理员 / 超级管理员） |
| **角色能力** | `user.has_perm(…)` | **全部访问控制**（API 门禁、按钮显隐、可见性、通知路由） |
| **组成员身份** | `user.groups` | 仅作「所属组: X」纯文本展示 |
| **对象所有权** | `creator == user`、`viewer == viewed` | 每行的组合规则 |

四轴各管一摊，互不替代。**能力（权限）是唯一的访问控制轴**。

## 权限词汇

- **Django 默认 CRUD**（每个模型自动生成，免费用）：`view_*` / `add_*` / `change_*` / `delete_*`。
- **命名工作流权限**（`Meta.permissions`，承载非纯记录变更的动作）：

| 权限代号 | 含义 |
|---|---|
| `news.manage_news` | 管理新闻 |
| `activities.manage_activity` | 可管理任意活动 |
| `activities.review_collection` | 可复审征集作品 |
| `tasks.manage_tasks` | 管理任务 |
| `tasks.assign_task` | 指派任务 |
| `tasks.manage_tags` | 管理任务标签 |
| `tutorials.manage_tutorials` | 可管理教程 |
| `about.manage_aboutpage` | 可编辑关于页 |
| `panorama.manage_panoramas` | 可管理校园全景图 |
| `exam_board.manage_exams` | 可管理考试看板 |
| `reviews.moderate` | 可审核内容（发布审核） |
| `reviews.force_publish` | 可免审发布 |
| `reviews.read_feedback` | 可查看并了结意见反馈 |
| `reviews.handle_report` | 可处理举报案 |
| `accounts.can_review_identity` | 可审核身份认证 |
| `accounts.manage_validity` | 可管理账号 / 认证有效期（对下位用户延 / 缩） |
| `messaging.manage_comment_thread` | 评论区协管 |
| `messaging.manage_announcement` | 管理横幅公告 |
| `messaging.mute_user` | 全站禁言 |

> 完整清单（含 Django 默认 CRUD）可在 Django Admin 的「组」页面查看。拆新权限的三条触发：**持有者现实中可能不同** / **前端要门禁独立 affordance** / **需独立审计**——任一满足才拆，否则并入最粗的已有权限（默认偏粗）。

## 门禁谱系：读与写

**读**是一档谱系，不是统一的「读权限」：

```
公开（匿名）→ 身份（已登录）→ 可见性过滤（本人 / 管理员）→ 敏感读（view_* / read_feedback）
```

- 常规内容读取（如新闻）匿名可读；任务等内容登录可读、并经 [accounts/visibility.py](../../accounts/visibility.py) 按所有权收窄；
- 仅**敏感读**使用专门权限（如 `reviews.read_feedback`）。

**写** = 权限与所有权组合。例如「能改这条任务」= `tasks.manage_tasks` **或** 你是创建者（`creator == user`）——所有权是另一轴，与权限组合，不算违反原则。

## 能力投影（前端契约）

- 后端把 `has_perm` 派生为**语义化 `can_*` 布尔**，随 `GET /auth/me/` 返回；`permissions` 字段**恒列全量键（true / false 都在）**，前端从不接触 `news.manage_news` 这类原始代号。
- 当前全量 17 键：

| 能力键 | 来源权限 |
|---|---|
| `can_manage_news` | `news.manage_news` |
| `can_manage_tasks` | `tasks.manage_tasks` |
| `can_assign_task` | `tasks.assign_task` |
| `can_manage_tags` | `tasks.manage_tags` |
| `can_change_activity` | `activities.manage_activity` |
| `can_review_collections` | `activities.review_collection` |
| `can_edit_about` | `about.manage_aboutpage` |
| `can_manage_panoramas` | `panorama.manage_panoramas` |
| `can_manage_exam` | `exam_board.manage_exams` |
| `can_view_feedback` | `reviews.read_feedback` |
| `can_handle_reports` | `reviews.handle_report` |
| `can_review_content` | `reviews.moderate` |
| `can_force_publish` | `reviews.force_publish` |
| `can_review_identity` | `accounts.can_review_identity` |
| `can_manage_comment_thread` | `messaging.manage_comment_thread` |
| `can_manage_announcement` | `messaging.manage_announcement` |
| `can_mute_user` | `messaging.mute_user` |

- 能力是**纯角色投影**（“凭你的角色能不能做 X”）；对象级判断（“能不能动**这条**”）由前端拿 `is_owner` / 对象字段另行组合（如编辑按钮显隐 = `can_manage_tasks || is_creator`）。
- 契约测试钉死「后端能力键集合 == 前端标签表键集合」，防止静默漂移。

## 身份徽章（展示层）

```
is_superuser                   → 超级管理员（最高，盖一切）
否则 is_staff                  → 管理员
否则 已登录且已认证              → 用户
否则（匿名 或 已登录未认证）      → 访客
```

徽章**与组、权限完全解耦**，不参与任何鉴权判定。「访客」= 匿名 ∪ 已登录未认证（未认证还不算正式用户，见 [身份认证](certification.md)）。

## 执行纪律

- **访问控制**（凭角色：*谁*能做 X）→ 命名 DRF `BasePermission` 子类，挂 `permission_classes` / `get_permissions()`；
- **状态机 / 业务规则**（凭状态：*何时*能做 X，如「pending 才能改」）→ **不是访问控制**；放视图体或各模块 `lifecycle.py`；
- 视图的 `permission_classes` 应能**独立**说明「谁能访问此 action」，不必看函数体；
- 组**名**绝不进任何分支条件（API 门禁、可见性、通知路由、按钮显隐都不认它）；
- `is_superuser` 是**唯一**应用访问逃生舱（`has_perm` 恒真，Django 内建）；`is_staff` 在应用访问里零权限——只表示可登录 Django Admin，外加触发「管理员」徽章；
- 绝不新增第二个绕过（如某个「应用管理员组」跳过权限检查）。

## 常见问题

- **「想让信息组拥有某功能」** → 给该组授予对应权限（或先建权限再授予），不要在任何代码里写 `groups.filter(name="信息组")`。
- **「某用户看不到入口 / 按钮」** → 依次查：权限是否已分配到用户的组 → `can_*` 投影是否为 true → 前端是否按 `is_owner` 组合；而不是去找组名逻辑。
- **「超级管理员为什么什么都能做」** → 超管的 `has_perm` 恒为 true，无需特判，也不应为此写任何分支。
