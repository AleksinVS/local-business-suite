from django.urls import path

from .views import (
    AIChatDetailView,
    AIChatIndexView,
    AIChatMessageCreateView,
    AIChatMessageStreamView,
    AIHubView,
    AIToolConfirmView,
    AIToolExecuteView,
)

app_name = "ai"

urlpatterns = [
    path("chat/", AIChatIndexView.as_view(), name="chat_index"),
    path("chat/<uuid:external_id>/", AIChatDetailView.as_view(), name="chat_detail"),
    path(
        "chat/<uuid:external_id>/send/",
        AIChatMessageCreateView.as_view(),
        name="chat_send",
    ),
    path(
        "chat/<uuid:external_id>/stream/",
        AIChatMessageStreamView.as_view(),
        name="chat_stream",
    ),
    path("", AIHubView.as_view(), name="hub"),
    path(
        "gateway/tools/<str:tool_code>/execute/",
        AIToolExecuteView.as_view(),
        name="tool_execute",
    ),
    path(
        "gateway/pending/<uuid:token>/confirm/",
        AIToolConfirmView.as_view(),
        name="tool_confirm",
    ),
]
