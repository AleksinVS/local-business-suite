from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0003_department_reference"),
        ("workorders", "0006_normalize_workorder_numbers"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workorder",
            name="device",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workorders",
                to="inventory.medicaldevice",
            ),
        ),
    ]
