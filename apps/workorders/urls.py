from django.urls import re_path

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
    re_path(r"^/?$", WorkOrderBoardView.as_view(), name="board"),
    re_path(
        r"^columns/(?P<pk>\d+)/?$",
        KanbanColumnDisplayView.as_view(),
        name="column_display",
    ),
    re_path(
        r"^columns/(?P<pk>\d+)/edit/?$",
        KanbanColumnEditView.as_view(),
        name="column_edit",
    ),
    re_path(
        r"^columns/(?P<pk>\d+)/rename/?$",
        KanbanColumnRenameView.as_view(),
        name="column_rename",
    ),
    re_path(r"^new/?$", WorkOrderCreateView.as_view(), name="create"),
    re_path(r"^(?P<pk>\d+)/?$", WorkOrderDetailView.as_view(), name="detail"),
    re_path(r"^(?P<pk>\d+)/edit/?$", WorkOrderUpdateView.as_view(), name="edit"),
    re_path(
        r"^(?P<pk>\d+)/comments/?$",
        WorkOrderCommentCreateView.as_view(),
        name="comment",
    ),
    re_path(
        r"^(?P<pk>\d+)/attachments/?$",
        WorkOrderAttachmentCreateView.as_view(),
        name="attachment",
    ),
    re_path(
        r"^(?P<pk>\d+)/confirm-closure/?$",
        WorkOrderConfirmClosureView.as_view(),
        name="confirm_closure",
    ),
    re_path(r"^(?P<pk>\d+)/rate/?$", WorkOrderRateView.as_view(), name="rate"),
    re_path(
        r"^(?P<pk>\d+)/transition/?$",
        WorkOrderTransitionView.as_view(),
        name="transition",
    ),
    re_path(
        r"^(?P<pk>\d+)/board-move/?$",
        WorkOrderBoardMoveView.as_view(),
        name="board_move",
    ),
]
