from django.urls import path

from .views import (
    AIChatDeleteView,
    AIChatDetailView,
    AIChatGenerateTitleView,
    AIChatIndexView,
    AIChatMessageCreateView,
    AIChatMessageStreamView,
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
