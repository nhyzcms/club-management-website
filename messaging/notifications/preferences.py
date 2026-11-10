"""通知订阅偏好：读取矩阵 / 应用更新（供设置页使用）。"""
from __future__ import annotations

from ..models import NotificationSubscription
from .registry import all_channels, all_sources


def build_preferences(user) -> dict:
    """构建订阅矩阵：源 × 通道（缺行回退源默认；站内默认开启、可关闭）。"""
    rows = {
        (s.source_key, s.channel_key): s.enabled
        for s in NotificationSubscription.objects.filter(user=user)
    }

    channels = []
    for ch in all_channels():
        try:
            available = ch.is_available(user)
        except Exception:  # pragma: no cover - 防御性
            available = False
        channels.append({
            "key": ch.key,
            "name": ch.name,
            "description": ch.description,
            "available": available,
        })

    sources = []
    for src in all_sources():
        matrix = {}
        for ch in all_channels():
            if ch.key == "site":
                matrix[ch.key] = rows.get((src.key, ch.key), True)  # 站内默认开启，用户可关闭
                continue
            matrix[ch.key] = rows.get((src.key, ch.key), ch.key in src.default_channels)
        sources.append({
            "key": src.key,
            "name": src.name,
            "description": src.description,
            "events": [{"key": e.key, "name": e.name} for e in src.events],
            "channels": matrix,
        })

    return {"sources": sources, "channels": channels}


class PreferencesError(ValueError):
    """无效的订阅更新。"""


def apply_updates(user, updates) -> None:
    """应用 ``[{"source":…, "channel":…, "enabled":…}, …]`` 变更。"""
    if not isinstance(updates, list):
        raise PreferencesError("updates 须为列表")
    valid_sources = {s.key for s in all_sources()}
    valid_channels = {c.key for c in all_channels()}
    for item in updates:
        if not isinstance(item, dict):
            raise PreferencesError("updates 条目须为对象")
        source = item.get("source")
        channel = item.get("channel")
        if source not in valid_sources:
            raise PreferencesError(f"未知源：{source}")
        if channel not in valid_channels:
            raise PreferencesError(f"未知通道：{channel}")
        # 站内与其它通道一致：用户有权拒绝接收（关闭后该源整体静默，见 dispatch）
        NotificationSubscription.objects.update_or_create(
            user=user, source_key=source, channel_key=channel,
            defaults={"enabled": bool(item.get("enabled"))},
        )
