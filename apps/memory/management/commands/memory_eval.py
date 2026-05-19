from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.json_utils import atomic_write_json
from apps.memory.deidentification import redact_text
from apps.memory.policies import scope_tokens_match
from apps.memory.routing import resolve_retrieval_route
from apps.memory.security import scan_for_secrets


class Command(BaseCommand):
    help = "Run synthetic memory smoke/security checks without real patient data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run checks without writing an eval JSON report.",
        )
        parser.add_argument(
            "--output-json",
            nargs="?",
            const="",
            help="Write a JSON report under data/memory/eval/. Optionally provide a file name.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        output_json = options.get("output_json")
        report = self._run_checks()
        failed = [check for check in report["checks"] if not check["passed"]]

        if output_json is not None and not dry_run:
            output_path = _eval_output_path(output_json)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(output_path, report)
            self.stdout.write(f"Memory eval report written: {output_path}")

        message = f"Memory eval checks: passed={len(report['checks']) - len(failed)}, failed={len(failed)}"
        if failed:
            raise CommandError(message + "; failed_checks=" + ", ".join(check["name"] for check in failed))
        self.stdout.write(self.style.SUCCESS(message))

    def _run_checks(self):
        checks = [
            _check_pii_detector(),
            _check_secret_bait(),
            _check_forbidden_scope(),
            _check_secret_route_denied(),
        ]
        return {
            "suite": "memory_smoke_security",
            "generated_at": timezone.now().isoformat(),
            "uses_real_patient_data": False,
            "checks": checks,
        }


def _check_pii_detector():
    text = (
        "Синтетическая карточка: ФИО: Тестов Тест Тестович; "
        "телефон +7 000 000-00-00; email synthetic.patient@example.test."
    )
    result = redact_text(text)
    safe_text = result.safe_text
    blocked = bool(result.blocked)
    expected_entities = {"RU_FULL_NAME", "PHONE", "EMAIL"}
    found_entities = {finding.entity_type for finding in result.findings}
    raw_values_removed = all(
        value not in safe_text
        for value in ("Тестов Тест Тестович", "+7 000 000-00-00", "synthetic.patient@example.test")
    )
    return {
        "name": "pii_detector",
        "passed": not blocked and expected_entities.issubset(found_entities) and raw_values_removed,
        "details": {
            "blocked": blocked,
            "found_entities": sorted(found_entities),
            "raw_values_removed": raw_values_removed,
        },
    }


def _check_secret_bait():
    result = scan_for_secrets("Synthetic technical note: api_key=not-a-real-placeholder-value")
    return {
        "name": "secret_bait",
        "passed": result.blocked and result.reason == "credential_material_detected",
        "details": {
            "blocked": result.blocked,
            "reason": result.reason,
            "finding_types": sorted({finding.finding_type for finding in result.findings}),
        },
    }


def _check_forbidden_scope():
    allowed_tokens = ["org:default", "team:biomed"]
    required_tokens = ["team:finance"]
    matched = scope_tokens_match(required_tokens, allowed_tokens)
    return {
        "name": "forbidden_scope",
        "passed": not matched,
        "details": {
            "required_tokens": required_tokens,
            "allowed_tokens": allowed_tokens,
            "matched": matched,
        },
    }


def _check_secret_route_denied():
    denied = False
    try:
        resolve_retrieval_route("secret")
    except PermissionDenied:
        denied = True
    return {
        "name": "secret_route_denied",
        "passed": denied,
        "details": {
            "sensitivity": "secret",
            "denied": denied,
        },
    }


def _eval_output_path(value):
    base_dir = Path(settings.DATA_DIR) / "memory" / "eval"
    if not value:
        filename = f"memory_eval_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
    else:
        filename = Path(str(value)).name
        if not filename:
            raise CommandError("Output JSON file name must not be empty.")
        if not filename.endswith(".json"):
            filename = f"{filename}.json"

    path = (base_dir / filename).resolve()
    base_resolved = base_dir.resolve()
    try:
        path.relative_to(base_resolved)
    except ValueError as exc:
        raise CommandError("Output JSON path must stay under data/memory/eval/.") from exc
    return path
