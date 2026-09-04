from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import uuid

from django import forms
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import DecimalValidator

from .models import (
    QUANTITY_DECIMAL_PLACES,
    QUANTITY_MAX_DIGITS,
    StockBalance,
    StorageLocation,
    Warehouse,
)
from .relocation import RelocationLineRequest, WarehouseRelocationError
from .relocation_selectors import (
    relocatable_stock_balances_queryset,
    relocation_destination_locations_queryset,
    relocation_destination_warehouses_queryset,
)


RELOCATION_SELECTION_SALT = "warehouse.relocation.selection.v1"
RELOCATION_SELECTION_MAX_AGE_SECONDS = 30 * 60


@dataclass(frozen=True)
class RelocationSelection:
    department_id: int
    idempotency_key: uuid.UUID
    lines: tuple[RelocationLineRequest, ...]
    balances: tuple[StockBalance, ...]


class RelocationDestinationForm(forms.Form):
    selection_token = forms.CharField(widget=forms.HiddenInput)
    operation_date = forms.DateField(
        label="Дата перемещения", widget=forms.DateInput(attrs={"type": "date"})
    )
    destination_warehouse = forms.ModelChoiceField(
        label="Склад назначения", queryset=Warehouse.objects.none()
    )
    destination_location = forms.ModelChoiceField(
        label="Адрес приёмки",
        queryset=StorageLocation.objects.none(),
        required=False,
    )

    def __init__(self, *args, actor, department_id: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.department_id = int(department_id)
        warehouses = relocation_destination_warehouses_queryset(
            actor, department_id=self.department_id
        )
        self.fields["destination_warehouse"].queryset = warehouses

        raw_warehouse_id = self.data.get("destination_warehouse") if self.is_bound else None
        if not raw_warehouse_id:
            initial_warehouse = self.initial.get("destination_warehouse")
            raw_warehouse_id = getattr(initial_warehouse, "pk", initial_warehouse)
        try:
            warehouse_id = int(raw_warehouse_id or 0)
        except (TypeError, ValueError):
            warehouse_id = 0
        if warehouse_id:
            self.fields["destination_location"].queryset = (
                relocation_destination_locations_queryset(
                    actor,
                    department_id=self.department_id,
                    warehouse_id=warehouse_id,
                )
            )

    def clean(self):
        cleaned = super().clean()
        warehouse = cleaned.get("destination_warehouse")
        location = cleaned.get("destination_location")
        if warehouse is None:
            return cleaned
        default = warehouse.default_receiving_location
        default_is_valid = bool(
            default
            and default.warehouse_id == warehouse.pk
            and default.is_active
            and default.purpose == StorageLocation.Purpose.AVAILABLE
        )
        if location is None and not default_is_valid:
            self.add_error(
                "destination_location",
                "У склада не задан однозначный адрес приёмки; выберите адрес.",
            )
        if location is not None and location.warehouse_id != warehouse.pk:
            self.add_error(
                "destination_location", "Адрес не относится к складу назначения."
            )
        return cleaned


def build_relocation_selection(*, actor, data) -> RelocationSelection:
    raw_ids = data.getlist("selected_balance") if hasattr(data, "getlist") else data.get(
        "selected_balance", []
    )
    if isinstance(raw_ids, (str, int)):
        raw_ids = [raw_ids]
    try:
        balance_ids = [int(value) for value in raw_ids]
    except (TypeError, ValueError) as exc:
        raise WarehouseRelocationError("Некорректный выбор остатка.") from exc
    if not balance_ids:
        raise WarehouseRelocationError("Выберите хотя бы одну строку остатка.")
    if any(value <= 0 for value in balance_ids) or len(set(balance_ids)) != len(balance_ids):
        raise WarehouseRelocationError("Выбранные строки остатка некорректны.")

    balances = tuple(
        relocatable_stock_balances_queryset(actor)
        .filter(pk__in=balance_ids)
        .select_related(
            "department", "warehouse", "location", "item__unit", "funding_source"
        )
        .order_by("pk")
    )
    if len(balances) != len(balance_ids):
        raise PermissionDenied("Одна или несколько выбранных строк недоступны.")
    department_ids = {balance.department_id for balance in balances}
    if len(department_ids) != 1:
        raise WarehouseRelocationError(
            "Одним документом можно перемещать остатки только одного подразделения."
        )

    lines = []
    for balance in balances:
        quantity = _positive_decimal(data.get(f"quantity_{balance.pk}"), "Количество")
        expected = _positive_decimal(
            data.get(f"expected_quantity_{balance.pk}"), "Ожидаемый остаток"
        )
        if expected != balance.quantity:
            raise WarehouseRelocationError(
                "Остатки изменились. Обновите список и повторите операцию."
            )
        if quantity > balance.quantity:
            raise WarehouseRelocationError(
                f"Для строки {balance.pk} указано больше доступного остатка."
            )
        lines.append(
            RelocationLineRequest(
                balance_id=balance.pk,
                quantity=quantity,
                expected_quantity=expected,
            )
        )
    return RelocationSelection(
        department_id=next(iter(department_ids)),
        idempotency_key=new_relocation_idempotency_key(),
        lines=tuple(lines),
        balances=balances,
    )


def dump_relocation_selection(selection: RelocationSelection) -> str:
    try:
        command_key = uuid.UUID(str(selection.idempotency_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise WarehouseRelocationError("Некорректный ключ операции.") from exc
    return signing.dumps(
        {
            "department_id": selection.department_id,
            "idempotency_key": str(command_key),
            "lines": [
                {
                    "balance_id": line.balance_id,
                    "quantity": format(
                        _positive_decimal(line.quantity, "Количество"), "f"
                    ),
                    "expected_quantity": format(
                        _positive_decimal(
                            line.expected_quantity, "Ожидаемый остаток"
                        ),
                        "f",
                    ),
                }
                for line in selection.lines
            ],
        },
        salt=RELOCATION_SELECTION_SALT,
        compress=True,
    )


def load_relocation_selection(
    token: str,
) -> tuple[int, tuple[RelocationLineRequest, ...], uuid.UUID]:
    try:
        payload = signing.loads(
            token,
            salt=RELOCATION_SELECTION_SALT,
            max_age=RELOCATION_SELECTION_MAX_AGE_SECONDS,
        )
        department_id = int(payload["department_id"])
        idempotency_key = uuid.UUID(str(payload["idempotency_key"]))
        lines = tuple(
            RelocationLineRequest(
                balance_id=int(item["balance_id"]),
                quantity=_positive_decimal(item["quantity"], "Количество"),
                expected_quantity=_positive_decimal(
                    item["expected_quantity"], "Ожидаемый остаток"
                ),
            )
            for item in payload["lines"]
        )
    except (signing.BadSignature, KeyError, TypeError, ValueError, ValidationError) as exc:
        raise WarehouseRelocationError(
            "Выбор для перемещения устарел или повреждён. Повторите отбор."
        ) from exc
    if department_id <= 0 or not lines:
        raise WarehouseRelocationError(
            "Выбор для перемещения устарел или повреждён. Повторите отбор."
        )
    return department_id, lines, idempotency_key


def new_relocation_idempotency_key() -> uuid.UUID:
    return uuid.uuid4()


def _positive_decimal(value, label: str) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WarehouseRelocationError(f"{label}: некорректное значение.") from exc
    if not normalized.is_finite() or normalized <= 0:
        raise WarehouseRelocationError(f"{label} должно быть больше нуля.")
    exponent = normalized.as_tuple().exponent
    if not isinstance(exponent, int) or abs(exponent) > 64:
        raise WarehouseRelocationError(f"{label}: значение выходит за допустимые пределы.")
    try:
        DecimalValidator(
            max_digits=QUANTITY_MAX_DIGITS,
            decimal_places=QUANTITY_DECIMAL_PLACES,
        )(normalized)
    except ValidationError as exc:
        raise WarehouseRelocationError(
            f"{label}: не более {QUANTITY_MAX_DIGITS} цифр, "
            f"из них {QUANTITY_DECIMAL_PLACES} после запятой."
        ) from exc
    return normalized
