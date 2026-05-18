from django.db import migrations, models
import django.utils.timezone
import apps.ai.models


def backfill_expires_at(apps, schema_editor):
    PendingAction = apps.get_model("ai", "PendingAction")
    PendingAction.objects.filter(expires_at__isnull=True).update(
        expires_at=django.utils.timezone.now() + django.utils.timezone.timedelta(minutes=15)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0007_alter_slashcommand_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="pendingaction",
            name="expires_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.RunPython(backfill_expires_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pendingaction",
            name="expires_at",
            field=models.DateTimeField(default=apps.ai.models.default_pending_action_expires_at),
        ),
        migrations.AlterField(
            model_name="pendingaction",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("confirmed", "Confirmed"),
                    ("cancelled", "Cancelled"),
                    ("expired", "Expired"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddIndex(
            model_name="pendingaction",
            index=models.Index(fields=["expires_at"], name="ai_pendinga_expires_77ce4c_idx"),
        ),
    ]
