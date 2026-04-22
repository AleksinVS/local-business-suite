from django.urls import re_path

from .views import (
    AIChatDetailView,
    AIChatIndexView,
    AIChatMessageCreateView,
    AIHubView,
    AIToolConfirmView,
    AIToolExecuteView,
)

app_name = "ai"

urlpatterns = [
    re_path(r"^chat/?$", AIChatIndexView.as_view(), name="chat_index"),
    re_path(
        r"^chat/(?P<external_id>[0-9a-f-]+)/?$",
        AIChatDetailView.as_view(),
        name="chat_detail",
    ),
    re_path(
        r"^chat/(?P<external_id>[0-9a-f-]+)/send/?$",
        AIChatMessageCreateView.as_view(),
        name="chat_send",
    ),
    re_path(r"^/?$", AIHubView.as_view(), name="hub"),
    re_path(
        r"^gateway/tools/(?P<tool_code>[^/]+)/execute/?$",
        AIToolExecuteView.as_view(),
        name="tool_execute",
    ),
    re_path(
        r"^gateway/pending/(?P<token>[0-9a-f-]+)/confirm/?$",
        AIToolConfirmView.as_view(),
        name="tool_confirm",
    ),
]
