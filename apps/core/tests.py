import json
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import CommandError, call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

import apps.core.json_utils as json_utils
from apps.core.json_utils import (
    validate_memory_claims_policy_payload,
    validate_memory_file_organization_profiles_payload,
    validate_memory_profiles_payload,
    validate_memory_retrieval_budget_payload,
    validate_memory_routing_payload,
    validate_memory_sources_payload,
    validate_memory_trust_policy_payload,
)
from apps.core.source_adapters import (
    ACCESS_MODE_ADAPTER_CHECK,
    SourceObjectEnvelope,
    get_source_adapter,
    register_source_adapter,
    resolve_privacy_profile,
    unregister_source_adapter,
)
from apps.core.ai_skills import (
    AgentSkillDescriptor,
    clear_agent_skills,
    get_agent_skill,
    register_agent_skill,
    registered_agent_skills,
)
from apps.core.performance import (
    PerformanceMetricsMiddleware,
    record_performance_event,
    summarize_performance_events,
)
from apps.core.postgresql_migration import validate_export_package, write_export_package
from apps.core.right_panels import (
    RightPanelDescriptor,
    build_right_panel_descriptor,
    clear_right_panel_providers,
    register_right_panel_provider,
    registered_right_panel_providers,
)
from apps.workorders.policies import ROLE_MANAGER
from config.settings import database_config_from_url
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


class DatabaseConfigTests(TestCase):
    def test_database_url_parser_builds_postgresql_config(self):
        config = database_config_from_url(
            "postgresql://local_user:p%40ss@db.local:5544/local_business_suite?sslmode=require"
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "local_business_suite")
        self.assertEqual(config["USER"], "local_user")
        self.assertEqual(config["PASSWORD"], "p@ss")
        self.assertEqual(config["HOST"], "db.local")
        self.assertEqual(config["PORT"], "5544")
        self.assertEqual(config["OPTIONS"]["sslmode"], "require")

    def test_wait_for_database_command_uses_default_connection(self):
        out = StringIO()

        call_command("wait_for_database", timeout=1, interval=0.01, stdout=out)

        self.assertIn("Database is available", out.getvalue())

    def test_postgres_migration_export_reads_legacy_sqlite_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = Path(tmpdir) / "legacy.sqlite3"
            with sqlite3.connect(sqlite_path) as connection:
                connection.execute("CREATE TABLE core_department (id integer primary key, name text, parent_id integer)")
                connection.execute("INSERT INTO core_department (name) VALUES (?)", ("demo",))

            with override_settings(LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES={"default": sqlite_path}):
                manifest = write_export_package(Path(tmpdir) / "export", dry_run=True)

        table = manifest["tables"][0]
        self.assertEqual(table["source_alias"], "default")
        self.assertEqual(table["table"], "core_department")
        self.assertEqual(table["columns"], ["id", "name", "parent_id"])
        self.assertEqual(table["row_count"], 1)

    def test_postgres_migration_export_prefers_domain_sqlite_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            default_path = Path(tmpdir) / "default.sqlite3"
            chat_path = Path(tmpdir) / "chat.sqlite3"
            with sqlite3.connect(default_path) as connection:
                connection.execute("CREATE TABLE ai_chatmessage (id integer primary key)")
                connection.execute("INSERT INTO ai_chatmessage (id) VALUES (1)")
            with sqlite3.connect(chat_path) as connection:
                connection.execute("CREATE TABLE ai_chatmessage (id integer primary key)")
                connection.execute("INSERT INTO ai_chatmessage (id) VALUES (2)")
                connection.execute("INSERT INTO ai_chatmessage (id) VALUES (3)")

            with override_settings(
                LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES={
                    "default": default_path,
                    "chat": chat_path,
                }
            ):
                manifest = write_export_package(Path(tmpdir) / "export", dry_run=True)

        table = manifest["tables"][0]
        self.assertEqual(table["source_alias"], "chat")
        self.assertEqual(table["table"], "ai_chatmessage")
        self.assertEqual(table["row_count"], 2)

    def test_postgres_migration_package_validation_checks_jsonl_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = Path(tmpdir) / "legacy.sqlite3"
            with sqlite3.connect(sqlite_path) as connection:
                connection.execute("CREATE TABLE core_department (id integer primary key, name text, parent_id integer)")
                connection.execute("INSERT INTO core_department (name) VALUES (?)", ("demo",))

            output_dir = Path(tmpdir) / "export"
            with override_settings(LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES={"default": sqlite_path}):
                write_export_package(output_dir)

            result = validate_export_package(output_dir)

        self.assertTrue(result["ok"])
        self.assertEqual(result["tables"][0]["actual"], 1)


