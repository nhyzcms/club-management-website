"""明信片互寄路由：挂在 ``/events/postcard/`` 下（经 events/urls.py include）。

公开端点在前、管理端点在 ``admin/`` 前缀后——一眼可辨暴露面。
"""
from django.urls import path

from . import views

urlpatterns = [
    # —— 公开（AllowAny + phase 门禁 + 限流 + Turnstile）——
    path("portal/", views.PortalView.as_view(), name="postcard-portal"),
    path("register/", views.RegisterView.as_view(), name="postcard-register"),
    path("my/", views.MyRegistrationsView.as_view(), name="postcard-my"),
    # 轮询凭证（审核中不泄露 6 位码）：只读状态 / 申请复核 / 清失败照片
    path("my/token/<str:token>/", views.MyTokenStatusView.as_view(), name="postcard-token-status"),
    path("my/token/<str:token>/review-request/", views.MyTokenReviewRequestView.as_view(), name="postcard-token-review"),
    path("my/token/<str:token>/purge-photos/", views.MyTokenPhotoPurgeView.as_view(), name="postcard-token-purge"),
    # 用户侧查询入口（按登记码 / 寄出人姓名，2026-11-08）
    path("lookup/", views.LookupView.as_view(), name="postcard-lookup"),
    path("my/<str:reg_code>/", views.MyRegistrationDetailView.as_view(), name="postcard-my-detail"),
    path("my/<str:reg_code>/review-request/", views.MyReviewRequestView.as_view(), name="postcard-my-review-request"),
    path("my/<str:reg_code>/purge-photos/", views.MyPhotoPurgeView.as_view(), name="postcard-my-purge-photos"),
    path("suggestions/", views.SuggestionsView.as_view(), name="postcard-suggestions"),
    path("announcement-pdf/", views.AnnouncementPdfView.as_view(), name="postcard-announcement-pdf"),
    path("photo/<int:pk>/", views.PhotoView.as_view(), name="postcard-photo"),
    # —— 管理（命名权限 + 审计）——
    path("admin/config/", views.AdminConfigView.as_view(), name="postcard-admin-config"),
    path("admin/publish/", views.AdminPublishView.as_view(), name="postcard-admin-publish"),
    # 多届活动：归档当前 / 归档并新建下一届（草稿）
    path("admin/archive/", views.AdminArchiveView.as_view(), name="postcard-admin-archive"),
    path("admin/new-season/", views.AdminNewSeasonView.as_view(), name="postcard-admin-new-season"),
    path("admin/barcodes/", views.AdminBarcodesView.as_view(), name="postcard-admin-barcodes"),
    path("admin/barcodes/pdf/", views.AdminBarcodesPdfView.as_view(), name="postcard-admin-barcodes-pdf"),
    path("admin/records/", views.AdminRecordsView.as_view(), name="postcard-admin-records"),
    path("admin/registrations/<str:reg_code>/", views.AdminRegistrationDetailView.as_view(), name="postcard-admin-registration"),
    path("admin/registrations/by-id/<int:pk>/", views.AdminRegistrationByIdView.as_view(), name="postcard-admin-registration-by-id"),
    path("admin/export/", views.AdminExportView.as_view(), name="postcard-admin-export"),
    path("admin/stats/", views.AdminStatsView.as_view(), name="postcard-admin-stats"),
    path("admin/lookup/", views.AdminLookupView.as_view(), name="postcard-admin-lookup"),
    path("admin/confirm/", views.AdminConfirmView.as_view(), name="postcard-admin-confirm"),
    path("admin/unreport/", views.AdminUnreportView.as_view(), name="postcard-admin-unreport"),
    path("admin/suggestions/", views.AdminSuggestionsView.as_view(), name="postcard-admin-suggestions"),
    path("admin/audit/", views.AdminAuditView.as_view(), name="postcard-admin-audit"),
    path("admin/ai/config/", views.AdminAIConfigView.as_view(), name="postcard-admin-ai-config"),
    path("admin/ai/test/", views.AdminAITestView.as_view(), name="postcard-admin-ai-test"),
    # 模型列表（只从服务商 /models 取，供「模型选择」下拉）
    path("admin/ai/models/", views.AdminAIModelsView.as_view(), name="postcard-admin-ai-models"),
    # 模拟环境用：临时上传一张样例图让 AI 解读（不落库）
    path("admin/ai/explain/", views.AdminAIExplainUploadView.as_view(), name="postcard-admin-ai-explain"),
    # 模拟环境用：按正式 prompt 跑一次真判定（不落库、不存照片、不写审计）
    path("admin/ai/preview/", views.AdminAIReviewPreviewView.as_view(), name="postcard-admin-ai-preview"),
    path("admin/ai/samples/", views.AdminAISamplesView.as_view(), name="postcard-admin-ai-samples"),
    path("admin/ai/samples/<int:pk>/", views.AdminAISampleDetailView.as_view(), name="postcard-admin-ai-sample"),
    path("admin/ai/samples/<int:pk>/explain/", views.AdminAISampleExplainView.as_view(), name="postcard-admin-ai-sample-explain"),
    path("admin/ai/samples/<int:pk>/image/", views.AdminAISampleImageView.as_view(), name="postcard-admin-ai-sample-image"),
    # 导入海报 → AI 识别参与学校（只回结果，不落库）
    path("admin/schools/import/", views.AdminSchoolsImportView.as_view(), name="postcard-admin-schools-import"),
    path("admin/review/", views.AdminReviewQueueView.as_view(), name="postcard-admin-review-queue"),
    path("admin/review/<int:item_pk>/", views.AdminReviewDecisionView.as_view(), name="postcard-admin-review-decision"),
]
