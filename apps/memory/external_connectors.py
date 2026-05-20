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
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from apps.core.json_utils import atomic_write_json

from .ingestion import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, index_snapshot_text
from .models import MemorySnapshot, MemorySource
from .security import scan_for_secrets


ENVELOPE_SCHEMA_VERSION = "external-memory-envelope-v1"
MANIFEST_SCHEMA_VERSION = "external-memory-manifest-v1"
CONNECTOR_VERSION = "external-api-mvp-v1"


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

    def list_recent(self, *, statuses: list[str] | None = None, limit: int = 20) -> list[ExternalQueueJob]:
        limit = max(1, min(int(limit), 200))
        params: list[str | int] = []
        where = ""
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            where = f"WHERE status IN ({placeholders})"
            params.extend(statuses)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM external_connector_jobs
                {where}
                ORDER BY updated_at DESC, created_at DESC, job_id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_job_from_row(row) for row in rows]

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


@dataclass(frozen=True)
class ExternalCleanupEntry:
    path: str
    artifact_kind: str
    retention_days: int
    expired_at: str
    removed: bool


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
            "connector_version": CONNECTOR_VERSION,
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
    assert_external_upsert_not_stale(source=source, envelope=envelope)
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

    issues = []
    raw_path = None
    raw_mode = _external_connector_config(source).get("raw_mode", "normalized_only")
    if raw_response is not None and raw_mode == "short_lived_raw_quarantine":
        raw_scan = scan_external_raw_response_for_secrets(raw_response)
        if raw_scan.blocked:
            issues.append(
                {
                    "issue_kind": "raw_quarantine_secret_detected",
                    "severity": "error",
                    "created_at": timezone.now().isoformat(),
                    "external_id": envelope["external_id"],
                    "object_type": envelope["object_type"],
                    "dlp": raw_scan.as_dict(),
                    "action": "raw_response_not_written",
                }
            )
        else:
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

    issues_path = base_dir / "issues.jsonl"
    if issues:
        issues_path.parent.mkdir(parents=True, exist_ok=True)
        with issues_path.open("a", encoding="utf-8") as issue_file:
            for issue in issues:
                issue_file.write(json.dumps(issue, ensure_ascii=False, sort_keys=True) + "\n")

    manifest_path = base_dir / "manifest.json"
    manifest = _load_existing_manifest(manifest_path)
    now_iso = timezone.now().isoformat()
    manifest.update(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "connector_version": (envelope.get("provenance") or {}).get("connector_version") or CONNECTOR_VERSION,
            "source_code": source.code,
            "run_id": run_id,
            "started_at": manifest.get("started_at") or now_iso,
            "finished_at": now_iso,
            "created_at": manifest.get("created_at") or now_iso,
            "queue_backend": getattr(settings, "LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND", "sqlite"),
            "retention": _external_connector_config(source).get("retention", {}),
            "retention_class": envelope.get("retention_class", "external_default"),
            "cursor_state": (envelope.get("provenance") or {}).get("cursor_state") or manifest.get("cursor_state") or {},
            "issues_path": str(issues_path) if issues_path.exists() else manifest.get("issues_path", ""),
        }
    )
    objects = {
        item.get("path"): item
        for item in manifest.get("objects", [])
        if isinstance(item, dict) and item.get("path")
    }
    object_entry = {
        "path": str(object_path),
        "content_hash": envelope["content_hash"],
        "operation": envelope["operation"],
        "collection": envelope["collection"],
        "object_type": envelope["object_type"],
        "external_id": envelope["external_id"],
        "source_updated_at": envelope.get("source_updated_at", ""),
    }
    if raw_path:
        object_entry["raw_path"] = str(raw_path)
    objects[str(object_path)] = object_entry
    manifest["objects"] = list(objects.values())
    manifest["object_count"] = len(manifest["objects"])
    manifest["error_count"] = int(manifest.get("error_count") or 0) + len(issues)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(manifest_path, manifest)

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
    assert_external_upsert_not_stale(source=source, envelope=envelope)
    source_object_id = _source_object_id(envelope)
    if envelope["operation"] == "delete":
        updated = MemorySnapshot.objects.filter(source=source, source_object_id=source_object_id, is_active=True).update(
            is_active=False,
            valid_to=timezone.now(),
            updated_at=timezone.now(),
        )
        append_external_tombstone(source=source, envelope=envelope)
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
    expected_hash = expected_external_content_hash(envelope)
    if envelope["content_hash"] != expected_hash:
        raise ValidationError("External envelope content_hash does not match canonical payload.")


def expected_external_content_hash(envelope: dict) -> str:
    return _sha256_json(
        {
            "operation": envelope.get("operation"),
            "source_code": envelope.get("source_code"),
            "collection": envelope.get("collection"),
            "object_type": envelope.get("object_type"),
            "external_id": envelope.get("external_id"),
            "title": envelope.get("title", ""),
            "payload": envelope.get("payload") or {},
            "source_updated_at": envelope.get("source_updated_at", ""),
        }
    )


def scan_external_raw_response_for_secrets(raw_response: dict):
    return scan_for_secrets(_render_json_for_secret_scan(raw_response or {}))