class PerformanceMetricsTests(TestCase):
    def test_summary_calculates_p50_and_p95_by_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "performance_events.jsonl"
            for duration in [10, 20, 30, 40, 100]:
                record_performance_event(
                    {
                        "route_name": "workorders:board",
                        "route_pattern": "workorders/",
                        "duration_ms": duration,
                        "status_code": 200,
                    },
                    path=path,
                )
            record_performance_event(
                {
                    "route_name": "ai:chat_stream",
                    "route_pattern": "ai/chat/<int:pk>/stream/",
                    "duration_ms": 600,
                    "status_code": 200,
                },
                path=path,
            )

            rows = summarize_performance_events(path, group_by="route_name")

        by_group = {row["group"]: row for row in rows}
        self.assertEqual(by_group["workorders:board"]["count"], 5)
        self.assertEqual(by_group["workorders:board"]["p50_ms"], 30)
        self.assertEqual(by_group["workorders:board"]["p95_ms"], 100)
        self.assertEqual(by_group["ai:chat_stream"]["p50_ms"], 600)

    @override_settings(
        LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED=True,
        LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE=1.0,
    )
    def test_middleware_writes_route_metadata_without_raw_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "performance_events.jsonl"

            def get_response(request):
                from django.http import HttpResponse

                return HttpResponse("ok")

            with override_settings(LOCAL_BUSINESS_PERFORMANCE_METRICS_PATH=path):
                request = RequestFactory().get("/workorders/123/?secret=value")
                request.resolver_match = type(
                    "ResolverMatch",
                    (),
                    {
                        "view_name": "workorders:detail",
                        "url_name": "detail",
                        "route": "workorders/<int:pk>/",
                    },
                )()
                response = PerformanceMetricsMiddleware(get_response)(request)

            self.assertEqual(response.status_code, 200)
            payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["route_name"], "workorders:detail")
            self.assertEqual(payload["route_pattern"], "workorders/<int:pk>/")
            stable_payload = {
                key: value for key, value in payload.items() if key not in {"created_at", "duration_ms"}
            }
            self.assertNotIn("123", json.dumps(stable_payload))
            self.assertNotIn("secret", json.dumps(stable_payload))


class SourceAdapterContractTests(TestCase):
    def test_envelope_normalizes_privacy_and_access_policy(self):
        envelope = SourceObjectEnvelope(
            source_code="test_source",
            source_origin="internal",
            source_kind="django_model",
            domain="tests",
            object_type="record",
            object_id="1",
            title="Test record",
            text="Searchable text",
            content_hash="",
            access_policy={
                "mode": ACCESS_MODE_ADAPTER_CHECK,
                "policy_ref": "tests.visible",
                "scope_tokens": ["org:default", "org:default"],
            },
        )

        self.assertEqual(envelope.privacy_profile, "pii_off")
        self.assertEqual(envelope.access_policy["scope_tokens"], ["org:default"])
        self.assertTrue(envelope.envelope_id)
        self.assertTrue(envelope.content_hash.startswith("sha256:"))

    def test_external_sources_default_to_guarded_pii(self):
        profile = resolve_privacy_profile(source_origin="external", source_kind="external_api")

        self.assertEqual(profile.profile_id, "pii_guarded")
        self.assertTrue(profile.detect)
        self.assertTrue(profile.audit)

    def test_adapter_registry_is_explicit_by_source_code(self):
        class DummyAdapter:
            source_code = "dummy_source"

        register_source_adapter(DummyAdapter(), replace=True)
        self.addCleanup(unregister_source_adapter, "dummy_source")

        self.assertIsNotNone(get_source_adapter("dummy_source"))


