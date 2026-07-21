from django.urls import path

from .views import (
    WaitingListDashboardView,
    WaitingListEntryCreateView,
    WaitingListEntryDetailView,
    WaitingListEntryUpdateView,
    WaitingListTransitionView,
)

app_name = "waiting_list"

urlpatterns = [
    path("", WaitingListDashboardView.as_view(), name="dashboard"),
    path("new/", WaitingListEntryCreateView.as_view(), name="create"),
    path("<int:pk>/", WaitingListEntryDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", WaitingListEntryUpdateView.as_view(), name="update"),
    path(
        "<int:pk>/transition/", WaitingListTransitionView.as_view(), name="transition"
    ),
]
