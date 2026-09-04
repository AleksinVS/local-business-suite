from django.urls import path

from apps.core.autocomplete import AutocompleteView

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
    path("autocomplete/departments/", AutocompleteView.as_view(provider_code="inventory.department"), name="department_options"),
    path("autocomplete/device-name/", AutocompleteView.as_view(provider_code="inventory.device_name"), name="device_name_options"),
    path("autocomplete/manufacturers/", AutocompleteView.as_view(provider_code="inventory.manufacturer"), name="manufacturer_options"),
    path("autocomplete/countries/", AutocompleteView.as_view(provider_code="inventory.production_country"), name="country_options"),
    path("autocomplete/models/", AutocompleteView.as_view(provider_code="inventory.model"), name="model_options"),
    path("autocomplete/addresses/", AutocompleteView.as_view(provider_code="inventory.address"), name="address_options"),
    path("autocomplete/locations/", AutocompleteView.as_view(provider_code="inventory.location"), name="location_options"),
    path("new/", MedicalDeviceCreateView.as_view(), name="create"),
    path("<int:pk>/", MedicalDeviceDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", MedicalDeviceUpdateView.as_view(), name="edit"),
    path("<int:pk>/archive/", MedicalDeviceArchiveView.as_view(), name="archive"),
]
