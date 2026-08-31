"""Единое чтение типизированных документов настроек.

Репозиторий не кэширует значения между запросами и процессами. Для связанной
группы документов PostgreSQL-строки читаются одним запросом, после чего каждый
потребитель получает глубокую копию проверенного снимка.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from apps.core.json_utils import load_json_file

from .document_hashes import InvalidDocumentPayload, document_hash, is_document_hash
from .document_registry import ConfigDocumentRegistry, get_document_registry
from .document_security import RawSecretValueError, assert_no_raw_secrets
from .models import RuntimeSettingDocument


class DocumentRepositoryError(RuntimeError):
    pass


class ConfigurationUnavailable(DocumentRepositoryError):
    """Критичный документ не может быть безопасно прочитан."""


class UnsupportedDocumentBackend(DocumentRepositoryError):
    pass


class DocumentSchemaMismatch(DocumentRepositoryError):
    pass


class DocumentMetadataCorrupt(DocumentRepositoryError):
    pass


class DocumentHashMismatch(DocumentRepositoryError):
    pass


@dataclass(frozen=True)
class RuntimeSettingSnapshot:
    document_id: str
    payload: Any
    source: str
    schema_version: int
    revision: int
    content_hash: str
    default_hash: str
    degraded: bool = False
    degradation_reason: str = ""
    migration_required: bool = False
    change_id: int | None = None

    def copy(self) -> "RuntimeSettingSnapshot":
        return replace(self, payload=deepcopy(self.payload))


_degradation_state: dict[str, dict[str, Any]] = {}


def get_document_degradation_state() -> dict[str, Any]:
    documents = deepcopy(_degradation_state)
    return {
        "degraded": any(item.get("degraded", False) for item in documents.values()),
        "migration_required": any(
            item["status"] == "migration_required" for item in documents.values()
        ),
        "documents": documents,
    }


def reset_document_degradation_state_for_tests() -> None:
    _degradation_state.clear()


class ConfigDocumentRepository:
    def __init__(self, registry: ConfigDocumentRegistry | None = None):
        self.registry = registry or get_document_registry()

    def get_document(self, document_id: str, *, request=None) -> RuntimeSettingSnapshot:
        return self.get_snapshot((document_id,), request=request)[document_id]

    def get_snapshot(
        self,
        document_ids: Iterable[str],
        *,
        request=None,
    ) -> dict[str, RuntimeSettingSnapshot]:
        requested = tuple(dict.fromkeys(str(item) for item in document_ids))
        if not requested:
            return {}
        for document_id in requested:
            self.registry.get(document_id)

        scope = self._connected_validation_scope(requested)
        cache = self._request_cache(request)
        missing = [document_id for document_id in scope if document_id not in cache]
        if missing:
            # Всю связанную компоненту читаем повторно только если до этого ни
            # один её документ не был зафиксирован запросом. Это не позволяет
            # смешать две ревизии зависимых документов внутри HTTP request.
            already_cached = set(scope) - set(missing)
            if already_cached:
                raise ConfigurationUnavailable(
                    "Связанная группа настроек была запрошена неполным снимком."
                )
            cache.update(self._load_scope(scope))
        return {document_id: cache[document_id].copy() for document_id in requested}

    def _load_scope(self, document_ids: Iterable[str]) -> dict[str, RuntimeSettingSnapshot]:
        specs = [self.registry.get(document_id) for document_id in sorted(document_ids)]
        generated = [
            spec.document_id
            for spec in specs
            if spec.active_backend not in {"git", "legacy_file", "database"}
        ]
        if generated:
            raise UnsupportedDocumentBackend(
                "Документы не имеют читаемого value backend: " + ", ".join(generated)
            )

        database_ids = [spec.document_id for spec in specs if spec.active_backend == "database"]
        rows = RuntimeSettingDocument.objects.filter(document_id__in=database_ids).in_bulk()

        snapshots: dict[str, RuntimeSettingSnapshot] = {}
        defaults: dict[str, Any] = {}
        for spec in specs:
            try:
                default_payload = self._load_default(spec)
                default_hash = document_hash(default_payload)
            except (OSError, ValueError, DocumentRepositoryError) as exc:
                self._mark_degraded(
                    spec.document_id,
                    code="default_unavailable",
                    fallback=False,
                )
                raise ConfigurationUnavailable(
                    f"Git-дефолт '{spec.document_id}' недоступен."
                ) from exc
            defaults[spec.document_id] = default_payload
            try:
                snapshot = self._build_snapshot(
                    spec=spec,
                    row=rows.get(spec.document_id),
                    default_payload=default_payload,
                    default_hash=default_hash,
                )
                self._validate_payload(spec, snapshot.payload)
            except (OSError, ValueError, ValidationError, DocumentRepositoryError) as exc:
                snapshot = self._handle_failure(
                    spec=spec,
                    default_payload=default_payload,
                    default_hash=default_hash,
                    exc=exc,
                )
            snapshots[spec.document_id] = snapshot

        snapshots = self._resolve_cross_validation(specs, snapshots, defaults)
        for spec in specs:
            snapshot = snapshots[spec.document_id]
            if snapshot.migration_required:
                self._mark_migration_required(
                    spec.document_id,
                    code=snapshot.degradation_reason or "default_drift",
                    degraded=snapshot.degraded,
                    fallback=snapshot.source == "git_default_fallback",
                )
            elif snapshot.degraded:
                continue
            else:
                _degradation_state.pop(spec.document_id, None)
        return snapshots

    def _resolve_cross_validation(self, specs, snapshots, defaults):
        """Применить допустимые fallback и затем проверить весь итоговый срез."""

        fallback_ids = {
            document_id
            for document_id, snapshot in snapshots.items()
            if snapshot.degraded
        }
        for _iteration in range(len(specs) + 1):
            payloads = {
                document_id: snapshot.payload
                for document_id, snapshot in snapshots.items()
            }
            violations = []
            for spec in specs:
                if spec.cross_validator is None:
                    continue
                related = {item: payloads[item] for item in spec.cross_document_ids}
                try:
                    spec.cross_validator(
                        deepcopy(payloads[spec.document_id]),
                        deepcopy(related),
                    )
                except (ValueError, ValidationError) as exc:
                    violations.append((spec, exc))
            if not violations:
                return snapshots

            changed = False
            for spec, exc in violations:
                if (
                    spec.failure_policy != "visible_default_fallback"
                    or spec.document_id in fallback_ids
                ):
                    self._mark_degraded(
                        spec.document_id,
                        code="cross_validation_failed",
                        fallback=False,
                    )
                    raise ConfigurationUnavailable(
                        f"Связанные настройки '{spec.document_id}' невалидны."
                    ) from exc
                fallback = defaults[spec.document_id]
                try:
                    self._validate_payload(spec, fallback)
                except (ValueError, ValidationError, InvalidDocumentPayload) as fallback_exc:
                    self._mark_degraded(
                        spec.document_id,
                        code="default_validation_failed",
                        fallback=False,
                    )
                    raise ConfigurationUnavailable(
                        f"Git-дефолт связанных настроек '{spec.document_id}' невалиден."
                    ) from fallback_exc
                fallback_hash = document_hash(fallback)
                snapshots[spec.document_id] = RuntimeSettingSnapshot(
                    document_id=spec.document_id,
                    payload=deepcopy(fallback),
                    source="git_default_fallback",
                    schema_version=spec.schema_version,
                    revision=0,
                    content_hash=fallback_hash,
                    default_hash=fallback_hash,
                    degraded=True,
                    degradation_reason="cross_validation_failed",
                )
                fallback_ids.add(spec.document_id)
                self._mark_degraded(
                    spec.document_id,
                    code="cross_validation_failed",
                    fallback=True,
                )
                changed = True
            if not changed:
                break
        raise ConfigurationUnavailable("Связанный срез настроек не удалось стабилизировать.")

    def _build_snapshot(self, *, spec, row, default_payload, default_hash):
        if spec.active_backend == "git":
            return RuntimeSettingSnapshot(
                document_id=spec.document_id,
                payload=deepcopy(default_payload),
                source="git_static",
                schema_version=spec.schema_version,
                revision=0,
                content_hash=default_hash,
                default_hash=default_hash,
            )
        if spec.active_backend == "legacy_file":
            payload = load_json_file(self._legacy_path(spec))
            return RuntimeSettingSnapshot(
                document_id=spec.document_id,
                payload=payload,
                source="legacy_file",
                schema_version=spec.schema_version,
                revision=0,
                content_hash=document_hash(payload),
                default_hash=default_hash,
                migration_required=document_hash(payload) != default_hash,
            )
        if spec.active_backend != "database":
            raise UnsupportedDocumentBackend(spec.active_backend)
        if row is None:
            return RuntimeSettingSnapshot(
                document_id=spec.document_id,
                payload=deepcopy(default_payload),
                source="git_default",
                schema_version=spec.schema_version,
                revision=0,
                content_hash=default_hash,
                default_hash=default_hash,
            )
        if row.schema_version != spec.schema_version:
            raise DocumentSchemaMismatch(
                f"Неподдерживаемая schema version документа '{spec.document_id}'."
            )
        if row.revision < 1 or not is_document_hash(row.content_hash) or not is_document_hash(row.default_hash):
            raise DocumentMetadataCorrupt(
                f"Повреждены метаданные документа '{spec.document_id}'."
            )
        actual_hash = document_hash(row.payload)
        if actual_hash != row.content_hash:
            raise DocumentHashMismatch(
                f"Не совпадает хеш документа '{spec.document_id}'."
            )
        return RuntimeSettingSnapshot(
            document_id=spec.document_id,
            payload=deepcopy(row.payload),
            source="database_override",
            schema_version=row.schema_version,
            revision=row.revision,
            content_hash=row.content_hash,
            default_hash=default_hash,
            migration_required=row.default_hash != default_hash,
        )

    def _handle_failure(self, *, spec, default_payload, default_hash, exc):
        code = self._error_code(exc)
        if spec.failure_policy != "visible_default_fallback":
            self._mark_degraded(spec.document_id, code=code, fallback=False)
            raise ConfigurationUnavailable(
                f"Настройки '{spec.document_id}' недоступны."
            ) from exc
        try:
            self._validate_payload(spec, default_payload)
        except (ValueError, ValidationError, InvalidDocumentPayload) as default_exc:
            self._mark_degraded(
                spec.document_id,
                code="default_validation_failed",
                fallback=False,
            )
            raise ConfigurationUnavailable(
                f"Настройки и Git-дефолт '{spec.document_id}' невалидны."
            ) from default_exc
        self._mark_degraded(spec.document_id, code=code, fallback=True)
        return RuntimeSettingSnapshot(
            document_id=spec.document_id,
            payload=deepcopy(default_payload),
            source="git_default_fallback",
            schema_version=spec.schema_version,
            revision=0,
            content_hash=default_hash,
            default_hash=default_hash,
            degraded=True,
            degradation_reason=code,
            migration_required=isinstance(exc, DocumentSchemaMismatch),
        )

    @staticmethod
    def _validate_payload(spec, payload) -> None:
        assert_no_raw_secrets(payload)
        document_hash(payload)
        if spec.validator is not None:
            spec.validator(deepcopy(payload))

    @staticmethod
    def _load_default(spec):
        if spec.default_path is None:
            raise UnsupportedDocumentBackend(
                f"У документа '{spec.document_id}' нет Git-дефолта."
            )
        return load_json_file(Path(settings.BASE_DIR) / spec.default_path)

    @staticmethod
    def _legacy_path(spec) -> Path:
        if spec.legacy_settings_path:
            value = getattr(settings, spec.legacy_settings_path, None)
            if value:
                return Path(value)
        if spec.default_path is None:
            raise UnsupportedDocumentBackend(
                f"У документа '{spec.document_id}' нет legacy path."
            )
        relative = Path(spec.default_path).relative_to("contracts")
        return Path(settings.RUNTIME_CONTRACTS_DIR) / relative

    def _connected_validation_scope(self, document_ids: Iterable[str]) -> tuple[str, ...]:
        return self.registry.connected_validation_scope(document_ids)

    @staticmethod
    def _request_cache(request) -> dict[str, RuntimeSettingSnapshot]:
        if request is None:
            return {}
        cache = getattr(request, "_config_document_snapshots", None)
        if cache is None:
            cache = {}
            request._config_document_snapshots = cache
        return cache

    @staticmethod
    def _mark_degraded(
        document_id: str,
        *,
        code: str,
        fallback: bool,
    ) -> None:
        _degradation_state[document_id] = {
            "status": "degraded",
            "code": code,
            "degraded": True,
            "fallback": fallback,
        }

    @staticmethod
    def _mark_migration_required(
        document_id: str,
        *,
        code: str,
        degraded: bool = False,
        fallback: bool = False,
    ) -> None:
        _degradation_state[document_id] = {
            "status": "migration_required",
            "code": code,
            "degraded": degraded,
            "fallback": fallback,
        }

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, DocumentSchemaMismatch):
            return "schema_mismatch"
        if isinstance(exc, DocumentHashMismatch):
            return "content_hash_mismatch"
        if isinstance(exc, DocumentMetadataCorrupt):
            return "metadata_corrupt"
        if isinstance(exc, InvalidDocumentPayload):
            return "invalid_json_payload"
        if isinstance(exc, RawSecretValueError):
            return "raw_secret_forbidden"
        return "validation_failed"


def get_document(document_id: str, *, request=None) -> RuntimeSettingSnapshot:
    return ConfigDocumentRepository().get_document(document_id, request=request)


def get_snapshot(document_ids: Iterable[str], *, request=None) -> Mapping[str, RuntimeSettingSnapshot]:
    return ConfigDocumentRepository().get_snapshot(document_ids, request=request)


def probe_settings_document_health() -> dict[str, Any]:
    """Активно проверить включённые DB-документы без раскрытия payload и путей."""

    registry = get_document_registry()
    repository = ConfigDocumentRepository(registry)
    database_ids = {
        spec.document_id
        for spec in registry.all()
        if spec.active_backend == "database"
    }
    documents: dict[str, dict[str, Any]] = {}
    visited: set[str] = set()
    unavailable = False
    for document_id in sorted(database_ids):
        if document_id in visited:
            continue
        scope = registry.connected_validation_scope((document_id,))
        scoped_database_ids = database_ids.intersection(scope)
        visited.update(scoped_database_ids)
        try:
            snapshots = repository.get_snapshot(scope)
        except (
            DatabaseError,
            DocumentRepositoryError,
            OSError,
            ValueError,
            ValidationError,
        ):
            unavailable = True
            state = get_document_degradation_state()["documents"]
            for scoped_id in sorted(scoped_database_ids):
                item = state.get(scoped_id, {})
                documents[scoped_id] = {
                    "status": "unavailable",
                    "code": item.get("code", "configuration_unavailable"),
                }
            continue
        state = get_document_degradation_state()["documents"]
        for scoped_id in sorted(scoped_database_ids):
            snapshot = snapshots[scoped_id]
            item = state.get(scoped_id)
            status = item["status"] if item else "ok"
            documents[scoped_id] = {
                "status": status,
                "source": snapshot.source,
                "revision": snapshot.revision,
                "schema_version": snapshot.schema_version,
                **({"code": item["code"]} if item else {}),
            }

    if unavailable:
        status = "error"
    elif any(item["status"] != "ok" for item in documents.values()):
        status = "degraded"
    else:
        status = "ok"
    return {"status": status, "documents": documents}
