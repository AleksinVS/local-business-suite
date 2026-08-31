"""Безопасное планирование и импорт legacy JSON-документов настроек.

Модуль намеренно не меняет legacy-файлы и не переключает читателей. Он связывает
старую файловую рабочую копию с уже подготовленной моделью
``RuntimeSettingDocument`` только после доказательства аудиторией того, что файл
был изменён через существующий проверенный writer.

Хеши здесь имеют две явные роли:

* ``legacy_hash`` — ``apps.core.contract_store.normalized_hash``. Именно его
  записал старый файловый writer в ``SettingsChange.after_hash``;
* ``document_hash`` — компактный канонический хеш из ``document_hashes``. Он
  хранится в новой DB-модели.

Это различие нельзя скрывать адаптером: одинаковый JSON получает разные хеши у
старого pretty-формата и нового compact-формата.
"""

from __future__ import annotations

import json
import errno
import os
import re
import secrets
import stat
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.models import F
from django.utils import timezone

from apps.core.contract_store import normalized_hash as legacy_hash
from apps.core.file_locks import access_control_write_lock_path, exclusive_file_lock

from .descriptors import mask_sensitive
from .document_hashes import canonical_json, document_hash, is_document_hash
from .document_registry import ConfigDocumentRegistry, get_document_registry
from .document_security import (
    RawSecretValueError,
    assert_no_raw_secrets,
    classify_secret_references,
)
from .document_services import advisory_lock_key
from .models import RuntimeSettingDocument, SettingsChange
from .services import build_masked_diff


IDENTICAL_DEFAULT = "identical_default"
AUDITED_OVERRIDE = "audited_override"
AMBIGUOUS_DRIFT = "ambiguous_drift"
MIGRATION_REQUIRED = "migration_required"
ENV_OVERRIDE = "env_override"
MISSING_RUNTIME = "missing_runtime"
ALREADY_IMPORTED = "already_imported"
CONFLICT = "conflict"
SECURITY_REVIEW_REQUIRED = "security_review_required"

BLOCKED_CLASSES = frozenset(
    {
        AMBIGUOUS_DRIFT,
        MIGRATION_REQUIRED,
        ENV_OVERRIDE,
        CONFLICT,
        SECURITY_REVIEW_REQUIRED,
    }
)

_ROLE_RULES_ID = "core.contract.role_rules"
_OPERATION_VERSION = 1
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class MigrationError(RuntimeError):
    """Ошибка планирования или безопасного применения миграции."""


class MigrationSliceError(MigrationError):
    """Передан неполный или недопустимый dependency slice."""


class UnsupportedMigrationBackend(MigrationError):
    """Apply требует PostgreSQL, но подключён другой backend."""


class UnsupportedMigrationPlatform(MigrationError):
    """Платформа не даёт нужных гарантий безопасной операторской записи."""


class UnsafeMigrationPath(MigrationError):
    """Операторский путь не удовлетворяет правилам безопасной записи."""


@dataclass(frozen=True)
class DocumentMigrationPlan:
    """Безопасный для вывода план одного документа без payload."""

    document_id: str
    domain: str
    storage_policy: str
    classification: str
    reason: str
    default_path: str | None
    runtime_path: str | None
    expected_runtime_path: str | None
    env_override: bool
    schema_version: int
    default_hash: str | None
    runtime_hash: str | None
    default_document_hash: str | None
    runtime_document_hash: str | None
    db_revision: int | None
    db_content_hash: str | None
    db_default_hash: str | None
    audit_change_id: int | None
    audit_after_hash: str | None
    audit_evidence: bool
    dependency_ids: tuple[str, ...] = ()
    backup_path: str | None = None
    backup_manifest_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["dependency_ids"] = list(self.dependency_ids)
        return result


