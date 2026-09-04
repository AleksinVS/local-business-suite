from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.warehouse.forms import (
    FundingSourceForm,
    StockDocumentForm,
    StockDocumentLineFormSet,
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
    reverse_document,
    save_catalog_record,
    save_report_profile,
    save_storage_location,
    save_warehouse,
)
from apps.warehouse.runtime_settings import get_warehouse_runtime_settings
from apps.warehouse.report_views import paginate_queryset, report_view


def _has_scope(user, capability):
    return department_ids_for_warehouse_scope(user, capability) != set()


def _ui_flags(user):
    return {
        "can_view_warehouse": _has_scope(user, WAREHOUSE_VIEW_SCOPE),
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
        balances_queryset = visible_stock_balances_queryset(request.user).select_related(
            "department", "warehouse", "location", "item__unit", "funding_source"
        )
        search = request.GET.get("q", "").strip()[:100]
        if search:
            balances_queryset = balances_queryset.filter(
                Q(item__name__icontains=search)
                | Q(item__code__icontains=search)
                | Q(series__icontains=search)
                | Q(warehouse__name__icontains=search)
                | Q(location__code__icontains=search)
            )
        page = paginate_queryset(balances_queryset, request)
        balances = list(page.object_list)
        warning_days = get_warehouse_runtime_settings(request=request)["expiry_warning_days"]
        today = date.today()
        for balance in balances:
            balance.days_to_expiry = (
                (balance.expires_on - today).days if balance.expires_on else None
            )
            balance.expiry_warning = (
                balance.days_to_expiry is not None
                and balance.days_to_expiry <= max(warning_days)
            )
        query = request.GET.copy()
        query.pop("page", None)
        context = {
            "balances": balances,
            "expiry_warning_days": warning_days,
            "page_obj": page,
            "total": page.paginator.count,
            "query": query.urlencode(),
            "search": search,
        }
        context.update(_ui_flags(request.user))
        return render(request, "warehouse/overview.html", context)


class StockDocumentListView(WarehouseAccessMixin, View):
    def get(self, request):
        documents = visible_stock_documents_queryset(request.user).select_related(
            "department", "created_by", "posted_by"
        )
        search = request.GET.get("q", "").strip()[:100]
        if search:
            documents = documents.filter(
                Q(number__icontains=search)
                | Q(requirement_number__icontains=search)
                | Q(department__name__icontains=search)
            )
        status = request.GET.get("status", "").strip()
        if status in StockDocument.Status.values:
            documents = documents.filter(status=status)
        document_type = request.GET.get("document_type", "").strip()
        if document_type in StockDocument.DocumentType.values:
            documents = documents.filter(document_type=document_type)
        page = paginate_queryset(documents, request)
        query = request.GET.copy()
        query.pop("page", None)
        context = {
            "documents": page.object_list,
            "page_obj": page,
            "total": page.paginator.count,
            "query": query.urlencode(),
            "search": search,
            "selected_status": status,
            "selected_document_type": document_type,
            "status_choices": StockDocument.Status.choices,
            "document_type_choices": StockDocument.DocumentType.choices,
        }
        context.update(_ui_flags(request.user))
        return render(request, "warehouse/documents.html", context)


class StockDocumentDetailView(WarehouseAccessMixin, View):
    def get(self, request, pk):
        document = get_object_or_404(
            visible_stock_documents_queryset(request.user).prefetch_related(
                "lines__item", "lines__funding_source"
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


def _is_panel_request(request):
    return request.headers.get("HX-Request") == "true" or request.GET.get("panel") == "1"


def _document_editor_context(request, document, *, form=None, formset=None):
    document_type = (
        form.data.get("document_type") if form is not None and form.is_bound else None
    ) or document.document_type
    if form is None:
        form = StockDocumentForm(actor=request.user, instance=document)
    if formset is None:
        department = None
        if document.department_id:
            department = document.department
        formset = StockDocumentLineFormSet(
            instance=document,
            form_kwargs={"actor": request.user, "department": department, "document_type": document_type},
        )
    return {
        "form": form,
        "formset": formset,
        "document": document,
        "document_is_edit": bool(document.pk),
        "panel_mode": "edit" if document.pk else "create",
    }


def _render_document_editor(request, context, *, status=200, panel=False):
    template = "warehouse/partials/document_editor.html" if panel else "warehouse/document_form.html"
    return render(request, template, context, status=status)


def _document_success_response(request, document):
    if _is_panel_request(request):
        response = render(request, "warehouse/partials/document_success.html", {"document": document})
        response["HX-Trigger"] = '{"rightPanelFormSucceeded":{},"warehouseDocumentsChanged":{},"warehouseStockChanged":{}}'
        return response
    messages.success(request, "Складской документ сохранён.")
    return redirect("warehouse:document_detail", pk=document.pk)


def _idempotent_document(request, actor):
    raw = request.POST.get("idempotency_key", "").strip()
    if not raw:
        return None
    try:
        key = UUID(raw)
    except (ValueError, TypeError, AttributeError):
        return None
    return StockDocument.objects.filter(idempotency_key=key, created_by=actor).first()


def _posted_value(data, prefix, field):
    return str(data.get(f"{prefix}-{field}", "") or "").strip()


def _document_payload_matches(document, data):
    """Compare an immutable replay with the document stored by the server."""
    for field in ("department", "document_type", "operation_date", "number", "comment", "reason"):
        expected = getattr(document, f"{field}_id", "") if field == "department" else getattr(document, field, "")
        if str(expected or "").strip() != str(data.get(field, "") or "").strip():
            return False
    lines = list(document.lines.order_by("sequence", "id"))
    try:
        total = int(data.get("lines-TOTAL_FORMS", "0"))
    except (TypeError, ValueError):
        return False
    if total != len(lines):
        return False
    line_fields = (
        "item", "series", "expires_on", "incomplete_reason", "funding_source",
        "quantity", "source_location", "destination_location", "fefo_override_reason",
    )
    for index, line in enumerate(lines):
        prefix = f"lines-{index}"
        posted_id = _posted_value(data, prefix, "id")
        if posted_id and posted_id != str(line.pk):
            return False
        expected_values = {
            "item": line.item_id,
            "series": line.series,
            "expires_on": line.expires_on.isoformat() if line.expires_on else "",
            "incomplete_reason": line.incomplete_reason,
            "funding_source": line.funding_source_id,
            "quantity": line.quantity,
            "source_location": line.source_location_id,
            "destination_location": line.destination_location_id,
            "fefo_override_reason": line.fefo_override_reason,
        }
        for field in line_fields:
            posted = _posted_value(data, prefix, field)
            if field == "quantity":
                try:
                    if Decimal(str(expected_values[field])) != Decimal(posted):
                        return False
                except (InvalidOperation, TypeError, ValueError):
                    return False
                continue
            if str(expected_values[field] or "").strip() != posted:
                return False
    return True


class StockDocumentCreateView(WarehouseAccessMixin, View):
    capability = WAREHOUSE_OPERATE_SCOPE

    def get(self, request):
        document = StockDocument(created_by=request.user, idempotency_key=uuid4())
        return _render_document_editor(
            request,
            _document_editor_context(request, document),
            panel=_is_panel_request(request),
        )

    @transaction.atomic
    def post(self, request):
        existing = _idempotent_document(request, request.user)
        if existing is not None:
            if not _document_payload_matches(existing, request.POST):
                return HttpResponse("Повторный запрос изменён и отклонён.", status=409)
            if request.POST.get("action") == "post" and existing.status == StockDocument.Status.DRAFT:
                post_document(document_id=existing.pk, actor=request.user)
            return _document_success_response(request, existing)
        document = StockDocument(created_by=request.user, idempotency_key=_parse_idempotency_key(request.POST.get("idempotency_key")) or uuid4())
        form = StockDocumentForm(request.POST, actor=request.user, instance=document)
        document_type = request.POST.get("document_type", "")
        if form.is_valid():
            document = form.save(commit=False)
            formset = StockDocumentLineFormSet(
                request.POST,
                instance=document,
                form_kwargs={
                    "actor": request.user,
                    "department": document.department,
                    "document_type": document.document_type,
                },
            )
            if formset.is_valid():
                try:
                    with transaction.atomic():
                        document.save()
                except IntegrityError:
                    existing = _idempotent_document(request, request.user)
                    if existing is None:
                        raise
                    return _document_success_response(request, existing)
                formset.save()
                if request.POST.get("action") == "post":
                    try:
                        post_document(document_id=document.pk, actor=request.user)
                    except ValidationError as exc:
                        _attach_service_error(form, formset, exc)
                        return _render_document_editor(request, _document_editor_context(request, document, form=form, formset=formset), status=422 if _is_panel_request(request) else 400, panel=_is_panel_request(request))
                return _document_success_response(request, document)
        else:
            formset = StockDocumentLineFormSet(
                request.POST,
                instance=document,
                form_kwargs={"actor": request.user, "document_type": document_type},
            )
            formset.is_valid()
        context = _document_editor_context(request, document, form=form, formset=formset)
        return _render_document_editor(
            request, context, status=422 if _is_panel_request(request) else 400, panel=_is_panel_request(request)
        )


def _parse_idempotency_key(raw):
    try:
        return UUID(str(raw).strip()) if raw else None
    except (ValueError, TypeError, AttributeError):
        return None


def _attach_service_error(form, formset, error):
    """Keep entered rows visible when posting rejects a draft."""
    if hasattr(error, "message_dict"):
        line_sequence = getattr(error, "line_sequence", None)
        line_target = None
        if line_sequence is not None:
            line_target = next(
                (line_form for line_form in formset.forms
                 if line_form.instance.sequence == line_sequence),
                None,
            )
        for field, messages_for_field in error.message_dict.items():
            target = line_target or form
            target.add_error(field if field in target.fields else None, messages_for_field)
    else:
        form.add_error(None, error.messages if hasattr(error, "messages") else str(error))


class StockDocumentEditView(WarehouseAccessMixin, View):
    capability = WAREHOUSE_OPERATE_SCOPE

    def _document(self, request, pk):
        return get_object_or_404(
            visible_stock_documents_queryset(request.user),
            pk=pk,
            status=StockDocument.Status.DRAFT,
        )

    def get(self, request, pk):
        document = self._document(request, pk)
        return _render_document_editor(request, _document_editor_context(request, document), panel=_is_panel_request(request))

    @transaction.atomic
    def post(self, request, pk):
        document = get_object_or_404(visible_stock_documents_queryset(request.user), pk=pk)
        if document.status == StockDocument.Status.POSTED:
            if request.POST.get("action") == "post" and _document_payload_matches(document, request.POST):
                return _document_success_response(request, document)
            return HttpResponse("Проведённый документ нельзя изменить.", status=409)
        if document.status != StockDocument.Status.DRAFT:
            return HttpResponse("Документ недоступен для редактирования.", status=409)
        form = StockDocumentForm(request.POST, actor=request.user, instance=document)
        if form.is_valid():
            document = form.save(commit=False)
            formset = StockDocumentLineFormSet(
                request.POST,
                instance=document,
                form_kwargs={"actor": request.user, "department": document.department, "document_type": document.document_type},
            )
            if formset.is_valid():
                document.save()
                formset.save()
                if request.POST.get("action") == "post":
                    try:
                        post_document(document_id=document.pk, actor=request.user)
                    except ValidationError as exc:
                        _attach_service_error(form, formset, exc)
                        return _render_document_editor(request, _document_editor_context(request, document, form=form, formset=formset), status=422 if _is_panel_request(request) else 400, panel=_is_panel_request(request))
                if _is_panel_request(request):
                    response = render(request, "warehouse/partials/document_success.html", {"document": document})
                    response["HX-Trigger"] = '{"rightPanelFormSucceeded":{},"warehouseDocumentsChanged":{},"warehouseStockChanged":{}}'
                    return response
                return redirect("warehouse:document_detail", pk=document.pk)
        else:
            formset = StockDocumentLineFormSet(
                request.POST,
                instance=document,
                form_kwargs={"actor": request.user, "document_type": request.POST.get("document_type", "")},
            )
            formset.is_valid()
        return _render_document_editor(
            request,
            _document_editor_context(request, document, form=form, formset=formset),
            status=422 if _is_panel_request(request) else 400,
            panel=_is_panel_request(request),
        )


class StockDocumentPanelView(StockDocumentDetailView):
    def get(self, request, pk):
        document = get_object_or_404(
            visible_stock_documents_queryset(request.user).prefetch_related("lines__item", "lines__funding_source"),
            pk=pk,
        )
        context = {
            "document": document,
            "can_operate_document": warehouse_scope_allows_department(actor=request.user, capability=WAREHOUSE_OPERATE_SCOPE, department=document.department),
            "can_adjust_document": warehouse_scope_allows_department(actor=request.user, capability=WAREHOUSE_ADJUST_SCOPE, department=document.department),
            "panel_mode": "view",
        }
        return render(request, "warehouse/partials/document_detail_panel.html", context)


class _ScopedCrudView(WarehouseAccessMixin, View):
    title = ""
    form_class = None
    route_name = ""
    edit_route_name = ""
    search_fields = ()

    def get_queryset(self):
        raise NotImplementedError

    def save(self, cleaned_data, object_id=None):
        raise NotImplementedError

    def list_queryset(self, request):
        queryset = self.get_queryset()
        search = request.GET.get("q", "").strip()[:100]
        if search and self.search_fields:
            predicate = Q()
            for field in self.search_fields:
                predicate |= Q(**{f"{field}__icontains": search})
            queryset = queryset.filter(predicate)
        return queryset, search

    def list_context(self, request, *, form, instance):
        queryset, search = self.list_queryset(request)
        page = paginate_queryset(queryset, request)
        query = request.GET.copy()
        query.pop("page", None)
        return {
            "title": self.title,
            "form": form,
            "objects": page.object_list,
            "edit_object": instance,
            "edit_route_name": self.edit_route_name,
            "page_obj": page,
            "total": page.paginator.count,
            "search": search,
            "query": query.urlencode(),
        }

    def get(self, request, pk=None):
        instance = get_object_or_404(self.get_queryset(), pk=pk) if pk else None
        return render(request, "warehouse/crud.html", self.list_context(
            request,
            form=self.form_class(actor=request.user, instance=instance),
            instance=instance,
        ))

    def post(self, request, pk=None):
        instance = get_object_or_404(self.get_queryset(), pk=pk) if pk else None
        form = self.form_class(request.POST, actor=request.user, instance=instance)
        if form.is_valid():
            self.save(form.cleaned_data, object_id=pk)
            messages.success(request, "Изменения сохранены.")
            return redirect(self.route_name)
        return render(request, "warehouse/crud.html", self.list_context(
            request, form=form, instance=instance
        ), status=400)


class WarehouseListView(_ScopedCrudView):
    capability = WAREHOUSE_MANAGE_LOCATIONS_SCOPE
    title = "Склады"
    form_class = WarehouseForm
    route_name = "warehouse:warehouses"
    edit_route_name = "warehouse:warehouse_edit"
    search_fields = ("code", "name", "department__name")

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
    search_fields = ("code", "name", "warehouse__code", "warehouse__name")

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
    search_fields = ("name", "department__name", "signer_name")

    def get_queryset(self):
        return manageable_report_profiles_queryset(self.request.user).select_related("department")

    def save(self, cleaned_data, object_id=None):
        return save_report_profile(
            actor=self.request.user, cleaned_data=cleaned_data, profile_id=object_id
        )


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
        queryset = model.objects.all().order_by("name", "pk")
        search = request.GET.get("q", "").strip()[:100]
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        page = paginate_queryset(queryset, request)
        query = request.GET.copy()
        query.pop("page", None)
        return render(
            request,
            "warehouse/catalog.html",
            {
                "title": title,
                "kind": kind,
                "form": form_class(instance=instance, actor=request.user),
                "objects": page.object_list,
                "edit_object": instance,
                "catalog_navigation": _catalog_navigation(),
                "page_obj": page,
                "total": page.paginator.count,
                "search": search,
                "query": query.urlencode(),
            },
        )

    def post(self, request, kind, pk=None):
        model, form_class, title = self._definition(kind)
        instance = get_object_or_404(model, pk=pk) if pk else None
        form = form_class(request.POST, instance=instance, actor=request.user)
        if form.is_valid():
            save_catalog_record(
                actor=request.user,
                model=model,
                cleaned_data=form.cleaned_data,
                object_id=pk,
            )
            messages.success(request, "Запись каталога сохранена.")
            return redirect("warehouse:catalog", kind=kind)
        queryset = model.objects.all().order_by("name", "pk")
        search = request.GET.get("q", "").strip()[:100]
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        page = paginate_queryset(queryset, request)
        query = request.GET.copy()
        query.pop("page", None)
        return render(
            request,
            "warehouse/catalog.html",
            {
                "title": title,
                "kind": kind,
                "form": form,
                "objects": page.object_list,
                "edit_object": instance,
                "catalog_navigation": _catalog_navigation(),
                "page_obj": page,
                "total": page.paginator.count,
                "search": search,
                "query": query.urlencode(),
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
    return report_view(
        request,
        report_kind="expense",
        actor=request.user,
        department_ids=department_ids_for_warehouse_scope(
            request.user, WAREHOUSE_VIEW_SCOPE
        ),
    )


@login_required
def rack_card_report_view(request):
    return report_view(
        request,
        report_kind="rack-card",
        actor=request.user,
        department_ids=department_ids_for_warehouse_scope(
            request.user, WAREHOUSE_VIEW_SCOPE
        ),
    )


@login_required
def availability_report_view(request):
    return report_view(
        request,
        report_kind="availability",
        actor=request.user,
        department_ids=department_ids_for_warehouse_scope(
            request.user, WAREHOUSE_VIEW_SCOPE
        ),
    )
