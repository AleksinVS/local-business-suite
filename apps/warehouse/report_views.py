from __future__ import annotations

from datetime import date

from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render

from .report_forms import WarehouseReportFilterForm, filter_report_rows
from .reports.datasets import ReportTooLargeError, build_department_availability, build_expense_report, build_rack_card
from .reports.exports import export_csv, export_xlsx, prepare_export_rows
from .runtime_settings import get_warehouse_runtime_settings
from .models import WarehouseReportProfile

HTML_REPORT_MAX_ROWS = 10_000


def report_view(request, *, report_kind, actor, department_ids):
    """Composable report endpoint; root URL wiring may delegate existing views here."""
    if department_ids == set():
        raise PermissionDenied("Отчёты склада недоступны.")
    period = report_kind == "expense"
    title, filename = (
        ("Расход за период", "warehouse-expense")
        if period
        else (("Стеллажная карта", "warehouse-rack-card") if report_kind == "rack-card" else ("Наличие", "warehouse-availability"))
    )
    settings_snapshot = get_warehouse_runtime_settings(request=request)
    form = WarehouseReportFilterForm(
        request.GET, actor=actor, period=period,
        expiry_warning_days=settings_snapshot["expiry_warning_days"],
    )
    if not form.is_valid():
        query = request.GET.copy()
        query.pop("page", None)
        query.pop("format", None)
        return render(
            request,
            "warehouse/report.html",
            {"rows": [], "name": title, "filter_form": form, "total": 0,
             "page_obj": None, "query": query.urlencode(), "report_profile": None},
            status=422,
        )
    data = form.cleaned_data
    scope = {data["department_id"]} if data.get("department_id") else department_ids
    try:
        if period:
            start, end = data.get("start") or date.today().replace(day=1), data.get("end") or date.today()
            rows = build_expense_report(department_ids=scope, period_start=start, period_end=end, max_rows=HTML_REPORT_MAX_ROWS)
            as_of = end
        else:
            as_of = data.get("as_of") or date.today()
            builder = build_rack_card if report_kind == "rack-card" else build_department_availability
            rows = builder(department_ids=scope, as_of=as_of, max_rows=HTML_REPORT_MAX_ROWS)
    except ReportTooLargeError as exc:
        return HttpResponse(
            f"{exc} Максимальный размер отчёта: {HTML_REPORT_MAX_ROWS:,} строк.",
            status=413,
            content_type="text/plain; charset=utf-8",
        )
    rows = filter_report_rows(rows, {**data, "as_of": as_of}, expiry_warning_days=settings_snapshot["expiry_warning_days"])
    metadata, report_profile = _report_profile_metadata(scope, as_of)
    if request.GET.get("format") == "csv":
        response = HttpResponse(export_csv(rows, metadata=metadata), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return response
    if request.GET.get("format") == "xlsx":
        response = HttpResponse(export_xlsx(rows, metadata=metadata), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
        return response
    paginator = Paginator(rows, 100)
    page = paginator.get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("format", None)
    return render(request, "warehouse/report.html", {"rows": prepare_export_rows(page.object_list), "name": title, "filter_form": form, "total": paginator.count, "page_obj": page, "query": query.urlencode(), "report_profile": report_profile})


def _report_profile_metadata(department_ids, as_of):
    if department_ids is None or len(department_ids) != 1:
        return {}, None
    profile = (
        WarehouseReportProfile.objects.filter(
            department_id=next(iter(department_ids)), is_active=True
        )
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=as_of))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of))
        .order_by("-valid_from", "-id")
        .first()
    )
    if profile is None:
        return {}, None
    metadata = {
        "Профиль": profile.name,
        "Гриф утверждения": profile.approval_label,
        "Должность подписанта": profile.signer_position,
        "Подписант": profile.signer_name,
        "Примечание": profile.footer_note,
    }
    return {key: value for key, value in metadata.items() if value}, profile


def paginate_queryset(queryset, request, *, per_page=50):
    """Shared bounded pagination helper for warehouse list integrations."""
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))
