from django.urls import path

from . import views

app_name = "memory"

urlpatterns = [
    path("review/", views.MemoryReviewDashboardView.as_view(), name="review_dashboard"),
    path("review/issues/", views.MemoryIssueListView.as_view(), name="review_issue_list"),
    path("review/issues/<int:pk>/", views.MemoryIssueDetailView.as_view(), name="review_issue_detail"),
    path("review/issues/<int:pk>/action/", views.MemoryIssueActionView.as_view(), name="review_issue_action"),
    path("review/index/", views.MemoryIndexListView.as_view(), name="review_index_list"),
    path("review/index/<path:document_id>/action/", views.MemoryIndexActionView.as_view(), name="review_index_action"),
    path("review/index/<path:document_id>/", views.MemoryIndexDetailView.as_view(), name="review_index_detail"),
    path("review/pending/", views.MemoryPendingListView.as_view(), name="review_pending_list"),
    path("review/pending/<str:memory_id>/action/", views.MemoryPendingActionView.as_view(), name="review_pending_action"),
    path("review/audit/", views.MemoryReviewAuditView.as_view(), name="review_audit"),
]
