"""明信片互寄 · 照片生命周期收口（方案 §7「照片留存」）。

规则（用户已认可，勿改动）：

- AI / 人工**通过** → 立即删物理文件（行保留、状态记终态——审计可查
  「哪张审过、结果如何」，``file`` 置空即「文件已删」标记）；
- 复核**失败**（ai_failed / manual_failed）→ 用户关标签页 ``sendBeacon``
  删 + **24h TTL** 兜底（gc_sweep）；
- **活动结束** → 该活动照片文件全量清除（状态翻转惰性触发 + 周期兜底）；
- 登记数据永久保留（除非管理员手动删）——照片行删除不影响登记记录。

本模块是照片文件删除的**唯一**入口（ai / views / gc 命令都经这里），
``purge_photo_file`` 幂等（文件已删再调无副作用）。
"""
from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from events.models import Event

from . import state
from .models import PostcardPhoto, PostcardRegistration

#: 复核失败照片的 TTL（小时）——用户没关标签页也兜底删。
FAILED_PHOTO_TTL_HOURS = 24
#: pending 卡死（线程被杀 / 进程重启）转人工的阈值（分钟）。
STALE_PENDING_MINUTES = 60

_ENDED_PURGE_KEY = "postcard:photos-purged:{event_pk}"


def purge_photo_file(photo: PostcardPhoto) -> None:
    """删物理文件 + ``file`` 置空（幂等；行保留）。失败静默。"""
    photo.delete_file()
    if photo.file:
        PostcardPhoto.objects.filter(pk=photo.pk).update(
            file="", updated_at=timezone.now(),
        )
        photo.file = ""


def settle_item_photos(
    item, review_state: str, verdict: dict | None = None, *, purge_files: bool = False,
) -> None:
    """把一个条目两面照片翻到统一状态；``purge_files``（通过）时删文件。"""
    now = timezone.now()
    item.photos.update(review_state=review_state, ai_verdict=verdict, updated_at=now)
    if purge_files:
        for photo in item.photos.all():
            purge_photo_file(photo)


def settle_registration(reg: PostcardRegistration, review_state: str, verdict: dict | None = None) -> int:
    """整单全部条目翻状态（AI 不可用 / worker 兜底路径）。返回条目数。"""
    count = 0
    for item in reg.items.prefetch_related("photos"):
        settle_item_photos(item, review_state, verdict)
        count += 1
    return count


def purge_registration_failed_photos(reg: PostcardRegistration) -> int:
    """用户关标签页 sendBeacon 入口：只删**终态失败**照片文件（通过的照片
    AI 已即时删过；pending 的还在审，不动）。幂等。"""
    purged = 0
    qs = PostcardPhoto.objects.filter(
        item__registration=reg,
        review_state__in=[PostcardPhoto.REVIEW_AI_FAILED, PostcardPhoto.REVIEW_MANUAL_FAILED],
    ).exclude(file="")
    for photo in qs:
        purge_photo_file(photo)
        purged += 1
    return purged


def purge_event_photos(event: Event) -> int:
    """活动结束全量清除：该活动全部照片文件（含 pending——活动都结束了，
    审核已无意义）。行与登记数据保留。幂等。"""
    purged = 0
    qs = PostcardPhoto.objects.filter(item__registration__event=event).exclude(file="")
    for photo in qs.iterator():
        purge_photo_file(photo)
        purged += 1
    return purged


def purge_event_files(event: Event) -> dict:
    """删除一届活动的全部物理文件（照片 / 样例图 / 公告 PDF），行不动。

    ``Event.delete()`` 只级联删行、**不删私有存储里的文件**，所以删活动之前
    必须走这里，否则留下永远查不到的孤儿文件。幂等，失败静默。
    """
    photos = purge_event_photos(event)
    samples = 0
    for sample in event.postcard_ai_samples.all():
        sample.delete_file()
        samples += 1
    announcement_pdf = False
    config = getattr(event, "postcard_config", None)
    if config is not None and config.announcement_pdf:
        try:
            config.announcement_pdf.delete(save=False)
            announcement_pdf = True
        except Exception:  # noqa: BLE001 —— 文件已丢失不该挡住删库
            pass
    return {"photos": photos, "samples": samples, "announcement_pdf": announcement_pdf}


def delete_season(event: Event) -> dict:
    """管理员删除整届（整批）活动：清物理文件 → 清缓存 → 删 Event。

    删 Event 会级联掉 config / 条码 / 登记 / 条目 / 照片行 / 建议 / 审计 /
    样例行——即「该年度的全部数据」。不可恢复，入口必须带二次确认。
    """
    stats = purge_event_files(event)
    # 惰性清理锁一并清掉，防同 pk 复用时的误判（SQLite 自增可能复用）。
    cache.delete(_ENDED_PURGE_KEY.format(event_pk=event.pk))
    event.delete()
    return stats


def maybe_purge_ended_event(event: Event | None, phase: str) -> None:
    """状态翻转惰性触发：phase 推导出「已结束」时清一次（cache 锁防重）。

    挂在 ``views._phase_guard``——任何明信片请求都会过这道闸，活动结束后
    第一个访客触发清除，无需等 cron。周期兜底见 ``gc_sweep``。
    """
    if event is None or phase != state.PHASE_ENDED:
        return
    key = _ENDED_PURGE_KEY.format(event_pk=event.pk)
    if cache.get(key):
        return
    cache.set(key, 1, None)  # 本活动只惰性清一次；后续由 gc_sweep 兜底
    purge_event_photos(event)


def gc_sweep(now=None) -> dict:
    """周期兜底（management command ``postcard_photo_gc`` 调用）：

    1. 已结束活动 → 照片文件全清（含 maybe_purge 漏网的）；
    2. 终态失败照片 > TTL → 删文件；
    3. pending 卡死 > 阈值 → 转人工复核（线程被杀的兜底）。

    返回统计 dict（命令行输出 / 测试断言用）。
    """
    now = now or timezone.now()
    stats = {"ended_events_purged": 0, "ttl_purged": 0, "stale_pending_to_manual": 0}

    for event in Event.objects.filter(module_key="postcard"):
        config = getattr(event, "postcard_config", None)
        if config is None:
            continue
        if state.phase_of(event, config, now=now) == state.PHASE_ENDED:
            stats["ended_events_purged"] += purge_event_photos(event)

    ttl_cutoff = now - timedelta(hours=FAILED_PHOTO_TTL_HOURS)
    stale_cutoff = now - timedelta(minutes=STALE_PENDING_MINUTES)

    for photo in PostcardPhoto.objects.filter(
        review_state__in=[
            PostcardPhoto.REVIEW_AI_FAILED, PostcardPhoto.REVIEW_MANUAL_FAILED,
        ],
        updated_at__lt=ttl_cutoff,
    ).exclude(file="").iterator():
        purge_photo_file(photo)
        stats["ttl_purged"] += 1

    stale_items = set(
        PostcardPhoto.objects.filter(
            review_state=PostcardPhoto.REVIEW_PENDING, created_at__lt=stale_cutoff,
        ).values_list("item_id", flat=True)
    )
    for item_id in stale_items:
        # 原子翻转：只把仍处 pending 的翻走（与后台线程竞争安全）。
        updated = PostcardPhoto.objects.filter(
            item_id=item_id, review_state=PostcardPhoto.REVIEW_PENDING,
        ).update(
            review_state=PostcardPhoto.REVIEW_MANUAL_PENDING,
            ai_verdict={"reason": "stale_pending_gc"},
            updated_at=now,
        )
        if updated:
            stats["stale_pending_to_manual"] += 1
    return stats
