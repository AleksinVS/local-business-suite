from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.warehouse.forms import (
    FundingSourceForm,
    StockDocumentForm,
    StockDocumentLineFormSet,
    StockLotRegistrationForm,
    StorageLocationForm,
    UnitOfMeasureForm,
    WarehouseForm,
    WarehouseItemCategoryForm,
    WarehouseItemForm,
    WarehouseReportProfileForm,
)
from apps.warehouse.models import (
    FundingSource,
    StockDocument,
    StockLot,
    UnitOfMeasure,
    WarehouseItem,
    WarehouseItemCategory,
    WarehouseReportProfile,
)
from apps.warehouse.policies import (
    WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
    WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
    WAREHOUSE_ADJUST_SCOPE,
    WAREHOUSE_OPERATE_SCOPE,
    WAREHOUSE_VIEW_SCOPE,
    can_manage_warehouse_catalog,
    department_ids_for_warehouse_scope,
    warehouse_scope_allows_department,
)
from apps.warehouse.reports import (
    build_department_availability,
    build_expense_report,
    build_rack_card,
    export_csv,
    export_xlsx,
)
from apps.warehouse.selectors import (
    manageable_location_warehouses_queryset,
    manageable_locations_queryset,
    manageable_report_profiles_queryset,
    visible_stock_balances_queryset,
    visible_stock_documents_queryset,
)
from apps.warehouse.services import (
    cancel_draft_document,
    post_document,
    register_stock_lot,
    reverse_document,
    save_catalog_record,
    save_report_profile,
    save_storage_location,
    save_warehouse,
)
from apps.warehouse.runtime_settings import get_warehouse_runtime_settings


def _has_scope(user, capability):
    return department_ids_for_warehouse_scope(user, capability) != set()


def _ui_flags(user):
    return {
        "can_operate_warehouse": _has_scope(user, WAREHOUSE_OPERATE_SCOPE),
        "can_adjust_warehouse": _has_scope(user, WAREHOUSE_ADJUST_SCOPE),
        "can_manage_warehouse_locations": _has_scope(
            user, WAREHOUSE_MANAGE_LOCATIONS_SCOPE
        ),
        "can_manage_warehouse_report_profiles": _has_scope(
            user, WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE
        ),
        "can_manage_warehouse_catalog": can_manage_warehouse_catalog(user),
    }


class WarehouseAccessMixin(LoginRequiredMixin):
    capability = WAREHOUSE_VIEW_SCOPE

    def scope_ids(self):
        ids = department_ids_for_warehouse_scope(self.request.user, self.capability)
        if ids == set():
            raise PermissionDenied("Раздел склада недоступен.")
        return ids

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.scope_ids()
        return super().dispatch(request, *args, **kwargs)


class StockOverviewView(WarehouseAccessMixin, View):
    def get(self, request):
        balances = list(visible_stock_balances_queryset(request.user).select_related(
            "department", "warehouse", "location", "lot__item__unit", "funding_source"
        )[:200])
        warning_days = get_warehouse_runtime_settings()["expiry_warning_days"]
        today = date.today()
        for balance in balances:
            balance.days_to_expiry = (
                (balance.lot.expires_on - today).days if balance.lot.expires_on else None
            )
            balance.expiry_warning = (
                balance.days_to_expiry is not None
                and balance.days_to_expiry <= max(warning_days)
            )
        context = {"balances": balances, "expiry_warning_days": warning_days}
        context.update(_ui_flags(request.user))
        return render(request, "warehouse/overview.html", context)


class StockDocumentListView(WarehouseAccessMixin, View):
    def get(self, request):
        documents = visible_stock_documents_queryset(request.user).select_related(
            "department", "created_by", "posted_by"
        )
        context = {"documents": documents}
        context.update(_ui_flags(request.user))
        return render(request, "warehouse/documents.html", context)


