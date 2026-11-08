"""明信片互寄 · 站内信（与内容送审同一套投递规则）。

规则（2026-11-08 用户指定）：**有新审核申请就给管理员发站内信**，且与先前
其他类型（内容送审 / 意见反馈 / 认证 / 密码重置）完全一致——
``notify_perm("review", ...)`` 按权限 ``events.review_postcard`` 动态投递、
尊重用户订阅开关、站内 + 推送、读掉后才重新通知。

同一登记码（同一发件人多次提交）的未读通知按 ``group`` 聚合成一条，
避免活动当天几十条重复提醒（见 ``ReviewSource.dedup_identity``）。
"""
from __future__ import annotations

from messaging.notifications.dispatch import users_with_perm
from messaging.services import notify_perm


def notify_reviewers(reg, *, actor=None) -> None:
    """一份提交进入人工复核队列 → 通知全部持复核权限的管理员。

    失败静默：通知不该拖垮审核主流程（与审计日志同一原则）。
    """
    try:
        notify_perm(
            "review",
            "postcard_submitted",
            "events.review_postcard",
            actor=actor,
            # manage_postcard 隐含复核权（与 CanReviewPostcard 一致），一并收信。
            extra_recipients=users_with_perm("events.manage_postcard"),
            payload={
                "type": "postcard",
                "id": reg.pk,
                "title": f"{reg.sender_name} 的明信片",
                # 同码聚合键：同一发件人的多次提交只占一条未读通知。
                "group": f"{reg.event_id}:{reg.reg_code}",
                "url": "/reviews?kind=postcard",
            },
        )
    except Exception:  # noqa: BLE001 —— 通知失败不影响审核状态机
        pass
