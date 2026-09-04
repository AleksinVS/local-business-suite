from django.db import migrations, models
import django.db.models.deletion


def populate_unambiguous_defaults(apps, schema_editor):
    Warehouse = apps.get_model("warehouse", "Warehouse")
    StorageLocation = apps.get_model("warehouse", "StorageLocation")

    for warehouse_id in Warehouse.objects.order_by("pk").values_list("pk", flat=True):
        candidates = list(
            StorageLocation.objects.filter(
                warehouse_id=warehouse_id,
                is_active=True,
                purpose="available",
            )
            .order_by("pk")
            .values_list("pk", flat=True)[:2]
        )
        if len(candidates) == 1:
            Warehouse.objects.filter(pk=warehouse_id).update(
                default_receiving_location_id=candidates[0]
            )


def clear_defaults(apps, schema_editor):
    Warehouse = apps.get_model("warehouse", "Warehouse")
    Warehouse.objects.update(default_receiving_location_id=None)


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0005_inline_series_contract")]

    operations = [
        migrations.AddField(
            model_name="warehouse",
            name="default_receiving_location",
            field=models.ForeignKey(
                blank=True,
                help_text="Активный доступный адрес этого склада.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="warehouse.storagelocation",
                verbose_name="Адрес приёмки по умолчанию",
            ),
        ),
        migrations.RunPython(populate_unambiguous_defaults, clear_defaults),
    ]
