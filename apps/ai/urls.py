from django.urls import path

from .views import (
    AIChatDeleteView,
    AIChatDetailView,
    AIChatGenerateTitleView,
    AIChatIndexView,
    AIChatMessageCreateView,
    AIChatMessageStreamView,
    AIUIAGUIRunProxyView,
    AIUIConfigView,
    AICopilotKitConfigView,
    AIPageContextUpdateView,
    AISidebarChatView,
    AISidebarChatClearView,
    AIChatUpdateModelView,
    AIChatUpdateTitleView,
    AIHubView,
    AISkillCatalogView,
    AISkillLoadView,
    AIToolConfirmView,
    AIToolExecuteView,
    SlashCommandCreateView,
    SlashCommandDeleteView,
    SlashCommandListView,
)

app_name = "ai"

urlpatterns = [
    path("chat/", AIChatIndexView.as_view(), name="chat_index"),
    path("chat/sidebar/", AISidebarChatView.as_view(), name="sidebar_chat"),
    path("chat/sidebar/clear/", AISidebarChatClearView.as_view(), name="sidebar_chat_clear"),
    path("ui/config/", AIUIConfigView.as_view(), name="ui_config"),
    path("ui/ag-ui/run/", AIUIAGUIRunProxyView.as_view(), name="ui_ag_ui_run"),
    path("chat/copilotkit/config/", AICopilotKitConfigView.as_view(), name="copilotkit_config"),
    path("context/window/", AIPageContextUpdateView.as_view(), name="page_context_update"),
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
    path(
        "chat/<uuid:external_id>/model/",
        AIChatUpdateModelView.as_view(),
        name="chat_update_model",
    ),
    path(
        "chat/<uuid:external_id>/title/",
        AIChatUpdateTitleView.as_view(),
        name="chat_update_title",
    ),
    path(
        "chat/<uuid:external_id>/generate-title/",
        AIChatGenerateTitleView.as_view(),
        name="chat_generate_title",
    ),
    path(
        "chat/<uuid:external_id>/delete/",
        AIChatDeleteView.as_view(),
        name="chat_delete",
    ),
    path(
        "chat/<uuid:external_id>/commands/",
        SlashCommandListView.as_view(),
        name="command_list",
    ),
    path(
        "chat/commands/create/",
        SlashCommandCreateView.as_view(),
        name="command_create",
    ),
    path(
        "chat/commands/<int:cmd_id>/delete/",
        SlashCommandDeleteView.as_view(),
        name="command_delete",
    ),
    path("", AIHubView.as_view(), name="hub"),
    path("gateway/skills/catalog/", AISkillCatalogView.as_view(), name="skill_catalog"),
    path("gateway/skills/<str:skill_id>/load/", AISkillLoadView.as_view(), name="skill_load"),
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