class StockDocumentDetailView(WarehouseAccessMixin, View):
    def get(self, request, pk):
        document = get_object_or_404(
            visible_stock_documents_queryset(request.user).prefetch_related(
                "lines__item", "lines__lot", "lines__funding_source"
            ),
            pk=pk,
        )
        context = {
            "document": document,
            "can_operate_document": warehouse_scope_allows_department(
                actor=request.user,
                capability=WAREHOUSE_OPERATE_SCOPE,
                department=document.department,
            ),
            "can_adjust_document": warehouse_scope_allows_department(
                actor=request.user,
                capability=WAREHOUSE_ADJUST_SCOPE,
                department=document.department,
            ),
        }
        return render(request, "warehouse/document_detail.html", context)


class StockDocumentCreateView(WarehouseAccessMixin, View):
    capability = WAREHOUSE_OPERATE_SCOPE

    def get(self, request):
        document = StockDocument(created_by=request.user)
        return render(
            request,
            "warehouse/document_form.html",
            {
                "form": StockDocumentForm(actor=request.user, instance=document),
                "formset": StockDocumentLineFormSet(
                    instance=document, form_kwargs={"actor": request.user}
                ),
            },
        )

    @transaction.atomic
    def post(self, request):
        document = StockDocument(created_by=request.user)
        form = StockDocumentForm(request.POST, actor=request.user, instance=document)
        if form.is_valid():
            document = form.save(commit=False)
            formset = StockDocumentLineFormSet(
                request.POST,
                instance=document,
                form_kwargs={"actor": request.user, "department": document.department},
            )
            if formset.is_valid():
                document.save()
                formset.save()
                messages.success(request, "Черновик складского документа сохранён.")
                return redirect("warehouse:document_detail", pk=document.pk)
        else:
            formset = StockDocumentLineFormSet(
                request.POST,
                instance=document,
                form_kwargs={"actor": request.user},
            )
            formset.is_valid()
        return render(
            request,
            "warehouse/document_form.html",
            {"form": form, "formset": formset},
            status=400,
        )


class _ScopedCrudView(WarehouseAccessMixin, View):
    title = ""
    form_class = None
    route_name = ""
    edit_route_name = ""

    def get_queryset(self):
        raise NotImplementedError

    def save(self, cleaned_data, object_id=None):
        raise NotImplementedError

    def get(self, request, pk=None):
        instance = get_object_or_404(self.get_queryset(), pk=pk) if pk else None
        return render(
            request,
            "warehouse/crud.html",
            {
                "title": self.title,
                "form": self.form_class(actor=request.user, instance=instance),
                "objects": self.get_queryset(),
                "edit_object": instance,
                "edit_route_name": self.edit_route_name,
            },
        )

    def post(self, request, pk=None):
        instance = get_object_or_404(self.get_queryset(), pk=pk) if pk else None
        form = self.form_class(request.POST, actor=request.user, instance=instance)
        if form.is_valid():
            self.save(form.cleaned_data, object_id=pk)
            messages.success(request, "Изменения сохранены.")
            return redirect(self.route_name)
        return render(
            request,
            "warehouse/crud.html",
            {
                "title": self.title,
                "form": form,
                "objects": self.get_queryset(),
                "edit_object": instance,
                "edit_route_name": self.edit_route_name,
            },
            status=400,
        )


class WarehouseListView(_ScopedCrudView):
    capability = WAREHOUSE_MANAGE_LOCATIONS_SCOPE
    title = "Склады"
    form_class = WarehouseForm
    route_name = "warehouse:warehouses"
    edit_route_name = "warehouse:warehouse_edit"

    def get_queryset(self):
        return manageable_location_warehouses_queryset(self.request.user).select_related("department")

    def save(self, cleaned_data, object_id=None):
        return save_warehouse(
            actor=self.request.user, cleaned_data=cleaned_data, warehouse_id=object_id
        )


