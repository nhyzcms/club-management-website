"""测试辅助（认证模型，ADR-0006）：给用户造 approved 认证通道，使其通过 IsVerified 写门禁。

生产中存量账号经迁移默认信任、新账号经邮箱 / 人工通道认证；测试里直接造 approved 行，
代表「已认证的普通成员」，聚焦被测逻辑（任务 / 消息 / 申报 / 新闻 等），不重复走认证流程。
"""

from accounts.models import Verification


def grant_verification(user, channel=Verification.CHANNEL_MANUAL):
    """给 user 造一条 approved 通道（默认 manual）；已存在则原样返回。返回 user 便于链式。"""
    Verification.objects.get_or_create(
        user=user,
        channel=channel,
        defaults={"status": Verification.STATUS_APPROVED},
    )
    return user
