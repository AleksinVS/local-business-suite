# ADR-0030 decision 3 (packet 05): the LLM graph-extraction contour
# (MemoryGraphEntity/MemoryGraphExtractionRun/MemoryGraphSchemaProposal/
# MemoryGraphReviewItem) is removed outright; typed edges now come from a
# deterministic materializer that parses each knowledge file's `relations:`
# frontmatter against the controlled edge-type vocabulary
# (contracts/ai/memory_graph_schema.json), landing in the new
# MemoryKnowledgeEdge projection table. The graph tables are empty in this
# early-stage deployment (no production data), so this migration does not
# export/archive rows before dropping the tables (waived by the owner; see
# migrations 0018/0020 for the archive pattern used when a table held data).
#
# NOTE: like migrations 0019/0021, this intentionally skips the individual
# RemoveField operations the autodetector proposes for
# MemoryGraphExtractionRun.source, MemoryGraphReviewItem.source/reviewed_by,
# and MemoryGraphSchemaProposal.reviewed_by: deleting the whole model outright
# via DeleteModel avoids an intermediate state where, on SQLite, a table
# "remake" runs against a state whose Meta.indexes/constraints still reference
# the already-removed field, which raises FieldDoesNotExist. Dropping the
# whole table via DeleteModel avoids that intermediate state entirely and is
# equivalent to the autodetector's plan on PostgreSQL.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0022_move_file_organization_models_to_filehub'),
    ]

    operations = [
        migrations.CreateModel(
            name='MemoryKnowledgeEdge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_path', models.CharField(max_length=1000)),
                ('source_knowledge_id', models.CharField(blank=True, max_length=160)),
                ('edge_type', models.CharField(max_length=80)),
                ('target', models.CharField(max_length=1000)),
                ('target_knowledge_id', models.CharField(blank=True, max_length=160)),
                ('target_path', models.CharField(blank=True, max_length=1000)),
                ('provenance', models.CharField(blank=True, max_length=1000)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Ребро знания памяти',
                'verbose_name_plural': 'Рёбра знаний памяти',
                'ordering': ['source_path', 'edge_type', 'target'],
            },
        ),
        migrations.AddIndex(
            model_name='memoryknowledgeedge',
            index=models.Index(fields=['source_path'], name='memory_memo_source__b3c2ce_idx'),
        ),
        migrations.AddIndex(
            model_name='memoryknowledgeedge',
            index=models.Index(fields=['source_knowledge_id'], name='memory_memo_source__ea2c95_idx'),
        ),
        migrations.AddIndex(
            model_name='memoryknowledgeedge',
            index=models.Index(fields=['edge_type'], name='memory_memo_edge_ty_13b29e_idx'),
        ),
        migrations.AddIndex(
            model_name='memoryknowledgeedge',
            index=models.Index(fields=['target'], name='memory_memo_target_44f798_idx'),
        ),
        migrations.AddIndex(
            model_name='memoryknowledgeedge',
            index=models.Index(fields=['target_knowledge_id'], name='memory_memo_target__cc034f_idx'),
        ),
        migrations.AddConstraint(
            model_name='memoryknowledgeedge',
            constraint=models.UniqueConstraint(fields=('source_path', 'edge_type', 'target'), name='memory_knowledge_edge_source_type_target_uniq'),
        ),
        migrations.DeleteModel(
            name='MemoryGraphEntity',
        ),
        migrations.DeleteModel(
            name='MemoryGraphExtractionRun',
        ),
        migrations.DeleteModel(
            name='MemoryGraphReviewItem',
        ),
        migrations.DeleteModel(
            name='MemoryGraphSchemaProposal',
        ),
    ]