class LocationListView(_ScopedCrudView):
    capability = WAREHOUSE_MANAGE_LOCATIONS_SCOPE
    title = "Адреса хранения"
    form_class = StorageLocationForm
    route_name = "warehouse:locations"
    edit_route_name = "warehouse:location_edit"

    def get_queryset(self):
        return manageable_locations_queryset(self.request.user).select_related(
            "warehouse__department"
        )

    def save(self, cleaned_data, object_id=None):
        return save_storage_location(
            actor=self.request.user, cleaned_data=cleaned_data, location_id=object_id
        )


class ReportProfileListView(_ScopedCrudView):
    capability = WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE
    title = "Профили складских отчётов"
    form_class = WarehouseReportProfileForm
    route_name = "warehouse:report_profiles"
    edit_route_name = "warehouse:report_profile_edit"

    def get_queryset(self):
        return manageable_report_profiles_queryset(self.request.user).select_related("department")

    def save(self, cleaned_data, object_id=None):
        return save_report_profile(
            actor=self.request.user, cleaned_data=cleaned_data, profile_id=object_id
        )


class StockLotRegistrationView(_ScopedCrudView):
    capability = WAREHOUSE_OPERATE_SCOPE
    title = "Регистрация партии"
    form_class = StockLotRegistrationForm
    route_name = "warehouse:lots"
    edit_route_name = ""

    def get_queryset(self):
        return StockLot.objects.select_related("item__unit").order_by(
            "item__name", "expires_on", "batch_number", "id"
        )[:200]

    def save(self, cleaned_data, object_id=None):
        if object_id is not None:
            raise PermissionDenied("Редактирование партии через этот экран запрещено.")
        return register_stock_lot(actor=self.request.user, cleaned_data=cleaned_data)


CATALOG_VIEWS = {
    "categories": (WarehouseItemCategory, WarehouseItemCategoryForm, "Категории"),
    "units": (UnitOfMeasure, UnitOfMeasureForm, "Единицы измерения"),
    "funding-sources": (FundingSource, FundingSourceForm, "Источники финансирования"),
    "items": (WarehouseItem, WarehouseItemForm, "Номенклатура"),
}


def _catalog_navigation():
    return [(kind, definition[2]) for kind, definition in CATALOG_VIEWS.items()]