def append_external_tombstone(*, source: MemorySource, envelope: dict) -> Path:
    tombstone_path = _external_tombstone_path(source=source, envelope=envelope)
    tombstone_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "source_code": source.code,
        "collection": envelope["collection"],
        "object_type": envelope["object_type"],
        "external_id": envelope["external_id"],
        "source_object_id": _source_object_id(envelope),
        "source_updated_at": envelope.get("source_updated_at", ""),
        "content_hash": envelope["content_hash"],
        "deleted_at": timezone.now().isoformat(),
        "provenance": envelope.get("provenance", {}),
    }
    with tombstone_path.open("a", encoding="utf-8") as tombstone_file:
        tombstone_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return tombstone_path


def assert_external_upsert_not_stale(*, source: MemorySource, envelope: dict) -> None:
    if envelope.get("operation") != "upsert":
        return
    tombstone = latest_external_tombstone(source=source, envelope=envelope)
    if not tombstone:
        return
    upsert_updated_at = _parse_optional_datetime(envelope.get("source_updated_at", ""))
    deleted_source_updated_at = _parse_optional_datetime(tombstone.get("source_updated_at", ""))
    if upsert_updated_at is None or deleted_source_updated_at is None:
        raise ValidationError("External upsert is older than, or not comparable with, a durable tombstone.")
    if upsert_updated_at <= deleted_source_updated_at:
        raise ValidationError("External upsert is older than, or not comparable with, a durable tombstone.")


def latest_external_tombstone(*, source: MemorySource, envelope: dict) -> dict | None:
    tombstone_path = _external_tombstone_path(source=source, envelope=envelope)
    if not tombstone_path.exists():
        return None
    latest = None
    for line in tombstone_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("external_id") == envelope.get("external_id"):
            latest = record
    return latest


def clean_external_connector_artifacts(
    *,
    source_code: str | None = None,
    dry_run: bool = True,
    now=None,
) -> list[ExternalCleanupEntry]:
    now = now or timezone.now()
    sources = MemorySource.objects.filter(config__has_key="external_connector")
    if source_code:
        sources = sources.filter(code=source_code)
    entries: list[ExternalCleanupEntry] = []
    for source in sources:
        retention = _external_connector_config(source).get("retention", {}) or {}
        source_dir = Path(settings.DATA_DIR) / "memory" / "external_api" / source.code
        entries.extend(
            _cleanup_glob(
                base_dir=source_dir,
                pattern="*/raw_quarantine/**/*.json",
                artifact_kind="raw_quarantine",
                retention_days=int(retention.get("raw_quarantine_days", 14)),
                dry_run=dry_run,
                now=now,
            )
        )
        entries.extend(
            _cleanup_glob(
                base_dir=source_dir,
                pattern="*/objects/**/*.json",
                artifact_kind="normalized_envelope",
                retention_days=int(retention.get("normalized_envelope_days", 90)),
                dry_run=dry_run,
                now=now,
            )
        )
        entries.extend(
            _cleanup_glob(
                base_dir=source_dir,
                pattern="*/manifest.json",
                artifact_kind="manifest",
                retention_days=int(retention.get("manifest_days", 365)),
                dry_run=dry_run,
                now=now,
            )
        )
        entries.extend(
            _cleanup_glob(
                base_dir=source_dir,
                pattern="*/issues.jsonl",
                artifact_kind="issues",
                retention_days=int(retention.get("manifest_days", 365)),
                dry_run=dry_run,
                now=now,
            )
        )
        entries.extend(
            _cleanup_glob(
                base_dir=source_dir,
                pattern="tombstones/**/*.jsonl",
                artifact_kind="tombstone",
                retention_days=int(retention.get("tombstone_days", 1095)),
                dry_run=dry_run,
                now=now,
            )
        )
        if not dry_run:
            _remove_empty_dirs(source_dir)
    return entries


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


def _render_json_for_secret_scan(value, *, prefix: str = "") -> str:
    if isinstance(value, dict):
        lines = []
        for key in sorted(value):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            lines.append(_render_json_for_secret_scan(value[key], prefix=child_prefix))
        return "\n".join(line for line in lines if line)
    if isinstance(value, list):
        return "\n".join(_render_json_for_secret_scan(item, prefix=prefix) for item in value)
    return f"{prefix}: {value}"


def _load_existing_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _external_tombstone_path(*, source: MemorySource, envelope: dict) -> Path:
    return (
        Path(settings.DATA_DIR)
        / "memory"
        / "external_api"
        / source.code
        / "tombstones"
        / _safe_name(envelope["collection"])
        / f"{_safe_name(envelope['object_type'])}.jsonl"
    )


def _parse_optional_datetime(value: str):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _cleanup_glob(
    *,
    base_dir: Path,
    pattern: str,
    artifact_kind: str,
    retention_days: int,
    dry_run: bool,
    now,
) -> list[ExternalCleanupEntry]:
    if retention_days < 0 or not base_dir.exists():
        return []
    cutoff = now - timezone.timedelta(days=retention_days)
    entries: list[ExternalCleanupEntry] = []
    for path in base_dir.glob(pattern):
        if not path.is_file():
            continue
        modified_at = timezone.datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.get_current_timezone())
        if modified_at > cutoff:
            continue
        removed = False
        if not dry_run:
            path.unlink(missing_ok=True)
            removed = True
        entries.append(
            ExternalCleanupEntry(
                path=str(path),
                artifact_kind=artifact_kind,
                retention_days=retention_days,
                expired_at=cutoff.isoformat(),
                removed=removed,
            )
        )
    return entries


def _remove_empty_dirs(base_dir: Path) -> None:
    if not base_dir.exists():
        return
    for path in sorted((item for item in base_dir.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            continue
