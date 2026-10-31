# 内容锚点：用 `ContentTarget` 统一「这条内容是谁」

日期：2026-10-30
状态：已实施（PR #214/#215 建立，PR #261 完成收尾）
相关：ADR-0014（审核流）、ADR-0044（账号拆表）

## 背景

系统里有四张表需要「挂」到任意一种内容上：

| 表 | 能挂在哪 |
|---|---|
| `Attachment` | 任务 / 意见反馈 / 新闻 / 作品 / 展品 |
| `Review` | 新闻 / 活动 / 教程 |
| `ReportCase` | 新闻 / 活动 / 教程 / 评论 **+ 用户** |
| `CommentThread` | 新闻 / 活动 / 任务 |

每张表都用「N 个可空外键 + 一条 CheckConstraint 保证恰好一个非空」实现。
这个模式在四个地方各写一遍，代价是：

1. **加一种宿主要改四张表**，四个迁移，四处约束，四处读取路径。
2. **每个宿主的反向访问器名不同**（`news.review` vs `activity.publication_review`），
   于是出现了 `reviews/visibility.py` 里那张 `_RELATED_NAME` 映射表。
3. **查询要按类型分支**。`public_q("activity")` 和 `public_q("news")` 是两套逻辑，
   因为它们的历史行为不同（见下）。
4. **约束表达力有限**。`ReportCase` 的「同一内容只能有一个未结案」要写四条
   `UniqueConstraint`（每张内容表一条），而 `CommentThread` 的「每个宿主恰好一条」
   靠 `OneToOne` 隐式保证，两者其实想说的是同一件事。

## 决定

建一张登记表 `common.ContentTarget`：

```python
class ContentTarget(models.Model):
    kind = CharField(...)        # news / activity / tutorial / task / comment / submission / exhibit / feedback
    object_id = BigIntegerField(...)
    # unique_together = (kind, object_id)
```

四张多态表改成 `target = ForeignKey(ContentTarget)`。

**`object_id` 不加外键。** 它指向 8 张不同的表，SQL 没有「指向多张表的外键」这种东西；
用 `GenericForeignKey` 会带来另一套问题（无法 JOIN、无法约束、`prefetch_related` 失效）。
这里选了最笨但最可控的方案：普通整数列 + 应用层保证一致性，孤儿由 `prune_orphan_targets` 兜底。

`target` 的语义是「这条内容行属于哪条内容」，`ContentTarget` 本身只是一个
`(kind, object_id)` 的唯一索引，没有业务字段。

## `ReportCase.reported_user` 为什么不进 target

最初的计划把 `reported_user` 也列进删除项，这是计划的错误。

**「人」不是「内容」。** 理由有三条：

1. `ContentTarget` 登记的是 8 张内容表。把 `User` 塞进去，`kind` 就从「内容类型」
   变成「内容类型 + 用户」，所有 `kind` 的消费方都要多一个分支。
2. 举报用户和举报内容可以**同时存在**——一个人发了违规内容，你既举报这条内容也举报这个人。
   如果两者都挤进 `target`，一行 `ReportCase` 只能表达一个。
3. 用户注销后举报案要留档。内容被删时 `ContentTarget` 会 CASCADE，但
   「这个用户被举报过三次」是历史记录，不该随账号消失。

所以 `ReportCase` 保留 `reported_user` 列，`target` 为空表示「举报的是人」。

## 迁移怎么做的

分两批，中间隔了 9 个 PR：

**B1（#214/#215）**：建表 + 回填 + 双写 + 切读。

- 回填 35 行（生产数据里这四张表加起来只有 35 行）
- 切读用 `Q(target=...) | Q(旧列=...)` 双路——**绝不 target-only**。
  存量行里可能有 target 为空的（回填漏的、绕过 `save()` 的裸 SQL 写入的），
  只走 target 会让它们「凭空消失」，症状是「评论没了、审核队列少了条目」，
  且只在特定入口复现。
- 写路径加 `TargetBackfillMixin`：`save()` 时如果 target 为空但有旧列，自动补上。
  放 `save()` 而不是四个调用点，因为写路径太多（视图、序列化器、admin、shell、
  管理命令、测试夹具），漏一个就留下 target 为空的行。

**B9（#261）**：删旧列。

删列之后宿主侧没有指向 target 的外键，`News.objects.filter(review__status=...)`
不再成立。但方向反过来是通的——`ContentTarget` 上有 `review` 反向，所以
`public_q` 改成子查询：

```python
def public_q(kind):
    if kind == "news":
        return Q(pk__in=_approved_object_ids("news"))
    if kind == "activity":
        return Q(pk__in=_approved_object_ids("activity")) | ~Q(
            pk__in=_with_review_object_ids("activity")
        )
```

`activity` 那条多一个 `~Q(pk__in=有审核行的)`，对应旧实现的 `isnull=True`——
**没有审核行的活动是公开的**（存量 ORM 与测试夹具的例外），而新闻/教程是
INNER JOIN 语义（没有审核行不公开）。这个不对称是历史行为，不是设计，但改它
会让线上内容突然消失，所以原样保留并写进注释。

## 后果

- 加一种宿主：`KIND_TO_MODEL` 加一行 + 建表迁移，四张多态表一行不用改。
- `public_q` 从「每个 kind 一套反向访问器」变成「每个 kind 一条子查询」，
  语义集中在一个文件里。
- 删列之后 `obj.attachments` / `news.review` 这些反向访问器不存在了，
  调用方改用 `attachments_of(obj)` / `Review.objects.filter(target=...)`。
- 代价：多态表的读取从「一次 JOIN」变成「一次 JOIN + 一次 target 查找」；
  批量场景需要按 kind 分组预取，不能逐行调 `content_host()`。
  生产这四张表加起来 35 行，代价可忽略。

## 留下的东西

- `common/targets.py`：`target_for` / `target_of` / `kind_of` / `host_ref` / `content_host` / `related_to`
- `common/management/commands/prune_orphan_targets.py`：清孤儿 target（宿主删了但 target 没删的）
- 删除宿主时的级联：`_on_host_deleted` 挂 `post_delete`，删宿主 → 删 target → CASCADE 带走附件/审核/举报/评论区