class AgentSkillContractTests(TestCase):
    def setUp(self):
        self.original_skills = registered_agent_skills()
        clear_agent_skills()

    def tearDown(self):
        clear_agent_skills()
        for provider in self.original_skills.values():
            register_agent_skill(provider, replace=True)
        super().tearDown()

    def test_descriptor_catalog_entry_is_safe_metadata(self):
        descriptor = AgentSkillDescriptor(
            skill_id="demo.open_panel",
            name="demo-open-panel",
            description="Открывает demo объект справа.",
            source_code="demo",
            object_types=("record",),
            required_tools=("ui.open_right_panel",),
            trigger_examples=("Открой demo 42",),
            body="Workflow instructions",
        )
        register_agent_skill(descriptor)

        entry = get_agent_skill("demo.open_panel").catalog_entry()

        self.assertEqual(entry["id"], "demo.open_panel")
        self.assertEqual(entry["source_code"], "demo")
        self.assertEqual(entry["required_tools"], ["ui.open_right_panel"])
        self.assertNotIn("body", entry)

    def test_registry_rejects_duplicate_and_invalid_id(self):
        descriptor = AgentSkillDescriptor(
            skill_id="demo.open_panel",
            name="demo-open-panel",
            description="Открывает demo объект справа.",
            body="Workflow instructions",
        )
        register_agent_skill(descriptor)
        with self.assertRaises(ValidationError):
            register_agent_skill(descriptor)
        with self.assertRaises(ValidationError):
            AgentSkillDescriptor(
                skill_id="../bad",
                name="bad",
                description="bad",
                body="bad",
            )


