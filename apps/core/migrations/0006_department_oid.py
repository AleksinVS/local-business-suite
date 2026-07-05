# Добавление поля OID в Department.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_alter_department_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="oid",
            field=models.CharField(
                verbose_name="OID",
                max_length=255,
                blank=True,
                null=True,
                db_index=True,
            ),
        ),
    ]
