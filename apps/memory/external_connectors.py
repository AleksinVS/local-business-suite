from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.json_utils import atomic_write_json

from .ingestion import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, index_snapshot_text
from .models import MemorySnapshot, MemorySource
from .security import scan_for_secrets


ENVELOPE_SCHEMA_VERSION = "external-memory-envelope-v1"


class ExternalJobKind:
    DISCOVER_EXTERNAL_SOURCE = "discover_external_source"
    SYNC_EXTERNAL_COLLECTION = "sync_external_collection"
    FETCH_EXTERNAL_PAGE = "fetch_external_page"
    FETCH_EXTERNAL_OBJECT = "fetch_external_object"
    NORMALIZE_EXTERNAL_OBJECT = "normalize_external_object"
    HANDOFF_EXTERNAL_OBJECT_TO_MEMORY = "handoff_external_object_to_memory"
    RECONCILE_EXTERNAL_DELETES = "reconcile_external_deletes"
    RETRY_EXTERNAL_FAILURE = "retry_external_failure"
    EXTERNAL_DEAD_LETTER = "external_dead_letter"


class ExternalJobStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ExternalQueueJob:
    job_id: str
    source_code: str
    job_kind: str
    status: str
    priority: int
    payload: dict
    result: dict
    error_message: str
    idempotency_key: str
    attempt_count: int
    max_attempts: int
    request_id: str