class RightPanelContractTests(TestCase):
    def setUp(self):
        self.original_providers = registered_right_panel_providers()
        clear_right_panel_providers()

    def tearDown(self):
        clear_right_panel_providers()
        for provider in self.original_providers.values():
            register_right_panel_provider(provider, replace=True)
        super().tearDown()

    def test_descriptor_serializes_safe_command_without_html(self):
        descriptor = RightPanelDescriptor(
            source_code="demo",
            object_type="record",
            object_id="42",
            title="Demo record",
            htmx_url="/demo/42/",
            drawer_size="large",
            context_hint="demo / record#42",
        )

        payload = descriptor.as_dict()

        self.assertEqual(payload["type"], "open_right_panel")
        self.assertEqual(payload["target"], "#global-right-panel-content")
        self.assertNotIn("html", payload)

    def test_provider_registry_rejects_duplicates_and_unknown_provider(self):
        class DummyProvider:
            source_code = "demo"
            object_type = "record"
            supported_modes = ("view",)

            def can_open(self, user, object_id, mode="view"):
                return True

            def build_panel(self, user, object_id, mode="view"):
                return RightPanelDescriptor(
                    source_code=self.source_code,
                    object_type=self.object_type,
                    object_id=object_id,
                    title="Demo",
                    htmx_url=f"/demo/{object_id}/",
                    mode=mode,
                )

        provider = DummyProvider()
        register_right_panel_provider(provider)

        self.assertIn(("demo", "record"), registered_right_panel_providers())
        with self.assertRaises(ValidationError):
            register_right_panel_provider(provider)
        with self.assertRaises(ValidationError):
            build_right_panel_descriptor(
                user=None,
                source_code="missing",
                object_type="record",
                object_id="42",
            )

    def test_unsupported_mode_and_denied_object_fail_closed(self):
        class DenyingProvider:
            source_code = "demo"
            object_type = "record"
            supported_modes = ("view",)

            def can_open(self, user, object_id, mode="view"):
                return False

            def build_panel(self, user, object_id, mode="view"):
                raise AssertionError("build_panel must not run when access is denied")

        register_right_panel_provider(DenyingProvider())

        with self.assertRaises(ValidationError):
            build_right_panel_descriptor(
                user=None,
                source_code="demo",
                object_type="record",
                object_id="42",
                mode="edit",
            )
        with self.assertRaises(PermissionDenied):
            build_right_panel_descriptor(
                user=None,
                source_code="demo",
                object_type="record",
                object_id="42",
            )


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

    def test_header_renders_current_user_name(self):
        self.manager.first_name = "Иван"
        self.manager.last_name = "Петров"
        self.manager.save(update_fields=["first_name", "last_name"])
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:dashboard"))

        self.assertContains(response, "Иван Петров")

    def test_header_falls_back_to_username_when_full_name_is_empty(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:dashboard"))

        self.assertContains(response, "manager-ui")

    def test_header_user_menu_contains_logout_action(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:dashboard"))

        self.assertContains(response, 'id="header-user-button"')
        self.assertContains(response, 'id="header-user-dropdown"')
        self.assertContains(response, f'action="{reverse("logout")}"')
        self.assertContains(response, "Выйти")

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

    def test_saving_invalid_role_rules_via_ui_is_rejected_and_file_unchanged(self):
        from apps.core.contract_store import _reset_for_tests
        from apps.settings_center.models import SettingsChange

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
            before = config_path.read_text(encoding="utf-8")
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=config_path):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                self.client.force_login(self.manager)
                response = self.client.post(
                    reverse("core:role_rules"),
                    {
                        "role_manager_manage_roles": "on",
                        "role_manager_view_scope": "totally_invalid_scope",
                    },
                )
                # Невалидный view_scope отклоняется валидатором в service layer.
                self.assertEqual(response.status_code, 302)
                self.assertEqual(config_path.read_text(encoding="utf-8"), before)
                self.assertEqual(
                    SettingsChange.objects.filter(setting_id="core.contract.role_rules").count(),
                    0,
                )

    def test_saving_role_rules_via_ui_creates_settings_change(self):
        from apps.core.contract_store import _reset_for_tests
        from apps.settings_center.models import SettingsChange

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
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=config_path):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                self.client.force_login(self.manager)
                response = self.client.post(
                    reverse("core:role_rules"),
                    {
                        "role_manager_manage_roles": "on",
                        "role_manager_create_workorder": "on",
                        "role_manager_view_scope": "authored",
                    },
                )
                self.assertEqual(response.status_code, 302)
                changes = SettingsChange.objects.filter(setting_id="core.contract.role_rules")
                self.assertEqual(changes.count(), 1)
                self.assertEqual(changes.first().status, SettingsChange.Status.APPLIED)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["manager"]["view_scope"], "authored")

    def test_role_rules_form_rejects_lost_update_with_stale_hidden_hash(self):
        """Классический lost update: два администратора открыли форму,
        второй сохраняет позже — его запись со старым hidden base_hash
        отклоняется, конкурентная правка не перезаписывается."""
        import copy

        from apps.core.contract_store import _reset_for_tests
        from apps.settings_center.contract_services import apply_contract_payload
        from apps.settings_center.models import SettingsChange

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
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=config_path):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                self.client.force_login(self.manager)

                # Администратор №2 открывает форму: hidden base_hash в контексте.
                response = self.client.get(reverse("core:role_rules"))
                stale_hash = response.context["role_rules_base_hash"]
                self.assertContains(response, 'name="base_hash"')

                # Администратор №1 сохраняет свою правку раньше (через service layer).
                concurrent = copy.deepcopy(initial_payload)
                concurrent["manager"]["view_scope"] = "department_branch"
                apply_contract_payload(
                    actor=self.manager,
                    setting_id="core.contract.role_rules",
                    raw_payload=json.dumps(concurrent, ensure_ascii=False),
                    confirmed=True,
                )

                # Администратор №2 сохраняет форму со старым hidden base_hash.
                response = self.client.post(
                    reverse("core:role_rules"),
                    {
                        "base_hash": stale_hash,
                        "role_manager_manage_roles": "on",
                        "role_manager_create_workorder": "on",
                        "role_manager_view_scope": "authored",
                    },
                    follow=True,
                )

                # Запись отклонена: файл хранит конкурентную версию, второй
                # SettingsChange не создан, пользователю показана ошибка.
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["manager"]["view_scope"], "department_branch")
                self.assertEqual(
                    SettingsChange.objects.filter(setting_id="core.contract.role_rules").count(),
                    1,
                )
                self.assertContains(response, "изменён другим процессом")


