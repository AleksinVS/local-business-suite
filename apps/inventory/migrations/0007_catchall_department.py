"""Создать подразделение-агрегатор «Вологодская областная больница №3».

Используется как обязательное значение по умолчанию для изделий, у которых
в источнике данных (выгрузка ФРМО и т. п.) поле «Структурное подразделение»
пустое. Запись нужна на уровне БД, чтобы форма создания изделия и
импорт-скрипт всегда могли на неё сослаться, не создавая агрегатор на лету.
"""

from django.db import migrations

CATCHALL_NAME = "Вологодская областная больница №3"


def forwards_create_catchall(apps, schema_editor):
    Department = apps.get_model("core", "Department")
    # Идемпотентно: get_or_create по уникальному (parent=None, name=...).
    # Текущий UniqueConstraint — на пару (parent, name); для parent=None
    # это превращается в (None, name), что подходит под наш случай.
    Department.objects.get_or_create(
        parent=None,
        name=CATCHALL_NAME,
        defaults={},
    )


def reverse_remove_catchall(apps, schema_editor):
    Department = apps.get_model("core", "Department")
    Department.objects.filter(parent=None, name=CATCHALL_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_department_oid"),
        ("inventory", "0006_medicaldevice_building_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards_create_catchall, reverse_remove_catchall),
    ]
