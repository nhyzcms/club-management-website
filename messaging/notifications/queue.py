"""通知外发投递队列（进程内）：生产者-消费者 + 守护线程 + DB 兜底。

设计（ADR-0024）：每个进程一份队列 + 一个 daemon 消费者线程——
- 投递点（``dispatch._deliver``）只做「写 pending 行 + enqueue(id)」——请求零阻塞；
- 消费者批量消费：原子认领（``next_retry_at`` 当锁）→ 发送（email 复用 SMTP 连接）；
- 失败按退避序列重排（1m/5m/30m/2h/6h，最多 5 次重试），超限落 ``failed`` 终态；
- 兜底：消费线程周期性扫描 DB 中「到期 pending」——覆盖进程重启残漏、入队丢失、
  队列满降级；语义 at-least-once（极端崩溃窗口可能重复一封，见 ADR）。

开关：``settings.NOTIFICATIONS_DELIVERY_ASYNC``（默认开）。关闭时 dispatch 走旧的
同步投递（本模块不参与）；测试期默认同步，异步用例用 ``override_settings`` 开启。
"""
from __future__ import annotations

import logging
import queue as queue_mod
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.core import mail as django_mail
from django.db import close_old_connections
from django.db.models import F, Q
from django.utils import timezone

from ..models import NotificationDelivery
from .registry import get_channel

logger = logging.getLogger(__name__)

# ---- 参数（设计稿 §2.3；按运维需要可调） ------------------------------------
QUEUE_MAXSIZE = 1000            # 单进程队列容量；满则静默落库、靠扫描兜底（不阻塞请求）
BATCH_MAX = 32                  # 单批最多处理条数
IDLE_TICK = 30                  # 空闲等待（秒）；也是扫描计时的唤醒节拍
SWEEP_INTERVAL = 900            # 兜底扫描最小间隔（秒）
SWEEP_LIMIT = 200               # 单次扫描最多捞取条数
CLAIM_LOCK = timedelta(minutes=5)   # 认领锁时长：发送中崩溃由它自动恢复
MAX_RETRIES = 5                 # 最多重试次数（首发 + 5 次重试）
RETRY_BACKOFF = (               # 第 1..5 次失败后的重试间隔
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
)
MAIL_CONN_IDLE_TIMEOUT = 300    # 共享 SMTP 连接空闲回收（秒）

# ---- 进程级单例状态 ----------------------------------------------------------
_lock = threading.Lock()
_q: queue_mod.Queue | None = None
_worker: threading.Thread | None = None
_stop = threading.Event()
_last_sweep = 0.0
_mail_conn = None
_mail_conn_used_at = 0.0


def _get_queue() -> queue_mod.Queue:
    global _q
    if _q is None:
        _q = queue_mod.Queue(maxsize=QUEUE_MAXSIZE)
    return _q


def _ensure_worker() -> None:
    """懒启动消费线程（首个入队才起；管理命令 / 测试不会意外拉起）。"""
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop.clear()
        _worker = threading.Thread(
            target=_consumer_loop, name="notif-delivery", daemon=True,
        )
        _worker.start()


def enqueue(delivery_id: int) -> None:
    """投递点入口（仅异步模式调用）：入队，微秒级返回。

    队列满时不阻塞、不抛异常——投递行保持 ``pending``，由周期扫描兜底补投。
    """
    _ensure_worker()
    try:
        _get_queue().put_nowait(delivery_id)
    except queue_mod.Full:
        logger.warning("通知队列已满，延迟由扫描补投 delivery=%s", delivery_id)


def stop_worker(timeout: float = 2.0) -> None:
    """停止消费线程并回收共享连接（测试收尾 / 进程收尾用）。"""
    global _worker
    _stop.set()
    worker = _worker
    if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
        worker.join(timeout)
    _worker = None
    _stop.clear()
    _reset_mail_conn()


# ---- 消费循环（守护线程） -----------------------------------------------------

def _consumer_loop() -> None:
    """批消费 + 周期兜底扫描；全包防御——循环绝不静默死亡。"""
    while not _stop.is_set():
        try:
            try:
                first = _get_queue().get(timeout=IDLE_TICK)
            except queue_mod.Empty:
                _maybe_sweep()
                _maybe_close_idle_mail()
                continue

            batch = [first]
            while len(batch) < BATCH_MAX:
                try:
                    batch.append(_get_queue().get_nowait())
                except queue_mod.Empty:
                    break

            stats = {"sent": 0, "retry": 0, "failed": 0, "skip": 0}
            for pid in batch:
                outcome = _process_one(pid)
                stats[outcome] = stats.get(outcome, 0) + 1

            if stats["sent"] or stats["retry"] or stats["failed"]:
                logger.info(
                    "通知队列：处理 %d 条（sent=%d retry=%d failed=%d skip=%d，队列余量≈%d）",
                    len(batch), stats["sent"], stats["retry"], stats["failed"],
                    stats["skip"], _get_queue().qsize(),
                )
            _maybe_sweep()
            _maybe_close_idle_mail()
        except Exception:  # pragma: no cover - 防御：任何异常都不允许杀死循环
            logger.exception("通知队列消费者异常（已捕获，循环继续）")
            time.sleep(1)