@dataclass(frozen=True)
class BackupRecord:
    document_id: str
    payload_path: str
    manifest_path: str
    payload_hash: str
    document_hash: str
    manifest_hash: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _path_text(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def expected_runtime_path(spec) -> Path | None:
    if spec.default_path is None:
        return None
    relative = Path(spec.default_path).relative_to("contracts")
    return Path(settings.RUNTIME_CONTRACTS_DIR) / relative


def effective_runtime_path(spec) -> Path | None:
    expected = expected_runtime_path(spec)
    if spec.legacy_settings_path:
        configured = getattr(settings, spec.legacy_settings_path, None)
        if configured:
            return Path(configured)
    return expected


def _absolute_without_following_symlinks(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_env_override(spec, runtime_path: Path | None, expected: Path | None) -> bool:
    if runtime_path is None or expected is None:
        return False
    return _absolute_without_following_symlinks(runtime_path) != _absolute_without_following_symlinks(expected)


def _path_lstat_status(path: Path) -> str | None:
    """Проверить target и каждый существующий parent до чтения.

    ``Path.exists()`` нельзя использовать первым: dangling symlink сообщает
    ``False`` и тогда был бы ошибочно классифицирован как missing_runtime.
    """

    path = _absolute_without_following_symlinks(path)
    parts = path.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if current == path:
                return "missing"
            # A missing parent is a normal missing-runtime case. Existing
            # parents were checked before reaching it.
            return "missing"
        except OSError:
            return "unsafe_lstat"
        if stat.S_ISLNK(info.st_mode):
            return "unsafe_symlink" if current == path else "unsafe_parent_symlink"
        if current != path and not stat.S_ISDIR(info.st_mode):
            return "unsafe_parent_not_directory"
        if current == path and not stat.S_ISREG(info.st_mode):
            return "unsafe_not_file"
        if os.name == "nt" and getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            return "unsafe_reparse_point"
    return None


def _directory_lstat_status(path: Path) -> str | None:
    """Проверить существующую цепочку каталога без следования ссылкам."""

    path = _absolute_without_following_symlinks(path)
    current = Path(path.parts[0])
    for part in path.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unsafe_lstat"
        if stat.S_ISLNK(info.st_mode):
            return "unsafe_parent_symlink"
        if not stat.S_ISDIR(info.st_mode):
            return "unsafe_parent_not_directory"
        if os.name == "nt" and getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            return "unsafe_reparse_point"
    return None


def _open_directory_fd(path: Path) -> int:
    """Открыть абсолютный каталог компонентами с O_NOFOLLOW на POSIX."""

    path = _absolute_without_following_symlinks(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.sep, flags | os.O_DIRECTORY | nofollow)
    try:
        for component in path.parts[1:]:
            child = os.open(
                component,
                flags | os.O_DIRECTORY | nofollow,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_regular_file(path: Path):
    """Открыть JSON-файл без следования symlink на POSIX.

    Parent directories открываются через ``openat(..., O_NOFOLLOW)``. Это не
    устраняет чужой плохо реализованный writer, но закрывает замену target или
    parent symlink между предварительным lstat и чтением.
    """

    path = _absolute_without_following_symlinks(path)
    status = _path_lstat_status(path)
    if status is not None:
        raise FileNotFoundError(status) if status == "missing" else OSError(status)
    if os.name == "nt":
        stream = open(path, "r", encoding="utf-8")
        if _path_lstat_status(path) is not None or not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            stream.close()
            raise OSError("unsafe_race")
        return stream

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    absolute_parts = path.parts
    directory_fd = os.open(os.sep, flags | os.O_DIRECTORY | nofollow)
    try:
        for component in absolute_parts[1:-1]:
            child_fd = os.open(
                component,
                flags | os.O_DIRECTORY | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = child_fd
        target_fd = os.open(absolute_parts[-1], flags | nofollow, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    if not stat.S_ISREG(os.fstat(target_fd).st_mode):
        os.close(target_fd)
        raise OSError("unsafe_not_file")
    return os.fdopen(target_fd, "r", encoding="utf-8")


def _read_json(path: Path | None) -> tuple[Any | None, str | None]:
    if path is None:
        return None, "missing"
    status = _path_lstat_status(path)
    if status == "missing":
        return None, "missing"
    if status is not None:
        return None, status
    try:
        with _open_regular_file(path) as stream:
            payload = json.load(stream)
        # Проверяем JSON-тип и запрет неявных Python-типов до любого hash.
        canonical_json(payload)
        return payload, None
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        if getattr(exc, "errno", None) in {
            errno.ELOOP,
            errno.ENOTDIR,
            errno.EISDIR,
        } or str(exc).startswith("unsafe_"):
            return None, "unsafe_race"
        return None, f"invalid_json:{type(exc).__name__}"
    except (UnicodeError, ValueError, TypeError) as exc:
        return None, f"invalid_json:{type(exc).__name__}"


def _schema_marker(payload: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(payload, dict):
        return ()
    return tuple(
        (key, repr(payload[key]))
        for key in ("schema_version", "$schema")
        if key in payload
    )


def _schema_marker_mismatch(default_payload: Any, runtime_payload: Any) -> bool:
    """Compare payload markers independently from spec.schema_version."""

    if not isinstance(default_payload, dict) or not isinstance(runtime_payload, dict):
        return False
    for key in ("schema_version", "$schema"):
        if (key in default_payload) != (key in runtime_payload):
            return True
        if key in default_payload and repr(default_payload[key]) != repr(runtime_payload[key]):
            return True
    return False


def _validate_payload(spec, payload: Any) -> str | None:
    try:
        canonical_json(payload)
        assert_no_raw_secrets(payload)
        if spec.validator is not None:
            spec.validator(deepcopy(payload))
    except RawSecretValueError:
        return "raw_secret"
    except Exception as exc:  # noqa: BLE001 - validator API is domain-owned
        return f"schema_or_domain_validation:{type(exc).__name__}"
    return None


def _latest_audit(document_id: str):
    return (
        SettingsChange.objects.filter(
            setting_id=document_id,
            status=SettingsChange.Status.APPLIED,
            action__in=(SettingsChange.Action.APPLY, SettingsChange.Action.ROLLBACK),
        )
        .order_by(F("applied_at").desc(nulls_last=True), F("created_at").desc(), F("pk").desc())
        .first()
    )


def _role_rules_security_review(default_payload: Any, runtime_payload: Any) -> bool:
    if not isinstance(default_payload, dict) or not isinstance(runtime_payload, dict):
        return False
    # Role defaults/viewer are access semantics, not ordinary drift. Missing
    # sections must be reviewed even if an old audit row happens to exist.
    return any(
        key in default_payload and key not in runtime_payload
        for key in ("$defaults", "viewer")
    )


def _db_row_state(row, default_payload: Any, spec) -> tuple[str | None, str | None]:
    """Validate row metadata and return ``(error, compact_payload_hash)``."""

    if row is None:
        return None, None
    if row.schema_version != spec.schema_version:
        return "schema_version_mismatch", None
    if row.revision < 1 or not is_document_hash(row.content_hash) or not is_document_hash(row.default_hash):
        return "db_metadata_corrupt", None
    try:
        compact = document_hash(row.payload)
    except Exception:
        return "db_payload_invalid", None
    if compact != row.content_hash:
        return "db_content_hash_mismatch", compact
    validation_error = _validate_payload(spec, row.payload)
    if validation_error == "raw_secret":
        return "db_raw_secret", compact
    if validation_error is not None:
        return "db_payload_schema_invalid", compact
    return None, compact


def classify_document(spec, *, registry: ConfigDocumentRegistry | None = None) -> DocumentMigrationPlan:
    """Classify one registered document without writing files or database rows."""

    del registry  # reserved for callers that keep a registry alongside the spec
    default_path = Path(settings.BASE_DIR) / spec.default_path if spec.default_path else None
    runtime_path = effective_runtime_path(spec)
    expected_path = expected_runtime_path(spec)
    env_override = _is_env_override(spec, runtime_path, expected_path)
    default_payload, default_error = _read_json(default_path)
    runtime_payload, runtime_error = _read_json(runtime_path)
    row = RuntimeSettingDocument.objects.filter(document_id=spec.document_id).first()
    row_error, row_compact_hash = _db_row_state(row, default_payload, spec)
    default_legacy = default_compact = runtime_legacy = runtime_compact = None
    if default_payload is not None:
        try:
            default_legacy = legacy_hash(default_payload)
            default_compact = document_hash(default_payload)
        except Exception:
            default_error = default_error or "invalid_default_payload"
    if runtime_payload is not None:
        try:
            runtime_legacy = legacy_hash(runtime_payload)
            runtime_compact = document_hash(runtime_payload)
        except Exception:
            runtime_error = runtime_error or "invalid_runtime_payload"

    if default_payload is not None:
        default_error = default_error or _validate_payload(spec, default_payload)
    if runtime_payload is not None:
        runtime_error = runtime_error or _validate_payload(spec, runtime_payload)

    marker_mismatch = (
        default_payload is not None
        and runtime_payload is not None
        and _schema_marker_mismatch(default_payload, runtime_payload)
    )
    if row is not None and default_payload is not None:
        marker_mismatch = marker_mismatch or _schema_marker_mismatch(
            default_payload, row.payload
        )

    latest = _latest_audit(spec.document_id)
    unresolved = SettingsChange.objects.filter(
        setting_id=spec.document_id,
        action__in=(SettingsChange.Action.APPLY, SettingsChange.Action.ROLLBACK),
        status__in=(SettingsChange.Status.PENDING, SettingsChange.Status.INCONSISTENT),
    ).exists()
    audit_after = str(latest.after_hash or "") if latest is not None else None
    evidence = bool(
        latest is not None
        and runtime_legacy is not None
        and audit_after == runtime_legacy
    )
    reason = ""

    if default_error:
        classification, reason = CONFLICT, f"default:{default_error}"
    elif env_override:
        classification, reason = ENV_OVERRIDE, "legacy path is overridden outside runtime contracts"
    elif unresolved:
        classification, reason = CONFLICT, "unresolved audit state exists"
    elif runtime_error == "raw_secret":
        classification, reason = CONFLICT, "runtime:raw_secret"
    elif marker_mismatch:
        classification, reason = MIGRATION_REQUIRED, "top-level payload schema marker differs"
    elif runtime_error and runtime_error.startswith("unsafe"):
        classification, reason = CONFLICT, "runtime path is unsafe"
    elif row_error:
        classification = MIGRATION_REQUIRED if row_error == "schema_version_mismatch" else CONFLICT
        reason = f"database:{row_error}"
    elif row is not None and runtime_error not in (None, "missing"):
        classification, reason = CONFLICT, "legacy runtime exists but is unreadable or invalid"
    elif row is not None:
        # Existing DB state is authoritative only if it is self-consistent and
        # agrees with the still-present legacy file when that file exists.
        if runtime_payload is not None and row_compact_hash != runtime_compact:
            classification, reason = CONFLICT, "database row and legacy runtime payload differ"
        elif row.default_hash != default_compact:
            classification, reason = MIGRATION_REQUIRED, "database row points to an old Git default"
        else:
            classification, reason = ALREADY_IMPORTED, "matching RuntimeSettingDocument already exists"
    elif runtime_error == "missing":
        classification, reason = MISSING_RUNTIME, "legacy runtime file is absent"
    elif runtime_error:
        classification = CONFLICT if runtime_error == "raw_secret" else MIGRATION_REQUIRED
        reason = f"runtime:{runtime_error}"
    elif runtime_payload is not None:
        if runtime_legacy == default_legacy:
            classification, reason = IDENTICAL_DEFAULT, "legacy runtime equals Git default"
        elif spec.document_id == _ROLE_RULES_ID and _role_rules_security_review(default_payload, runtime_payload):
            classification, reason = SECURITY_REVIEW_REQUIRED, "role defaults/viewer drift requires access review"
        elif (
            isinstance(default_payload, dict)
            and isinstance(runtime_payload, dict)
            and set(default_payload) - set(runtime_payload)
        ):
            classification, reason = MIGRATION_REQUIRED, "Git default has keys missing from runtime payload"
        elif evidence:
            classification, reason = AUDITED_OVERRIDE, "latest applied audit proves this legacy runtime payload"
        else:
            classification, reason = AMBIGUOUS_DRIFT, "no latest applied audit proves this runtime payload"
    else:
        classification, reason = CONFLICT, "runtime payload could not be read"

    return DocumentMigrationPlan(
        document_id=spec.document_id,
        domain=spec.domain,
        storage_policy=spec.storage_policy,
        classification=classification,
        reason=reason,
        default_path=spec.default_path,
        runtime_path=_path_text(runtime_path),
        expected_runtime_path=_path_text(expected_path),
        env_override=env_override,
        schema_version=spec.schema_version,
        default_hash=default_legacy,
        runtime_hash=runtime_legacy,
        default_document_hash=default_compact,
        runtime_document_hash=runtime_compact,
        db_revision=row.revision if row is not None else None,
        db_content_hash=row.content_hash if row is not None else None,
        db_default_hash=row.default_hash if row is not None else None,
        audit_change_id=latest.pk if latest is not None else None,
        audit_after_hash=audit_after,
        audit_evidence=evidence,
        dependency_ids=tuple(spec.cross_document_ids),
    )


def _select_specs(
    document_ids: Sequence[str] | None,
    registry: ConfigDocumentRegistry,
) -> tuple[Any, ...]:
    if document_ids:
        requested = tuple(dict.fromkeys(str(item) for item in document_ids))
        for document_id in requested:
            spec = registry.get(document_id)
            if spec.storage_policy != "database_override":
                raise MigrationSliceError(
                    f"Документ '{document_id}' не является database_override."
                )
            if spec.active_backend != "legacy_file":
                raise MigrationSliceError(
                    f"Документ '{document_id}' уже не использует legacy_file; "
                    "его нельзя импортировать повторно."
                )
        connected = registry.connected_validation_scope(requested)
        if set(connected) != set(requested):
            missing = sorted(set(connected) - set(requested))
            raise MigrationSliceError(
                "Для связанного среза нужны все документы: " + ", ".join(missing)
            )
        selected = requested
    else:
        selected = tuple(
            spec.document_id
            for spec in registry.all()
            if spec.storage_policy == "database_override"
            and spec.active_backend == "legacy_file"
        )
    return tuple(registry.get(document_id) for document_id in sorted(selected))


def plan_migration(
    document_ids: Sequence[str] | None = None,
    *,
    registry: ConfigDocumentRegistry | None = None,
) -> tuple[DocumentMigrationPlan, ...]:
    """Return a stable, read-only plan for database_override documents."""

    registry = registry or get_document_registry()
    specs = _select_specs(document_ids, registry)
    try:
        plans = [classify_document(spec, registry=registry) for spec in specs]
    except DatabaseError as exc:
        raise MigrationError(
            "Хранилище документов настроек недоступно; сначала выполните миграции БД."
        ) from exc

    # Cross-document validation is meaningful only for an otherwise importable
    # connected slice.  It uses the effective payload that apply will use:
    # an existing DB row, an audited legacy override, or the Git default for a
    # successful no-op.  This makes plan/apply agree before any backup is made.
    if not any(item.classification in BLOCKED_CLASSES for item in plans):
        effective: dict[str, Any] = {}
        for index, (spec, item) in enumerate(zip(specs, plans)):
            row = RuntimeSettingDocument.objects.filter(document_id=spec.document_id).first()
            if row is not None:
                effective[spec.document_id] = deepcopy(row.payload)
                continue
            if item.classification == AUDITED_OVERRIDE:
                payload, error = _read_json(effective_runtime_path(spec))
            else:
                payload, error = _read_json(Path(settings.BASE_DIR) / spec.default_path)
            if error or payload is None:
                plans[index] = replace(
                    item,
                    classification=CONFLICT,
                    reason="effective payload became unavailable during planning",
                )
                continue
            effective[spec.document_id] = deepcopy(payload)
        if len(effective) == len(specs):
            for index, spec in enumerate(specs):
                if spec.cross_validator is None:
                    continue
                related = {
                    dependency: deepcopy(effective[dependency])
                    for dependency in spec.cross_document_ids
                }
                try:
                    spec.cross_validator(deepcopy(effective[spec.document_id]), related)
                except Exception:  # noqa: BLE001 - domain validator contract
                    plans[index] = replace(
                        plans[index],
                        classification=MIGRATION_REQUIRED,
                        reason="connected effective slice failed domain validation",
                    )
    return tuple(plans)


def operation_fingerprint(entry: DocumentMigrationPlan) -> str:
    from hashlib import sha256

    value = {
        "operation": "settings_document_import",
        "version": _OPERATION_VERSION,
        "document_id": entry.document_id,
        "runtime_hash": entry.runtime_hash,
        "default_hash": entry.default_hash,
    }
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fresh_legacy_payload_for_insert(
    planned: DocumentMigrationPlan,
    current: DocumentMigrationPlan,
    spec,
) -> tuple[Any, Any]:
    """Повторно доказать source/default/audit непосредственно перед INSERT.

    ``current_plans`` защищает от изменений, случившихся до общей проверки.
    Эта проверка выполняется для каждого документа сразу перед его INSERT и
    поэтому не использует payload, прочитанный до recheck.
    """

    runtime_path = effective_runtime_path(spec)
    if _path_text(runtime_path) != planned.runtime_path:
        raise MigrationError(f"Источник legacy изменился после plan: {planned.document_id}")
    payload, error = _read_json(runtime_path)
    if error or payload is None:
        raise MigrationError(f"Legacy payload недоступен перед INSERT: {planned.document_id}")
    if legacy_hash(payload) != planned.runtime_hash or legacy_hash(payload) != current.runtime_hash:
        raise MigrationError(f"Legacy payload изменился перед INSERT: {planned.document_id}")
    validation_error = _validate_payload(spec, payload)
    if validation_error:
        raise MigrationError(
            f"Payload изменился и больше невалиден: {planned.document_id}: {validation_error}"
        )

    default_path = Path(settings.BASE_DIR) / spec.default_path
    default_payload, default_error = _read_json(default_path)
    if default_error or default_payload is None:
        raise MigrationError(f"Git default недоступен перед INSERT: {planned.document_id}")
    default_runtime_hash = legacy_hash(default_payload)
    if default_runtime_hash != planned.default_hash or default_runtime_hash != current.default_hash:
        raise MigrationError(f"Git default изменился перед INSERT: {planned.document_id}")
    latest = _latest_audit(planned.document_id)
    if (
        latest is None
        or latest.storage_kind != "runtime_contract"
        or str(latest.after_hash or "") != legacy_hash(payload)
    ):
        raise MigrationError(f"Legacy audit изменился перед INSERT: {planned.document_id}")
    return deepcopy(payload), deepcopy(default_payload)


def _verify_imported_documents_before_commit(
    plans: Sequence[DocumentMigrationPlan],
    registry: ConfigDocumentRegistry,
) -> None:
    """Проверить source и созданные строки перед выходом из transaction."""

    for planned in plans:
        if planned.classification != AUDITED_OVERRIDE:
            continue
        spec = registry.get(planned.document_id)
        runtime_path = effective_runtime_path(spec)
        if _path_text(runtime_path) != planned.runtime_path:
            raise MigrationError(f"Источник legacy изменился перед commit: {planned.document_id}")
        payload, error = _read_json(runtime_path)
        if error or payload is None or legacy_hash(payload) != planned.runtime_hash:
            raise MigrationError(f"Legacy payload изменился перед commit: {planned.document_id}")
        default_payload, default_error = _read_json(Path(settings.BASE_DIR) / spec.default_path)
        if default_error or default_payload is None or legacy_hash(default_payload) != planned.default_hash:
            raise MigrationError(f"Git default изменился перед commit: {planned.document_id}")
        row = RuntimeSettingDocument.objects.select_for_update().filter(
            document_id=planned.document_id
        ).first()
        if row is None or row.content_hash != document_hash(payload):
            raise MigrationError(f"Runtime document не совпал перед commit: {planned.document_id}")
        latest = _latest_audit(planned.document_id)
        if (
            latest is None
            or latest.storage_kind != "runtime_document"
            or latest.status != SettingsChange.Status.APPLIED
            or str(latest.after_hash or "") != row.content_hash
        ):
            raise MigrationError(f"Новый audit не подтверждён перед commit: {planned.document_id}")


def _assert_safe_existing_directory(root: Path) -> Path:
    root = _absolute_without_following_symlinks(root)
    directory_status = _directory_lstat_status(root)
    if directory_status is not None:
        raise UnsafeMigrationPath(f"backup-root должен быть существующим каталогом: {root}")
    project_root = _absolute_without_following_symlinks(Path(settings.BASE_DIR))
    runtime_root = _absolute_without_following_symlinks(Path(settings.RUNTIME_CONTRACTS_DIR))
    try:
        root.relative_to(project_root)
    except ValueError:
        pass
    else:
        raise UnsafeMigrationPath("backup-root должен находиться вне корня проекта.")
    try:
        root.relative_to(runtime_root)
    except ValueError:
        pass
    else:
        raise UnsafeMigrationPath("backup-root не должен находиться в data/contracts.")
    if (root / ".git").exists() or (root / "contracts").exists():
        raise UnsafeMigrationPath("backup-root не должен быть корнем Git или contracts.")
    return root


def _assert_safe_output(path: Path, *, local_only: bool) -> Path:
    path = _absolute_without_following_symlinks(path)
    target_status = _path_lstat_status(path)
    if target_status not in (None, "missing"):
        raise UnsafeMigrationPath(f"Файл вывода имеет небезопасный target: {target_status}")
    parent_status = _directory_lstat_status(path.parent)
    if parent_status not in (None, "missing"):
        raise UnsafeMigrationPath(f"Путь вывода небезопасен: {parent_status}")
    if local_only:
        local_root = _absolute_without_following_symlinks(Path(settings.BASE_DIR) / ".local")
        try:
            path.relative_to(local_root)
        except ValueError as exc:
            raise UnsafeMigrationPath("--output разрешён только внутри .local/") from exc
    return path


def _windows_target_has_reparse_point(path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _atomic_write(path: Path, content: str, *, overwrite: bool = True) -> None:
    """Атомарная безопасная запись с dirfd/O_NOFOLLOW на POSIX."""

    if os.name == "nt":
        raise UnsupportedMigrationPlatform(
            "Запись migration backup/report/export на Windows закрыта; "
            "используйте stdout plan и выполняйте операторскую миграцию на POSIX-host."
        )
    path = _absolute_without_following_symlinks(path)
    status = _path_lstat_status(path)
    if status not in (None, "missing"):
        raise UnsafeMigrationPath(f"Нельзя записать небезопасный target: {status}")
    # Do not create through a symlinked parent.  Check first, create only
    # genuinely missing parents, then re-check immediately before opening the
    # directory fd below.
    if status == "missing":
        path.parent.mkdir(parents=True, exist_ok=True)
        status = _path_lstat_status(path)
        if status not in (None, "missing"):
            raise UnsafeMigrationPath(f"Путь записи изменился: {status}")
    if not overwrite and status is None:
        raise UnsafeMigrationPath(f"Доказательство уже существует: {path.name}")
    directory_fd = _open_directory_fd(path.parent)
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor = None
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            target_info = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            target_info = None
        if target_info is not None:
            if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISREG(target_info.st_mode):
                raise UnsafeMigrationPath("Target изменён на symlink или не regular file.")
            if not overwrite:
                raise UnsafeMigrationPath(f"Доказательство уже существует: {path.name}")
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _file_identity(path: Path) -> tuple[int, int] | None:
    """Вернуть identity regular file без следования ссылкам."""

    try:
        info = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None
    return info.st_dev, info.st_ino


def _unlink_created_file(path: Path, identity: tuple[int, int] | None) -> None:
    """Удалить только тот regular file, который создал текущий вызов."""

    if identity is None or _file_identity(path) != identity:
        return
    try:
        path.unlink()
    except OSError:
        pass


def _backup_document(entry: DocumentMigrationPlan, root: Path, payload: Any) -> BackupRecord:
    safe_id = _SAFE_NAME.sub("_", entry.document_id).strip("._") or "document"
    nonce = secrets.token_hex(8)
    payload_path = root / f"{safe_id}.{entry.runtime_hash[:12]}.{nonce}.json"
    manifest_path = root / f"{safe_id}.{entry.runtime_hash[:12]}.{nonce}.manifest.json"
    legacy = legacy_hash(payload)
    compact = document_hash(payload)
    try:
        assert_no_raw_secrets(payload)
    except RawSecretValueError as exc:
        raise MigrationError("backup:raw_secret") from exc
    manifest = {
        "format": "settings-document-backup-v1",
        "document_id": entry.document_id,
        "source_path": entry.runtime_path,
        "schema_version": entry.schema_version,
        "runtime_hash": legacy,
        "document_hash": compact,
        "default_hash": entry.default_hash,
        "created_at": timezone.now().isoformat(),
    }
    manifest_hash = document_hash(manifest)
    manifest["manifest_hash"] = manifest_hash
    _atomic_write(payload_path, canonical_json(payload) + "\n", overwrite=False)
    written_payload, error = _read_json(payload_path)
    if error or written_payload is None or legacy_hash(written_payload) != legacy:
        raise MigrationError(f"Проверка backup не пройдена для {entry.document_id}.")
    _atomic_write(manifest_path, canonical_json(manifest) + "\n", overwrite=False)
    written_manifest, error = _read_json(manifest_path)
    if error or written_manifest is None:
        raise MigrationError(f"Manifest backup не читается для {entry.document_id}.")
    check_manifest = dict(written_manifest)
    actual_manifest_hash = check_manifest.pop("manifest_hash", None)
    if (
        actual_manifest_hash != manifest_hash
        or document_hash(check_manifest) != manifest_hash
        or check_manifest.get("document_id") != entry.document_id
        or check_manifest.get("runtime_hash") != legacy
        or check_manifest.get("document_hash") != compact
        or check_manifest.get("default_hash") != entry.default_hash
    ):
        raise MigrationError(f"Хеш manifest backup не совпал для {entry.document_id}.")
    return BackupRecord(
        document_id=entry.document_id,
        payload_path=str(payload_path),
        manifest_path=str(manifest_path),
        payload_hash=legacy,
        document_hash=compact,
        manifest_hash=manifest_hash,
    )


def _acquire_advisory_locks(document_ids: Iterable[str]) -> None:
    if connection.vendor != "postgresql":
        raise UnsupportedMigrationBackend(
            "settings_documents_migrate --apply требует PostgreSQL для advisory locks."
        )
    with connection.cursor() as cursor:
        for document_id in sorted(document_ids):
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [advisory_lock_key(document_id)])


def _require_superuser(actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise MigrationError("Apply требует активного superuser --actor-id.")
    user = get_user_model().objects.filter(pk=actor.pk, is_active=True).first()
    if user is None or not user.is_superuser:
        raise MigrationError("Apply разрешён только активному superuser.")
    return user


def apply_migration(
    document_ids: Sequence[str],
    *,
    actor,
    backup_root: str | os.PathLike[str],
    registry: ConfigDocumentRegistry | None = None,
) -> tuple[DocumentMigrationPlan, ...]:
    """Импортировать audited overrides одной PostgreSQL-транзакцией."""

    if not document_ids:
        raise MigrationSliceError("Apply требует явный непустой список document IDs.")
    # Reject before acquiring the legacy lock or writing a backup. SQLite is
    # still useful for read-only plan/tests but cannot provide this guarantee.
    if os.name == "nt":
        raise UnsupportedMigrationPlatform(
            "settings_documents_migrate --apply закрыт на Windows из-за "
            "недостаточных гарантий no-follow/dirfd."
        )
    if connection.vendor != "postgresql":
        raise UnsupportedMigrationBackend(
            "settings_documents_migrate --apply требует PostgreSQL для advisory locks."
        )
    actor = _require_superuser(actor)
    root = _assert_safe_existing_directory(Path(backup_root))
    registry = registry or get_document_registry()
    write_lock_path = access_control_write_lock_path()
    if _directory_lstat_status(write_lock_path.parent) is not None:
        raise UnsafeMigrationPath("Каталог общей блокировки runtime contracts небезопасен.")

    # The lock covers the final plan, file reads, backup and DB transaction. It
    # is the same lock used by legacy Settings Center writers; a late external
    # mutation is still detected by the hash recheck below.
    with exclusive_file_lock(write_lock_path) as held_lock:
        plans = plan_migration(document_ids, registry=registry)
        allowed = {
            AUDITED_OVERRIDE,
            IDENTICAL_DEFAULT,
            MISSING_RUNTIME,
            ALREADY_IMPORTED,
        }
        if any(entry.classification not in allowed for entry in plans):
            details = "; ".join(
                f"{item.document_id}: {item.classification}" for item in plans
            )
            raise MigrationError(f"Apply заблокирован классификациями: {details}")

        payloads: dict[str, Any] = {}
        backups: dict[str, BackupRecord] = {}
        for entry in plans:
            if entry.classification != AUDITED_OVERRIDE:
                continue
            payload, error = _read_json(
                Path(entry.runtime_path) if entry.runtime_path else None
            )
            if error or payload is None or entry.runtime_hash != legacy_hash(payload):
                raise MigrationError(
                    f"Legacy payload изменился после plan: {entry.document_id}"
                )
            try:
                assert_no_raw_secrets(payload)
            except RawSecretValueError as exc:
                raise MigrationError(f"{entry.document_id}: runtime:raw_secret") from exc
            validation_error = _validate_payload(registry.get(entry.document_id), payload)
            if validation_error:
                raise MigrationError(
                    f"Payload невалиден: {entry.document_id}: {validation_error}"
                )
            payloads[entry.document_id] = deepcopy(payload)
            backups[entry.document_id] = _backup_document(entry, root, payload)

        with transaction.atomic():
            _acquire_advisory_locks(entry.document_id for entry in plans)
            actor = _require_superuser(actor)
            rows = RuntimeSettingDocument.objects.select_for_update().filter(
                document_id__in=[entry.document_id for entry in plans]
            ).in_bulk()

            # Re-read every document after both locks. This catches a mutation
            # that did not cooperate with the legacy file lock and protects
            # against a stale plan/audit/DB row.
            current_plans = tuple(
                classify_document(registry.get(entry.document_id), registry=registry)
                for entry in plans
            )
            for planned, current in zip(plans, current_plans):
                if planned.classification == AUDITED_OVERRIDE:
                    if current.classification == ALREADY_IMPORTED:
                        continue
                    if (
                        current.classification != AUDITED_OVERRIDE
                        or current.runtime_hash != planned.runtime_hash
                        or current.default_hash != planned.default_hash
                        or not current.audit_evidence
                    ):
                        raise MigrationError(
                            f"Legacy/audit версия изменилась после plan: {planned.document_id}"
                        )
                elif current.classification != planned.classification:
                    # A no-op can become already_imported if another worker
                    # completed it while this process was waiting for locks.
                    if current.classification != ALREADY_IMPORTED:
                        raise MigrationError(
                            f"Состояние изменилось после plan: {planned.document_id}"
                        )
                if current.classification in BLOCKED_CLASSES:
                    raise MigrationError(
                        f"Apply заблокирован повторной проверкой: {planned.document_id}"
                    )

            current_payloads: dict[str, Any] = {}
            for planned in plans:
                if planned.document_id in rows:
                    current_payloads[planned.document_id] = deepcopy(
                        rows[planned.document_id].payload
                    )
                elif planned.document_id in payloads:
                    current_payloads[planned.document_id] = deepcopy(
                        payloads[planned.document_id]
                    )
                else:
                    default_payload, default_error = _read_json(
                        Path(settings.BASE_DIR)
                        / registry.get(planned.document_id).default_path
                    )
                    if default_error or default_payload is None:
                        raise MigrationError(
                            f"Git default исчез между plan и apply: {planned.document_id}"
                        )
                    current_payloads[planned.document_id] = deepcopy(default_payload)

            # Validate the complete effective dependency slice before the first
            # INSERT. No partial DB/audit state can survive a failure here.
            for planned in plans:
                spec = registry.get(planned.document_id)
                if spec.cross_validator is None:
                    continue
                related = {
                    dependency: deepcopy(current_payloads[dependency])
                    for dependency in spec.cross_document_ids
                }
                try:
                    spec.cross_validator(
                        deepcopy(current_payloads[planned.document_id]),
                        related,
                    )
                except Exception as exc:  # noqa: BLE001 - domain validator contract
                    raise MigrationError(
                        f"Связанный срез не прошёл проверку: {planned.document_id}"
                    ) from exc

            results: list[DocumentMigrationPlan] = []
            for planned, current in zip(plans, current_plans):
                spec = registry.get(planned.document_id)
                row = rows.get(planned.document_id)
                if current.classification == ALREADY_IMPORTED:
                    values = planned.as_dict()
                    values.update(
                        classification=ALREADY_IMPORTED,
                        reason="matching RuntimeSettingDocument already exists",
                    )
                    results.append(DocumentMigrationPlan(**values))
                    continue
                if planned.classification != AUDITED_OVERRIDE:
                    # identical_default and missing_runtime are explicitly
                    # successful no-ops and never create DB/audit rows.
                    results.append(current)
                    continue
                if row is not None:
                    raise MigrationError(
                        f"Строка RuntimeSettingDocument появилась во время apply: {planned.document_id}"
                    )
                payload, default_payload = _fresh_legacy_payload_for_insert(
                    planned, current, spec
                )
                compact = document_hash(payload)
                default_compact = document_hash(default_payload)
                fingerprint = operation_fingerprint(current)
                if SettingsChange.objects.filter(
                    operation_fingerprint=fingerprint
                ).exists():
                    raise MigrationError(f"Операция уже имеет audit row: {planned.document_id}")
                RuntimeSettingDocument.objects.create(
                    document_id=planned.document_id,
                    schema_version=spec.schema_version,
                    payload=deepcopy(payload),
                    revision=1,
                    content_hash=compact,
                    default_hash=default_compact,
                    updated_by=actor,
                )
                backup = backups[planned.document_id]
                SettingsChange.objects.create(
                    actor=actor,
                    setting_id=planned.document_id,
                    domain=spec.domain,
                    storage_kind="runtime_document",
                    action=SettingsChange.Action.APPLY,
                    status=SettingsChange.Status.APPLIED,
                    before_hash=default_compact,
                    after_hash=compact,
                    before_snapshot=deepcopy(default_payload),
                    after_snapshot=deepcopy(payload),
                    document_revision_before=None,
                    document_revision_after=1,
                    contract_relpath=spec.default_path or "",
                    masked_diff=build_masked_diff(default_payload, payload),
                    validation_result=mask_sensitive(
                        {
                            "valid": True,
                            "migration": "legacy_json_to_runtime_document",
                            "legacy_runtime_hash": current.runtime_hash,
                            "legacy_default_hash": current.default_hash,
                            "legacy_audit_change_id": current.audit_change_id,
                            "backup_manifest_hash": backup.manifest_hash,
                            "secret_scan": classify_secret_references(payload),
                        }
                    ),
                    operation_fingerprint=fingerprint,
                    requires_restart=spec.requires_restart,
                    requires_reindex=spec.requires_reindex,
                    applied_at=timezone.now(),
                )
                values = current.as_dict()
                values.update(
                    classification=ALREADY_IMPORTED,
                    reason="legacy override imported atomically",
                    db_revision=1,
                    db_content_hash=compact,
                    db_default_hash=default_compact,
                    backup_path=backup.payload_path,
                    backup_manifest_path=backup.manifest_path,
                )
                results.append(DocumentMigrationPlan(**values))
            _verify_imported_documents_before_commit(plans, registry)
            held_lock.assert_current()
            return tuple(results)


def export_document(
    document_id: str,
    *,
    output: str | os.PathLike[str],
    manifest_output: str | os.PathLike[str] | None = None,
    registry: ConfigDocumentRegistry | None = None,
) -> dict[str, Any]:
    """Экспортировать effective payload и manifest без изменения источника."""

    if os.name == "nt":
        raise UnsupportedMigrationPlatform(
            "settings_documents_export закрыт на Windows; используйте защищённый POSIX-host."
        )
    registry = registry or get_document_registry()
    spec = registry.get(document_id)
    if spec.storage_policy != "database_override":
        raise MigrationError(f"Экспорт пакета 03 поддерживает только database_override: {document_id}")
    plan = classify_document(spec, registry=registry)
    if plan.classification in BLOCKED_CLASSES:
        raise MigrationError(f"Экспорт заблокирован: {document_id}: {plan.classification}")
    row = RuntimeSettingDocument.objects.filter(document_id=document_id).first()
    if row is not None:
        payload = deepcopy(row.payload)
        source = "database_override"
        revision = row.revision
    else:
        runtime_payload, runtime_error = _read_json(effective_runtime_path(spec))
        if runtime_error is None and runtime_payload is not None:
            payload = runtime_payload
            source = "legacy_file"
        else:
            payload, error = _read_json(Path(settings.BASE_DIR) / spec.default_path)
            if error or payload is None:
                raise MigrationError(f"Git default недоступен: {document_id}")
            source = "git_default"
        revision = 0
    assert_no_raw_secrets(payload)
    validation_error = _validate_payload(spec, payload)
    if validation_error:
        raise MigrationError(f"Payload невалиден: {document_id}: {validation_error}")
    compact = document_hash(payload)
    default_payload, default_error = _read_json(Path(settings.BASE_DIR) / spec.default_path)
    if default_error or default_payload is None:
        raise MigrationError(f"Git default недоступен: {document_id}")
    manifest = {
        "format": "settings-document-export-v1",
        "document_id": document_id,
        "source": source,
        "schema_version": spec.schema_version,
        "revision": revision,
        "content_hash": compact,
        "default_hash": document_hash(default_payload),
        "exported_at": timezone.now().isoformat(),
    }
    manifest_hash = document_hash(manifest)
    manifest["manifest_hash"] = manifest_hash
    output_path = _assert_safe_output(Path(output), local_only=False)
    manifest_path = _assert_safe_output(
        Path(manifest_output) if manifest_output else output_path.with_suffix(".manifest.json"),
        local_only=False,
    )
    if output_path == manifest_path:
        raise UnsafeMigrationPath("Export payload и manifest должны быть разными файлами.")
    output_preexisting = _path_lstat_status(output_path) is None
    manifest_preexisting = _path_lstat_status(manifest_path) is None
    output_identity = manifest_identity = None
    try:
        _atomic_write(output_path, canonical_json(payload) + "\n", overwrite=False)
        output_identity = _file_identity(output_path)
        _atomic_write(manifest_path, canonical_json(manifest) + "\n", overwrite=False)
        manifest_identity = _file_identity(manifest_path)
        written_payload, payload_error = _read_json(output_path)
        if payload_error or written_payload is None or document_hash(written_payload) != compact:
            raise MigrationError(f"Проверка экспортированного payload не пройдена: {document_id}")
        written_manifest, manifest_error = _read_json(manifest_path)
        if manifest_error or not isinstance(written_manifest, dict):
            raise MigrationError(f"Проверка manifest экспорта не пройдена: {document_id}")
        actual_manifest_hash = written_manifest.pop("manifest_hash", None)
        if (
            actual_manifest_hash != manifest_hash
            or document_hash(written_manifest) != manifest_hash
            or written_manifest.get("content_hash") != compact
        ):
            raise MigrationError(f"Хеш manifest экспорта не совпал: {document_id}")
    except Exception:
        # Never remove an operator's pre-existing evidence. If this invocation
        # created the payload and the manifest failed, remove only our file.
        if not output_preexisting:
            _unlink_created_file(output_path, output_identity)
        if not manifest_preexisting:
            _unlink_created_file(manifest_path, manifest_identity)
        raise
    return {
        "document_id": document_id,
        "output": str(output_path),
        "manifest": str(manifest_path),
        "source": source,
        "revision": revision,
        "content_hash": compact,
        "default_hash": manifest["default_hash"],
        "manifest_hash": manifest_hash,
    }


# Названия-синонимы облегчают использование из management command и тестов.
classify_legacy_document = classify_document
build_migration_plan = plan_migration
