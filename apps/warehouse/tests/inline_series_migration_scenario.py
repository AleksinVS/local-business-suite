"""Isolated-database scenario used by the migration integration test."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import os

import django


def main():
    django.setup()

    from django.conf import settings
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    old_target = [("warehouse", "0002_warehouseauditevent_department_and_more")]
    switch_target = [("warehouse", "0004_inline_series_switch_projection")]
    final_target = [("warehouse", "0005_inline_series_contract")]

    executor = MigrationExecutor(connection)
    executor.migrate(old_target)
    old_apps = executor.loader.project_state(old_target).apps
    Department = old_apps.get_model("core", "Department")
    user_app, user_model = settings.AUTH_USER_MODEL.split(".")
    User = old_apps.get_model(user_app, user_model)
    Category = old_apps.get_model("warehouse", "WarehouseItemCategory")
    Unit = old_apps.get_model("warehouse", "UnitOfMeasure")
    Item = old_apps.get_model("warehouse", "WarehouseItem")
    Funding = old_apps.get_model("warehouse", "FundingSource")
    Warehouse = old_apps.get_model("warehouse", "Warehouse")
    Location = old_apps.get_model("warehouse", "StorageLocation")
    Lot = old_apps.get_model("warehouse", "StockLot")
    Document = old_apps.get_model("warehouse", "StockDocument")
    Line = old_apps.get_model("warehouse", "StockDocumentLine")
    Entry = old_apps.get_model("warehouse", "StockEntry")
    Balance = old_apps.get_model("warehouse", "StockBalance")

    department = Department.objects.create(name="Migration test")
    actor = User.objects.create(
        username="migration-test",
        password="!",
        is_active=True,
        is_superuser=True,
        is_staff=True,
    )
    category = Category.objects.create(code="migration-cat", name="Migration")
    unit = Unit.objects.create(code="migration-pcs", name="pcs", quantity_precision=0)
    item = Item.objects.create(
        code="migration-item", name="Migration item", category=category, unit=unit
    )
    funding = Funding.objects.create(code="migration-fund", name="Migration fund")
    warehouse = Warehouse.objects.create(
        department=department, code="migration-wh", name="Migration warehouse"
    )
    location = Location.objects.create(
        warehouse=warehouse, code="migration-location", name="Migration location"
    )
    expiry = date(2028, 1, 1)
    scenario = os.environ.get("WAREHOUSE_INLINE_SERIES_SCENARIO", "success")
    expiries = (expiry, date(2029, 1, 1)) if scenario == "conflict" else (expiry, expiry)
    lots = [
        Lot.objects.create(item=item, batch_number=" A   1 ", expires_on=expiries[0]),
        Lot.objects.create(item=item, batch_number="a 1", expires_on=expiries[1]),
    ]

    def seed_stock(lot, quantity, sequence):
        document = Document.objects.create(
            department=department,
            document_type="receipt",
            status="posted",
            operation_date=date(2026, 9, sequence),
            created_by=actor,
            posted_by=actor,
        )
        line = Line.objects.create(
            document=document,
            sequence=1,
            item=lot.item,
            lot=lot,
            funding_source=funding,
            quantity=quantity,
            destination_location=location,
        )
        entry = Entry.objects.create(
            document=document,
            document_line=line,
            department=department,
            warehouse=warehouse,
            location=location,
            lot=lot,
            unit=unit,
            funding_source=funding,
            quantity=quantity,
            operation_date=document.operation_date,
        )
        Balance.objects.create(
            department=department,
            warehouse=warehouse,
            location=location,
            lot=lot,
            funding_source=funding,
            quantity=quantity,
        )
        return entry

    seeded_entries = [
        seed_stock(lot, quantity, sequence)
        for sequence, (lot, quantity) in enumerate(
            zip(lots, (Decimal("3"), Decimal("4"))), 1
        )
    ]

    if scenario == "conflict":
        try:
            MigrationExecutor(connection).migrate(
                [("warehouse", "0003_inline_series_expand")]
            )
        except RuntimeError as exc:
            assert "конфликтующими сроками" in str(exc)
        else:
            raise AssertionError("Conflicting expiry migration unexpectedly succeeded")
        recorder = MigrationExecutor(connection).recorder
        assert not recorder.migration_qs.filter(
            app="warehouse", name="0003_inline_series_expand"
        ).exists()
        print("inline-series conflict rollback: OK")
        return

    if scenario == "entry_mismatch":
        Entry.objects.filter(pk=seeded_entries[0].pk).update(lot_id=lots[1].pk)
        try:
            MigrationExecutor(connection).migrate(
                [("warehouse", "0003_inline_series_expand")]
            )
        except RuntimeError as exc:
            assert "разные StockLot" in str(exc)
        else:
            raise AssertionError("Entry/line StockLot mismatch unexpectedly migrated")
        recorder = MigrationExecutor(connection).recorder
        assert not recorder.migration_qs.filter(
            app="warehouse", name="0003_inline_series_expand"
        ).exists()
        print("inline-series entry snapshot rollback: OK")
        return

    # Force keys whose first differing integer is 2 vs 10. A lexicographic
    # JSON sort puts 10 before 2, while the canonical checksum order is numeric.
    extra_items = [
        Item.objects.create(
            code=f"migration-item-{number}",
            name=f"Migration item {number}",
            category=category,
            unit=unit,
        )
        for number in range(2, 11)
    ]
    assert extra_items[0].pk == 2
    assert extra_items[-1].pk == 10
    extra_lots = [
        Lot.objects.create(
            item=extra_items[0],
            batch_number=" Z   2 ",
            expires_on=None,
            incomplete_reason="Legacy expiry is absent",
        ),
        Lot.objects.create(
            item=extra_items[-1],
            batch_number="a 10",
            expires_on=date(2030, 1, 1),
        ),
    ]
    seed_stock(extra_lots[0], Decimal("2"), 3)
    seed_stock(extra_lots[1], Decimal("10"), 4)

    expected_entry_count = 4
    expected_balance_count = 3
    expected_quantity = Decimal("19")

    executor = MigrationExecutor(connection)
    executor.migrate(switch_target)
    switch_apps = executor.loader.project_state(switch_target).apps
    SwitchEntry = switch_apps.get_model("warehouse", "StockEntry")
    SwitchBalance = switch_apps.get_model("warehouse", "StockBalance")
    assert SwitchEntry.objects.count() == expected_entry_count
    assert SwitchBalance.objects.count() == expected_balance_count
    assert sum(SwitchBalance.objects.values_list("quantity", flat=True)) == expected_quantity
    assert set(SwitchEntry.objects.values_list("series_key", flat=True)) == {
        "a 1",
        "z 2",
        "a 10",
    }
    assert SwitchBalance.objects.filter(item_id=2, expires_on__isnull=True).exists()

    # The reversible switch step reconstructs the old per-lot projection.
    executor = MigrationExecutor(connection)
    executor.migrate([("warehouse", "0003_inline_series_expand")])
    expanded_apps = executor.loader.project_state(
        [("warehouse", "0003_inline_series_expand")]
    ).apps
    ExpandedBalance = expanded_apps.get_model("warehouse", "StockBalance")
    assert ExpandedBalance.objects.count() == 4
    assert set(ExpandedBalance.objects.values_list("quantity", flat=True)) == {
        Decimal("2"),
        Decimal("3"),
        Decimal("4"),
        Decimal("10"),
    }

    executor = MigrationExecutor(connection)
    executor.migrate(switch_target)

    # The irreversible contract step requires an explicit, attributed command
    # after the reversible migration has been exercised.
    from django.core.management import call_command

    call_command(
        "warehouse_rebuild_balances",
        actor=actor.username,
        check=True,
        verbosity=0,
    )
    call_command(
        "warehouse_reconcile_inline_series",
        actor=actor.username,
        record_checkpoint=True,
        verbosity=0,
    )

    executor = MigrationExecutor(connection)
    executor.migrate(final_target)
    final_apps = executor.loader.project_state(final_target).apps
    FinalEntry = final_apps.get_model("warehouse", "StockEntry")
    FinalBalance = final_apps.get_model("warehouse", "StockBalance")
    Audit = final_apps.get_model("warehouse", "WarehouseAuditEvent")
    assert FinalEntry.objects.count() == expected_entry_count
    assert FinalBalance.objects.count() == expected_balance_count
    assert sum(FinalBalance.objects.values_list("quantity", flat=True)) == expected_quantity
    assert not any(field.name == "lot" for field in FinalEntry._meta.fields)
    try:
        final_apps.get_model("warehouse", "StockLot")
    except LookupError:
        pass
    else:
        raise AssertionError("StockLot still exists after the contract migration")
    assert set(
        Audit.objects.filter(
            object_type="WarehouseInlineSeriesMigration"
        ).values_list("action", flat=True)
    ) >= {
        "inline_series.migration_expand",
        "inline_series.migration_switch",
        "inline_series.migration_contract",
    }
    print("inline-series migration e2e: OK")


if __name__ == "__main__":
    main()
