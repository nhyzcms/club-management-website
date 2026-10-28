from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import security_center, login_challenge, views
from .identity_review import IdentityReviewViewSet
from .inbox import InboxView
from .password_reset_review import PasswordResetRequestViewSet

router = DefaultRouter()
router.register(r"identity-reviews", IdentityReviewViewSet, basename="identity-review")
router.register(
    r"password-reset-requests", PasswordResetRequestViewSet, basename="password-reset-request",
)

urlpatterns = [
    path("inbox/", InboxView.as_view(), name="inbox"),
    path("login/", views.login_view, name="login"),
    path("login/challenge/", login_challenge.challenge_send_view, name="login_challenge_send"),
    path("login/challenge/verify/", login_challenge.challenge_verify_view, name="login_challenge_verify"),
    path("login/challenge/status/", login_challenge.challenge_status_view, name="login_challenge_status"),
    path("register/", views.register_view, name="register"),
    path("verify-email/", views.verify_email_view, name="verify_email"),
    path("resend-verification/", views.resend_verification_view, name="resend_verification"),
    path("identity-proof/<int:pk>/", views.identity_proof_file_view, name="identity_proof_file"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.me_view, name="me"),
    path("verification/", views.verification_status_view, name="verification_status"),
    path("validity/", views.validity_summary_view, name="validity_summary"),
    path("validity/ack/", views.validity_ack_view, name="validity_ack"),
    path("verification/email/bind/", views.verification_email_bind_view, name="verification_email_bind"),
    path("verification/manual/submit/", views.verification_manual_submit_view, name="verification_manual_submit"),
    path("verification/authcode/redeem/", views.verification_authcode_redeem_view, name="verification_authcode_redeem"),
    path("member/", views.member_identity_view, name="member_identity"),
    path("member/claim/", views.member_claim_view, name="member_claim"),
    path("member/check/", views.member_check_view, name="member_check"),
    path("member/lookup/", views.member_lookup_view, name="member_lookup"),
    path("stepup/", views.stepup_status_view, name="stepup_status"),
    path("stepup/email/send/", views.stepup_email_send_view, name="stepup_email_send"),
    path("stepup/verify/", views.stepup_verify_view, name="stepup_verify"),
    path("stepup/questions/", views.stepup_questions_view, name="stepup_questions"),
    path("stepup/events/", views.stepup_events_view, name="stepup_events"),
    path("security/overview/", security_center.security_overview_view, name="security_overview"),
    path("devices/", security_center.devices_view, name="devices"),
    path("devices/<int:pk>/", security_center.device_revoke_view, name="device_revoke"),
    path("login-events/", security_center.login_events_view, name="login_events"),
    path("totp/", security_center.totp_list_view, name="totp_list"),
    path("totp/setup/", security_center.totp_setup_view, name="totp_setup"),
    path("totp/confirm/", security_center.totp_confirm_view, name="totp_confirm"),
    path("totp/<int:pk>/", security_center.totp_delete_view, name="totp_delete"),
    path("recovery-codes/", security_center.recovery_codes_view, name="recovery_codes"),
    path("sessions/", views.sessions_view, name="sessions"),
    # 多端登录（ADR-0028）：个人中心下线单台 / 下线其他所有设备。
    path("sessions/revoke-others/", views.sessions_revoke_others_view, name="sessions_revoke_others"),
    path("sessions/<int:session_id>/revoke/", views.session_revoke_view, name="session_revoke"),
    path("csrf/", views.csrf_token_view, name="csrf_token"),
    path("password-reset/", views.password_reset_view, name="password_reset"),
    path("password-reset/confirm/", views.password_reset_confirm_view, name="password_reset_confirm"),
    # 忘记密码 → 管理员手动重置（2026-10）：匿名提交申请 + 审批人取证明。
    path("password-reset/request/", views.password_reset_request_view, name="password_reset_request"),
    path(
        "password-reset-requests/<int:pk>/proof/",
        views.password_reset_proof_file_view,
        name="password_reset_proof_file",
    ),
    # 管理员重置后的首次登录强制改密。
    path("password/force-change/", views.force_change_password_view, name="force_change_password"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/update/", views.profile_update_view, name="profile_update"),
    path("profile/change-password/", views.change_password_view, name="change_password"),
    path("account/delete/", views.delete_account_view, name="delete_account"),
    path("users/", views.users_view, name="users"),
    path("users/<int:id>/profile/", views.user_profile_view, name="user_profile"),
    path("users/<int:id>/content/", views.user_content_view, name="user_content"),
    path("", include(router.urls)),
]
