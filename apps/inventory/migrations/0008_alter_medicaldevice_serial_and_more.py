"""Привести поля MedicalDevice в соответствие с новой логикой импорта ФРМО.

Изменения:
- ``serial_number``: убрать ``unique=True``, разрешить пустые значения
  (``blank=True, null=True``).
- ``inventory_number``: добавить ``unique=True`` (естественный ключ
  для импорт-скрипта и защита от случайных дублей).
- Удалить поля ``building``, ``floor``, ``room`` — заменены единым полем
  ``address`` (TextField), в которое импорт-скрипт склеивает адреса
  нескольких строк через "; ".
- Старый не-unique индекс ``inventory_m_invento_677ec8_idx`` удаляется,
  чтобы не дублировать уникальный индекс, который создаст ``unique=True``.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_department_oid"),
        ("inventory", "0007_catchall_department"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="medicaldevice",
            name="inventory_m_invento_677ec8_idx",
        ),
        migrations.AlterField(
            model_name="medicaldevice",
            name="serial_number",
            field=models.CharField(
                blank=True,
                max_length=128,
                null=True,
                verbose_name="Серийный номер",
            ),
        ),
        migrations.AlterField(
            model_name="medicaldevice",
            name="inventory_number",
            field=models.CharField(
                blank=True,
                max_length=128,
                unique=True,
                verbose_name="Инвентарный номер",
            ),
        ),
        migrations.RemoveField(
            model_name="medicaldevice",
            name="building",
        ),
        migrations.RemoveField(
            model_name="medicaldevice",
            name="floor",
        ),
        migrations.RemoveField(
            model_name="medicaldevice",
            name="room",
        ),
        migrations.AddField(
            model_name="medicaldevice",
            name="address",
            field=models.TextField(blank=True, verbose_name="Адрес"),
        ),
        migrations.AlterField(
            model_name="medicaldevice",
            name="department",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="medical_devices",
                to="core.department",
                verbose_name="Структурное подразделение",
            ),
        ),
    ]