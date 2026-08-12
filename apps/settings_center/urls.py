from django.urls import path

from . import views

app_name = "settings_center"

urlpatterns = [
    path("", views.SettingsDashboardView.as_view(), name="dashboard"),
    path("workflow/transitions/", views.WorkflowTransitionMatrixView.as_view(), name="workflow_transitions"),
    path("workorders/status-colors/", views.WorkOrderStatusColorSettingsView.as_view(), name="workorder_status_colors"),
    path("boards/", views.BoardAccessListView.as_view(), name="board_access_list"),
    path("boards/<int:pk>/access/", views.BoardAccessView.as_view(), name="board_access"),
    path("access/roles/", views.RoleCatalogView.as_view(), name="role_catalog"),
    path("access/roles/<str:role_code>/", views.RoleDefinitionView.as_view(), name="role_definition"),
    path("settings/<path:setting_id>/", views.SettingDetailView.as_view(), name="setting_detail"),
    path("env/", views.EnvStatusView.as_view(), name="env_status"),
    path("env/propose/", views.EnvProposalView.as_view(), name="env_propose"),
    path("help/<path:setting_id>/ask/", views.HelpAskView.as_view(), name="help_ask"),
    path("help/<path:setting_id>/", views.HelpPanelView.as_view(), name="help_panel"),
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/new/", views.UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/edit/", views.UserUpdateView.as_view(), name="user_edit"),
    path(
        "users/<int:pk>/memory-groups/",
        views.MemoryGroupMembershipView.as_view(),
        name="memory_group_membership",
    ),
    path("users/<int:pk>/profile/", views.UserProfileUpdateView.as_view(), name="user_profile_edit"),
    path("users/<int:pk>/disable/", views.UserDisableView.as_view(), name="user_disable"),
    path("users/<int:pk>/ad-link/", views.UserADLinkView.as_view(), name="user_ad_link"),
]