def _process_one(delivery_id: int) -> str:
    """处理单条投递：原子认领 → 发送 → 标记。返回 sent / retry / failed / skip。"""
    close_old_connections()
    try:
        now = timezone.now()
        # 原子认领：把 next_retry_at 推到未来（锁）；并发方（其他 worker / 扫描）会跳过。
        claimed = (
            NotificationDelivery.objects
            .filter(pk=delivery_id, status=NotificationDelivery.STATUS_PENDING)
            .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
            .update(next_retry_at=now + CLAIM_LOCK)
        )
        if not claimed:
            return "skip"

        delivery = (
            NotificationDelivery.objects
            .select_related("notification", "notification__recipient")
            .get(pk=delivery_id)
        )
        channel = get_channel(delivery.channel_key)
        if channel is None:
            _mark_failed(delivery, f"未知通道：{delivery.channel_key}")
            return "failed"

        # 建行与发送存在时间差：发送前复查通道可用性（邮箱被撤认证等情形不再打扰）。
        try:
            available = channel.is_available(delivery.notification.recipient)
        except Exception:  # pragma: no cover - 防御性
            available = False
        if not available:
            _mark_failed(delivery, "收件人当前不可用（邮箱未认证或已停用）")
            return "failed"

        try:
            conn = _mail_connection(channel)
            channel.deliver(delivery, connection=conn)
        except Exception as exc:
            _reset_mail_conn()
            return _schedule_retry_or_fail(delivery, exc)

        _mark_sent(delivery)
        return "sent"
    finally:
        close_old_connections()


def _mark_sent(delivery: NotificationDelivery) -> None:
    NotificationDelivery.objects.filter(pk=delivery.pk).update(
        status=NotificationDelivery.STATUS_SENT,
        sent_at=timezone.now(),
        last_error="",
        attempts=F("attempts") + 1,
    )


def _mark_failed(delivery: NotificationDelivery, reason: str) -> None:
    NotificationDelivery.objects.filter(pk=delivery.pk).update(
        status=NotificationDelivery.STATUS_FAILED,
        last_error=reason[:500],
        attempts=F("attempts") + 1,
    )
    logger.warning(
        "通知投递失败（终态）：delivery=%s channel=%s 原因=%s",
        delivery.pk, delivery.channel_key, reason,
    )


def _schedule_retry_or_fail(delivery: NotificationDelivery, exc: Exception) -> str:
    """失败处理：未超限则按退避重排（回 pending），超限落 failed 终态。"""
    attempts = (delivery.attempts or 0) + 1
    if attempts > MAX_RETRIES:
        _mark_failed(delivery, str(exc))
        return "failed"
    delay = RETRY_BACKOFF[attempts - 1]
    NotificationDelivery.objects.filter(pk=delivery.pk).update(
        status=NotificationDelivery.STATUS_PENDING,
        last_error=str(exc)[:500],
        attempts=attempts,
        next_retry_at=timezone.now() + delay,
    )
    logger.info(
        "通知投递失败将重试：delivery=%s channel=%s 第 %s 次失败，%s 后重试：%s",
        delivery.pk, delivery.channel_key, attempts, delay, str(exc)[:200],
    )
    return "retry"


# ---- 兜底扫描 -----------------------------------------------------------------

def sweep(limit: int = SWEEP_LIMIT) -> int:
    """补投 DB 中到期的 pending：重启残漏 / 队列满降级 / 已到期的重试。

    并发安全：逐个走 ``_process_one`` 的原子认领——多 worker 同时扫描不会重复。
    返回实际处理条数。
    """
    now = timezone.now()
    ids = list(
        NotificationDelivery.objects
        .filter(status=NotificationDelivery.STATUS_PENDING)
        .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    if not ids:
        return 0
    processed = 0
    for pid in ids:
        if _process_one(pid) != "skip":
            processed += 1
    logger.info("通知队列：兜底扫描处理 %d 条（候选 %d）", processed, len(ids))
    return processed


def _maybe_sweep() -> None:
    global _last_sweep
    now = time.monotonic()
    if now - _last_sweep < SWEEP_INTERVAL:
        return
    _last_sweep = now
    sweep()


def drain_now(limit: int = 200) -> int:
    """同步排空：先清内存队列，再兜底扫库。测试与 flush 命令入口；返回处理条数。"""
    processed = 0
    if _q is not None:
        while processed < limit:
            try:
                pid = _q.get_nowait()
            except queue_mod.Empty:
                break
            _process_one(pid)
            processed += 1
    if processed < limit:
        processed += sweep(limit=limit - processed)
    return processed


# ---- 共享 SMTP 连接（email 通道复用） ------------------------------------------

def _mail_connection(channel):
    """为使用共享连接的通道（email）提供复用的 SMTP 连接；其他通道返回 None。"""
    global _mail_conn, _mail_conn_used_at
    if not getattr(channel, "uses_shared_connection", False):
        return None
    if _mail_conn is None:
        _mail_conn = django_mail.get_connection()
    _mail_conn.open()  # 幂等：已打开时为 no-op；打开失败抛异常 → 记为投递失败并重试
    _mail_conn_used_at = time.monotonic()
    return _mail_conn


def _reset_mail_conn() -> None:
    global _mail_conn
    if _mail_conn is not None:
        try:
            _mail_conn.close()
        except Exception:  # pragma: no cover - 关闭失败无碍重开
            pass
        _mail_conn = None


def _maybe_close_idle_mail() -> None:
    if _mail_conn is not None and time.monotonic() - _mail_conn_used_at > MAIL_CONN_IDLE_TIMEOUT:
        _reset_mail_conn()
