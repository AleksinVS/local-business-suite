from django.urls import path

from .views import (
    WorkOrderAttachmentCreateView,
    WorkOrderBoardView,
    WorkOrderCommentCreateView,
    WorkOrderCreateView,
    WorkOrderDetailView,
    WorkOrderTransitionView,
)

app_name = "workorders"

urlpatterns = [
    path("", WorkOrderBoardView.as_view(), name="board"),
    path("new/", WorkOrderCreateView.as_view(), name="create"),
    path("<int:pk>/", WorkOrderDetailView.as_view(), name="detail"),
    path("<int:pk>/comments/", WorkOrderCommentCreateView.as_view(), name="comment"),
    path("<int:pk>/attachments/", WorkOrderAttachmentCreateView.as_view(), name="attachment"),
    path("<int:pk>/transition/", WorkOrderTransitionView.as_view(), name="transition"),
]
