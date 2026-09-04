from django.urls import path

from apps.core.autocomplete import AutocompleteView

from . import relocation_views, views

app_name = "warehouse"
urlpatterns = [
    path("", views.StockOverviewView.as_view(), name="overview"),
    path("stock/", relocation_views.relocation_stock_list_view, name="stock"),
    path(
        "relocations/panel/",
        relocation_views.relocation_panel_view,
        name="relocation_panel",
    ),
    path(
        "relocations/",
        relocation_views.relocation_create_view,
        name="relocation_create",
    ),
    path(
        "relocations/autocomplete/destinations/",
        relocation_views.RelocationDestinationAutocompleteView.as_view(),
        name="relocation_destination_autocomplete",
    ),
    path(
        "relocations/autocomplete/locations/",
        relocation_views.RelocationLocationAutocompleteView.as_view(),
        name="relocation_location_autocomplete",
    ),
    path("documents/", views.StockDocumentListView.as_view(), name="documents"),
    path("autocomplete/department/", AutocompleteView.as_view(provider_code="warehouse.department"), name="autocomplete_department"),
    path("autocomplete/item/", AutocompleteView.as_view(provider_code="warehouse.item"), name="autocomplete_item"),
    path("autocomplete/series/", AutocompleteView.as_view(provider_code="warehouse.series"), name="autocomplete_series"),
    path("autocomplete/source/", AutocompleteView.as_view(provider_code="warehouse.source"), name="autocomplete_source"),
    path("autocomplete/location/", AutocompleteView.as_view(provider_code="warehouse.location"), name="autocomplete_location"),
    path("autocomplete/report-department/", AutocompleteView.as_view(provider_code="warehouse.report_department"), name="autocomplete_report_department"),
    path("autocomplete/stock-department/", AutocompleteView.as_view(provider_code="warehouse.stock_department"), name="autocomplete_stock_department"),
    path("autocomplete/report-profile-department/", AutocompleteView.as_view(provider_code="warehouse.report_profile_department"), name="autocomplete_report_profile_department"),
    path("autocomplete/manage-department/", AutocompleteView.as_view(provider_code="warehouse.manage_department"), name="autocomplete_manage_department"),
    path("autocomplete/stock-warehouse/", AutocompleteView.as_view(provider_code="warehouse.stock_warehouse"), name="autocomplete_stock_warehouse"),
    path("autocomplete/stock-location/", AutocompleteView.as_view(provider_code="warehouse.stock_location"), name="autocomplete_stock_location"),
    path("autocomplete/stock-item/", AutocompleteView.as_view(provider_code="warehouse.stock_item"), name="autocomplete_stock_item"),
    path("autocomplete/stock-category/", AutocompleteView.as_view(provider_code="warehouse.stock_category"), name="autocomplete_stock_category"),
    path("autocomplete/stock-source/", AutocompleteView.as_view(provider_code="warehouse.stock_source"), name="autocomplete_stock_source"),
    path("autocomplete/manage-warehouse/", AutocompleteView.as_view(provider_code="warehouse.manage_warehouse"), name="autocomplete_manage_warehouse"),
    path("autocomplete/manage-location/", AutocompleteView.as_view(provider_code="warehouse.manage_location"), name="autocomplete_manage_location"),
    path("autocomplete/catalog-category/", AutocompleteView.as_view(provider_code="warehouse.catalog_category"), name="autocomplete_catalog_category"),
    path("autocomplete/catalog-unit/", AutocompleteView.as_view(provider_code="warehouse.catalog_unit"), name="autocomplete_catalog_unit"),
    path("documents/new/", views.StockDocumentCreateView.as_view(), name="document_new"),
    path("documents/new/panel/", views.StockDocumentCreateView.as_view(), name="document_new_panel"),
    path("documents/<int:pk>/", views.StockDocumentDetailView.as_view(), name="document_detail"),
    path("documents/<int:pk>/panel/", views.StockDocumentPanelView.as_view(), name="document_detail_panel"),
    path("documents/<int:pk>/edit/panel/", views.StockDocumentEditView.as_view(), name="document_edit_panel"),
    path("documents/<int:pk>/post/", views.post_document_action, name="document_post"),
    path("documents/<int:pk>/cancel/", views.cancel_document_action, name="document_cancel"),
    path("documents/<int:pk>/reverse/", views.reverse_document_action, name="document_reverse"),
    path("reports/expense/", views.expense_report_view, name="report_expense"),
    path("reports/rack-card/", views.rack_card_report_view, name="report_rack_card"),
    path("reports/availability/", views.availability_report_view, name="report_availability"),
    path("warehouses/", views.WarehouseListView.as_view(), name="warehouses"),
    path("warehouses/<int:pk>/", views.WarehouseListView.as_view(), name="warehouse_edit"),
    path("locations/", views.LocationListView.as_view(), name="locations"),
    path("locations/<int:pk>/", views.LocationListView.as_view(), name="location_edit"),
    path("report-profiles/", views.ReportProfileListView.as_view(), name="report_profiles"),
    path("report-profiles/<int:pk>/", views.ReportProfileListView.as_view(), name="report_profile_edit"),
    path("catalog/<slug:kind>/", views.CatalogListView.as_view(), name="catalog"),
    path("catalog/<slug:kind>/<int:pk>/", views.CatalogListView.as_view(), name="catalog_edit"),
]
