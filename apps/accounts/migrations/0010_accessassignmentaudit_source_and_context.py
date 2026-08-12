import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_accessassignmentaudit_technical_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessassignmentaudit",
            name="correlation_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, verbose_name="Идентификатор операции"),
        ),
        migrations.AddField(
            model_name="accessassignmentaudit",
            name="is_break_glass",
            field=models.BooleanField(default=False, verbose_name="Резервное изменение"),
        ),
        migrations.AddField(
            model_name="accessassignmentaudit",
            name="preview_fingerprint",
            field=models.CharField(editable=False, max_length=64, null=True, unique=True, verbose_name="Отпечаток предпросмотра"),
        ),
        migrations.AddField(
            model_name="accessassignmentaudit",
            name="reason",
            field=models.TextField(blank=True, verbose_name="Причина"),
        ),
        migrations.AddField(
            model_name="accessassignmentaudit",
            name="source",
            field=models.CharField(
                choices=[
                    ("settings_center", "Раздел доступа"),
                    ("django_admin_break_glass", "Резервный Django Admin"),
                    ("ai", "ИИ-инструмент"),
                    ("ad_sync", "Синхронизация Active Directory"),
                ],
                db_index=True,
                default="settings_center",
                max_length=48,
                verbose_name="Источник изменения",
            ),
        ),
    ]
