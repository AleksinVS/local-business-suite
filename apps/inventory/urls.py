from django.urls import re_path

from .views import (
    MedicalDeviceArchiveView,
    MedicalDeviceCreateView,
    MedicalDeviceListView,
    MedicalDeviceUpdateView,
)

app_name = "inventory"

urlpatterns = [
    re_path(r"^/?$", MedicalDeviceListView.as_view(), name="list"),
    re_path(r"^new/?$", MedicalDeviceCreateView.as_view(), name="create"),
    re_path(r"^(?P<pk>\d+)/edit/?$", MedicalDeviceUpdateView.as_view(), name="edit"),
    re_path(
        r"^(?P<pk>\d+)/archive/?$", MedicalDeviceArchiveView.as_view(), name="archive"
    ),
]
