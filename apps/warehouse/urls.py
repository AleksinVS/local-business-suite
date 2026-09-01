from django.urls import path

from . import views

app_name = "warehouse"
urlpatterns = [
    path("", views.StockOverviewView.as_view(), name="overview"),
    path("documents/", views.StockDocumentListView.as_view(), name="documents"),
    path("documents/new/", views.StockDocumentCreateView.as_view(), name="document_new"),
    path("documents/<int:pk>/", views.StockDocumentDetailView.as_view(), name="document_detail"),
    path("documents/<int:pk>/post/", views.post_document_action, name="document_post"),
    path("documents/<int:pk>/cancel/", views.cancel_document_action, name="document_cancel"),
    path("documents/<int:pk>/reverse/", views.reverse_document_action, name="document_reverse"),
    path("lots/", views.StockLotRegistrationView.as_view(), name="lots"),
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