class SQLiteExternalConnectorQueueBackend:
    """Durable connector queue stored outside the primary Django database."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or settings.LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def enqueue(
        self,
        *,
        source_code: str,
        job_kind: str,
        payload: dict,
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 3,
        request_id: str = "",
    ) -> ExternalQueueJob:
        now = _now_iso()
        job_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO external_connector_jobs (
                    job_id, source_code, job_kind, status, priority, payload_json, result_json,
                    error_message, idempotency_key, attempt_count, max_attempts, request_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    source_code,
                    job_kind,
                    ExternalJobStatus.PENDING,
                    priority,
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                    "{}",
                    "",
                    idempotency_key,
                    0,
                    max_attempts,
                    request_id,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM external_connector_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _job_from_row(row)

    def lease(self, *, limit: int = 1, lease_seconds: int = 300) -> list[ExternalQueueJob]:
        now = _now_iso()
        locked_until = _future_iso(lease_seconds)
        leased = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM external_connector_jobs
                WHERE status IN (?, ?)
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND (locked_until IS NULL OR locked_until <= ?)
                ORDER BY priority DESC, created_at ASC, job_id ASC
                LIMIT ?
                """,
                (ExternalJobStatus.PENDING, ExternalJobStatus.RETRY_WAIT, now, now, limit),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE external_connector_jobs
                    SET status = ?, attempt_count = attempt_count + 1, started_at = ?,
                        locked_until = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (ExternalJobStatus.RUNNING, now, locked_until, now, row["job_id"]),
                )
            connection.commit()
            for row in rows:
                fresh = connection.execute(
                    "SELECT * FROM external_connector_jobs WHERE job_id = ?",
                    (row["job_id"],),
                ).fetchone()
                leased.append(_job_from_row(fresh))
        return leased

    def complete(self, job_id: str, *, result: dict | None = None) -> ExternalQueueJob:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE external_connector_jobs
                SET status = ?, result_json = ?, error_message = '', finished_at = ?,
                    locked_until = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    ExternalJobStatus.SUCCEEDED,
                    json.dumps(result or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                    job_id,
                ),
            )
            row = connection.execute("SELECT * FROM external_connector_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _job_from_row(row)

    def fail(self, job_id: str, *, error_message: str, retry_delay_seconds: int = 60) -> ExternalQueueJob:
        now = _now_iso()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM external_connector_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise ValidationError("External connector queue job does not exist.")
            status = ExternalJobStatus.DEAD_LETTER if row["attempt_count"] >= row["max_attempts"] else ExternalJobStatus.RETRY_WAIT
            next_attempt_at = None if status == ExternalJobStatus.DEAD_LETTER else _future_iso(retry_delay_seconds)
            connection.execute(
                """
                UPDATE external_connector_jobs
                SET status = ?, error_message = ?, next_attempt_at = ?, locked_until = NULL,
                    updated_at = ?, finished_at = CASE WHEN ? = ? THEN ? ELSE finished_at END
                WHERE job_id = ?
                """,
                (status, error_message, next_attempt_at, now, status, ExternalJobStatus.DEAD_LETTER, now, job_id),
            )
            row = connection.execute("SELECT * FROM external_connector_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _job_from_row(row)

    def stats(self) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM external_connector_jobs GROUP BY status ORDER BY status"
            ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def get(self, job_id: str) -> ExternalQueueJob | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM external_connector_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS external_connector_jobs (
                    job_id TEXT PRIMARY KEY,
                    source_code TEXT NOT NULL,
                    job_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL UNIQUE,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    next_attempt_at TEXT,
                    locked_until TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    request_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS external_connector_jobs_ready_idx
                ON external_connector_jobs(status, next_attempt_at, locked_until, priority, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS external_connector_jobs_source_idx
                ON external_connector_jobs(source_code, status, created_at)
                """
            )


def get_external_queue_backend():
    backend = getattr(settings, "LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND", "sqlite")
    if backend != "sqlite":
        raise ValidationError(f"Unsupported external connector queue backend: {backend}")
    return SQLiteExternalConnectorQueueBackend()


def build_external_envelope(
    *,
    source_code: str,
    collection: str,
    object_type: str,
    external_id: str,
    title: str,
    payload: dict,
    operation: str = "upsert",
    run_id: str = "",
    external_url: str = "",
    source_updated_at: str = "",
    scope_tokens: list[str] | None = None,
    sensitivity: str = "internal",
    retention_class: str = "external_default",
) -> dict:
    if operation not in {"upsert", "delete"}:
        raise ValidationError("External envelope operation must be 'upsert' or 'delete'.")
    if not source_code or not collection or not object_type or not external_id:
        raise ValidationError("source_code, collection, object_type and external_id are required.")
    normalized_payload = payload or {}
    content_hash = _sha256_json(
        {
            "operation": operation,
            "source_code": source_code,
            "collection": collection,
            "object_type": object_type,
            "external_id": external_id,
            "title": title,
            "payload": normalized_payload,
            "source_updated_at": source_updated_at,
        }
    )
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "source_code": source_code,
        "collection": collection,
        "object_type": object_type,
        "external_id": external_id,
        "external_url": external_url,
        "operation": operation,
        "source_updated_at": source_updated_at,
        "content_hash": content_hash,
        "title": title,
        "payload": normalized_payload,
        "relations": [],
        "scope_tokens": scope_tokens or ["org:default"],
        "sensitivity": sensitivity,
        "retention_class": retention_class,
        "provenance": {
            "connector_version": "external-api-mvp-v1",
            "sync_run_id": run_id or _run_id(),
            "fetched_at": timezone.now().isoformat(),
        },
    }


def enqueue_external_envelope(
    *,
    source: MemorySource,
    envelope: dict,
    raw_response: dict | None = None,
    request_id: str = "",
    priority: int = 0,
):
    envelope_path = write_external_landing_artifacts(source=source, envelope=envelope, raw_response=raw_response)
    backend = get_external_queue_backend()
    idempotency_key = f"{source.code}:{envelope['collection']}:{envelope['external_id']}:{envelope['content_hash']}"
    return backend.enqueue(
        source_code=source.code,
        job_kind=ExternalJobKind.HANDOFF_EXTERNAL_OBJECT_TO_MEMORY,
        payload={"envelope_path": str(envelope_path)},
        idempotency_key=idempotency_key,
        priority=priority,
        request_id=request_id,
    )


def write_external_landing_artifacts(*, source: MemorySource, envelope: dict, raw_response: dict | None = None) -> Path:
    validate_external_envelope(envelope)
    rendered = render_external_envelope_text(envelope)
    secret_scan = scan_for_secrets(rendered)
    if secret_scan.blocked:
        raise ValidationError("Normalized external envelope contains credential material.")

    run_id = str((envelope.get("provenance") or {}).get("sync_run_id") or _run_id())
    base_dir = Path(settings.DATA_DIR) / "memory" / "external_api" / source.code / _safe_name(run_id)
    object_dir = base_dir / "objects" / _safe_name(envelope["object_type"])
    object_path = object_dir / f"{_safe_name(envelope['external_id'])}.json"
    object_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(object_path, envelope)

    manifest_path = base_dir / "manifest.json"
    manifest = {
        "schema_version": "external-memory-manifest-v1",
        "source_code": source.code,
        "run_id": run_id,
        "created_at": timezone.now().isoformat(),
        "queue_backend": getattr(settings, "LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND", "sqlite"),
        "retention": _external_connector_config(source).get("retention", {}),
        "objects": [{"path": str(object_path), "content_hash": envelope["content_hash"]}],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(manifest_path, manifest)

    raw_mode = _external_connector_config(source).get("raw_mode", "normalized_only")
    if raw_response is not None and raw_mode == "short_lived_raw_quarantine":
        raw_path = base_dir / "raw_quarantine" / _safe_name(envelope["object_type"]) / f"{_safe_name(envelope['external_id'])}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            raw_path,
            {
                "source_code": source.code,
                "run_id": run_id,
                "external_id": envelope["external_id"],
                "retention_class": "short_lived_raw_quarantine",
                "created_at": timezone.now().isoformat(),
                "raw_response": raw_response,
            },
        )
    return object_path


def process_external_connector_jobs(*, limit: int = 10, lease_seconds: int = 300) -> list[dict]:
    backend = get_external_queue_backend()
    results = []
    for job in backend.lease(limit=limit, lease_seconds=lease_seconds):
        try:
            result = process_external_connector_job(job)
            backend.complete(job.job_id, result=result)
            results.append({"job_id": job.job_id, "status": ExternalJobStatus.SUCCEEDED, "result": result})
        except Exception as exc:
            failed = backend.fail(job.job_id, error_message=str(exc))
            results.append({"job_id": job.job_id, "status": failed.status, "error": str(exc)})
    return results


def process_external_connector_job(job: ExternalQueueJob) -> dict:
    if job.job_kind != ExternalJobKind.HANDOFF_EXTERNAL_OBJECT_TO_MEMORY:
        raise ValidationError(f"Unsupported external connector job kind: {job.job_kind}")
    envelope_path = Path(job.payload.get("envelope_path", ""))
    if not envelope_path.exists():
        raise ValidationError("External connector envelope_path does not exist.")
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    return handoff_external_envelope_to_memory(envelope=envelope, envelope_path=envelope_path)


def handoff_external_envelope_to_memory(*, envelope: dict, envelope_path: Path | None = None) -> dict:
    validate_external_envelope(envelope)
    source = MemorySource.objects.get(code=envelope["source_code"])
    source_object_id = _source_object_id(envelope)
    if envelope["operation"] == "delete":
        updated = MemorySnapshot.objects.filter(source=source, source_object_id=source_object_id, is_active=True).update(
            is_active=False,
            valid_to=timezone.now(),
            updated_at=timezone.now(),
        )
        return {"operation": "delete", "source_object_id": source_object_id, "deactivated_snapshots": updated}

    safe_text = render_external_envelope_text(envelope)
    with transaction.atomic():
        MemorySnapshot.objects.filter(source=source, source_object_id=source_object_id, is_active=True).update(
            is_active=False,
            valid_to=timezone.now(),
            updated_at=timezone.now(),
        )
        snapshot_defaults = {
            "schema_version": envelope["schema_version"],
            "extractor_version": "external-api-mvp-v1",
            "status": MemorySnapshot.Status.READY,
            "extracted_at": timezone.now(),
            "valid_to": None,
            "is_active": True,
            "raw_path": str(envelope_path or envelope.get("external_url") or f"external:{source_object_id}"),
            "pii_policy_applied": source.pii_policy or "deidentify_before_index",
            "scope_tokens": list(envelope.get("scope_tokens") or ["org:default"]),
            "sensitivity": envelope.get("sensitivity") or source.sensitivity,
            "metadata": {
                "external": {
                    "collection": envelope["collection"],
                    "object_type": envelope["object_type"],
                    "external_id": envelope["external_id"],
                    "external_url": envelope.get("external_url", ""),
                    "source_updated_at": envelope.get("source_updated_at", ""),
                },
                "provenance": envelope.get("provenance", {}),
                "retention_class": envelope.get("retention_class", ""),
            },
        }
        snapshot, _ = MemorySnapshot.objects.update_or_create(
            source=source,
            source_object_id=source_object_id,
            content_hash=envelope["content_hash"],
            defaults=snapshot_defaults,
        )
    indexed = index_snapshot_text(
        snapshot=snapshot,
        safe_text=safe_text,
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    )
    return {"operation": "upsert", "snapshot_id": snapshot.id, **indexed}


def validate_external_envelope(envelope: dict):
    if not isinstance(envelope, dict):
        raise ValidationError("External envelope must be a JSON object.")
    required = {
        "schema_version",
        "source_code",
        "collection",
        "object_type",
        "external_id",
        "operation",
        "content_hash",
        "payload",
        "scope_tokens",
        "sensitivity",
        "provenance",
    }
    missing = required - set(envelope.keys())
    if missing:
        raise ValidationError(f"External envelope misses required fields: {', '.join(sorted(missing))}.")
    if envelope["schema_version"] != ENVELOPE_SCHEMA_VERSION:
        raise ValidationError("Unsupported external envelope schema_version.")
    if envelope["operation"] not in {"upsert", "delete"}:
        raise ValidationError("External envelope operation must be 'upsert' or 'delete'.")
    if not isinstance(envelope.get("payload"), dict):
        raise ValidationError("External envelope payload must be a JSON object.")
    if not isinstance(envelope.get("scope_tokens"), list) or not envelope["scope_tokens"]:
        raise ValidationError("External envelope scope_tokens must be a non-empty list.")


def render_external_envelope_text(envelope: dict) -> str:
    payload = envelope.get("payload") or {}
    lines = [
        f"Source: {envelope.get('source_code', '')}",
        f"Collection: {envelope.get('collection', '')}",
        f"Object type: {envelope.get('object_type', '')}",
        f"External id: {envelope.get('external_id', '')}",
    ]
    if envelope.get("title"):
        lines.append(f"Title: {envelope['title']}")
    for key in sorted(payload):
        value = payload[key]
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines).strip() + "\n"


def _job_from_row(row) -> ExternalQueueJob:
    return ExternalQueueJob(
        job_id=row["job_id"],
        source_code=row["source_code"],
        job_kind=row["job_kind"],
        status=row["status"],
        priority=row["priority"],
        payload=json.loads(row["payload_json"] or "{}"),
        result=json.loads(row["result_json"] or "{}"),
        error_message=row["error_message"],
        idempotency_key=row["idempotency_key"],
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        request_id=row["request_id"],
    )


def _connect_path() -> Path:
    return Path(settings.LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH)


def _now_iso() -> str:
    return timezone.now().isoformat()


def _future_iso(seconds: int) -> str:
    return (timezone.now() + timezone.timedelta(seconds=seconds)).isoformat()


def _run_id() -> str:
    return timezone.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value))
    return safe.strip(".-") or "item"


def _sha256_json(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _source_object_id(envelope: dict) -> str:
    return f"external:{envelope['collection']}:{envelope['object_type']}:{envelope['external_id']}"


def _external_connector_config(source: MemorySource) -> dict:
    return (source.config or {}).get("external_connector", {}) or {}
