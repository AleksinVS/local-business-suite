from django.urls import path

from .views import (
    MedicalDeviceArchiveView,
    MedicalDeviceCreateView,
    MedicalDeviceDetailView,
    MedicalDeviceListView,
    MedicalDeviceUpdateView,
)

app_name = "inventory"

urlpatterns = [
    path("", MedicalDeviceListView.as_view(), name="list"),
    path("new/", MedicalDeviceCreateView.as_view(), name="create"),
    path("<int:pk>/", MedicalDeviceDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", MedicalDeviceUpdateView.as_view(), name="edit"),
    path("<int:pk>/archive/", MedicalDeviceArchiveView.as_view(), name="archive"),
]
