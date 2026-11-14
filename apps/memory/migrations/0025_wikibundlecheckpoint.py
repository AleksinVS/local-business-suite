from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("memory", "0024_memorygroupmembershipaudit")]

    operations = [
        migrations.CreateModel(
            name="WikiBundleCheckpoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bundle_id", models.CharField(max_length=160, unique=True)),
                ("revision", models.CharField(blank=True, max_length=64)),
                ("policy_hash", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(default="pending", max_length=16)),
                ("error", models.CharField(blank=True, max_length=64)),
                ("conflicting_ids", models.JSONField(blank=True, default=list)),
            ],
        ),
    ]
