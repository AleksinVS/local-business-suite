from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseNotAllowed
from django.shortcuts import render
from django.utils import timezone

from apps.core.autocomplete import AutocompleteView
from .policies import (
    WAREHOUSE_OPERATE_SCOPE,
    WAREHOUSE_VIEW_SCOPE,
    department_ids_for_warehouse_scope,
)

from .relocation import create_and_post_relocation
from .relocation_forms import (
    RelocationDestinationForm,
    build_relocation_selection,
    dump_relocation_selection,
    load_relocation_selection,
)
from .relocation_selectors import (
    paginated_visible_stock_balances,
    register_relocation_autocomplete_providers,
    relocatable_stock_balances_queryset,
    sanitized_stock_filter_query,
    stock_filter_options,
)


register_relocation_autocomplete_providers()


class RelocationDestinationAutocompleteView(AutocompleteView):
    provider_code = "warehouse.relocation_destination"


class RelocationLocationAutocompleteView(AutocompleteView):
    provider_code = "warehouse.relocation_location"


@login_required
def relocation_stock_list_view(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    view_ids = department_ids_for_warehouse_scope(
        request.user, WAREHOUSE_VIEW_SCOPE
    )
    if view_ids == set():
        raise PermissionDenied("Раздел склада недоступен.")
    operate_ids = department_ids_for_warehouse_scope(
        request.user, WAREHOUSE_OPERATE_SCOPE
    )
    page = paginated_visible_stock_balances(request.user, request.GET)
    for balance in page.object_list:
        balance.can_relocate = operate_ids is None or balance.department_id in operate_ids
    can_relocate = any(balance.can_relocate for balance in page.object_list)
    filter_options = stock_filter_options(request.user, request.GET, operate=False)
    selected_ids = {
        key: _positive_int(request.GET.get(key))
        for key in ("department_id", "warehouse_id", "location_id", "category_id", "funding_source_id", "item_id")
    }
    selected_filter_labels = {
        "department_id": _selected_choice(filter_options["departments"], selected_ids["department_id"]),
        "warehouse_id": _selected_choice(filter_options["warehouses"], selected_ids["warehouse_id"]),
        "location_id": _selected_choice(filter_options["locations"], selected_ids["location_id"]),
        "category_id": _selected_choice(filter_options["categories"], selected_ids["category_id"]),
        "funding_source_id": _selected_choice(filter_options["funding_sources"], selected_ids["funding_source_id"]),
        "item_id": _selected_choice(
            filter_options["items"] if "items" in filter_options else (), selected_ids["item_id"]
        ),
    }
    return render(
        request,
        "warehouse/relocation/stock_list.html",
        {
            "page": page,
            "filters": request.GET,
            "filter_options": filter_options,
            "selected_filter_labels": selected_filter_labels,
            "pagination_query": sanitized_stock_filter_query(request.GET),
            "can_relocate": can_relocate,
            "relocation_panel_url": "/warehouse/relocations/panel/",
        },
    )


@login_required
def relocation_panel_view(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        selection = build_relocation_selection(actor=request.user, data=request.POST)
    except PermissionDenied:
        raise
    except ValidationError as exc:
        return _render_selection_error(request, exc)

    token = dump_relocation_selection(selection)
    form = RelocationDestinationForm(
        actor=request.user,
        department_id=selection.department_id,
        initial={
            "selection_token": token,
            "operation_date": timezone.localdate(),
        },
    )
    return _render_panel(
        request,
        form=form,
        balances=selection.balances,
        department_id=selection.department_id,
        lines=selection.lines,
    )


@login_required
def relocation_create_view(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    token = request.POST.get("selection_token", "")
    try:
        department_id, lines, command_key = load_relocation_selection(token)
    except ValidationError as exc:
        return _render_selection_error(request, exc)

    form = RelocationDestinationForm(
        request.POST,
        actor=request.user,
        department_id=department_id,
    )
    if form.is_valid():
        try:
            document = create_and_post_relocation(
                actor=request.user,
                lines=lines,
                destination_warehouse_id=form.cleaned_data[
                    "destination_warehouse"
                ].pk,
                destination_location_id=(
                    form.cleaned_data["destination_location"].pk
                    if form.cleaned_data.get("destination_location")
                    else None
                ),
                operation_date=form.cleaned_data["operation_date"],
                idempotency_key=command_key,
            )
        except PermissionDenied:
            raise
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            response = render(
                request,
                "warehouse/relocation/success.html",
                {"document": document},
            )
            response["HX-Trigger"] = json.dumps(
                {
                    "warehouseDocumentsChanged": {"documentId": document.pk},
                    "warehouseStockChanged": {"documentId": document.pk},
                    "rightPanelClose": {},
                    "rightPanelFormSucceeded": {"documentId": document.pk},
                },
                ensure_ascii=False,
            )
            return response

    balances = _selection_balances(request.user, lines)
    return _render_panel(
        request,
        form=form,
        balances=balances,
        department_id=department_id,
        lines=lines,
        status=422,
    )


def _selection_balances(actor, lines):
    balance_ids = [line.balance_id for line in lines]
    return tuple(
        relocatable_stock_balances_queryset(actor)
        .filter(pk__in=balance_ids)
        .select_related(
            "department", "warehouse", "location", "item__unit", "funding_source"
        )
        .order_by("pk")
    )


def _render_panel(
    request, *, form, balances, department_id, lines, status: int = 200
):
    requested_by_id = {line.balance_id: line for line in lines}
    rows = [
        {"balance": balance, "requested": requested_by_id.get(balance.pk)}
        for balance in balances
    ]
    selected_warehouse = _selected_choice(
        form.fields["destination_warehouse"].queryset,
        form["destination_warehouse"].value(),
    )
    selected_location = _selected_choice(
        form.fields["destination_location"].queryset,
        form["destination_location"].value(),
    )
    response = render(
        request,
        "warehouse/relocation/panel.html",
        {
            "form": form,
            "rows": rows,
            "department_id": department_id,
            "selected_warehouse_label": (
                selected_warehouse.name if selected_warehouse else ""
            ),
            "selected_location_label": (
                str(selected_location) if selected_location else ""
            ),
            "selected_warehouse_has_default": bool(
                selected_warehouse
                and selected_warehouse.default_receiving_location_id
                and selected_warehouse.default_receiving_location
                and selected_warehouse.default_receiving_location.is_active
                and selected_warehouse.default_receiving_location.purpose == "available"
            ),
            "relocation_save_url": "/warehouse/relocations/",
            "destination_autocomplete_url": (
                "/warehouse/relocations/autocomplete/destinations/"
            ),
            "location_autocomplete_url": (
                "/warehouse/relocations/autocomplete/locations/"
            ),
        },
        status=status,
    )
    response["HX-Trigger-After-Swap"] = json.dumps(
        {"warehouseRelocationPanelReady": {}}, ensure_ascii=False
    )
    return response


def _selected_choice(queryset, value):
    try:
        object_id = int(value or 0)
    except (TypeError, ValueError):
        return None
    if not object_id:
        return None
    return queryset.filter(pk=object_id).first()


def _positive_int(value):
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _render_selection_error(request, exc: ValidationError):
    return render(
        request,
        "warehouse/relocation/error.html",
        {"error": _validation_text(exc)},
        status=422,
    )


def _add_service_error(form, exc: ValidationError):
    if hasattr(exc, "message_dict"):
        for field, messages in exc.message_dict.items():
            target = field if field in form.fields else None
            for message in messages:
                form.add_error(target, message)
        return
    for message in exc.messages:
        form.add_error(None, message)


def _validation_text(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        return " ".join(
            message
            for messages in exc.message_dict.values()
            for message in messages
        )
    return " ".join(exc.messages)
