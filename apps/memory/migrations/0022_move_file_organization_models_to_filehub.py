# ADR-0030 decision 5 (packet 04): the File Source Auto Organization contour
# (11 ``MemoryFile*`` models, ``file_organization*`` modules, UI and
# management commands) is extracted from ``apps.memory`` into a new frozen
# app ``apps.filehub``, with no functional change.
#
# This migration removes the 11 models from the ``memory`` app *state only*
# (``database_operations=[]``): the physical tables are left untouched.
# ``apps.filehub``'s ``0001_initial`` migration re-creates the same models
# under the ``filehub`` app label, state-only, pinning ``Meta.db_table`` to
# the original ``memory_memoryfile*`` table names so the physical schema is
# byte-for-byte identical before and after this pair of migrations. See
# ``apps/filehub/README.md`` and ADR-0025 for the freeze status.
#
# Models are removed in reverse-dependency order (most-dependent first) so
# that, at every point in this operations list, no remaining model in this
# migration still references an already-removed one -- mirroring the order
# the autodetector would use for a real deletion.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0021_drop_candidate_and_review_action_tables'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name='MemoryFileMoveJob'),
                migrations.DeleteModel(name='MemoryFileOrganizationDecision'),
                migrations.DeleteModel(name='MemoryFileOrganizationProposal'),
                migrations.DeleteModel(name='MemoryFileUsageEvent'),
                migrations.DeleteModel(name='MemoryFileVirtualPlacement'),
                migrations.DeleteModel(name='MemoryFileVirtualRule'),
                migrations.DeleteModel(name='MemoryFileVirtualView'),
                migrations.DeleteModel(name='MemoryFilePathAlias'),
                migrations.DeleteModel(name='MemoryFilePhysicalPlacement'),
                migrations.DeleteModel(name='MemoryFileObjectVersion'),
                migrations.DeleteModel(name='MemoryFileObject'),
            ],
        ),
    ]
