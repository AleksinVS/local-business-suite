from django.urls import path

from .views import (
    WorkOrderAttachmentCreateView,
    WorkOrderBoardView,
    KanbanColumnEditView,
    KanbanColumnDisplayView,
    KanbanColumnRenameView,
    WorkOrderCommentCreateView,
    WorkOrderCreateView,
    WorkOrderDetailView,
    WorkOrderRateView,
    WorkOrderUpdateView,
    WorkOrderConfirmClosureView,
    WorkOrderTransitionView,
    WorkOrderBoardMoveView,
)

app_name = "workorders"

urlpatterns = [
    path("", WorkOrderBoardView.as_view(), name="board"),
    path("columns/<int:pk>/", KanbanColumnDisplayView.as_view(), name="column_display"),
    path("columns/<int:pk>/edit/", KanbanColumnEditView.as_view(), name="column_edit"),
    path(
        "columns/<int:pk>/rename/",
        KanbanColumnRenameView.as_view(),
        name="column_rename",
    ),
    path("new/", WorkOrderCreateView.as_view(), name="create"),
    path("<int:pk>/", WorkOrderDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", WorkOrderUpdateView.as_view(), name="edit"),
    path("<int:pk>/comments/", WorkOrderCommentCreateView.as_view(), name="comment"),
    path(
        "<int:pk>/attachments/",
        WorkOrderAttachmentCreateView.as_view(),
        name="attachment",
    ),
    path(
        "<int:pk>/confirm-closure/",
        WorkOrderConfirmClosureView.as_view(),
        name="confirm_closure",
    ),
    path("<int:pk>/rate/", WorkOrderRateView.as_view(), name="rate"),
    path("<int:pk>/transition/", WorkOrderTransitionView.as_view(), name="transition"),
    path("<int:pk>/board-move/", WorkOrderBoardMoveView.as_view(), name="board_move"),
]
