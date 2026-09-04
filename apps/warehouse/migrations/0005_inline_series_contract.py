from collections import defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError


EXPAND_ACTION = "inline_series.migration_expand"
SWITCH_ACTION = "inline_series.migration_switch"
CONTRACT_ACTION = "inline_series.migration_contract"


def _serialized_key(key):
    department_id, warehouse_id, location_id, item_id, series_key, expires_on, source_id = key
    return [
        department_id,
        warehouse_id,
        location_id,
        item_id,
        series_key,
        expires_on.isoformat() if expires_on else None,
        source_id,
    ]


def _projection_checksum(totals):
    ordered = sorted(totals, key=_projection_sort_key)
    payload = [
        [*_serialized_key(key), format(totals[key], "f")]
        for key in ordered
        if totals[key]
    ]
    return sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _projection_sort_key(key):
    (
        department_id,
        warehouse_id,
        location_id,
        item_id,
        series_key,
        expires_on,
        source_id,
    ) = key
    return (
        department_id,
        warehouse_id,
        location_id,
        item_id,
        series_key,
        expires_on is None,
        expires_on or date.max,
        source_id,
    )


def _row_checksum(queryset, fields):
    digest = sha256()
    count = 0
    for row in queryset.order_by("id").values_list(*fields).iterator():
        serializable = [
            value.isoformat()
            if hasattr(value, "isoformat")
            else format(value, "f")
            if isinstance(value, Decimal)
            else value
            for value in row
        ]
        digest.update(
            json.dumps(
                serializable, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        )
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def verify_before_contract(apps, schema_editor):
    StockDocumentLine = apps.get_model("warehouse", "StockDocumentLine")
    StockEntry = apps.get_model("warehouse", "StockEntry")
    StockBalance = apps.get_model("warehouse", "StockBalance")
    WarehouseAuditEvent = apps.get_model("warehouse", "WarehouseAuditEvent")

    expand = WarehouseAuditEvent.objects.filter(
        action=EXPAND_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="expand",
    ).order_by("-id").first()
    switch = WarehouseAuditEvent.objects.filter(
        action=SWITCH_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="switch",
    ).order_by("-id").first()
    if expand is None or switch is None:
        raise RuntimeError("Нет обеих контрольных точек expand/switch; contract запрещён.")

    entry_fields = (
        "id",
        "document_id",
        "document_line_id",
        "department_id",
        "warehouse_id",
        "location_id",
        "item_id",
        "series",
        "series_key",
        "expires_on",
        "incomplete_reason",
        "unit_id",
        "funding_source_id",
        "quantity",
        "operation_date",
    )
    line_fields = (
        "id",
        "document_id",
        "sequence",
        "item_id",
        "series",
        "series_key",
        "expires_on",
        "incomplete_reason",
        "funding_source_id",
        "quantity",
        "source_location_id",
        "destination_location_id",
    )
    entry_count, entry_checksum = _row_checksum(StockEntry.objects.all(), entry_fields)
    line_count, line_checksum = _row_checksum(StockDocumentLine.objects.all(), line_fields)
    for checkpoint in (expand, switch):
        if (
            checkpoint.summary.get("entry_count") != entry_count
            or checkpoint.summary.get("entry_checksum") != entry_checksum
        ):
            raise RuntimeError("Журнал изменился после контрольной точки; contract остановлен.")
    if (
        expand.summary.get("line_count") != line_count
        or expand.summary.get("line_checksum") != line_checksum
    ):
        raise RuntimeError("Строки документов изменились после backfill; contract остановлен.")

    expiries = defaultdict(set)
    expected = defaultdict(Decimal)
    for entry in StockEntry.objects.all().iterator():
        if entry.item_id is None or entry.series is None or entry.series_key is None:
            raise RuntimeError("Журнал содержит незаполненные inline-поля.")
        if entry.series_key:
            expiries[(entry.item_id, entry.series_key)].add(entry.expires_on)
        expected[
            (
                entry.department_id,
                entry.warehouse_id,
                entry.location_id,
                entry.item_id,
                entry.series_key,
                entry.expires_on,
                entry.funding_source_id,
            )
        ] += entry.quantity
    conflicts = [key for key, values in expiries.items() if len(values) > 1]
    if conflicts:
        raise RuntimeError("Журнал содержит конфликтующие сроки одной серии; contract запрещён.")

    actual = defaultdict(Decimal)
    for balance in StockBalance.objects.all().iterator():
        if balance.item_id is None or balance.series is None or balance.series_key is None:
            raise RuntimeError("Проекция содержит незаполненные inline-поля.")
        actual[
            (
                balance.department_id,
                balance.warehouse_id,
                balance.location_id,
                balance.item_id,
                balance.series_key,
                balance.expires_on,
                balance.funding_source_id,
            )
        ] += balance.quantity
    expected_nonzero = {key: value for key, value in expected.items() if value}
    actual_nonzero = {key: value for key, value in actual.items() if value}
    if expected_nonzero != actual_nonzero:
        raise RuntimeError("Проекция расходится с журналом; contract запрещён.")
    projection_checksum = _projection_checksum(expected)
    if projection_checksum != switch.summary.get("projection_checksum"):
        raise RuntimeError("Контрольная сумма проекции не совпадает со switch-точкой.")

    # A non-empty production ledger requires an explicit, actor-attributed
    # reconciliation between the reversible switch and destructive contract
    # steps.  Empty databases remain bootstrap-friendly for tests/new installs.
    if entry_count or line_count or StockBalance.objects.exists():
        operator_checkpoint = WarehouseAuditEvent.objects.filter(
            action="inline_series.reconciled",
            object_type="WarehouseInlineSeriesMigration",
            object_id="all",
            department_id__isnull=True,
            actor_id__isnull=False,
        ).order_by("-id").first()
        if operator_checkpoint is None:
            raise RuntimeError(
                "Перед contract-шагом выполните `warehouse_reconcile_inline_series "
                "--actor <superuser> --record-checkpoint` на миграции 0004."
            )
        actor = operator_checkpoint.actor
        if not actor.is_active or not actor.is_superuser:
            raise RuntimeError("Контрольную сверку перед contract должен выполнить superuser.")
        operator_summary = operator_checkpoint.summary or {}
        if (
            operator_summary.get("entry_count") != entry_count
            or operator_summary.get("journal_checksum") != entry_checksum
            or operator_summary.get("expected_projection_checksum") != projection_checksum
            or operator_summary.get("actual_projection_checksum") != projection_checksum
            or not operator_summary.get("ok")
        ):
            raise RuntimeError(
                "Контрольная сверка устарела или не совпадает с журналом; повторите команду."
            )

    WarehouseAuditEvent.objects.create(
        actor_id=None,
        department_id=None,
        action=CONTRACT_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="contract",
        reason="StockLot удаляется после успешной контрольной сверки",
        summary={
            "version": 1,
            "entry_count": entry_count,
            "entry_checksum": entry_checksum,
            "line_count": line_count,
            "line_checksum": line_checksum,
            "projection_checksum": projection_checksum,
            "balance_count": StockBalance.objects.count(),
        },
    )


def irreversible_contract(apps, schema_editor):
    raise IrreversibleError(
        "Удаление StockLot является подтверждённым contract-шагом. "
        "Для отката восстановите резервную копию либо остановитесь на миграции 0004."
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0004_inline_series_switch_projection")]

    operations = [
        migrations.RunPython(verify_before_contract, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name="stockentry",
            name="warehouse_s_locatio_d33d86_idx",
        ),
        migrations.RemoveIndex(
            model_name="stockbalance",
            name="warehouse_s_lot_id_0d446e_idx",
        ),
        migrations.RemoveField(model_name="stockdocumentline", name="lot"),
        migrations.RemoveField(model_name="stockentry", name="lot"),
        migrations.RemoveField(model_name="stockbalance", name="lot"),
        migrations.DeleteModel(name="StockLot"),
        migrations.AlterModelOptions(
            name="stockbalance",
            options={
                "ordering": [
                    "department",
                    "warehouse",
                    "location",
                    "item",
                    "series_key",
                    "expires_on",
                    "funding_source",
                ],
                "verbose_name": "Текущий остаток",
                "verbose_name_plural": "Текущие остатки",
            },
        ),
        migrations.RunPython(migrations.RunPython.noop, irreversible_contract),
    ]
