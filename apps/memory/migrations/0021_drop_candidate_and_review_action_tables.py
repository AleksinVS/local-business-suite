# ADR-0030 decision 4 (packet 03): MemoryKnowledgeCandidate and
# MemoryReviewAction are removed — candidacy and risky-edit review now ride
# the git propose -> pending -> review -> stable primitive (see migration
# 0020, which archives every row of both tables and materializes a pending
# organization page for every still-open candidate before this migration
# drops the tables).
#
# NOTE: like migration 0019, this intentionally skips the individual
# RemoveField operations the autodetector proposes for MemoryReviewAction's
# own FK fields (access_audit/actor/index_job/issue/search_document/
# source_object): the whole model is deleted outright below via DeleteModel,
# and on SQLite an intermediate RemoveField forces a table "remake" against a
# state where Meta.indexes still reference the already-removed field, which
# raises FieldDoesNotExist. Dropping the whole table via DeleteModel avoids
# that intermediate state entirely and is equivalent on PostgreSQL.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0020_archive_and_materialize_pending_candidates'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='memoryingestionissue',
            options={'ordering': ['status', '-created_at', '-id'], 'permissions': [('view_review_queue', 'Может просматривать очередь ревью памяти'), ('review_issues', 'Может ревьюировать проблемы памяти'), ('review_privacy_issues', 'Может ревьюировать проблемы приватности памяти'), ('manage_search_index', 'Может управлять поисковым индексом памяти'), ('view_memory_access_audit', 'Может просматривать аудит доступа к памяти')], 'verbose_name': 'Проблема загрузки памяти', 'verbose_name_plural': 'Проблемы загрузки памяти'},
        ),
        migrations.DeleteModel(
            name='MemoryKnowledgeCandidate',
        ),
        migrations.DeleteModel(
            name='MemoryReviewAction',
        ),
    ]
