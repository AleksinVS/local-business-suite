# Воспроизводимый исходник локальной проверки P0

Дата: 2026-10-22. Экспериментальный HTTP/SQL/latency сценарий, не постоянный
pytest-модуль вне штатной структуры тестов. Исполняемый файл хранится только
в `.local/lbs-factory-p0/test_p0_baseline.py` по AGENTS.md.

На момент исходного запуска использовался временный путь
`workflow/active/lbs-factory-p0/baseline_checks.py`; исторический лог сохранён.
Ниже тот же исходник без изменений. SHA256: `c63e06d49b73fe309772ed41f38db9f2d7467e92ccfc1f17ea5c9725575ad5c0`.
Пути и процессный профиль запуска — в
[VERIFICATION](../../../docs/architecture/lbs-factory/p0/VERIFICATION.md#воспроизведение).

Извлечение из корня проекта:

```bash
python3 - <<'PYBASELINE'
from pathlib import Path
record = Path('workflow/active/lbs-factory-p0/BASELINE_CHECKS.md').read_text()
code = record.split('```python\n', 1)[1].split('\n```', 1)[0]
target = Path('.local/lbs-factory-p0/test_p0_baseline.py')
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(code + '\n')
PYBASELINE
```

## Исходник

```python
"""Synthetic P0 baseline; never run against a deployment database.

Run explicitly through pytest with config.settings_test and Git-default contract
paths (the main agent prepares those environment variables before Django starts).
Timing includes Django test client/template/SQL-capture overhead; no network,
browser, IIS/AD, production corpus or external model is exercised. This is an
observed baseline, not an SLA. Only successful assertions publish metrics.json.
"""

import hashlib
import json
import math
import os
import platform
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.contract_store import _reset_for_tests
from apps.waiting_list.models import WaitingListAuditLog, WaitingListEntry, WaitingListStatus
from apps.waiting_list.policies import ROLE_DOCTOR
from apps.waiting_list.selectors import visible_waiting_list_entries
from apps.workorders.policies import role_rules


def sample_summary(samples_ms, sql_counts):
    """Nearest-rank percentiles, kept with every numeric input for reproduction."""
    ordered = sorted(samples_ms)
    return {
        "samples": len(ordered),
        "p50_ms": ordered[math.ceil(len(ordered) * 0.50) - 1],
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "durations_ms": samples_ms,
        "sql_counts": sql_counts,
        "sql_count_min": min(sql_counts),
        "sql_count_max": max(sql_counts),
    }


@pytest.mark.integration
@pytest.mark.serial
class P0WaitingListBaselineTests(TestCase):
    """Git-default doctor read-all/write-authored and one real HTTP journey."""

    def setUp(self):
        self.local_root = Path(settings.BASE_DIR) / ".local" / "lbs-factory-p0"
        self.local_root.mkdir(parents=True, exist_ok=True)
        self.assertEqual(os.environ.get("DJANGO_SETTINGS_MODULE"), "config.settings_test")
        self.assertEqual(connection.vendor, "sqlite", "This artifact is for local SQLite only")
        self.assertTrue(
            Path(connection.settings_dict["NAME"]).resolve().is_relative_to(
                (Path(settings.BASE_DIR) / ".local").resolve()
            ),
            "Refuse a database outside .local",
        )
        self.temp = TemporaryDirectory(prefix="synthetic-baseline-", dir=self.local_root)
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)
        contracts = Path(settings.BASE_DIR) / "contracts"
        self.isolation = override_settings(
            DATA_DIR=self.scratch,
            RUNTIME_CONTRACTS_DIR=self.scratch / "contracts",
            MEDIA_ROOT=self.scratch / "media",
            STATIC_ROOT=self.scratch / "staticfiles",
            LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=(),
            LOCAL_BUSINESS_ROLE_RULES_FILE=contracts / "role_rules.json",
            LOCAL_BUSINESS_WORKFLOW_RULES_FILE=contracts / "workflow_rules.json",
            LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE=contracts / "workorder_status_colors.json",
            LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS_FILE=contracts / "waiting_list_status_colors.json",
        )
        self.isolation.enable()
        self.addCleanup(self.isolation.disable)
        _reset_for_tests()
        self.addCleanup(_reset_for_tests)
        User = get_user_model()
        self.author = User.objects.create_user(username="p0-synthetic-author", password=None)
        self.other_doctor = User.objects.create_user(username="p0-synthetic-other", password=None)
        self.outsider = User.objects.create_user(username="p0-synthetic-outsider", password=None)
        doctor, _ = Group.objects.get_or_create(name=ROLE_DOCTOR)
        self.author.groups.add(doctor)
        self.other_doctor.groups.add(doctor)
        self.rules = role_rules()
        # Fail visibly if the baseline contract changes instead of modifying it.
        self.assertEqual(self.rules[ROLE_DOCTOR]["waiting_list_view_scope"], "all")
        self.assertEqual(self.rules[ROLE_DOCTOR]["waiting_list_edit_scope"], "authored")
        self.assertEqual(self.rules[ROLE_DOCTOR]["waiting_list_transition_scope"], "authored")
        self.metrics = {
            "schema_version": 1,
            "synthetic": True,
            "scope": "local SQLite, Django test client, Git-default contracts",
            "production_measured": False,
            "python": platform.python_version(),
            "database_vendor": connection.vendor,
            "percentiles": "nearest rank; warm sequential samples; no latency SLA",
            "contract_sha256": {
                name: hashlib.sha256((contracts / name).read_bytes()).hexdigest()
                for name in (
                    "role_rules.json", "workflow_rules.json",
                    "workorder_status_colors.json", "waiting_list_status_colors.json",
                )
            },
            "selector": {},
            "http": {},
        }

    def add_synthetic_rows(self, start, stop):
        # Bulk rows are selector input only; audited writes are checked through HTTP.
        WaitingListEntry.objects.bulk_create([
            WaitingListEntry(
                author=self.author if index % 2 == 0 else self.other_doctor,
                patient_name=f"СИНТЕТИКА P0 {index:04d}",
                patient_dob=date(2000, 1, 1),
                patient_phone="+7 (000) 000-00-00",
                service_id="s1",
                comment="Искусственная запись для измерения, реальных ПДн нет",
            )
            for index in range(start, stop)
        ])

    def measure_selector(self, expected_rows):
        def select():
            return list(visible_waiting_list_entries(
                self.author, rules_payload=self.rules,
            ).values_list("pk", flat=True))

        self.assertEqual(len(select()), expected_rows)  # warm caches, not queryset
        durations, counts, entry_select_counts = [], [], []
        for _ in range(20):
            with CaptureQueriesContext(connection) as queries:
                started = perf_counter()
                ids = select()  # new queryset each time, fully evaluated
                elapsed = (perf_counter() - started) * 1000
            self.assertEqual(len(ids), expected_rows)
            self.assertEqual(len(set(ids)), expected_rows)
            durations.append(elapsed)
            counts.append(len(queries))
            entry_select_counts.append(sum(
                'FROM "waiting_list_waitinglistentry"' in query["sql"]
                for query in queries.captured_queries
            ))
        # Regular doctor has a group-membership SELECT plus the entries SELECT.
        # Avoid forcing a false one-query promise for the complete selector.
        self.assertEqual(set(entry_select_counts), {1})
        self.assertGreaterEqual(min(counts), 1)
        self.assertLessEqual(max(counts), 2)
        result = sample_summary(durations, counts)
        result["rows"] = expected_rows
        result["entry_select_counts"] = entry_select_counts
        self.metrics["selector"][str(expected_rows)] = result
        return counts

    def measured_http(self, name, method, url, *, data=None, expected=200, repeats=1):
        durations, counts = [], []
        response = None
        for _ in range(repeats):
            with CaptureQueriesContext(connection) as queries:
                started = perf_counter()
                response = getattr(self.client, method)(url, data=data or {})
                # client returns fully rendered template responses; access body too.
                _ = response.content
                elapsed = (perf_counter() - started) * 1000
            self.assertEqual(response.status_code, expected)
            durations.append(elapsed)
            counts.append(len(queries))
        result = sample_summary(durations, counts)
        result["status_code"] = response.status_code
        self.metrics["http"][name] = result
        return response

    def test_selector_scaling_and_audited_http_journey(self):
        self.add_synthetic_rows(0, 100)
        small_counts = self.measure_selector(100)
        self.add_synthetic_rows(100, 1000)
        large_counts = self.measure_selector(1000)
        self.assertEqual(small_counts, large_counts, "Query count must not grow with rows")
        dashboard = reverse("waiting_list:dashboard")
        create_url = reverse("waiting_list:create")
        foreign = WaitingListEntry.objects.filter(author=self.other_doctor).first()
        foreign_detail = reverse("waiting_list:detail", kwargs={"pk": foreign.pk})

        self.client.force_login(self.outsider)
        self.measured_http("outsider_dashboard_denied", "get", dashboard, expected=403)
        denied = self.measured_http("outsider_detail_denied", "get", foreign_detail, expected=403)
        self.assertNotContains(denied, foreign.patient_name, status_code=403)
        self.assertEqual(WaitingListAuditLog.objects.count(), 0)

        self.client.force_login(self.author)
        self.client.get(dashboard)  # warm full-page rendering outside measured samples
        response = self.measured_http("dashboard_1000_warm", "get", dashboard, repeats=10)
        self.assertEqual(len(response.context["entries"]), 1000)
        self.assertContains(response, "СИНТЕТИКА P0 0000")
        # Current read-all semantics are intentional; foreign writes remain denied.
        self.measured_http("doctor_foreign_detail_allowed", "get", foreign_detail)
        self.measured_http(
            "doctor_foreign_update_denied", "post",
            reverse("waiting_list:update", kwargs={"pk": foreign.pk}),
            data={"patient_name": "ЗАПРЕЩЁННОЕ ИЗМЕНЕНИЕ"}, expected=403,
        )
        self.measured_http(
            "doctor_foreign_transition_denied", "post",
            reverse("waiting_list:transition", kwargs={"pk": foreign.pk}),
            data={"status": WaitingListStatus.SCHEDULED}, expected=403,
        )
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, WaitingListStatus.WAITING)
        self.assertTrue(foreign.patient_name.startswith("СИНТЕТИКА P0"))
        self.assertEqual(WaitingListAuditLog.objects.count(), 0)

        fields = {
            "patient_name": "СИНТЕТИКА P0 HTTP",
            "patient_dob": "01.01.2000",
            "patient_phone": "+7 (000) 000-00-00",
            "service_id": "s1",
            "date_tag": "",
            "date_end": "",
            "comment": "Искусственная HTTP-запись",
        }
        self.measured_http("create", "post", create_url, data=fields, expected=302)
        entry = WaitingListEntry.objects.get(patient_name=fields["patient_name"])
        self.assertEqual(entry.author_id, self.author.pk)
        self.assertEqual(list(entry.audit_logs.values_list("action", flat=True)), ["Запись создана"])
        detail_url = reverse("waiting_list:detail", kwargs={"pk": entry.pk})
        self.client.get(detail_url)
        self.measured_http("own_detail_warm", "get", detail_url, repeats=10)
        fields["comment"] = "Искусственное изменение HTTP"
        self.measured_http(
            "update", "post", reverse("waiting_list:update", kwargs={"pk": entry.pk}),
            data=fields, expected=302,
        )
        entry.refresh_from_db()
        self.assertEqual(entry.comment, fields["comment"])
        self.assertTrue(entry.audit_logs.filter(action="Изменены поля: комментарий").exists())
        self.measured_http(
            "transition", "post", reverse("waiting_list:transition", kwargs={"pk": entry.pk}),
            data={"status": WaitingListStatus.SCHEDULED}, expected=302,
        )
        entry.refresh_from_db()
        self.assertEqual(entry.status, WaitingListStatus.SCHEDULED)
        self.assertEqual(entry.audit_logs.count(), 3)
        self.assertEqual(set(entry.audit_logs.values_list("actor_id", flat=True)), {self.author.pk})
        self.assertTrue(entry.audit_logs.filter(action="Статус изменен на 'Назначена'").exists())
        self.assertEqual(WaitingListEntry.objects.count(), 1001)
        self.assertEqual(WaitingListAuditLog.objects.count(), 3)
        self.metrics["http_journey"] = {"entry_count": 1001, "audit_log_count": 3, "passed": True}
        # Publish numeric summaries only: no SQL, patient fields, user IDs or secrets.
        target = self.local_root / "metrics.json"
        temporary = self.local_root / "metrics.json.tmp"
        temporary.write_text(json.dumps(self.metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
```
