"""账号注销（自服务）：软删除 + 敏感信息清除（ADR-0027）。

用户从个人中心主动注销时走这里，**不做物理删除**：

- **保留** ``User`` / ``Profile`` 行：账号主键（``User.id``）、用户名（账号唯一编码）、
  真实姓名、注册时间、评论 / 私信 / 新闻等历史内容归属全部留在库里，后台仍可审计；
  这样也不会因删除外键而破坏历史数据（兼容性优先）。
- **清除**敏感信息：登录邮箱、邮箱 / 认证码等验证通道标识、头像、生日、性别、简介、
  身份证明材料（行 + 私有存储文件）、登录会话与设备记录、站内通知与通知偏好。
- **吊销**全部登录：删 Django Session 行 + ``UserSession`` 行，并把密码置为不可用
  （``set_unusable_password``），因此既有会话与后续登录都失效。
- **标记** ``Profile.deleted_at``：所有「注销态」判定的唯一真源；公开展示位统一渲染成
  「该用户已注销」（``messaging.serializers.SimpleUserSerializer``），私信历史照常可读但
  不能再向该用户发消息。
"""
from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from .identity_review import revoke_user_sessions
from .models import (
    IdentityProof,
    Profile,
    SecurityQuestion,
    StepUpEmailCode,
    StepUpEvent,
    UserSession,
    Verification,
)


class AccountDeletionError(Exception):
    """注销被拒绝（视图负责映射成 HTTP）。"""

    def __init__(self, message: str, *, status: int = 400, reason: str = ""):
        self.message = message
        self.status = status
        self.reason = reason
        super().__init__(message)


@transaction.atomic
def delete_account(user: User) -> Profile:
    """注销 ``user``：软删除 + 清敏感信息。返回更新后的 :class:`Profile`。

    幂等语义：已注销账号再次调用抛 ``account_already_deleted``（不给「重复注销」伪装成功，
    否则并发 / 重放无法区分）。
    """
    profile, _created = Profile.objects.get_or_create(user=user)
    if profile.deleted_at is not None:
        raise AccountDeletionError(
            "该账号已注销。", status=409, reason="account_already_deleted",
        )
    # 管理员 / 超管账号不开放自助注销：站点只有极少数管理员，误触会让社团失去后台。
    # 需要离任请先由社长 / 服务器管理员调整角色后再注销。
    if user.is_staff or user.is_superuser:
        raise AccountDeletionError(
            "管理员账号不能自行注销，请先联系社长或服务器管理员调整角色。",
            status=403,
            reason="account_deletion_protected",
        )

    now = timezone.now()

    # 1) 身份证明材料：文件 + 行一并删除（注销后不再保留审计证据）。
    for proof in IdentityProof.objects.filter(user=user):
        if proof.file:
            proof.file.delete(save=False)
        proof.delete()

    # 2) 头像文件（Profile 行保留，只清字段）。
    if profile.avatar:
        profile.avatar.delete(save=False)

    # 3) 验证通道：邮箱 identifier / 认证码标识等随身信息随行删除；
    #    ValidityNotice 经 CASCADE 一并清掉。
    Verification.objects.filter(user=user).delete()

    # 4) 登录会话与设备记录：先删 Django Session（强制下线），再删 UserSession 行。
    revoke_user_sessions(user)
    UserSession.objects.filter(user=user).delete()

    # 4.1) 安全验证（Step-up，ADR-0026）的敏感残留：安全问题答案哈希、邮箱验证码
    #      （sent_to 是邮箱原文）、带 IP 的审计事件。
    SecurityQuestion.objects.filter(user=user).delete()
    StepUpEmailCode.objects.filter(user=user).delete()
    StepUpEvent.objects.filter(user=user).delete()

    # 5) 站内通知 / 通知偏好 / 已读状态（个人数据，且含私信摘要）。
    #    延迟 import：messaging 依赖 accounts，模块顶部 import 会成环。
    from messaging.models import MessageReadStatus, Notification, NotificationSubscription

    Notification.objects.filter(recipient=user).delete()
    NotificationSubscription.objects.filter(user=user).delete()
    MessageReadStatus.objects.filter(user=user).delete()

    # 6) 账号本体：清邮箱、清密码（不可用）、停用（挡登录 / 全部公开列表）。
    #    用户名（账号唯一编码）、主键、date_joined 一律不动。
    user.email = ""
    user.first_name = ""
    user.last_name = ""
    user.is_active = False
    user.set_unusable_password()
    user.save(update_fields=["email", "first_name", "last_name", "is_active", "password"])

    # 7) 资料：清敏感字段，保留真实姓名（审计需要）、昵称与身份标签；
    #    打上注销标记。
    profile.avatar = ""
    profile.birthday = None
    profile.gender = ""
    profile.bio = ""
    profile.registration_deadline = None
    profile.expiry_disabled_at = None
    profile.deleted_at = now
    profile.save(
        update_fields=[
            "avatar", "birthday", "gender", "bio",
            "registration_deadline", "expiry_disabled_at", "deleted_at",
        ]
    )
    return profile
