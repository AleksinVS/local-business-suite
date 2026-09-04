from collections import defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from django.db import migrations, models
import django.db.models.deletion


EXPAND_ACTION = "inline_series.migration_expand"
SWITCH_ACTION = "inline_series.migration_switch"


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


def _projection_checksum(totals):
    payload = [
        [*_serialized_key(key), format(totals[key], "f")]
        for key in sorted(totals, key=_projection_sort_key)
        if totals[key]
    ]
    return sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _journal_checksum(queryset):
    digest = sha256()
    count = 0
    fields = (
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


def switch_projection(apps, schema_editor):
    StockDocumentLine = apps.get_model("warehouse", "StockDocumentLine")
    StockEntry = apps.get_model("warehouse", "StockEntry")
    StockBalance = apps.get_model("warehouse", "StockBalance")
    WarehouseAuditEvent = apps.get_model("warehouse", "WarehouseAuditEvent")

    missing_counts = {
        "lines": StockDocumentLine.objects.filter(
            models.Q(series__isnull=True)
            | models.Q(series_key__isnull=True)
            | models.Q(incomplete_reason__isnull=True)
        ).count(),
        "entries": StockEntry.objects.filter(
            models.Q(item__isnull=True)
            | models.Q(series__isnull=True)
            | models.Q(series_key__isnull=True)
            | models.Q(incomplete_reason__isnull=True)
        ).count(),
        "balances": StockBalance.objects.filter(
            models.Q(item__isnull=True)
            | models.Q(series__isnull=True)
            | models.Q(series_key__isnull=True)
            | models.Q(incomplete_reason__isnull=True)
        ).count(),
    }
    if any(missing_counts.values()):
        raise RuntimeError(f"Expand/backfill inline-серий не завершён: {missing_counts}.")

    checkpoint = WarehouseAuditEvent.objects.filter(
        action=EXPAND_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="expand",
    ).order_by("-id").first()
    if checkpoint is None:
        raise RuntimeError("Не найдена контрольная точка expand/backfill inline-серий.")

    entry_count, entry_checksum = _journal_checksum(StockEntry.objects.all())
    if (
        checkpoint.summary.get("entry_count") != entry_count
        or checkpoint.summary.get("entry_checksum") != entry_checksum
    ):
        raise RuntimeError("Журнал изменился после expand-контрольной точки; switch остановлен.")

    totals = defaultdict(Decimal)
    samples = {}
    for entry in StockEntry.objects.order_by("operation_date", "id").iterator():
        key = (
            entry.department_id,
            entry.warehouse_id,
            entry.location_id,
            entry.item_id,
            entry.series_key,
            entry.expires_on,
            entry.funding_source_id,
        )
        totals[key] += entry.quantity
        samples.setdefault(key, entry)
    if any(quantity < 0 for quantity in totals.values()):
        raise RuntimeError("Журнал содержит отрицательный итог; switch остановлен.")

    StockBalance.objects.all().delete()
    StockBalance.objects.bulk_create(
        [
            StockBalance(
                department_id=key[0],
                warehouse_id=key[1],
                location_id=key[2],
                lot_id=samples[key].lot_id,
                item_id=key[3],
                series=samples[key].series,
                series_key=key[4],
                expires_on=key[5],
                incomplete_reason=samples[key].incomplete_reason,
                funding_source_id=key[6],
                quantity=quantity,
            )
            for key, quantity in sorted(
                totals.items(), key=lambda item: _projection_sort_key(item[0])
            )
            if quantity
        ],
        batch_size=1000,
    )
    projection_checksum = _projection_checksum(totals)
    if projection_checksum != checkpoint.summary.get("projection_checksum"):
        raise RuntimeError("Контрольная сумма проекции изменилась до switch.")
    WarehouseAuditEvent.objects.create(
        actor_id=None,
        department_id=None,
        action=SWITCH_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="switch",
        reason="Проекция пересобрана по целевому ключу inline-серий",
        summary={
            "version": 1,
            "entry_count": entry_count,
            "entry_checksum": entry_checksum,
            "projection_checksum": projection_checksum,
            "balance_count": StockBalance.objects.count(),
        },
    )


def reverse_switch_projection(apps, schema_editor):
    StockEntry = apps.get_model("warehouse", "StockEntry")
    StockBalance = apps.get_model("warehouse", "StockBalance")
    WarehouseAuditEvent = apps.get_model("warehouse", "WarehouseAuditEvent")
    totals = defaultdict(Decimal)
    samples = {}
    for entry in StockEntry.objects.order_by("operation_date", "id").iterator():
        key = (
            entry.department_id,
            entry.warehouse_id,
            entry.location_id,
            entry.lot_id,
            entry.funding_source_id,
        )
        totals[key] += entry.quantity
        samples.setdefault(key, entry)
    if any(quantity < 0 for quantity in totals.values()):
        raise RuntimeError("Журнал содержит отрицательный итог; обратная пересборка остановлена.")
    StockBalance.objects.all().delete()
    StockBalance.objects.bulk_create(
        [
            StockBalance(
                department_id=key[0],
                warehouse_id=key[1],
                location_id=key[2],
                lot_id=key[3],
                item_id=sample.item_id,
                series=sample.series,
                series_key=sample.series_key,
                expires_on=sample.expires_on,
                incomplete_reason=sample.incomplete_reason,
                funding_source_id=key[4],
                quantity=quantity,
            )
            for key, quantity in sorted(totals.items())
            if quantity
            for sample in (samples[key],)
        ],
        batch_size=1000,
    )
    WarehouseAuditEvent.objects.filter(
        action=SWITCH_ACTION,
        object_type="WarehouseInlineSeriesMigration",
        object_id="switch",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0003_inline_series_expand")]

    operations = [
        migrations.RunPython(switch_projection, reverse_switch_projection),
        migrations.RemoveConstraint(
            model_name="stockbalance",
            name="warehouse_unique_balance_key",
        ),
        migrations.AlterField(
            model_name="stockdocumentline",
            name="series",
            field=models.CharField(blank=True, max_length=255, verbose_name="Серия"),
        ),
        migrations.AlterField(
            model_name="stockdocumentline",
            name="series_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=255, verbose_name="Нормализованный ключ серии"),
        ),
        migrations.AlterField(
            model_name="stockdocumentline",
            name="incomplete_reason",
            field=models.TextField(blank=True, help_text="Обязательна, если серия или срок годности не указаны.", verbose_name="Причина неполных данных"),
        ),
        migrations.AlterField(
            model_name="stockdocumentline",
            name="fefo_override_reason",
            field=models.TextField(blank=True, help_text="Обязательна, если выбрана не самая ранняя доступная серия.", verbose_name="Причина отклонения от FEFO"),
        ),
        migrations.AlterField(
            model_name="stockentry",
            name="item",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_entries", to="warehouse.warehouseitem", verbose_name="Позиция"),
        ),
        migrations.AlterField(
            model_name="stockentry",
            name="series",
            field=models.CharField(blank=True, max_length=255, verbose_name="Серия"),
        ),
        migrations.AlterField(
            model_name="stockentry",
            name="series_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=255, verbose_name="Нормализованный ключ серии"),
        ),
        migrations.AlterField(
            model_name="stockentry",
            name="incomplete_reason",
            field=models.TextField(blank=True, verbose_name="Причина неполных данных"),
        ),
        migrations.AlterField(
            model_name="stockbalance",
            name="item",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_balances", to="warehouse.warehouseitem", verbose_name="Позиция"),
        ),
        migrations.AlterField(
            model_name="stockbalance",
            name="series",
            field=models.CharField(blank=True, max_length=255, verbose_name="Серия"),
        ),
        migrations.AlterField(
            model_name="stockbalance",
            name="series_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=255, verbose_name="Нормализованный ключ серии"),
        ),
        migrations.AlterField(
            model_name="stockbalance",
            name="incomplete_reason",
            field=models.TextField(blank=True, verbose_name="Причина неполных данных"),
        ),
        migrations.AddConstraint(
            model_name="stockbalance",
            constraint=models.UniqueConstraint(
                fields=(
                    "department",
                    "warehouse",
                    "location",
                    "item",
                    "series_key",
                    "expires_on",
                    "funding_source",
                ),
                name="warehouse_unique_inline_balance_key",
                nulls_distinct=False,
            ),
        ),
        migrations.AddIndex(
            model_name="stockdocumentline",
            index=models.Index(fields=["item", "series_key", "expires_on"], name="wh_line_series_lookup"),
        ),
        migrations.AddIndex(
            model_name="stockentry",
            index=models.Index(fields=["location", "item", "series_key", "expires_on", "funding_source"], name="wh_entry_stock_lookup"),
        ),
        migrations.AddIndex(
            model_name="stockbalance",
            index=models.Index(fields=["item", "series_key", "expires_on", "quantity"], name="wh_balance_series_qty"),
        ),
    ]
