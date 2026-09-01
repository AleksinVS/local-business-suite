"""Architecture checks for memory/FileHub configuration snapshots."""

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import SimpleTestCase
from django.core.exceptions import ValidationError

from apps.filehub.file_organization import get_file_organization_profile
from apps.analytics.config_documents import get_document_specs as get_analytics_document_specs
from apps.analytics.config_documents import get_analytics_document_payload
from apps.core.config_documents import get_document_specs as get_core_document_specs
from apps.settings_center.document_registry import (
    DATABASE_BACKEND_RELEASED_DOCUMENT_IDS,
    get_document_registry,
)
from apps.memory.config_documents import (
    get_document_specs as get_memory_document_specs,
    get_memory_document_payload,
    get_memory_document_snapshots,
)
from apps.memory.document_ingestion import (
    assert_source_projection_matches_contract,
    get_source_ingestion_profile,
)
from apps.memory.vector_backends import get_default_vector_backend


pytestmark = pytest.mark.unit


class MemoryStorageSnapshotArchitectureTests(SimpleTestCase):
    def test_migrated_consumers_do_not_read_startup_payload_constants(self):
        root = Path(__file__).resolve().parents[1]
        payload_names = (
            "SOURCES",
            "PROFILES",
            "ROUTING",
            "TRUST_POLICY",
            "CLAIMS_POLICY",
            "RETRIEVAL_BUDGET",
            "INGESTION_PROFILES",
            "FILE_ORGANIZATION_PROFILES",
            "GRAPH_SCHEMA",
        )
        consumer_paths = (
            root / "document_ingestion.py",
            root / "policies.py",
            root / "retrieval.py",
            root / "routing.py",
            root / "knowledge_edges.py",
            root / "embeddings.py",
            root / "management" / "commands" / "memory_eval.py",
            root / "management" / "commands" / "memory_reindex.py",
            root / "management" / "commands" / "memory_sync_source.py",
            root.parent / "filehub" / "file_organization.py",
            root.parent / "filehub" / "file_organization_baseline.py",
            root.parent / "filehub" / "file_organization_incoming.py",
            root.parent / "filehub" / "file_organization_move.py",
            root.parent / "filehub" / "file_organization_stats.py",
            root.parent / "analytics" / "services.py",
        )
        forbidden = tuple(f'getattr(settings, "LOCAL_BUSINESS_MEMORY_{name}"' for name in payload_names)
        for path in consumer_paths:
            source = path.read_text(encoding="utf-8")
            self.assertFalse(
                any(marker in source for marker in forbidden),
                f"startup payload read remains in {path}",
            )
        analytics_source = (root.parent / "analytics" / "services.py").read_text(encoding="utf-8")
        self.assertNotIn("settings.LOCAL_BUSINESS_ANALYTICS_SOURCES_FILE", analytics_source)
        self.assertNotIn("settings.LOCAL_BUSINESS_ANALYTICS_METRICS_FILE", analytics_source)
        self.assertNotIn("settings.LOCAL_BUSINESS_ANALYTICS_MONITORS_FILE", analytics_source)

    def test_static_claims_analytics_and_integration_documents_are_read_only(self):
        analytics_specs = get_analytics_document_specs()
        self.assertTrue(analytics_specs)
        for spec in analytics_specs:
            self.assertEqual(spec.storage_policy, "git_static")
            self.assertEqual(spec.active_backend, "git")
            self.assertEqual(spec.write_policy, "read_only")
            self.assertIsNone(spec.legacy_settings_path)
        integration_spec = get_core_document_specs()[0]
        self.assertEqual(integration_spec.document_id, "core.integration.registry")
        self.assertEqual(integration_spec.storage_policy, "git_static")
        self.assertEqual(integration_spec.active_backend, "git")
        self.assertEqual(integration_spec.write_policy, "read_only")
        self.assertIsNone(integration_spec.legacy_settings_path)

        from apps.memory.settings_descriptors import get_settings_descriptors

        descriptors = {
            descriptor.setting_id: descriptor
            for descriptor in get_settings_descriptors()
        }
        self.assertEqual(
            descriptors["memory.contract.claims_policy"].write_policy,
            "read_only",
        )
        self.assertEqual(descriptors["memory.contract.claims_policy"].widget, "json_viewer")
        self.assertNotIn("settings_path", descriptors["memory.contract.claims_policy"].metadata)
        self.assertEqual(
            descriptors["memory.contract.graph_schema"].write_policy,
            "requires_domain_workflow",
        )
        claims_spec = next(
            spec
            for spec in get_memory_document_specs()
            if spec.document_id == "memory.contract.claims_policy"
        )
        self.assertIsNone(claims_spec.legacy_settings_path)
        self.assertNotIn(
            "settings_payload_attr",
            (Path(__file__).resolve().parents[1] / "settings_descriptors.py").read_text(
                encoding="utf-8"
            ),
        )

    def test_memory_database_release_is_exact_connected_eight_document_slice(self):
        memory_ids = {
            document_id
            for document_id in DATABASE_BACKEND_RELEASED_DOCUMENT_IDS
            if document_id.startswith("memory.contract.")
        }
        self.assertEqual(
            memory_ids,
            {
                "memory.contract.sources",
                "memory.contract.profiles",
                "memory.contract.routing",
                "memory.contract.trust_policy",
                "memory.contract.retrieval_budget",
                "memory.contract.ingestion_profiles",
                "memory.contract.file_organization_profiles",
                "memory.contract.graph_schema",
            },
        )
        registry = get_document_registry()
        for document_id in memory_ids:
            spec = registry.get(document_id)
            self.assertEqual(spec.storage_policy, "database_override")
            self.assertIn(spec.active_backend, {"legacy_file", "database"})
            if spec.requires_reindex:
                self.assertTrue(callable(spec.transactional_outbox_callback))
            connected_memory_ids = {
                related
                for related in registry.connected_validation_scope((document_id,))
                if related.startswith("memory.contract.")
            }
            self.assertTrue(connected_memory_ids <= memory_ids)
        self.assertNotIn("memory.contract.claims_policy", memory_ids)

    def test_static_contracts_have_no_startup_payload_assignments(self):
        settings_source = (
            Path(__file__).resolve().parents[3] / "config" / "settings.py"
        ).read_text(encoding="utf-8")
        self.assertNotRegex(
            settings_source,
            r"(?m)^LOCAL_BUSINESS_ANALYTICS_[A-Z0-9_]+\s*=\s*_load_contract_payload\(",
        )
        self.assertNotRegex(
            settings_source,
            r"(?m)^LOCAL_BUSINESS_INTEGRATION_REGISTRY\s*=\s*_load_contract_payload\(",
        )

    def test_operation_snapshot_reader_loads_once_and_explicit_payload_is_reusable(self):
        document_id = "memory.contract.ingestion_profiles"
        revision = SimpleNamespace(
            document_id=document_id,
            payload={"profiles": {"test": {}}},
            revision=3,
            schema_version=1,
            content_hash="sha256:test",
            default_hash="sha256:test",
            source="database_override",
        )
        with patch(
            "apps.settings_center.document_repository.get_snapshot",
            return_value={document_id: revision},
        ) as reader:
            snapshots = get_memory_document_snapshots(document_ids=(document_id,))
        reader.assert_called_once_with((document_id,), request=None)
        self.assertEqual(get_memory_document_payload(document_id, snapshots=snapshots), revision.payload)

    def test_data_dir_override_does_not_replace_repository_snapshot(self):
        document_id = "memory.contract.profiles"
        revision = SimpleNamespace(document_id=document_id, payload={"from": "repository"})
        with patch(
            "apps.settings_center.document_repository.get_snapshot",
            return_value={document_id: revision},
        ):
            from django.test import override_settings

            with override_settings(DATA_DIR=Path("/tmp/other-data")):
                self.assertEqual(
                    get_memory_document_payload(document_id),
                    {"from": "repository"},
                )

    def test_explicit_payload_override_is_a_test_only_compatibility_hook(self):
        from django.test import override_settings

        payload = {"profiles": {"fixture": {}}}
        with override_settings(LOCAL_BUSINESS_MEMORY_PROFILES=payload):
            self.assertEqual(
                get_memory_document_payload(
                    "memory.contract.profiles",
                    snapshots={
                        "memory.contract.profiles": SimpleNamespace(
                            payload={"from": "repository"}
                        )
                    },
                ),
                payload,
            )

    def test_analytics_reader_uses_repository_unless_file_is_explicitly_overridden(self):
        document_id = "analytics.contract.sources"
        revision = SimpleNamespace(document_id=document_id, payload=[{"code": "repo"}])
        with patch(
            "apps.settings_center.document_repository.get_snapshot",
            return_value={document_id: revision},
        ):
            from django.test import override_settings

            with override_settings(DATA_DIR=Path("/tmp/other-data")):
                self.assertEqual(
                    get_analytics_document_payload("sources"),
                    [{"code": "repo"}],
                )

    def test_profile_helpers_accept_a_job_snapshot(self):
        self.assertIn("snapshots", inspect.signature(get_source_ingestion_profile).parameters)
        self.assertIn("snapshots", inspect.signature(get_file_organization_profile).parameters)

    def test_filehub_locks_nullable_relations_after_base_row_lock(self):
        filehub_root = Path(__file__).resolve().parents[2] / "filehub"
        guarded_sources = (
            filehub_root / "file_organization_stats.py",
            filehub_root / "file_organization.py",
            filehub_root / "file_organization_move.py",
            filehub_root.parent / "memory" / "review_services.py",
        )
        for path in guarded_sources:
            source = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                source,
                r"select_for_update\(\)\s*\.select_related\(",
                f"nullable relation lock must be split in {path}",
            )
        stats_source = (filehub_root / "file_organization_stats.py").read_text(encoding="utf-8")
        self.assertIn("locked_files = list(", stats_source)
        move_source = (filehub_root / "file_organization_move.py").read_text(encoding="utf-8")
        base_row_lock = "file_object = MemoryFileObject.objects.select_for_update().get"
        nullable_relation_lock = "MemoryFileObjectVersion.objects.select_for_update()"
        self.assertIn(base_row_lock, move_source)
        self.assertIn(nullable_relation_lock, move_source)
        self.assertLess(move_source.index(base_row_lock), move_source.index(nullable_relation_lock))

    def test_item_loops_receive_the_operation_snapshot(self):
        root = Path(__file__).resolve().parents[1]
        reconcile_source = (
            root / "management" / "commands" / "source_adapter_reconcile.py"
        ).read_text(encoding="utf-8")
        reindex_source = (
            root / "management" / "commands" / "memory_reindex.py"
        ).read_text(encoding="utf-8")
        reconcile_source_source = (
            root / "management" / "commands" / "memory_reconcile.py"
        ).read_text(encoding="utf-8")
        self.assertLess(
            reconcile_source.index("memory_snapshots ="),
            reconcile_source.index("for source_object in"),
        )
        self.assertIn("snapshots=memory_snapshots", reconcile_source)
        self.assertLess(
            reindex_source.index("ingestion_snapshots ="),
            reindex_source.index("for document in"),
        )
        self.assertIn("snapshots=ingestion_snapshots", reindex_source)
        self.assertLess(
            reconcile_source_source.index("snapshots ="),
            reconcile_source_source.index("for item in"),
        )
        self.assertIn("index_knowledge_item(item, snapshots=snapshots)", reconcile_source_source)
        self.assertIn('"memory.contract.graph_schema"', reconcile_source_source)
        self.assertIn("materialize_knowledge_edges(\n            dry_run=dry_run, snapshots=snapshots", reconcile_source_source)

    def test_architecture_validator_uses_one_effective_snapshot_scope(self):
        from apps.core.management.commands.validate_architecture_contracts import (
            EFFECTIVE_SNAPSHOT_DOCUMENT_IDS,
        )

        required = {
            "core.integration.registry",
            "analytics.contract.sources",
            "analytics.contract.metrics",
            "memory.contract.sources",
            "memory.contract.profiles",
            "memory.contract.ingestion_profiles",
        }
        self.assertTrue(required.issubset(EFFECTIVE_SNAPSHOT_DOCUMENT_IDS))
        source = Path(
            __file__
        ).resolve().parents[2] / "core" / "management" / "commands" / "validate_architecture_contracts.py"
        source_text = source.read_text(encoding="utf-8")
        self.assertEqual(source_text.count("ConfigDocumentRepository().get_snapshot("), 1)
        self.assertNotIn("settings.LOCAL_BUSINESS_MEMORY_", source_text)
        self.assertNotIn("settings.LOCAL_BUSINESS_ANALYTICS_", source_text)

    def test_stale_source_projection_is_rejected_before_ingestion(self):
        from types import SimpleNamespace

        source = SimpleNamespace(
            code="fixture_source",
            config={"code": "fixture_source", "source_ref": "old"},
        )
        snapshots = {
            "memory.contract.sources": SimpleNamespace(
                payload=[{"code": "fixture_source", "source_ref": "new"}]
            )
        }
        with self.assertRaises(ValidationError):
            assert_source_projection_matches_contract(source, snapshots=snapshots)

    def test_deleted_source_contract_fails_before_filesystem_side_effect(self):
        source = SimpleNamespace(
            code="deleted_source",
            config={"code": "deleted_source"},
        )
        snapshots = {
            "memory.contract.sources": SimpleNamespace(
                payload=[{"code": "still_registered", "title": "Other source"}]
            )
        }
        with patch("apps.memory.document_ingestion.resolve_source_root") as resolve_root:
            with self.assertRaises(ValidationError):
                assert_source_projection_matches_contract(source, snapshots=snapshots)
            resolve_root.assert_not_called()

    def test_vector_configuration_errors_are_not_silently_disabled(self):
        from apps.settings_center.document_repository import ConfigurationUnavailable
        from django.test import override_settings

        with patch(
            "apps.memory.config_documents.get_memory_document_payload",
            side_effect=ConfigurationUnavailable("profiles unavailable"),
        ):
            with override_settings(LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND="lancedb"):
                with self.assertRaises(ConfigurationUnavailable):
                    get_default_vector_backend()
