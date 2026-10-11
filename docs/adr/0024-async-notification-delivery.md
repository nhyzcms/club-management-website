# 通知外发异步化：进程内队列 + 守护线程 + DB 兜底

日期：2026-10-11

外发投递（目前为 **email**）原在请求内同步完成：`dispatch` 创建 `NotificationDelivery` 行后经 `transaction.on_commit` 当场建 SMTP 会话发信。三个问题：**请求被 SMTP 拖慢**（`EMAIL_TIMEOUT=5` 仅是上限）；**失败只留痕、不重试**（163 偶发抖动即丢一封）；**每封邮件一个 SMTP 会话**。本 ADR 把外发投递升级为**默认异步**——进程内 `queue.Queue` + 守护线程 + `NotificationDelivery` 表兜底；**零新依赖、零新常驻进程**（延续 [ADR-0015](0015-channels-without-redis.md) 的节制；多 worker 前提下每进程一份，见 [ADR-0021](0021-postgresql-redis-and-multiworker.md)）。

## 决策

1. **每进程一份队列 + 一个 daemon 消费者线程**（`messaging/notifications/queue.py`）。gunicorn 每 worker 各自一份，天然并行；投递点只做「建 `pending` 行 + `enqueue(id)`」，微秒级返回。线程**懒启动**（首个入队才起），管理命令 / 测试不会意外拉起。
2. **DB 兜底 = `NotificationDelivery` 升级语义（零 DDL）**：入队即 `pending`；成功标 `sent`；失败按退避重排——**1m / 5m / 30m / 2h / 6h，至多 5 次重试**——超限落 `failed` 终态。消费线程周期性（默认 15 分钟）扫描「到期 `pending`」补投：覆盖**进程重启残漏、队列满降级、失败到期重试**。重启不丢。
3. **原子认领防重**：单语句 `UPDATE … WHERE status='pending' AND (next_retry_at IS NULL OR next_retry_at<=now) SET next_retry_at=now+5min`；多 worker 并发扫描不会重复投递；「发送中崩溃」由 5 分钟锁自动恢复。语义 **at-least-once**（极端窗口可能重复一封，但不再丢）。
4. **SMTP 连接复用**：消费者批量取任务（每批 ≤32），email 通道复用一条常开连接（空闲 5 分钟回收）。`BaseChannel.deliver(delivery, *, connection=None)` 签名放宽，其余通道忽略该参数。
5. **开关 `NOTIFICATIONS_DELIVERY_ASYNC`**：默认**开**；`=0` 回退旧同步行为（无需回退版本）。测试期默认同步（断言即时、无后台线程），异步用例以 `override_settings` 显式开启。
6. **运维入口 `manage.py flush_notifications [--limit N]`**：手动排空（排障 / 补投）。

## 被否的方案

- **Celery / RQ / huey + Redis**：生产 Redis 为「缓存式配置」（关持久化 + `allkeys-lru`），不适合当可靠队列；不为「几十封/天」的通道引入 broker 与常驻 worker。否。
- **纯内存队列（不做 DB 兜底）**：进程死 = 在途任务静默丢失；重试仅覆盖进程存活期。否。
- **全局单队列（跨 worker）**：需共享介质，等于回到 broker 或常驻轮询进程；单消费者在多 worker 下反成瓶颈。否。
- **站内通道也异步化**：站内是「落库 + WS 推送」快路径（无失败重试需求），不动。否。

## 兼容与迁移

- **零 DDL**：`pending / attempts / next_retry_at / last_error` 字段与索引在 messaging 0005 迁移已含，本次无新迁移。
- **缺省中性**：不设开关 = 异步；`=0` = 与旧版一致的同步投递（失败仅留痕）。
- **语义变化**：失败不再是「一次即终」，而是退避重试至多 5 次；最终失败可在管理后台按 `failed` 审计（`last_error` 留痕）。
- 相关文档：[配置参考](../configuration.md)。
