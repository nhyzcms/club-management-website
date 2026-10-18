from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .identity_review import IdentityReviewViewSet
from .inbox import InboxView

router = DefaultRouter()
router.register(r"identity-reviews", IdentityReviewViewSet, basename="identity-review")

urlpatterns = [
    path("inbox/", InboxView.as_view(), name="inbox"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("verify-email/", views.verify_email_view, name="verify_email"),
    path("resend-verification/", views.resend_verification_view, name="resend_verification"),
    path("identity-proof/<int:pk>/", views.identity_proof_file_view, name="identity_proof_file"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.me_view, name="me"),
    path("verification/", views.verification_status_view, name="verification_status"),
    path("verification/email/bind/", views.verification_email_bind_view, name="verification_email_bind"),
    path("verification/manual/submit/", views.verification_manual_submit_view, name="verification_manual_submit"),
    path("verification/authcode/redeem/", views.verification_authcode_redeem_view, name="verification_authcode_redeem"),
    path("member/", views.member_identity_view, name="member_identity"),
    path("member/claim/", views.member_claim_view, name="member_claim"),
    path("member/check/", views.member_check_view, name="member_check"),
    path("stepup/", views.stepup_status_view, name="stepup_status"),
    path("stepup/email/send/", views.stepup_email_send_view, name="stepup_email_send"),
    path("stepup/verify/", views.stepup_verify_view, name="stepup_verify"),
    path("stepup/questions/", views.stepup_questions_view, name="stepup_questions"),
    path("stepup/events/", views.stepup_events_view, name="stepup_events"),
    path("sessions/", views.sessions_view, name="sessions"),
    path("csrf/", views.csrf_token_view, name="csrf_token"),
    path("password-reset/", views.password_reset_view, name="password_reset"),
    path("password-reset/confirm/", views.password_reset_confirm_view, name="password_reset_confirm"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/update/", views.profile_update_view, name="profile_update"),
    path("profile/change-password/", views.change_password_view, name="change_password"),
    path("account/delete/", views.delete_account_view, name="delete_account"),
    path("users/", views.users_view, name="users"),
    path("users/<int:id>/profile/", views.user_profile_view, name="user_profile"),
    path("users/<int:id>/content/", views.user_content_view, name="user_content"),
    path("", include(router.urls)),
]