class CatalogListView(LoginRequiredMixin, View):
    def _definition(self, kind):
        if kind not in CATALOG_VIEWS:
            raise PermissionDenied("Неизвестный раздел каталога.")
        return CATALOG_VIEWS[kind]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_manage_warehouse_catalog(request.user):
            raise PermissionDenied("Управление складским каталогом запрещено.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, kind, pk=None):
        model, form_class, title = self._definition(kind)
        instance = get_object_or_404(model, pk=pk) if pk else None
        return render(
            request,
            "warehouse/catalog.html",
            {
                "title": title,
                "kind": kind,
                "form": form_class(instance=instance),
                "objects": model.objects.all(),
                "edit_object": instance,
                "catalog_navigation": _catalog_navigation(),
            },
        )

    def post(self, request, kind, pk=None):
        model, form_class, title = self._definition(kind)
        instance = get_object_or_404(model, pk=pk) if pk else None
        form = form_class(request.POST, instance=instance)
        if form.is_valid():
            save_catalog_record(
                actor=request.user,
                model=model,
                cleaned_data=form.cleaned_data,
                object_id=pk,
            )
            messages.success(request, "Запись каталога сохранена.")
            return redirect("warehouse:catalog", kind=kind)
        return render(
            request,
            "warehouse/catalog.html",
            {
                "title": title,
                "kind": kind,
                "form": form,
                "objects": model.objects.all(),
                "edit_object": instance,
                "catalog_navigation": _catalog_navigation(),
            },
            status=400,
        )


@login_required
def post_document_action(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    post_document(document_id=pk, actor=request.user)
    messages.success(request, "Документ проведён.")
    return redirect("warehouse:document_detail", pk=pk)


@login_required
def cancel_document_action(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    cancel_draft_document(
        document_id=pk, actor=request.user, reason=request.POST.get("reason", "")
    )
    messages.success(request, "Черновик отменён.")
    return redirect("warehouse:document_detail", pk=pk)


@login_required
def reverse_document_action(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    reversal = reverse_document(
        source_document_id=pk,
        actor=request.user,
        operation_date=_parse_date(request.POST.get("operation_date"), date.today()),
        reason=request.POST.get("reason", ""),
    )
    messages.success(request, "Документ сторнирован.")
    return redirect("warehouse:document_detail", pk=reversal.pk)


def _parse_date(raw_value, fallback):
    if not raw_value:
        return fallback
    try:
        return date.fromisoformat(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Некорректная дата отчёта.") from exc


def _report_profile_metadata(department_ids, as_of):
    if department_ids is None or len(department_ids) != 1:
        return {}, None
    department_id = next(iter(department_ids))
    profile = (
        WarehouseReportProfile.objects.filter(
            department_id=department_id,
            is_active=True,
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


def _report_response(request, rows, *, title, filename, department_ids, as_of):
    metadata, profile = _report_profile_metadata(department_ids, as_of)
    fmt = request.GET.get("format", "html")
    if fmt == "csv":
        response = HttpResponse(
            export_csv(rows, metadata=metadata), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return response
    if fmt == "xlsx":
        response = HttpResponse(
            export_xlsx(rows, metadata=metadata),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
        return response
    if fmt != "html":
        return HttpResponseBadRequest("Неизвестный формат отчёта.")
    return render(
        request,
        "warehouse/report.html",
        {"rows": rows, "name": title, "report_profile": profile},
    )


def _report_scope(request):
    ids = department_ids_for_warehouse_scope(request.user, WAREHOUSE_VIEW_SCOPE)
    if ids == set():
        raise PermissionDenied("Отчёты склада недоступны.")
    raw_department_id = request.GET.get("department_id", "").strip()
    if not raw_department_id:
        return ids
    try:
        department_id = int(raw_department_id)
    except ValueError as exc:
        raise ValidationError("Некорректное подразделение отчёта.") from exc
    if ids is not None and department_id not in ids:
        raise PermissionDenied("Подразделение отчёта недоступно.")
    return {department_id}


@login_required
def expense_report_view(request):
    try:
        start = _parse_date(request.GET.get("start"), date.today().replace(day=1))
        end = _parse_date(request.GET.get("end"), date.today())
        department_ids = _report_scope(request)
        rows = build_expense_report(
            department_ids=department_ids, period_start=start, period_end=end
        )
    except (ValidationError, ValueError) as exc:
        return HttpResponseBadRequest(str(exc))
    return _report_response(
        request, rows, title="Расход за период", filename="warehouse-expense",
        department_ids=department_ids, as_of=end,
    )


@login_required
def rack_card_report_view(request):
    try:
        as_of = _parse_date(request.GET.get("as_of"), date.today())
        department_ids = _report_scope(request)
    except ValidationError as exc:
        return HttpResponseBadRequest(str(exc))
    rows = build_rack_card(department_ids=department_ids, as_of=as_of)
    return _report_response(
        request, rows, title="Стеллажная карта", filename="warehouse-rack-card",
        department_ids=department_ids, as_of=as_of,
    )


@login_required
def availability_report_view(request):
    try:
        as_of = _parse_date(request.GET.get("as_of"), date.today())
        department_ids = _report_scope(request)
    except ValidationError as exc:
        return HttpResponseBadRequest(str(exc))
    rows = build_department_availability(department_ids=department_ids, as_of=as_of)
    return _report_response(
        request, rows, title="Наличие", filename="warehouse-availability",
        department_ids=department_ids, as_of=as_of,
    )