class ContractStoreTests(TestCase):
    def setUp(self):
        from apps.core.contract_store import _reset_for_tests

        _reset_for_tests()
        self.addCleanup(_reset_for_tests)
        self.base = json_utils.load_json_file("contracts/role_rules.json")

    def _write(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_cache_invalidates_on_metadata_key_change(self):
        from apps.core.contract_store import get_contract
        from apps.core.json_utils import atomic_write_json

        with tempfile.TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            self._write(role_file, self.base)
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file):
                first = get_contract("role_rules")
                self.assertIn("manager", first)
                self.assertNotEqual(first["manager"].get("display_name"), "Изменённый менеджер")

                changed = json.loads(json.dumps(self.base))
                changed["manager"]["display_name"] = "Изменённый менеджер"
                # Атомарная запись через os.replace меняет inode -> ключ
                # (st_mtime_ns, st_size, st_ino) отличается, кэш инвалидируется.
                atomic_write_json(role_file, changed)

                second = get_contract("role_rules")
                self.assertEqual(second["manager"].get("display_name"), "Изменённый менеджер")

    def test_independent_workers_see_change_after_apply(self):
        from apps.core.contract_store import _reset_for_tests, get_contract
        from apps.settings_center.contract_services import apply_contract_payload

        actor = User.objects.create_user(username="store-admin", password="pass", is_staff=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            self._write(role_file, self.base)
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file):
                # "Воркер A" читает и кэширует текущую версию.
                worker_a_before = get_contract("role_rules")
                self.assertNotEqual(
                    worker_a_before["manager"].get("display_name"), "Роль обновлена"
                )

                changed = json.loads(json.dumps(self.base))
                changed["manager"]["display_name"] = "Роль обновлена"
                apply_contract_payload(
                    actor=actor,
                    setting_id="core.contract.role_rules",
                    raw_payload=json.dumps(changed, ensure_ascii=False),
                    confirmed=True,
                )

                # Тот же процесс без in-process refresh перечитывает новую версию.
                worker_a_after = get_contract("role_rules")
                self.assertEqual(worker_a_after["manager"].get("display_name"), "Роль обновлена")

                # Независимый "воркер B" (пустой кэш) видит ту же новую версию.
                _reset_for_tests()
                worker_b = get_contract("role_rules")
                self.assertEqual(worker_b["manager"].get("display_name"), "Роль обновлена")

    def test_returned_payload_mutation_does_not_corrupt_cache(self):
        from apps.core.contract_store import get_contract

        with tempfile.TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            self._write(role_file, self.base)
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file):
                first = get_contract("role_rules")
                original_scope = first["manager"]["view_scope"]
                first["manager"]["view_scope"] = "none"
                first["__injected__"] = {"x": 1}

                second = get_contract("role_rules")
                self.assertEqual(second["manager"]["view_scope"], original_scope)
                self.assertNotIn("__injected__", second)

    def test_first_read_of_broken_file_fails_fast(self):
        from apps.core.contract_store import ContractStoreError, get_contract

        with tempfile.TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            role_file.write_text("{ broken json ", encoding="utf-8")
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file):
                with self.assertRaises(ContractStoreError):
                    get_contract("role_rules")

    def test_broken_file_after_valid_read_serves_last_valid_and_flags_degradation(self):
        from apps.core.contract_store import get_contract, get_degradation_state

        with tempfile.TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            self._write(role_file, self.base)
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file):
                valid = get_contract("role_rules")
                self.assertIn("manager", valid)
                self.assertFalse(get_degradation_state()["degraded"])

                # Ломаем файл: размер и mtime меняются -> ключ отличается ->
                # store пытается перечитать, ловит ошибку и отдаёт последний валидный.
                role_file.write_text("{ broken json ", encoding="utf-8")
                served = get_contract("role_rules")
                self.assertEqual(served["manager"], valid["manager"])

                state = get_degradation_state()
                self.assertTrue(state["degraded"])
                self.assertIn("role_rules", state["contracts"])


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

    def test_health_details_reports_contract_store_degradation(self):
        from apps.core.contract_store import _reset_for_tests

        _reset_for_tests()
        self.addCleanup(_reset_for_tests)
        self.client.force_login(self.staff)

        with tempfile.TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            role_file.write_text(
                json_utils.pretty_json(json_utils.load_json_file("contracts/role_rules.json")),
                encoding="utf-8",
            )
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file):
                # Health активно читает контракты через store: первый запрос
                # валиден (и заполняет кэш воркера).
                response = self.client.get(reverse("core:health_details"))
                self.assertEqual(response.json()["services"]["contracts"], {"status": "ok"})

                # Порчу файла обнаруживает сам health-запрос, без предварительных
                # чтений контракта другим кодом (активная проверка, не только
                # пассивный флаг текущего воркера).
                role_file.write_text("{ broken json ", encoding="utf-8")
                response = self.client.get(reverse("core:health_details"))
                contracts = response.json()["services"]["contracts"]
                self.assertEqual(contracts["status"], "degraded")
                self.assertIn("role_rules", contracts["contracts"])


