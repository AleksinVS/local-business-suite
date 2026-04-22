from django.urls import re_path

from .views import (
    WaitingListDashboardView,
    WaitingListEntryCreateView,
    WaitingListEntryDetailView,
    WaitingListEntryUpdateView,
    WaitingListTransitionView,
)

app_name = "waiting_list"

urlpatterns = [
    re_path(r"^/?$", WaitingListDashboardView.as_view(), name="dashboard"),
    re_path(r"^new/?$", WaitingListEntryCreateView.as_view(), name="create"),
    re_path(r"^(?P<pk>\d+)/?$", WaitingListEntryDetailView.as_view(), name="detail"),
    re_path(
        r"^(?P<pk>\d+)/edit/?$", WaitingListEntryUpdateView.as_view(), name="update"
    ),
    re_path(
        r"^(?P<pk>\d+)/transition/?$",
        WaitingListTransitionView.as_view(),
        name="transition",
    ),
]
