import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("memory", "0023_knowledge_edges_and_drop_graph_extraction_models"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MemoryGroupMembershipAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("groups_before", models.JSONField(default=list)),
                ("groups_after", models.JSONField(default=list)),
                ("groups_added", models.JSONField(default=list)),
                ("groups_removed", models.JSONField(default=list)),
                ("reason", models.TextField()),
                ("preview_fingerprint", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="memory_group_membership_actions", to=settings.AUTH_USER_MODEL)),
                ("target_user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="memory_group_membership_history", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Изменение технических групп памяти",
                "verbose_name_plural": "Изменения технических групп памяти",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["target_user", "-created_at"], name="memory_group_target_idx"),
                    models.Index(fields=["actor", "-created_at"], name="memory_group_actor_idx"),
                ],
            },
        ),
    ]