class ArchitectureContractTests(TestCase):
    def test_validate_architecture_contracts_command_passes(self):
        required_settings = (
            "LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE",
            "LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES_FILE",
            "LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE",
            "LOCAL_BUSINESS_MEMORY_TRUST_POLICY_FILE",
            "LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY_FILE",
            "LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET_FILE",
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
                        "index_profiles": ["fulltext_default"],
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

    def test_memory_trust_policy_rejects_invalid_trust_status(self):
        payload = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "ai" / "memory_trust_policy.json").read_text(encoding="utf-8"))
        payload["defaults_by_source_kind"]["external_api_snapshot"]["trust_status"] = "trusted_by_prompt"

        with self.assertRaisesMessage(ValidationError, "trust_status"):
            validate_memory_trust_policy_payload(payload)

    def test_memory_claims_and_retrieval_budget_contracts_pass(self):
        default_contracts = Path(__file__).resolve().parents[2] / "contracts" / "ai"
        validate_memory_claims_policy_payload(
            json.loads((default_contracts / "memory_claims_policy.json").read_text(encoding="utf-8"))
        )
        validate_memory_retrieval_budget_payload(
            json.loads((default_contracts / "memory_retrieval_budget.json").read_text(encoding="utf-8"))
        )
        validate_memory_file_organization_profiles_payload(
            json.loads((default_contracts / "memory_file_organization_profiles.json").read_text(encoding="utf-8"))
        )

    def test_validate_architecture_contracts_reads_memory_contract_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            profiles_path = tmp_path / "memory_profiles.json"
            routing_path = tmp_path / "memory_routing.json"
            sources_path = tmp_path / "memory_sources.json"
            ingestion_profiles_path = tmp_path / "memory_ingestion_profiles.json"
            file_organization_profiles_path = tmp_path / "memory_file_organization_profiles.json"
            graph_schema_path = tmp_path / "memory_graph_schema.json"
            trust_policy_path = tmp_path / "memory_trust_policy.json"
            claims_policy_path = tmp_path / "memory_claims_policy.json"
            retrieval_budget_path = tmp_path / "memory_retrieval_budget.json"
            default_contracts = Path(__file__).resolve().parents[2] / "contracts" / "ai"
            profiles_payload = json.loads((default_contracts / "memory_profiles.json").read_text(encoding="utf-8"))
            routing_payload = json.loads((default_contracts / "memory_routing.json").read_text(encoding="utf-8"))
            sources_payload = json.loads((default_contracts / "memory_sources.json").read_text(encoding="utf-8"))
            ingestion_profiles_payload = json.loads(
                (default_contracts / "memory_ingestion_profiles.json").read_text(encoding="utf-8")
            )
            file_organization_profiles_payload = json.loads(
                (default_contracts / "memory_file_organization_profiles.json").read_text(encoding="utf-8")
            )
            trust_policy_payload = json.loads((default_contracts / "memory_trust_policy.json").read_text(encoding="utf-8"))
            claims_policy_payload = json.loads((default_contracts / "memory_claims_policy.json").read_text(encoding="utf-8"))
            retrieval_budget_payload = json.loads((default_contracts / "memory_retrieval_budget.json").read_text(encoding="utf-8"))
            routing_payload["routes"]["secret"]["default_llm"] = "local"
            profiles_path.write_text(json.dumps(profiles_payload), encoding="utf-8")
            routing_path.write_text(
                json.dumps(routing_payload),
                encoding="utf-8",
            )
            sources_path.write_text(json.dumps(sources_payload), encoding="utf-8")
            ingestion_profiles_path.write_text(json.dumps(ingestion_profiles_payload), encoding="utf-8")
            file_organization_profiles_path.write_text(json.dumps(file_organization_profiles_payload), encoding="utf-8")
            graph_schema_path.write_text(json.dumps(valid_memory_graph_schema_payload()), encoding="utf-8")
            trust_policy_path.write_text(json.dumps(trust_policy_payload), encoding="utf-8")
            claims_policy_path.write_text(json.dumps(claims_policy_payload), encoding="utf-8")
            retrieval_budget_path.write_text(json.dumps(retrieval_budget_payload), encoding="utf-8")

            with override_settings(
                LOCAL_BUSINESS_MEMORY_PROFILES_FILE=profiles_path,
                LOCAL_BUSINESS_MEMORY_ROUTING_FILE=routing_path,
                LOCAL_BUSINESS_MEMORY_SOURCES_FILE=sources_path,
                LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE=ingestion_profiles_path,
                LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES_FILE=file_organization_profiles_path,
                LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE=graph_schema_path,
                LOCAL_BUSINESS_MEMORY_TRUST_POLICY_FILE=trust_policy_path,
                LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY_FILE=claims_policy_path,
                LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET_FILE=retrieval_budget_path,
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


class CheckStaticfilesCommandTests(TestCase):
    """Покрывает ``manage.py check_staticfiles`` в режиме ``--source-dir``.

    Команда смотрит на ``settings.BASE_DIR / static/src`` и
    ``settings.STATIC_ROOT`` — мы подменяем оба пути на временные директории
    и проверяем три сценария: согласовано, расхождение, legacy-артефакт.
    """

    def setUp(self):
        import shutil

        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        # Команда строит ``static_src`` как ``BASE_DIR / static / src``,
        # а mirror — как ``STATIC_ROOT / src``. Подменяем ``BASE_DIR`` и
        # ``STATIC_ROOT`` соответственно.
        self.src = self.root / "static" / "src"
        self.dst = self.root / "staticfiles"
        # Источник и зеркало создаём сразу оба, чтобы даже тесты, которые
        # пишут только в ``src/``, не падали на «staticfiles/src/ отсутствует».
        self.src.mkdir(parents=True)
        self.dst.mkdir(parents=True)
        (self.dst / "src").mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._temp.cleanup)
        self.addCleanup(lambda: shutil.rmtree(self.src, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(self.dst, ignore_errors=True))

    def _run(self, *args) -> tuple[str, str, bool]:
        import io as _io

        stdout, stderr = _io.StringIO(), _io.StringIO()
        raised = False
        try:
            with override_settings(BASE_DIR=str(self.root), STATIC_ROOT=str(self.dst)):
                call_command("check_staticfiles", *args, stdout=stdout, stderr=stderr)
        except CommandError:
            raised = True
        return stdout.getvalue(), stderr.getvalue(), raised

    def _touch_pair(self, relpath: str, src_text: str = "// js", dst_text: str | None = None) -> None:
        # ``relpath`` — это путь ВНУТРИ ``static/src/`` (без ведущего ``src/``).
        # ``self.src`` уже равен ``BASE_DIR/static/src``, mirror — ``STATIC_ROOT/src``.
        src_file = self.src / relpath
        dst_file = self.dst / "src" / relpath
        src_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text(src_text, encoding="utf-8")
        dst_file.write_text(dst_text if dst_text is not None else src_text, encoding="utf-8")

    def _touch_src_only(self, relpath: str, text: str = "// js") -> None:
        src_file = self.src / relpath
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text(text, encoding="utf-8")

    def _touch_dst_only(self, relpath: str, text: str = "// js") -> None:
        dst_file = self.dst / "src" / relpath
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_text(text, encoding="utf-8")

    def test_mirrored_files_pass(self):
        self._touch_pair("js/example.js")
        self._touch_pair("css/example.css")
        out, _, raised = self._run()
        self.assertFalse(raised)
        self.assertIn("синхр", out.lower() + out)

    def test_missing_staticfiles_copy_fails_with_fail_flag(self):
        self._touch_src_only("js/orphan.js")
        _, err, raised = self._run("--fail")
        self.assertTrue(raised)
        self.assertIn("orphan.js", err)

    def test_missing_staticfiles_copy_warns_without_fail_flag(self):
        self._touch_src_only("js/orphan.js")
        out, err, raised = self._run()
        self.assertFalse(raised)
        combined = (out + err).lower()
        self.assertIn("orphan.js", combined)
        self.assertIn("collectstatic", combined)

    def test_size_mismatch_is_reported(self):
        self._touch_pair("js/big.js", src_text="x" * 10, dst_text="y" * 5)
        _, err, raised = self._run("--fail")
        self.assertTrue(raised)
        self.assertIn("big.js", err)

    def test_legacy_artifact_is_listed_and_can_be_ignored(self):
        # Берём имя, которое НЕ подавлено по умолчанию (не ``*.bak``,
        # не hashed manifest, не ``.gz``), чтобы команда его показала.
        self._touch_dst_only("ai_ui/orphan_no_match.js")
        out, err, raised = self._run()
        self.assertFalse(raised)
        self.assertIn("orphan_no_match.js", out + err)
        # Через ``--ignore`` артефакт подавляется.
        out2, err2, raised2 = self._run("--ignore", "orphan_*")
        self.assertFalse(raised2)
        self.assertNotIn("orphan_no_match.js", out2 + err2)

    def test_html_assets_are_not_required_to_be_in_staticfiles(self):
        # ``index.html`` лежит только в static/src/, его не обязательно
        # держать под ``staticfiles/`` — команда должна это пропустить.
        html = self.src / "index.html"
        html.parent.mkdir(parents=True, exist_ok=True)
        html.write_text("<html></html>", encoding="utf-8")
        out, _, raised = self._run()
        self.assertFalse(raised)
        self.assertIn("синхр", out.lower() + out)
