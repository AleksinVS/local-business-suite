from django.urls import path

from . import views

app_name = "filehub"

urlpatterns = [
    path("files/", views.MemoryFileUserViewsView.as_view(), name="user_file_views"),
    path("review/file-organization/", views.MemoryFileOrganizationView.as_view(), name="file_organization"),
    path(
        "review/file-organization/proposals/<int:pk>/action/",
        views.MemoryFileOrganizationProposalActionView.as_view(),
        name="file_organization_proposal_action",
    ),
]
