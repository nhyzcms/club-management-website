# Channels 无 Redis：单 ASGI worker，WebSocket 只推送

日期：2026-08-27 · 与 jinha 协作

> 修订（2026-10-10）：生产已引入 Redis 频道层并允许多 ASGI worker（[ADR-0021](0021-postgresql-redis-and-multiworker.md)）；本 ADR 的「单进程 / InMemory」约束仅适用于**未配置 `REDIS_URL`** 的部署。

生产今日是 **Gunicorn WSGI、2 worker**。消息重置需要把**私信 / 通知 / 当前打开的评论区**推到已登录客户端。SQLite 本就怕多写者；Channels 的 `InMemoryChannelLayer` 也不能跨进程扇出。v1 的约束是：**一个 ASGI 进程，进程内内存层，WebSocket 只推不聊。**

这与 `docs/specs/2026-07-11-single-session-kickout-design.md` **不冲突**。该文否掉 WebSocket，是因为**仅为挤号**引入 Channels + Redis + ASGI 过重，改走 HTTP 中间件 + 401 + 60s 轮询。本 ADR 为消息推送引入 Channels，**挤号仍走那条 HTTP 路径**，不把强制下线挂上本 socket。

## 决策

1. **v1 一个 ASGI 进程。** `start.sh` 以 `gunicorn -k uvicorn.workers.UvicornWorker --workers 1` 绑定 `config.asgi:application`，unix socket 不变（更新器 SIGHUP 仍有效）。未另开 Redis ADR 之前，禁止把 worker 调回 >1。
2. **Channel layer = `InMemoryChannelLayer`**（开发、测试、生产 v1）。worker > 1 时再单开 ADR 谈 Redis。
3. **WebSocket 入口 `/ws/messaging/`。** `ProtocolTypeRouter`：HTTP 走原 Django；WebSocket 走 `AuthMiddlewareStack`。已登录用户进组 `user_{id}`；详情页再 `subscribe_thread` / `unsubscribe_thread` 订当前评论区。
4. **只推送，不是 IM。** 事件三种：`dm`、`notification`、`comment`。不推输入状态、已读回执、在线状态。历史仍走 HTTP；重连后客户端重新拉列表。
5. **横幅公告不靠 socket。** 访客无连接；AppShell 在加载 / 聚焦 / 导航时轮询 `GET /messaging/banners/current/`。
6. **挤号继续 HTTP。** `SingleSessionMiddleware` + 401 `session_superseded` 仍是唯一挤号通道；本 socket 不发下线事件。

Nginx **对上游**须 `proxy_http_version 1.1` 并转发 `Upgrade` / `Connection`（Uvicorn unix socket 只说 HTTP/1.1；WebSocket 的 Upgrade 也在这一段）。浏览器到 nginx 可以是 HTTP/2 或 HTTP/3，写在 `listen` 上，不要按路径拆 `location`，也不要对 unix socket 写 `proxy_http_version 2`。开发代理给 `/ws` 开 `ws: true`。完整站点配置见 [deployment.md](../operations/deployment.md#nginx-两段协议)。

## 被否的方案

- **v1 就上 Redis + 多 worker**：社团流量撑不住这份运维；SQLite 多写者也先崩。否。
- **把挤号改挂 WebSocket**：2026-07-11 已否「仅为挤号上 Channels」；本 socket 存在也不回头改挤号。否。
- **做成即时通讯**：输入状态、回执、在线、会话内历史走 WS——范围远超「评论区 + 私信 + 通知」的推送适配器。否。
- **WS 当事实源**：断线丢事件、与 HTTP 双写。历史与写入仍以 HTTP 为准。否。
