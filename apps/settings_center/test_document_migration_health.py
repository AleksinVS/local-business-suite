import json
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import Warning
from django.test import RequestFactory, TestCase

from .checks import (
    check_settings_document_migration,
    probe_settings_migration_health,
)


def migration_plan(document_id, classification):
    return SimpleNamespace(document_id=document_id, classification=classification)


@pytest.mark.integration
class SettingsMigrationHealthTests(TestCase):
    @patch("apps.settings_center.checks.plan_migration")
    def test_blocking_classes_are_reported_without_sensitive_details(self, plan):
        plan.return_value = (
            migration_plan("core.one", "migration_required"),
            migration_plan("core.two", "ambiguous_drift"),
            migration_plan("core.three", "env_override"),
            migration_plan("core.four", "conflict"),
            migration_plan("core.five", "security_review_required"),
            migration_plan("core.six", "identical_default"),
        )

        result = probe_settings_migration_health()

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["documents"]["core.one"]["code"], "migration_required")
        self.assertEqual(result["documents"]["core.two"]["code"], "ambiguous_legacy")
        self.assertEqual(result["documents"]["core.three"]["code"], "env_override")
        self.assertEqual(result["documents"]["core.four"]["code"], "conflict")
        self.assertEqual(
            result["documents"]["core.five"]["code"], "security_review_required"
        )
        self.assertNotIn("reason", result)
        self.assertNotIn("path", repr(result).lower())

    @patch("apps.settings_center.checks.plan_migration", return_value=())
    def test_no_blocking_documents_are_ok(self, plan):
        self.assertEqual(probe_settings_migration_health(), {"status": "ok", "documents": {}})

    @patch("apps.settings_center.checks.plan_migration", return_value=())
    @patch("apps.settings_center.checks.get_document_registry")
    def test_active_database_document_is_excluded_from_legacy_probe(
        self, registry, plan
    ):
        from .document_registry import get_document_registry

        waiting = replace(
            get_document_registry().get("waiting_list.contract.status_colors"),
            active_backend="database",
        )
        registry.return_value.all.return_value = (waiting,)

        result = probe_settings_migration_health()

        self.assertEqual(result, {"status": "ok", "documents": {}})
        plan.assert_not_called()

    @patch("apps.settings_center.checks.plan_migration")
    def test_database_failure_is_sanitized(self, plan):
        from django.db import OperationalError

        plan.side_effect = OperationalError("secret path /tmp/private database details")

        result = probe_settings_migration_health()

        self.assertEqual(result, {"status": "error", "code": "store_unavailable", "documents": {}})
        self.assertNotIn("private", repr(result))

    @patch("apps.settings_center.checks.plan_migration")
    def test_wrapped_database_failure_is_store_unavailable(self, plan):
        from django.db import OperationalError

        wrapped = RuntimeError("safe wrapper")
        wrapped.__cause__ = OperationalError("private database details")
        plan.side_effect = wrapped

        result = probe_settings_migration_health()

        self.assertEqual(result["code"], "store_unavailable")
        self.assertNotIn("private", repr(result))

    @patch("apps.settings_center.checks.plan_migration")
    def test_non_database_planner_failure_is_sanitized(self, plan):
        plan.side_effect = ValueError("private path /tmp/contracts")

        result = probe_settings_migration_health()

        self.assertEqual(
            result,
            {"status": "error", "code": "migration_unavailable", "documents": {}},
        )
        self.assertNotIn("private", repr(result))
        self.assertNotIn("/tmp", repr(result))

    @patch("apps.settings_center.checks.probe_settings_migration_health")
    def test_system_check_reports_safe_document_ids_and_classes(self, health):
        health.return_value = {
            "status": "degraded",
            "documents": {
                "core.two": {"classification": "ambiguous_drift", "code": "ambiguous_legacy"},
                "core.one": {"classification": "migration_required", "code": "migration_required"},
            },
        }

        messages = check_settings_document_migration(None)

        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], Warning)
        self.assertEqual(messages[0].id, "settings_center.W002")
        self.assertIn("core.one", messages[0].hint)
        self.assertIn("migration_required", messages[0].hint)
        self.assertNotIn("/", messages[0].hint)
        self.assertNotIn("reason", messages[0].hint.lower())

    @patch("apps.settings_center.checks.probe_settings_migration_health")
    def test_system_check_store_unavailable_has_safe_hint(self, health):
        health.return_value = {
            "status": "error",
            "code": "store_unavailable",
            "documents": {},
        }

        messages = check_settings_document_migration(None)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "settings_center.W002")
        self.assertNotIn("store_unavailable", messages[0].hint)
        self.assertNotIn("/", messages[0].hint)

    def test_health_details_exposes_migration_service(self):
        user = get_user_model().objects.create_superuser(
            username="migration-health-admin", password="password", email="admin@example.test"
        )
        self.client.force_login(user)
        with (
            patch("apps.core.health_views.httpx.get") as http_get,
            patch("apps.settings_center.document_repository.probe_settings_document_health", return_value={"status": "ok", "documents": {}}),
            patch(
                "apps.settings_center.checks.probe_settings_migration_health",
                return_value={"status": "degraded", "documents": {"core.one": {"classification": "conflict", "code": "conflict"}}},
            ),
        ):
            http_get.return_value.status_code = 200
            http_get.return_value.json.return_value = {"status": "ok"}
            response = self.client.get("/health/details/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["services"]["settings_document_migration"]["status"], "degraded")

    def test_health_details_redacts_dependency_exception_text_and_urls(self):
        from apps.core.health_views import health_details
        from apps.core.contract_store import ContractStoreError

        request = RequestFactory().get("/health/details/")
        request.user = SimpleNamespace(is_active=True, is_staff=True)
        with (
            patch(
                "apps.core.health_views.connection.cursor",
                side_effect=RuntimeError("database secret /private/db"),
            ),
            patch(
                "apps.core.health_views.httpx.get",
                side_effect=RuntimeError("agent secret http://private-agent"),
            ),
            patch(
                "apps.core.contract_store.registered_contracts",
                return_value=("private_contract",),
            ),
            patch(
                "apps.core.contract_store.get_contract",
                side_effect=ContractStoreError("contract secret /private/file"),
            ),
            patch(
                "apps.core.contract_store.get_degradation_state",
                return_value={"degraded": False, "contracts": {}},
            ),
            patch(
                "apps.settings_center.document_repository.probe_settings_document_health",
                return_value={"status": "ok", "documents": {}},
            ),
            patch(
                "apps.settings_center.checks.probe_settings_migration_health",
                return_value={"status": "ok", "documents": {}},
            ),
        ):
            response = health_details.__wrapped__(request)

        payload = json.loads(response.content)
        rendered = repr(payload)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("/private", rendered)
        self.assertNotIn("private-agent", rendered)
        self.assertEqual(
            payload["services"]["contracts"]["contracts"]["private_contract"],
            {"code": "invalid_contract"},
        )
