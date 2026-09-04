from collections import defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import re
import unicodedata

from django.db import migrations, models
import django.db.models.deletion


CHECKPOINT_ACTION = "inline_series.migration_expand"
SPACE_RE = re.compile(r"\s+")


def _normalize(value):
    display = unicodedata.normalize("NFC", str(value or ""))
    display = SPACE_RE.sub(" ", display.strip())
    key = display.casefold()
    if len(display) > 255 or len(key) > 255:
        raise RuntimeError("Серия после нормализации превышает 255 символов.")
    return display, key


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
    payload = []
    ordered = sorted(totals, key=_projection_sort_key)
    for key in ordered:
        if totals[key]:
            payload.append([*_serialized_key(key), format(totals[key], "f")])
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


def expand_inline_series(apps, schema_editor):
    StockLot = apps.get_model("warehouse", "StockLot")
    StockDocumentLine = apps.get_model("warehouse", "StockDocumentLine")
    StockEntry = apps.get_model("warehouse", "StockEntry")
    StockBalance = apps.get_model("warehouse", "StockBalance")
    WarehouseAuditEvent = apps.get_model("warehouse", "WarehouseAuditEvent")

    referenced_lot_ids = set(
        StockDocumentLine.objects.values_list("lot_id", flat=True)
    )
    referenced_lot_ids.update(StockEntry.objects.values_list("lot_id", flat=True))
    referenced_lot_ids.update(StockBalance.objects.values_list("lot_id", flat=True))
    lots = StockLot.objects.in_bulk(referenced_lot_ids)
    missing = referenced_lot_ids - set(lots)
    if missing:
        raise RuntimeError("Есть ссылки на отсутствующие записи StockLot.")

    expiries = defaultdict(set)
    normalized = {}
    for lot_id, lot in lots.items():
        display, key = _normalize(lot.batch_number)
        normalized[lot_id] = (
            lot.item_id,
            display,
            key,
            lot.expires_on,
            lot.incomplete_reason or "",
        )
        if key:
            expiries[(lot.item_id, key)].add(lot.expires_on)
    conflicts = [key for key, values in expiries.items() if len(values) > 1]
    if conflicts:
        sample = ", ".join(f"item={item_id}, series={key}" for item_id, key in conflicts[:10])
        raise RuntimeError(
            "Обнаружены серии с конфликтующими сроками годности; миграция не угадывает "
            f"значения. Исправьте данные до повторного запуска: {sample}."
        )

    lines = []
    for line in StockDocumentLine.objects.all().iterator():
        item_id, display, key, expires_on, incomplete_reason = normalized[line.lot_id]
        if line.item_id != item_id:
            raise RuntimeError(
                f"Строка документа {line.pk} ссылается на позицию, отличную от StockLot."
            )
        line.series = display
        line.series_key = key
        line.expires_on = expires_on
        line.incomplete_reason = incomplete_reason
        lines.append(line)
        if len(lines) >= 1000:
            StockDocumentLine.objects.bulk_update(
                lines,
                ["series", "series_key", "expires_on", "incomplete_reason"],
                batch_size=1000,
            )
            lines.clear()
    if lines:
        StockDocumentLine.objects.bulk_update(
            lines, ["series", "series_key", "expires_on", "incomplete_reason"], batch_size=1000
        )

    entries = []
    for entry in StockEntry.objects.select_related("document_line").all().iterator():
        item_id, display, key, expires_on, incomplete_reason = normalized[entry.lot_id]
        line = entry.document_line
        if line.document_id != entry.document_id:
            raise RuntimeError(
                f"Проводка {entry.pk} относится не к документу своей строки."
            )
        if line.lot_id != entry.lot_id:
            raise RuntimeError(
                f"Проводка {entry.pk} и строка {line.pk} ссылаются на разные StockLot."
            )
        if line.item_id != item_id:
            raise RuntimeError(
                f"Проводка {entry.pk} содержит несогласованный снимок item/StockLot."
            )
        entry.item_id = item_id
        entry.series = display
        entry.series_key = key
        entry.expires_on = expires_on
        entry.incomplete_reason = incomplete_reason
        entries.append(entry)
        if len(entries) >= 1000:
            StockEntry.objects.bulk_update(
                entries,
                ["item", "series", "series_key", "expires_on", "incomplete_reason"],
                batch_size=1000,
            )
            entries.clear()
    if entries:
        StockEntry.objects.bulk_update(
            entries,
            ["item", "series", "series_key", "expires_on", "incomplete_reason"],
            batch_size=1000,
        )

    balances = []
    for balance in StockBalance.objects.all().iterator():
        item_id, display, key, expires_on, incomplete_reason = normalized[balance.lot_id]
        balance.item_id = item_id
        balance.series = display
        balance.series_key = key
        balance.expires_on = expires_on
        balance.incomplete_reason = incomplete_reason
        balances.append(balance)
        if len(balances) >= 1000:
            StockBalance.objects.bulk_update(
                balances,
                ["item", "series", "series_key", "expires_on", "incomplete_reason"],
                batch_size=1000,
            )
            balances.clear()
    if balances:
        StockBalance.objects.bulk_update(
            balances,
            ["item", "series", "series_key", "expires_on", "incomplete_reason"],
            batch_size=1000,
        )

    expected = defaultdict(Decimal)
    for entry in StockEntry.objects.all().iterator():
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
    actual = defaultdict(Decimal)
    for balance in StockBalance.objects.all().iterator():
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
        raise RuntimeError(
            "Проекция остатков расходится с журналом; сначала выполните пересборку на старой версии."
        )

    entry_count, entry_checksum = _row_checksum(
        StockEntry.objects.all(),
        (
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
        ),
    )
    line_count, line_checksum = _row_checksum(
        StockDocumentLine.objects.all(),
        (
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
        ),
    )
    projection_checksum = _projection_checksum(expected)
    WarehouseAuditEvent.objects.create(
        actor_id=None,
        department_id=None,
        action=CHECKPOINT_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="expand",
        reason="Автоматическая сверка expand/backfill до удаления StockLot",
        summary={
            "version": 1,
            "entry_count": entry_count,
            "entry_checksum": entry_checksum,
            "line_count": line_count,
            "line_checksum": line_checksum,
            "projection_checksum": projection_checksum,
            "balance_count_before_rebuild": StockBalance.objects.count(),
        },
    )


