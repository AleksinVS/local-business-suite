from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.test import override_settings
from pathlib import Path
import json
import tempfile

from apps.core.models import Department
from apps.inventory.models import MedicalDevice
from apps.workorders.models import Board, WorkOrder, WorkOrderStatus
from apps.workorders.policies import ROLE_MANAGER
from .models import (
    AnalyticsContentObject,
    AnalyticsCase,
    AnalyticsDiagnosticRun,
    AnalyticsDuplicateCandidate,
    AnalyticsFact,
    AnalyticsMetricCandidate,
    AnalyticsMetricSnapshot,
    AnalyticsSignal,
)
from .services import (
    dedup_analytics_source,
    extract_analytics_source,
    recalculate_metrics,
    reflect_knowledge,
    run_signal_diagnostic,
    sync_analytics_source,
)

User = get_user_model()
RUNTIME_DATABASES = {"default", "chat", "knowledge_meta", "analytics_control"}


class AnalyticsDashboardTests(TestCase):
    databases = RUNTIME_DATABASES
    def setUp(self):
        self.department = Department.objects.create(name="Приемное отделение")
        self.device = MedicalDevice.objects.create(
            name="Дефибриллятор",
            serial_number="SN-003",
            department=self.department,
        )
        self.manager = User.objects.create_user(username="chief", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.manager.groups.add(manager_group)
        self.user = User.objects.create_user(username="guest", password="pass")
        self.board = Board.objects.create(title="Test Board", slug="test-board-analytics")
        WorkOrder.objects.create(
            title="Плановое ТО",
            description="Проверка питания.",
            department=self.department,
            author=self.manager,
            board=self.board,
            device=self.device,
            status=WorkOrderStatus.RESOLVED,
        )

    def test_manager_can_view_analytics_dashboard(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сводка по заявкам")
        self.assertContains(response, "Выполнена")
        self.assertNotContains(response, f"<td>{WorkOrderStatus.RESOLVED}</td>", html=True)

    def test_regular_user_cannot_view_analytics_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertEqual(response.status_code, 403)


class KnowledgeDrivenAnalyticsTests(TestCase):
    databases = RUNTIME_DATABASES
    def test_email_fixture_sync_extracts_business_facts_and_metrics(self):
        with analytics_contract_settings() as settings_override:
            with override_settings(**settings_override):
                sync_result = sync_analytics_source(source_code="test_reports_imap")
                self.assertEqual(sync_result.created, 3)
                self.assertEqual(AnalyticsContentObject.objects.count(), 3)

                extract_result = extract_analytics_source(source_code="test_reports_imap")
                self.assertEqual(extract_result["packets"], 3)
                self.assertGreaterEqual(extract_result["facts"], 2)
                self.assertTrue(AnalyticsFact.objects.filter(fact_type="department_report_received").exists())
                self.assertTrue(AnalyticsFact.objects.filter(fact_type="department_issue_reported").exists())
                self.assertTrue(AnalyticsFact.objects.filter(fact_type="regulator_request_received").exists())

                metric_result = recalculate_metrics()
                self.assertGreaterEqual(metric_result["snapshots"], 1)
                self.assertTrue(AnalyticsMetricSnapshot.objects.filter(metric_code="department_issues_reported").exists())
                self.assertTrue(AnalyticsSignal.objects.filter(monitor_code="department_issues_present").exists())

    def test_dedup_creates_candidate_for_same_report_in_two_messages(self):
        with analytics_contract_settings() as settings_override:
            with override_settings(**settings_override):
                sync_analytics_source(source_code="test_reports_imap")
                result = dedup_analytics_source(source_code="test_reports_imap")
                self.assertEqual(result["created"], 1)
                candidate = AnalyticsDuplicateCandidate.objects.get()
                self.assertIn(candidate.match_kind, {"exact_normalized_text_hash", "business_key", "near_duplicate"})

    def test_reflection_proposes_metric_candidate_for_repeated_fact_type(self):
        with analytics_contract_settings() as settings_override:
            with override_settings(**settings_override):
                sync_analytics_source(source_code="test_reports_imap")
                extract_analytics_source(source_code="test_reports_imap")
                result = reflect_knowledge()
                self.assertGreaterEqual(result["candidates"], 1)
                self.assertTrue(AnalyticsMetricCandidate.objects.exists())

    def test_diagnostic_dry_run_does_not_persist_run_or_case(self):
        with analytics_contract_settings() as settings_override:
            with override_settings(**settings_override):
                sync_analytics_source(source_code="test_reports_imap")
                extract_analytics_source(source_code="test_reports_imap")
                recalculate_metrics()
                signal = AnalyticsSignal.objects.get(monitor_code="department_issues_present")

                result = run_signal_diagnostic(signal_id=signal.signal_id, dry_run=True)

                signal.refresh_from_db()
                self.assertEqual(result["diagnostic_run_id"], "")
                self.assertEqual(signal.status, AnalyticsSignal.Status.OPEN)
                self.assertEqual(AnalyticsDiagnosticRun.objects.count(), 0)
                self.assertEqual(AnalyticsCase.objects.count(), 0)

    def test_management_commands_dry_run(self):
        with analytics_contract_settings() as settings_override:
            with override_settings(**settings_override):
                call_command("analytics_sync_source", source_code="test_reports_imap", dry_run=True)
                call_command("analytics_recalculate_metrics", dry_run=True)


class analytics_contract_settings:
    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.data_dir = root / "data"
        contracts_dir = root / "contracts"
        contracts_dir.mkdir(parents=True)
        self.sources = contracts_dir / "sources.json"
        self.scope_rules = contracts_dir / "analysis_scope_rules.json"
        self.business_facts = contracts_dir / "business_facts.json"
        self.metrics = contracts_dir / "metrics.json"
        self.monitors = contracts_dir / "monitors.json"
        self.playbooks = contracts_dir / "diagnostic_playbooks.json"
        self.routes = contracts_dir / "workflow_routes.json"
        self.dedup = contracts_dir / "dedup_rules.json"
        self.retention = contracts_dir / "retention_profiles.json"
        write_json(self.sources, test_sources_payload())
        write_json(self.scope_rules, [
            {
                "code": "test_scope",
                "title": "Test scope",
                "owner": "analytics",
                "sources": ["test_reports_imap"],
                "include": {"folders": ["INBOX"], "time_window": "now-24h"},
                "exclude": {"sensitivity": ["secret"]},
                "limits": {"max_source_items": 100},
                "sampling": {"strategy": "changed_since_watermark", "fallback": "latest"},
                "requires_audit": True,
            }
        ])
        write_json(self.business_facts, [
            {
                "code": "department_report_received",
                "title": "Department report received",
                "owner": "analytics",
                "description": "test",
                "dimensions": ["department"],
                "measures": ["reports"],
                "sensitivity": "confidential",
            },
            {
                "code": "department_issue_reported",
                "title": "Department issue reported",
                "owner": "analytics",
                "description": "test",
                "dimensions": ["department"],
                "measures": ["issues"],
                "sensitivity": "confidential",
            },
            {
                "code": "regulator_request_received",
                "title": "Regulator request received",
                "owner": "analytics",
                "description": "test",
                "dimensions": ["regulator"],
                "measures": ["requests"],
                "sensitivity": "confidential",
            },
        ])
        write_json(self.metrics, [
            {
                "code": "department_issues_reported",
                "title": "Department issues reported",
                "owner": "analytics",
                "fact_type": "department_issue_reported",
                "aggregation": "count",
                "measure": "issues",
                "window": "24h",
                "refresh_mode": "scheduled",
                "scope_tokens": ["org:test"],
                "sensitivity": "confidential",
            }
        ])
        write_json(self.monitors, [
            {
                "code": "department_issues_present",
                "title": "Department issues present",
                "owner": "analytics",
                "metric_code": "department_issues_reported",
                "condition": "gte",
                "threshold": 1,
                "severity": "high",
                "workflow_route": "department_issue_review",
                "enabled": True,
            }
        ])
        write_json(self.playbooks, [
            {
                "code": "department_issue_review",
                "title": "Department issue review",
                "owner": "analytics",
                "signal_kinds": ["department_issues_present"],
                "allowed_evidence": ["analytics_fact"],
                "autonomous_actions": ["create_draft_case"],
                "requires_human_review": True,
            }
        ])
        write_json(self.routes, [
            {
                "code": "department_issue_review",
                "title": "Department issue review",
                "owner": "analytics",
                "target": "analytics_case",
                "requires_confirmation": True,
                "allowed_autonomous_actions": ["create_draft_case"],
            }
        ])
        write_json(self.dedup, [
            {
                "code": "default_content_dedup",
                "owner": "analytics",
                "exact_hash_fields": ["raw_sha256"],
                "near_duplicate_fields": ["near_duplicate_key"],
                "semantic_fields": ["subject", "predicate", "object"],
                "authority_priority": ["official_mail_body"],
                "auto_merge_exact": True,
                "review_near_duplicates": True,
            }
        ])
        write_json(self.retention, [
            {
                "code": "email_normalized_default",
                "owner": "analytics",
                "raw_retention_days": 0,
                "normalized_retention_days": 90,
                "fact_retention_days": 730,
                "audit_retention_days": 1095,
            }
        ])
        return {
            "DATA_DIR": self.data_dir,
            "LOCAL_BUSINESS_ANALYTICS_SOURCES_FILE": self.sources,
            "LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES_FILE": self.scope_rules,
            "LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS_FILE": self.business_facts,
            "LOCAL_BUSINESS_ANALYTICS_METRICS_FILE": self.metrics,
            "LOCAL_BUSINESS_ANALYTICS_MONITORS_FILE": self.monitors,
            "LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS_FILE": self.playbooks,
            "LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES_FILE": self.routes,
            "LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES_FILE": self.dedup,
            "LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES_FILE": self.retention,
        }

    def __exit__(self, exc_type, exc, traceback):
        self.temp_dir.cleanup()


def test_sources_payload():
    body = (
        "Отчет заведующего: отделение терапии, период 2026-W21. "
        "Риск: кадровый дефицит. Обязательство: подготовить график до 2026-05-24."
    )
    return [
        {
            "code": "test_reports_imap",
            "title": "Test reports mailbox",
            "source_kind": "email_imap",
            "owner": "analytics",
            "enabled": True,
            "sync_mode": "scheduled",
            "schedule": "*/15 * * * *",
            "scope_tokens": ["org:test"],
            "sensitivity": "confidential",
            "retention_profile": "email_normalized_default",
            "config": {
                "mailbox_code": "reports",
                "folders": ["INBOX"],
                "body_analysis": True,
                "attachments": "metadata_and_handoff",
                "fixture_messages": [
                    {
                        "uidvalidity": "fixture",
                        "uid": "1",
                        "message_id": "<report-1@example.local>",
                        "folder": "INBOX",
                        "subject": "Отчет заведующего отделением терапии за неделю 2026-W21",
                        "from": "head@example.local",
                        "to": ["reports@example.local"],
                        "sent_at": "2026-05-21T09:00:00+03:00",
                        "body": body,
                        "attachments": [],
                    },
                    {
                        "uidvalidity": "fixture",
                        "uid": "2",
                        "message_id": "<report-2@example.local>",
                        "folder": "INBOX",
                        "subject": "FWD: Отчет заведующего отделением терапии за неделю 2026-W21",
                        "from": "assistant@example.local",
                        "to": ["reports@example.local"],
                        "sent_at": "2026-05-21T09:05:00+03:00",
                        "body": body,
                        "attachments": [],
                    },
                    {
                        "uidvalidity": "fixture",
                        "uid": "3",
                        "message_id": "<regulator-1@example.local>",
                        "folder": "INBOX",
                        "subject": "Запрос Росздравнадзора N 2026-0012",
                        "from": "regulator@example.local",
                        "to": ["reports@example.local"],
                        "sent_at": "2026-05-21T10:00:00+03:00",
                        "body": "Просим предоставить 12 документов по теме описания УЗИ. Срок ответа 5 дней.",
                        "attachments": [],
                    },
                ],
            },
        }
    ]


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
