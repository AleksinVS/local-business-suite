from django.urls import path

from .views import (
    MedicalDeviceArchiveView,
    MedicalDeviceCreateView,
    MedicalDeviceListView,
    MedicalDeviceUpdateView,
)

app_name = "inventory"

urlpatterns = [
    path("", MedicalDeviceListView.as_view(), name="list"),
    path("new/", MedicalDeviceCreateView.as_view(), name="create"),
    path("<int:pk>/edit/", MedicalDeviceUpdateView.as_view(), name="edit"),
    path("<int:pk>/archive/", MedicalDeviceArchiveView.as_view(), name="archive"),
]