def reverse_expand_inline_series(apps, schema_editor):
    StockDocumentLine = apps.get_model("warehouse", "StockDocumentLine")
    StockEntry = apps.get_model("warehouse", "StockEntry")
    StockBalance = apps.get_model("warehouse", "StockBalance")
    WarehouseAuditEvent = apps.get_model("warehouse", "WarehouseAuditEvent")
    for model in (StockDocumentLine, StockEntry, StockBalance):
        model.objects.all().update(
            series=None,
            series_key=None,
            expires_on=None,
            incomplete_reason=None,
            **({"item_id": None} if model is not StockDocumentLine else {}),
        )
    WarehouseAuditEvent.objects.filter(
        action=CHECKPOINT_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="expand",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0002_warehouseauditevent_department_and_more")]

    operations = [
        migrations.AddField(
            model_name="stockdocumentline",
            name="series",
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name="Серия"),
        ),
        migrations.AddField(
            model_name="stockdocumentline",
            name="series_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=255, null=True, verbose_name="Нормализованный ключ серии"),
        ),
        migrations.AddField(
            model_name="stockdocumentline",
            name="expires_on",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="Срок годности"),
        ),
        migrations.AddField(
            model_name="stockdocumentline",
            name="incomplete_reason",
            field=models.TextField(blank=True, help_text="Обязательна, если серия или срок годности не указаны.", null=True, verbose_name="Причина неполных данных"),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="item",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="stock_entries", to="warehouse.warehouseitem", verbose_name="Позиция"),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="series",
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name="Серия"),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="series_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=255, null=True, verbose_name="Нормализованный ключ серии"),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="expires_on",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="Срок годности"),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="incomplete_reason",
            field=models.TextField(blank=True, null=True, verbose_name="Причина неполных данных"),
        ),
        migrations.AddField(
            model_name="stockbalance",
            name="item",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="stock_balances", to="warehouse.warehouseitem", verbose_name="Позиция"),
        ),
        migrations.AddField(
            model_name="stockbalance",
            name="series",
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name="Серия"),
        ),
        migrations.AddField(
            model_name="stockbalance",
            name="series_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=255, null=True, verbose_name="Нормализованный ключ серии"),
        ),
        migrations.AddField(
            model_name="stockbalance",
            name="expires_on",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="Срок годности"),
        ),
        migrations.AddField(
            model_name="stockbalance",
            name="incomplete_reason",
            field=models.TextField(blank=True, null=True, verbose_name="Причина неполных данных"),
        ),
        migrations.RunPython(expand_inline_series, reverse_expand_inline_series),
    ]
