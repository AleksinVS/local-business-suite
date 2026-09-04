from django.urls import path

from apps.core.autocomplete import AutocompleteView

from . import views

app_name = "filehub"

urlpatterns = [
    path("autocomplete/files/", AutocompleteView.as_view(provider_code="filehub.file_object"), name="file_object_options"),
    path("files/", views.MemoryFileUserViewsView.as_view(), name="user_file_views"),
    path("review/file-organization/", views.MemoryFileOrganizationView.as_view(), name="file_organization"),
    path(
        "review/file-organization/proposals/<int:pk>/action/",
        views.MemoryFileOrganizationProposalActionView.as_view(),
        name="file_organization_proposal_action",
    ),
]
