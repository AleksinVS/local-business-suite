import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

import apps.core.json_utils as json_utils
from apps.core.json_utils import (
    validate_memory_profiles_payload,
    validate_memory_routing_payload,
    validate_memory_sources_payload,
)
from apps.workorders.policies import ROLE_MANAGER
from .models import Department

User = get_user_model()


def get_optional_json_validator(test_case, validator_name):
    validator = getattr(json_utils, validator_name, None)
    if validator is None:
        test_case.skipTest(f"{validator_name} is not implemented yet")
    return validator


def valid_memory_graph_schema_payload():
    return {
        "schema_version": "1.0",
        "name": "memory_graph_schema",
        "description": "Default test graph schema.",
        "entity_types": {
            "Department": {
                "label": "Подразделение",
                "description": "Организационная единица.",
                "positive_examples": ["Отдел медицинской техники"],
                "negative_examples": ["кабинет"],
                "attributes": ["name"],
                "status": "accepted",
            },
            "Procedure": {
                "label": "Процедура",
                "description": "Рабочая процедура или регламент.",
                "positive_examples": ["плановое обслуживание"],
                "negative_examples": ["инвентарный номер"],
                "attributes": ["name"],
                "status": "accepted",
            },
        },
        "relation_types": {
            "department_responsible_for_procedure": {
                "label": "подразделение отвечает за процедуру",
                "subject_type": "Department",
                "object_type": "Procedure",
                "description": "Ответственность подразделения за процедуру.",
                "status": "accepted",
            }
        },
        "attribute_types": {
            "name": {
                "value_type": "string",
                "status": "accepted",
            }
        },
        "canonicalization_rules": [],
        "negative_examples": [],
        "forbidden_patterns": [],
        "confidence_thresholds": {"auto_accept": 0.85, "review": 0.6},
        "auto_accept_policy": {"enabled": True},
        "review_policy": {"unknown_schema_item": "needs_expert_review"},
        "department_evidence": [],
        "changelog": [],
    }


class DepartmentModelTests(TestCase):
    def test_full_name_and_descendants_follow_hierarchy(self):
        root = Department.objects.create(name="Стационар")
        child = Department.objects.create(name="Кардиология", parent=root)
        grandchild = Department.objects.create(name="Палата интенсивной терапии", parent=child)

        self.assertEqual(str(grandchild), "Стационар / Кардиология / Палата интенсивной терапии")
        self.assertEqual(set(root.descendant_ids()), {root.id, child.id, grandchild.id})


class DepartmentViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager-ui", password="pass")
        self.staff = User.objects.create_user(username="staff-ui", password="pass", is_staff=True)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.manager.groups.add(manager_group)
        self.department = Department.objects.create(name="Стационар")

    def test_manager_can_open_department_directory(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:department_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подразделения")

    def test_manager_can_create_child_department(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("core:department_create"),
            {"name": "ОРИТ", "parent": self.department.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Department.objects.filter(name="ОРИТ", parent=self.department).exists())

    def test_department_nav_link_visible_for_manager(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, reverse("core:department_list"))

    def test_admin_link_visible_for_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, reverse("admin:index"))

    @override_settings(APP_DISPLAY_NAME="БУЗ ВО ВОБ №3")
    def test_custom_app_display_name_is_rendered(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "БУЗ ВО ВОБ №3")

    @override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=Path("/tmp/nonexistent-role-rules.json"))
    def test_manager_can_open_role_rules_editor(self):
        Path("/tmp/nonexistent-role-rules.json").write_text('{"manager": {"view_scope": "all", "create_workorder": true, "edit_scope": "all", "comment_scope": "visible", "upload_attachment_scope": "visible", "confirm_closure_scope": "all", "rate_scope": "all", "transition_scope": "all", "transition_targets": "*", "manage_inventory": true, "manage_board_columns": true, "manage_assignments": true, "view_analytics": true, "manage_departments": true, "manage_roles": true}}', encoding="utf-8")
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:role_rules"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Права ролей")

    def test_manager_can_save_role_rules_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "role_rules.json"
            initial_payload = {
                "manager": {
                    "view_scope": "all",
                    "create_workorder": True,
                    "edit_scope": "all",
                    "comment_scope": "visible",
                    "upload_attachment_scope": "visible",
                    "confirm_closure_scope": "all",
                    "rate_scope": "all",
                    "transition_scope": "all",
                    "transition_targets": "*",
                    "manage_inventory": True,
                    "manage_board_columns": True,
                    "manage_assignments": True,
                    "view_analytics": True,
                    "manage_departments": True,
                    "manage_roles": True,
                }
            }
            config_path.write_text(json.dumps(initial_payload), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=config_path,
                LOCAL_BUSINESS_ROLE_RULES=initial_payload,
            ):
                self.client.force_login(self.manager)
                response = self.client.post(
                    reverse("core:role_rules"),
                    {
                        "role_manager_create_workorder": "on",
                        "role_manager_manage_inventory": "",
                        "role_manager_manage_board_columns": "",
                        "role_manager_manage_assignments": "",
                        "role_manager_view_analytics": "",
                        "role_manager_manage_departments": "",
                        "role_manager_manage_roles": "",
                        "role_manager_view_scope": "authored",
                    },
                )
                self.assertEqual(response.status_code, 302)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                # View updates existing roles in-place
                self.assertTrue(saved["manager"]["create_workorder"])
                self.assertFalse(saved["manager"]["manage_inventory"])
                self.assertFalse(saved["manager"]["manage_board_columns"])
                self.assertFalse(saved["manager"]["manage_assignments"])
                self.assertFalse(saved["manager"]["view_analytics"])
                self.assertFalse(saved["manager"]["manage_departments"])
                self.assertFalse(saved["manager"]["manage_roles"])
                self.assertEqual(saved["manager"]["view_scope"], "authored")


class DiagnosticEndpointTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="diagnostic-staff",
            password="pass",
            is_staff=True,
        )

    def test_basic_health_is_minimal(self):
        response = self.client.get(reverse("core:health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_details_requires_staff(self):
        response = self.client.get(reverse("core:health_details"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff)
        response = self.client.get(reverse("core:health_details"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("services", response.json())


class ArchitectureContractTests(TestCase):
    def test_validate_architecture_contracts_command_passes(self):
        required_settings = (
            "LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE",
            "LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE",
        )
        for setting_name in required_settings:
            if not hasattr(settings, setting_name):
                self.skipTest(f"{setting_name} is not configured yet")
        call_command("validate_architecture_contracts")

    @override_settings(LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT=90, GUNICORN_TIMEOUT=30)
    def test_validate_architecture_contracts_rejects_short_gunicorn_timeout(self):
        with self.assertRaisesMessage(ValidationError, "GUNICORN_TIMEOUT"):
            call_command("validate_architecture_contracts")

    def test_memory_sources_reject_missing_required_fields(self):
        with self.assertRaisesMessage(ValidationError, "source_kind"):
            validate_memory_sources_payload(
                [
                    {
                        "code": "workorders_public_timeline",
                        "domain": "workorders",
                        "owner": "operations",
                        "enabled": True,
                        "sync_mode": "incremental",
                        "scope_rule": "workorder_visibility",
                        "sensitivity": "internal",
                        "pii_policy": "deidentify_before_index",
                        "versioning_mode": "hard_active_soft_raw",
                        "extractor_profile": "workorder_v1",
                        "chunking_profile": "short_business_event_v1",
                        "index_profiles": ["vector_default"],
                    }
                ]
            )

    def test_memory_profiles_reject_missing_required_payload(self):
        with self.assertRaisesMessage(ValidationError, "ranking_profiles"):
            validate_memory_profiles_payload(
                {
                    "chunking_profiles": {
                        "short_business_event_v1": {
                            "max_tokens": 500,
                            "overlap_tokens": 60,
                            "preserve_fields": ["number"],
                        }
                    },
                    "embedding_profiles": {
                        "local_multilingual_v1": {
                            "provider": "local",
                            "model": "BAAI/bge-m3",
                            "dimensions": 1024,
                            "normalization": True,
                        }
                    },
                }
            )

    def test_memory_routing_rejects_missing_route_for_sensitivity(self):
        with self.assertRaisesMessage(ValidationError, "confidential"):
            validate_memory_routing_payload(
                {
                    "version": "1.0",
                    "name": "memory_routing",
                    "description": "Test routing payload",
                    "sensitivity_levels": ["public", "confidential"],
                    "default_route": "public",
                    "routes": {
                        "public": {
                            "default_llm": "local",
                            "cloud_allowed": True,
                            "requires_redaction": False,
                            "allow_original_pii": False,
                            "allowed_context_kinds": ["question"],
                            "denial_reason": None,
                        }
                    },
                    "cloud_gate": {
                        "mode": "explicit_allow",
                        "max_sensitivity": "public",
                        "requires_redaction": True,
                        "forbidden_sensitivities": ["confidential"],
                    },
                }
            )

    def test_validate_architecture_contracts_reads_memory_contract_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            profiles_path = tmp_path / "memory_profiles.json"
            routing_path = tmp_path / "memory_routing.json"
            sources_path = tmp_path / "memory_sources.json"
            ingestion_profiles_path = tmp_path / "memory_ingestion_profiles.json"
            graph_schema_path = tmp_path / "memory_graph_schema.json"
            default_contracts = Path(__file__).resolve().parents[2] / "contracts" / "ai"
            profiles_payload = json.loads((default_contracts / "memory_profiles.json").read_text(encoding="utf-8"))
            routing_payload = json.loads((default_contracts / "memory_routing.json").read_text(encoding="utf-8"))
            sources_payload = json.loads((default_contracts / "memory_sources.json").read_text(encoding="utf-8"))
            ingestion_profiles_payload = json.loads(
                (default_contracts / "memory_ingestion_profiles.json").read_text(encoding="utf-8")
            )
            routing_payload["routes"]["secret"]["default_llm"] = "local"
            profiles_path.write_text(json.dumps(profiles_payload), encoding="utf-8")
            routing_path.write_text(
                json.dumps(routing_payload),
                encoding="utf-8",
            )
            sources_path.write_text(json.dumps(sources_payload), encoding="utf-8")
            ingestion_profiles_path.write_text(json.dumps(ingestion_profiles_payload), encoding="utf-8")
            graph_schema_path.write_text(json.dumps(valid_memory_graph_schema_payload()), encoding="utf-8")

            with override_settings(
                LOCAL_BUSINESS_MEMORY_PROFILES_FILE=profiles_path,
                LOCAL_BUSINESS_MEMORY_ROUTING_FILE=routing_path,
                LOCAL_BUSINESS_MEMORY_SOURCES_FILE=sources_path,
                LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE=ingestion_profiles_path,
                LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE=graph_schema_path,
            ):
                with self.assertRaisesMessage(ValidationError, "secret"):
                    call_command("validate_architecture_contracts")

    def test_generate_change_plan_command_uses_task_brief(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brief_path = Path(tmpdir) / "brief.json"
            output_path = Path(tmpdir) / "plan.json"
            brief_path.write_text(
                json.dumps(
                    {
                        "id": "TASK-42",
                        "title": "Improve board filters",
                        "status": "draft",
                        "requested_by": "product-owner",
                        "target_modules": ["apps/workorders"],
                        "objective": "Compact board filters and preserve current permissions.",
                        "constraints": ["Do not change workflow rules."],
                        "deliverables": ["Updated UI", "Updated tests"],
                        "acceptance_checks": ["./.venv/bin/python manage.py test apps.workorders.tests"],
                    }
                ),
                encoding="utf-8",
            )
            call_command("generate_change_plan", str(brief_path), "--output", str(output_path))
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["brief_id"], "TASK-42")
            self.assertEqual(payload["title"], "Improve board filters")
            self.assertEqual(payload["status"], "draft")


class MemoryIngestionContractExpectationTests(TestCase):
    def test_memory_ingestion_profiles_accept_expected_bootstrap_shape(self):
        validator = get_optional_json_validator(self, "validate_memory_ingestion_profiles_payload")

        validator(
            {
                "version": "1.0",
                "name": "memory_ingestion_profiles",
                "description": "Default test profiles for memory ingestion.",
                "adapter_profiles": {
                    "local_readonly_v1": {
                        "adapter_kind": "local_path",
                        "follow_symlinks": False,
                    }
                },
                "parser_profiles": {
                    "document_cascade_v1": {
                        "cascade": ["native_text", "docling_placeholder", "ocr_placeholder"],
                        "supported_extensions": [".txt", ".pdf"],
                        "extract_embedded_images": False,
                    }
                },
                "ocr_profiles": {
                    "local_ocr_v1": {
                        "enabled": False,
                        "backend": "tesseract",
                        "languages": ["rus", "eng"],
                        "cloud_policy": "deny",
                    }
                },
                "limit_profiles": {
                    "default_limits_v1": {
                        "max_file_size_mb": 100,
                        "parser_timeout_seconds": 120,
                        "ocr_timeout_seconds": 300,
                    }
                },
                "profiles": {
                    "corporate_docs_v1": {
                        "adapter_profile": "local_readonly_v1",
                        "parser_profile": "document_cascade_v1",
                        "ocr_profile": "local_ocr_v1",
                        "limit_profile": "default_limits_v1",
                        "raw_mode": "reference_only",
                        "acl_mode": "scope_rule",
                        "partial_indexing": "enabled",
                        "issue_policy": {
                            "create_issue_kinds": [
                                "encrypted_file",
                                "unsupported_format",
                                "file_too_large",
                                "partial_indexed",
                            ]
                        },
                    }
                },
            }
        )

    def test_memory_ingestion_profiles_reject_missing_parser_profiles(self):
        validator = get_optional_json_validator(self, "validate_memory_ingestion_profiles_payload")

        with self.assertRaisesMessage(ValidationError, "parser_profiles"):
            validator(
                {
                    "version": "1.0",
                    "name": "memory_ingestion_profiles",
                    "description": "Default test profiles for memory ingestion.",
                    "adapter_profiles": {},
                    "ocr_profiles": {},
                    "limit_profiles": {},
                    "profiles": {},
                }
            )

    def test_memory_graph_schema_accepts_expected_bootstrap_shape(self):
        validator = get_optional_json_validator(self, "validate_memory_graph_schema_payload")

        validator(valid_memory_graph_schema_payload())

    def test_memory_graph_schema_rejects_unknown_relation_pair_types(self):
        validator = get_optional_json_validator(self, "validate_memory_graph_schema_payload")
        payload = valid_memory_graph_schema_payload()
        payload["relation_types"]["department_responsible_for_procedure"]["object_type"] = "UnknownType"

        with self.assertRaisesMessage(ValidationError, "object_type"):
            validator(payload)


class DemoSeedCommandTests(TestCase):
    def test_seed_hospital_demo_creates_reference_data(self):
        call_command("seed_hospital_demo")
        self.assertTrue(Department.objects.filter(name="Стационар").exists())
        self.assertTrue(User.objects.filter(username="chief_manager").exists())
