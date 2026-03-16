from django.urls import path

from .views import MedicalDeviceCreateView, MedicalDeviceListView

app_name = "inventory"

urlpatterns = [
    path("", MedicalDeviceListView.as_view(), name="list"),
    path("new/", MedicalDeviceCreateView.as_view(), name="create"),
]
