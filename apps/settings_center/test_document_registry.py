from dataclasses import FrozenInstanceError
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from .document_registry import (
    DATABASE_BACKEND_RELEASED_DOCUMENT_IDS,
    ConfigDocumentRegistry,
    get_document_registry,
)
from .document_specs import ConfigDocumentSpec
from .registry import get_registry

from apps.core.management.commands.settings_documents_inventory import (
    Command as InventoryCommand,
)

pytestmark = pytest.mark.unit


def _static_spec(document_id, path, **kwargs):
    return ConfigDocumentSpec(
        document_id=document_id,
        domain="test",
        storage_policy="git_static",
        default_path=path,
        schema_version=1,
        validator=lambda payload: None,
        failure_policy="fail_closed",
        write_policy="read_only",
        required_permission="manage_settings",
        owner="test",
        active_backend="git",
        **kwargs,
    )


class DocumentRegistryTests(SimpleTestCase):
    def test_access_consumers_do_not_read_legacy_settings_directly(self):
        from .architecture_validation import find_migrated_document_access_violations

        self.assertEqual(find_migrated_document_access_violations(), ())

    def test_registry_matches_all_value_documents(self):
        registry = get_document_registry()
        expected_paths = {
            path.relative_to(settings.BASE_DIR).as_posix()
            for path in Path(settings.BASE_DIR).glob("contracts/**/*.json")
            if "/schemas/" not in path.as_posix() and path.name != ".desc.json"
        }
        registered_paths = {spec.default_path for spec in registry.all()}

        self.assertEqual(len(registry.all()), 29)
        self.assertEqual(registered_paths, expected_paths)
        self.assertEqual(len({spec.document_id for spec in registry.all()}), 29)

    def test_database_override_release_gate_covers_all_thirteen_documents(self):
        registry = get_document_registry()
        database_ids = {
            spec.document_id
            for spec in registry.all()
            if spec.storage_policy == "database_override"
        }
        self.assertEqual(database_ids, DATABASE_BACKEND_RELEASED_DOCUMENT_IDS)
        self.assertEqual(len(database_ids), 13)
        self.assertTrue(
            all(
                spec.active_backend in {"legacy_file", "database"}
                for spec in registry.all()
                if spec.document_id in database_ids
            )
        )

    def test_registered_database_descriptors_have_no_removed_payload_attributes(self):
        registry = get_document_registry()
        documents = {spec.document_id: spec for spec in registry.all()}
        for descriptor in get_registry().all():
            spec = documents.get(descriptor.setting_id)
            if spec is None or spec.storage_policy != "database_override":
                continue
            self.assertNotIn("settings_payload_attr", descriptor.metadata)

    def test_architecture_validator_file_access_guard_is_clean(self):
        from .architecture_validation import (
            find_migrated_document_access_violations,
            validate_contract_registry_coverage,
        )

        self.assertEqual(find_migrated_document_access_violations(), ())
        validate_contract_registry_coverage()

    def test_architecture_validator_detects_synthetic_direct_reader(self):
        from .architecture_validation import find_migrated_document_access_violations

        with tempfile.TemporaryDirectory() as directory:
            apps_root = Path(directory) / "apps"
            apps_root.mkdir()
            contracts_root = Path(directory) / "contracts"
            contracts_root.mkdir()
            (contracts_root / "rogue.json").write_text("{}", encoding="utf-8")
            (apps_root / "unsafe_consumer.py").write_text(
                "from django.conf import settings\n"
                "from apps.core.json_utils import load_json_file\n"
                "CONTRACT_PATH = 'contracts/rogue.json'\n"
                "payload = load_json_file('contracts/role_rules.json')\n"
                "with open(CONTRACT_PATH) as stream:\n"
                "    payload = stream.read()\n"
                "path = settings.LOCAL_BUSINESS_ROLE_RULES_FILE\n",
                encoding="utf-8",
            )
            violations = find_migrated_document_access_violations(root=Path(directory))

        self.assertTrue(any("unsafe_consumer.py" in item for item in violations))
        self.assertTrue(any("load_json_file" in item for item in violations))
        self.assertTrue(any("settings.LOCAL_BUSINESS_ROLE_RULES_FILE" in item for item in violations))
        self.assertTrue(any("unregistered:contracts/rogue.json" in item for item in violations))

    def test_architecture_validator_detects_known_filename_constant_reader(self):
        from .architecture_validation import find_migrated_document_access_violations

        with tempfile.TemporaryDirectory() as directory:
            apps_root = Path(directory) / "apps"
            apps_root.mkdir()
            (apps_root / "unsafe_consumer.py").write_text(
                "from apps.core.json_utils import load_json_file\n"
                "NAME = 'role_rules.json'\n"
                "payload = load_json_file(NAME)\n",
                encoding="utf-8",
            )
            violations = find_migrated_document_access_violations(root=Path(directory))

        self.assertTrue(any("unsafe_consumer.py" in item for item in violations))
        self.assertTrue(any("load_json_file" in item for item in violations))
        self.assertFalse(any("unregistered:" in item for item in violations))

    def test_architecture_validator_detects_memory_payload_attribute(self):
        from .architecture_validation import find_migrated_document_access_violations

        with tempfile.TemporaryDirectory() as directory:
            apps_root = Path(directory) / "apps"
            apps_root.mkdir()
            (apps_root / "unsafe_consumer.py").write_text(
                "from django.conf import settings\n"
                "payload = settings.LOCAL_BUSINESS_MEMORY_PROFILES\n",
                encoding="utf-8",
            )
            violations = find_migrated_document_access_violations(root=Path(directory))

        self.assertTrue(
            any("settings.LOCAL_BUSINESS_MEMORY_PROFILES" in item for item in violations)
        )

    def test_architecture_validator_detects_registered_path_through_custom_reader(self):
        from .architecture_validation import find_migrated_document_access_violations

        with tempfile.TemporaryDirectory() as directory:
            apps_root = Path(directory) / "apps"
            apps_root.mkdir()
            (apps_root / "unsafe_consumer.py").write_text(
                "def custom_reader(path):\n"
                "    return path\n"
                "payload = custom_reader('contracts/ai/tools.json')\n",
                encoding="utf-8",
            )
            violations = find_migrated_document_access_violations(root=Path(directory))

        self.assertTrue(
            any("direct:contracts/ai/tools.json" in item for item in violations)
        )

    def test_legacy_contract_snapshot_uses_default_on_clean_runtime(self):
        from .contract_services import read_contract_snapshot

        descriptor = get_registry().get("waiting_list.contract.status_colors")
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "contracts"
            with override_settings(
                RUNTIME_CONTRACTS_DIR=runtime,
                LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS_FILE=(
                    runtime / "waiting_list_status_colors.json"
                ),
            ):
                snapshot = read_contract_snapshot(descriptor)

        self.assertEqual(snapshot.source, "git_default")
        self.assertEqual(snapshot.revision, 0)

    def test_settings_has_no_migrated_payload_constants(self):
        settings_source = (Path(settings.BASE_DIR) / "config" / "settings.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS =",
            settings_source,
        )
        self.assertNotIn(
            "LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS = _load_contract_payload",
            settings_source,
        )

    def test_all_defaults_and_cross_document_rules_validate(self):
        self.assertTrue(get_document_registry().validate_defaults())

    def test_runtime_descriptors_are_projected_from_specs(self):
        expected_ids = {
            "core.contract.role_rules",
            "core.contract.workflow_rules",
            "workorders.contract.status_colors",
            "waiting_list.contract.status_colors",
            "ai.contract.registry",
            "ai.contract.tools",
            "ai.contract.task_types",
            "ai.contract.models",
            "ai.contract.chat_settings",
            "memory.contract.sources",
            "memory.contract.profiles",
            "memory.contract.routing",
            "memory.contract.trust_policy",
            "memory.contract.claims_policy",
            "memory.contract.retrieval_budget",
            "memory.contract.ingestion_profiles",
            "memory.contract.file_organization_profiles",
            "memory.contract.graph_schema",
        }
        documents = {spec.document_id: spec for spec in get_document_registry().all()}
        runtime_descriptors = [
            descriptor
            for descriptor in get_registry().all()
            if descriptor.storage_kind == "runtime_contract"
        ]
        self.assertEqual(len(runtime_descriptors), 18)
        self.assertEqual({item.setting_id for item in runtime_descriptors}, expected_ids)
        self.assertTrue(expected_ids <= set(documents))
        for descriptor in runtime_descriptors:
            spec = documents[descriptor.setting_id]
            self.assertEqual(descriptor.write_policy, spec.write_policy)
            self.assertEqual(descriptor.required_permission, spec.required_permission)
            self.assertEqual(descriptor.sensitivity, spec.sensitivity)
            self.assertEqual(descriptor.requires_restart, spec.requires_restart)
            self.assertEqual(descriptor.requires_reindex, spec.requires_reindex)
            self.assertEqual(descriptor.metadata.get("settings_path"), spec.legacy_settings_path)
            for key in (
                "storage_policy",
                "active_backend",
                "failure_policy",
                "delivery_scope",
                "cross_document_ids",
            ):
                self.assertEqual(descriptor.metadata[key], getattr(spec, key))
            if spec.validator is not None:
                self.assertIs(descriptor.metadata.get("validator_callable"), spec.validator)

    def test_security_and_presentation_policies_are_explicit(self):
        registry = get_document_registry()
        self.assertEqual(
            registry.get("core.contract.role_rules").write_policy,
            "requires_domain_workflow",
        )
        self.assertEqual(
            registry.get("memory.contract.graph_schema").write_policy,
            "requires_domain_workflow",
        )
        for document_id in (
            "waiting_list.contract.status_colors",
            "workorders.contract.status_colors",
            "ai.contract.chat_settings",
        ):
            self.assertEqual(
                registry.get(document_id).failure_policy,
                "visible_default_fallback",
            )
        for document_id in (
            "ai.contract.registry",
            "ai.contract.tools",
            "ai.contract.task_types",
            "analytics.contract.analysis_scope_rules",
        ):
            self.assertEqual(registry.get(document_id).failure_policy, "fail_closed")

    def test_spec_is_frozen_and_override_has_callable_validator(self):
        spec = get_document_registry().get("core.contract.role_rules")
        self.assertTrue(callable(spec.validator))
        with self.assertRaises(FrozenInstanceError):
            spec.owner = "other"

    def test_registry_rejects_duplicate_ids_paths_unknown_links_and_cycles(self):
        first = _static_spec("a", "contracts/a.json")
        duplicate_path = _static_spec("b", "contracts/a.json")
        with self.assertRaises(ValueError):
            ConfigDocumentRegistry((first, first), validate_default_paths=False)
        with self.assertRaises(ValueError):
            ConfigDocumentRegistry((first, duplicate_path), validate_default_paths=False)

        missing_link = _static_spec(
            "a",
            "contracts/a.json",
            cross_document_ids=("missing",),
            cross_validator=lambda candidate, related: None,
        )
        with self.assertRaises(ValueError):
            ConfigDocumentRegistry((missing_link,), validate_default_paths=False)

        left = _static_spec(
            "left",
            "contracts/left.json",
            cross_document_ids=("right",),
            cross_validator=lambda candidate, related: None,
        )
        right = _static_spec(
            "right",
            "contracts/right.json",
            cross_document_ids=("left",),
            cross_validator=lambda candidate, related: None,
        )
        with self.assertRaises(ValueError):
            ConfigDocumentRegistry((left, right), validate_default_paths=False)

    def test_none_paths_do_not_conflict_for_generated_documents(self):
        specs = tuple(
            ConfigDocumentSpec(
                document_id=f"generated.{index}",
                domain="test",
                storage_policy="generated_file",
                default_path=None,
                schema_version=1,
                validator=None,
                failure_policy="fail_closed",
                write_policy="read_only",
                required_permission="manage_settings",
                owner="test",
                active_backend="generated_file",
            )
            for index in range(2)
        )
        self.assertEqual(
            len(ConfigDocumentRegistry(specs, validate_default_paths=False).all()),
            2,
        )

    def test_invalid_metadata_traversal_and_secret_fallback_are_rejected(self):
        with self.assertRaises(ValueError):
            ConfigDocumentSpec(
                "x", "x", "database_override", "contracts/x.json", 0,
                lambda value: None, "fail_closed", "editable", "manage_settings", "x",
            )
        with self.assertRaises(ValueError):
            _static_spec("x", "contracts/../private.json")
        with self.assertRaises(ValueError):
            ConfigDocumentSpec(
                "x", "x", "database_override", "contracts/x.json", 1,
                lambda value: None, "visible_default_fallback", "editable",
                "manage_settings", "x", sensitivity="restricted",
            )

    def test_inventory_uses_effective_env_path_and_does_not_expose_values(self):
        local_root = Path(settings.BASE_DIR) / ".local"
        local_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_root) as directory:
            override_path = Path(directory) / "role_rules.json"
            payload = json.loads((Path(settings.BASE_DIR) / "contracts/role_rules.json").read_text())
            override_path.write_text(json.dumps(payload), encoding="utf-8")
            output = StringIO()
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=override_path):
                call_command("settings_documents_inventory", stdout=output)
            report = json.loads(output.getvalue())
        role = next(item for item in report if item["document_id"] == "core.contract.role_rules")
        self.assertTrue(role["env_override"])
        self.assertEqual(role["effective_runtime_path"], str(override_path))
        self.assertNotIn("$capabilities", output.getvalue())

    def test_inventory_output_rejects_symlinks_and_external_paths(self):
        local_root = Path(settings.BASE_DIR) / ".local"
        local_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_root) as directory:
            root = Path(directory)
            external_link = root / "external-link.json"
            external_link.symlink_to(Path(settings.BASE_DIR) / "data" / "do-not-write.json")
            dangling_link = root / "dangling-link.json"
            dangling_link.symlink_to(root / "missing.json")
            parent_link = root / "parent-link"
            parent_link.symlink_to(Path(settings.BASE_DIR) / "data", target_is_directory=True)
            for path in (external_link, dangling_link, parent_link / "report.json"):
                with self.subTest(path=path), self.assertRaises(CommandError):
                    call_command("settings_documents_inventory", "--output", str(path))
            with self.assertRaises(CommandError):
                call_command(
                    "settings_documents_inventory",
                    "--output",
                    str(Path(settings.BASE_DIR) / "report.json"),
                )

    def test_inventory_secret_scan_distinguishes_values_handles_and_policy_objects(self):
        self.assertEqual(
            InventoryCommand._secret_scan({"password": "must-not-appear"}, None),
            "rejected",
        )
        self.assertEqual(
            InventoryCommand._secret_scan({"api_key_env": "API_KEY"}, None),
            "reference_only",
        )
        self.assertEqual(
            InventoryCommand._secret_scan(
                {"secret": {"cloud_allowed": False, "default_llm": "deny"}},
                None,
            ),
            "clear",
        )

    def test_windows_output_helper_rechecks_components_and_replaces_atomically(self):
        local_root = Path(settings.BASE_DIR) / ".local"
        local_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_root) as directory:
            root = Path(directory)
            output = root / "nested" / "report.json"
            InventoryCommand._safe_write_windows(output, root, "{}\n")
            self.assertEqual(output.read_text(encoding="utf-8"), "{}\n")

            blocked = root / "blocked" / "report.json"
            with patch.object(
                InventoryCommand,
                "_is_reparse_point",
                side_effect=lambda path: Path(path).name == "blocked",
            ), self.assertRaises(CommandError):
                InventoryCommand._safe_write_windows(blocked, root, "{}\n")
