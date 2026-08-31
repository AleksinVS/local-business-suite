"""Транзакционная запись рабочих документов настроек в PostgreSQL."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from .document_hashes import document_hash, is_document_hash
from .document_registry import ConfigDocumentRegistry, get_document_registry
from .document_repository import (
    ConfigDocumentRepository,
    DocumentRepositoryError,
    DocumentSchemaMismatch,
    RuntimeSettingSnapshot,
)
from .document_security import RawSecretValueError, assert_no_raw_secrets
from .descriptors import mask_sensitive
from .models import RuntimeSettingDocument, SettingsChange
from .policies import can_manage_settings
from .services import build_masked_diff


class DocumentWriteError(ValidationError):
    pass


class DocumentWriteConflict(DocumentWriteError):
    pass


class UnsupportedDocumentWriteBackend(DocumentWriteError):
    pass


class DocumentMigrationRequired(DocumentWriteError):
    pass


class SecretBearingDocument(DocumentWriteError):
    pass


@dataclass(frozen=True)
class ExpectedDocumentVersion:
    revision: int
    content_hash: str


def advisory_lock_key(document_id: str) -> int:
    """Стабильный signed bigint для pg_advisory_xact_lock."""

    unsigned = int.from_bytes(hashlib.sha256(document_id.encode("utf-8")).digest()[:8], "big")
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned


class ConfigDocumentWriter:
    def __init__(self, registry: ConfigDocumentRegistry | None = None):
        self.registry = registry or get_document_registry()
        self.repository = ConfigDocumentRepository(self.registry)

    def save_document(
        self,
        *,
        actor,
        document_id: str,
        payload: Any,
        expected_revision: int,
        expected_content_hash: str,
        operation_fingerprint: str | None = None,
        audit_context: Mapping[str, Any] | None = None,
        on_commit: Callable[[], None] | None = None,
    ) -> RuntimeSettingSnapshot:
        spec = self.registry.get(document_id)
        if spec.write_policy != "editable":
            raise PermissionDenied("Документ изменяется только специальным доменным сценарием.")
        actor = self._require_actor(actor, spec.required_permission)
        result = self._save_documents(
            actor=actor,
            candidates={document_id: payload},
            expected={
                document_id: ExpectedDocumentVersion(
                    revision=expected_revision,
                    content_hash=expected_content_hash,
                )
            },
            operation_fingerprints={document_id: operation_fingerprint},
            audit_context=audit_context,
            on_commit=on_commit,
            locked_authorize=lambda: self._require_actor(actor, spec.required_permission),
        )
        return result[document_id]

    def save_document_via_domain_workflow(
        self,
        *,
        actor,
        document_id: str,
        payload: Any,
        expected_revision: int,
        expected_content_hash: str,
        authorize: Callable[[Any], None],
        operation_fingerprint: str | None = None,
        audit_context: Mapping[str, Any] | None = None,
        on_commit: Callable[[], None] | None = None,
    ) -> RuntimeSettingSnapshot:
        spec = self.registry.get(document_id)
        if spec.write_policy != "requires_domain_workflow":
            raise DocumentWriteError("Для документа не объявлен специальный доменный сценарий.")
        actor = self._require_authenticated_actor(actor)
        authorize(actor)

        def locked_domain_authorize():
            fresh = self._authorize_domain_actor(actor, authorize)
            return self._require_actor(fresh, spec.required_permission)

        return self._save_documents(
            actor=actor,
            candidates={document_id: payload},
            expected={
                document_id: ExpectedDocumentVersion(
                    revision=expected_revision,
                    content_hash=expected_content_hash,
                )
            },
            operation_fingerprints={document_id: operation_fingerprint},
            audit_context=audit_context,
            on_commit=on_commit,
            locked_authorize=locked_domain_authorize,
        )[document_id]

    def save_documents_via_domain_workflow(
        self,
        *,
        actor,
        candidates: Mapping[str, Any],
        expected: Mapping[str, ExpectedDocumentVersion],
        authorize: Callable[[Any], None],
        operation_fingerprints: Mapping[str, str | None] | None = None,
        audit_context: Mapping[str, Any] | None = None,
        on_commit: Callable[[], None] | None = None,
    ) -> dict[str, RuntimeSettingSnapshot]:
        """Атомарно изменить закрытый доменный срез одним решением полномочий."""

        specs = [self.registry.get(document_id) for document_id in candidates]
        if not specs or not any(
            spec.write_policy == "requires_domain_workflow" for spec in specs
        ):
            raise DocumentWriteError("Срез не объявляет специальный доменный сценарий.")
        if any(spec.write_policy == "read_only" for spec in specs):
            raise PermissionDenied("Доменный сценарий не может менять read-only документ.")
        candidate_ids = tuple(sorted(candidates))
        closed_scope = self._connected_validation_scope((candidate_ids[0],))
        if not set(candidate_ids).issubset(closed_scope):
            raise DocumentWriteError(
                "Доменный сценарий может менять документы только одной связанной компоненты."
            )
        actor = self._require_authenticated_actor(actor)
        authorize(actor)

        def locked_domain_authorize():
            fresh = self._authorize_domain_actor(actor, authorize)
            for spec in specs:
                fresh = self._require_actor(fresh, spec.required_permission)
            return fresh

        return self._save_documents(
            actor=actor,
            candidates=candidates,
            expected=expected,
            operation_fingerprints=operation_fingerprints,
            audit_context=audit_context,
            on_commit=on_commit,
            locked_authorize=locked_domain_authorize,
        )

    def rollback_document(
        self,
        *,
        actor,
        document_id: str,
        source_change_id: int,
        expected_revision: int,
        expected_content_hash: str,
        authorize: Callable[[Any], None] | None = None,
        audit_context: Mapping[str, Any] | None = None,
    ) -> RuntimeSettingSnapshot:
        spec = self.registry.get(document_id)
        if spec.write_policy == "requires_domain_workflow":
            if authorize is None:
                raise PermissionDenied("Rollback требует авторизации доменного сценария.")
            actor = self._require_authenticated_actor(actor)
            authorize(actor)
        else:
            actor = self._require_actor(actor, spec.required_permission)
        source = SettingsChange.objects.filter(
            pk=source_change_id,
            setting_id=document_id,
            storage_kind="runtime_document",
            status=SettingsChange.Status.APPLIED,
            action__in=(SettingsChange.Action.APPLY, SettingsChange.Action.ROLLBACK),
        ).first()
        if source is None or source.before_snapshot is None:
            raise DocumentWriteError("Версия для rollback не найдена или не содержит снимок.")
        result = self._save_documents(
            actor=actor,
            candidates={document_id: source.before_snapshot},
            expected={
                document_id: ExpectedDocumentVersion(
                    revision=expected_revision,
                    content_hash=expected_content_hash,
                )
            },
            actions={document_id: SettingsChange.Action.ROLLBACK},
            rollback_of={document_id: source},
            audit_context=audit_context,
            locked_authorize=(
                (
                    lambda: self._require_actor(
                        self._authorize_domain_actor(actor, authorize),
                        spec.required_permission,
                    )
                )
                if spec.write_policy == "requires_domain_workflow"
                else (lambda: self._require_actor(actor, spec.required_permission))
            ),
        )
        return result[document_id]

    def _save_documents(
        self,
        *,
        actor,
        candidates: Mapping[str, Any],
        expected: Mapping[str, ExpectedDocumentVersion],
        actions: Mapping[str, str] | None = None,
        rollback_of: Mapping[str, SettingsChange] | None = None,
        operation_fingerprints: Mapping[str, str | None] | None = None,
        audit_context: Mapping[str, Any] | None = None,
        on_commit: Callable[[], None] | None = None,
        locked_authorize: Callable[[], Any] | None = None,
    ) -> dict[str, RuntimeSettingSnapshot]:
        if connection.vendor != "postgresql":
            raise UnsupportedDocumentWriteBackend(
                "Транзакционная запись документов настроек поддерживается только PostgreSQL."
            )
        candidate_ids = tuple(sorted(candidates))
        if not candidate_ids or set(candidate_ids) != set(expected):
            raise DocumentWriteError("Для каждого кандидата нужна ожидаемая версия.")
        scope = self._connected_validation_scope(candidate_ids)
        legacy = [
            document_id
            for document_id in scope
            if self.registry.get(document_id).active_backend == "legacy_file"
        ]
        if legacy:
            raise UnsupportedDocumentWriteBackend(
                "Нельзя атомарно изменить срез с legacy-зависимостями: " + ", ".join(legacy)
            )
        for document_id in candidate_ids:
            spec = self.registry.get(document_id)
            if spec.storage_policy != "database_override" or spec.active_backend != "database":
                raise UnsupportedDocumentWriteBackend(
                    f"Документ '{document_id}' ещё не переключён на PostgreSQL."
                )
            version = expected[document_id]
            if version.revision < 0 or not is_document_hash(version.content_hash):
                raise DocumentWriteError("Ожидаемая версия документа имеет неверный формат.")
        try:
            assert_no_raw_secrets(dict(audit_context or {}))
        except RawSecretValueError as exc:
            raise SecretBearingDocument(str(exc)) from exc

        actions = actions or {}
        rollback_of = rollback_of or {}
        operation_fingerprints = operation_fingerprints or {}
        with transaction.atomic():
            self._acquire_locks(scope)
            if locked_authorize is not None:
                actor = locked_authorize()
            fingerprints = [
                value for value in operation_fingerprints.values() if value is not None
            ]
            if len(fingerprints) != len(set(fingerprints)) or SettingsChange.objects.filter(
                operation_fingerprint__in=fingerprints
            ).exists():
                raise DocumentWriteConflict("Операция уже была применена.")
            rows = RuntimeSettingDocument.objects.select_for_update().filter(
                document_id__in=scope
            ).in_bulk()
            try:
                snapshots = self._locked_snapshots(scope, rows)
            except RawSecretValueError as exc:
                raise SecretBearingDocument(str(exc)) from exc
            for document_id in scope:
                current = snapshots[document_id]
                if current.degraded:
                    raise DocumentWriteError(
                        f"Документ '{document_id}' повреждён; запись закрыта до явного восстановления."
                    )
                if current.migration_required:
                    raise DocumentMigrationRequired(
                        f"Документ '{document_id}' требует отдельной миграции схемы или дефолта."
                    )
            for document_id in candidate_ids:
                current = snapshots[document_id]
                version = expected[document_id]
                if current.revision != version.revision or current.content_hash != version.content_hash:
                    raise DocumentWriteConflict(
                        f"Документ '{document_id}' уже изменён. Перечитайте актуальную версию."
                    )

            payloads = {
                document_id: deepcopy(snapshot.payload)
                for document_id, snapshot in snapshots.items()
            }
            for document_id, payload in candidates.items():
                spec = self.registry.get(document_id)
                try:
                    self.repository._validate_payload(spec, payload)
                except RawSecretValueError as exc:
                    raise SecretBearingDocument(str(exc)) from exc
                payloads[document_id] = deepcopy(payload)
                if document_hash(payload) == snapshots[document_id].content_hash:
                    raise DocumentWriteError(f"В документе '{document_id}' нет изменений.")

            for document_id in scope:
                spec = self.registry.get(document_id)
                if spec.cross_validator is None:
                    continue
                related = {item: payloads[item] for item in spec.cross_document_ids}
                spec.cross_validator(deepcopy(payloads[document_id]), deepcopy(related))

            result: dict[str, RuntimeSettingSnapshot] = {}
            for document_id in candidate_ids:
                spec = self.registry.get(document_id)
                before = snapshots[document_id]
                after_payload = deepcopy(payloads[document_id])
                after_hash = document_hash(after_payload)
                row = rows.get(document_id)
                revision = before.revision + 1
                default_payload = self.repository._load_default(spec)
                default_hash = document_hash(default_payload)
                inserting = row is None
                if inserting:
                    row = RuntimeSettingDocument(document_id=document_id)
                row.schema_version = spec.schema_version
                row.payload = after_payload
                row.revision = revision
                row.content_hash = after_hash
                row.default_hash = default_hash
                row.updated_by = actor
                if inserting:
                    try:
                        # Savepoint сохраняет внешнюю транзакцию пригодной для
                        # классификации гонки с писателем, который не взял lock.
                        with transaction.atomic():
                            row.save(force_insert=True)
                    except IntegrityError as exc:
                        if self._is_unique_violation(exc):
                            raise DocumentWriteConflict(
                                f"Документ '{document_id}' был создан параллельно."
                            ) from exc
                        raise
                else:
                    row.save()
                try:
                    with transaction.atomic():
                        change = SettingsChange.objects.create(
                            actor=actor,
                            setting_id=document_id,
                            domain=spec.domain,
                            storage_kind="runtime_document",
                            action=actions.get(document_id, SettingsChange.Action.APPLY),
                            status=SettingsChange.Status.APPLIED,
                            before_hash=before.content_hash,
                            after_hash=after_hash,
                            before_snapshot=deepcopy(before.payload),
                            after_snapshot=after_payload,
                            document_revision_before=before.revision or None,
                            document_revision_after=revision,
                            masked_diff=build_masked_diff(before.payload, after_payload),
                            validation_result=mask_sensitive(
                                {"valid": True, **deepcopy(dict(audit_context or {}))}
                            ),
                            operation_fingerprint=operation_fingerprints.get(document_id),
                            rollback_of=rollback_of.get(document_id),
                            requires_restart=spec.requires_restart,
                            requires_reindex=spec.requires_reindex,
                            applied_at=timezone.now(),
                        )
                except IntegrityError as exc:
                    if self._is_unique_violation(exc):
                        raise DocumentWriteConflict("Операция уже была применена.") from exc
                    raise
                result[document_id] = RuntimeSettingSnapshot(
                    document_id=document_id,
                    payload=deepcopy(after_payload),
                    source="database_override",
                    schema_version=spec.schema_version,
                    revision=revision,
                    content_hash=after_hash,
                    default_hash=default_hash,
                    change_id=change.pk,
                )
            if on_commit is not None:
                transaction.on_commit(on_commit)
            return result

    def _locked_snapshots(self, scope: Iterable[str], rows) -> dict[str, RuntimeSettingSnapshot]:
        result = {}
        for document_id in scope:
            spec = self.registry.get(document_id)
            default = self.repository._load_default(spec)
            default_hash = document_hash(default)
            try:
                snapshot = self.repository._build_snapshot(
                    spec=spec,
                    row=rows.get(document_id),
                    default_payload=default,
                    default_hash=default_hash,
                )
                self.repository._validate_payload(spec, snapshot.payload)
            except RawSecretValueError:
                raise
            except DocumentSchemaMismatch as exc:
                raise DocumentMigrationRequired(
                    f"Документ '{document_id}' требует миграции schema_version."
                ) from exc
            except (DocumentRepositoryError, ValidationError, ValueError) as exc:
                raise DocumentWriteError(
                    f"Документ '{document_id}' повреждён; запись закрыта до явного восстановления."
                ) from exc
            result[document_id] = snapshot
        return result

    def _connected_validation_scope(self, document_ids: Iterable[str]) -> tuple[str, ...]:
        return self.repository._connected_validation_scope(document_ids)

    @staticmethod
    def _acquire_locks(document_ids: Iterable[str]) -> None:
        with connection.cursor() as cursor:
            for document_id in sorted(document_ids):
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [advisory_lock_key(document_id)])

    @staticmethod
    def _require_authenticated_actor(actor):
        if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
            raise PermissionDenied("Требуется вход в систему.")
        fresh = get_user_model().objects.filter(pk=actor.pk).first()
        if fresh is None or not fresh.is_active:
            raise PermissionDenied("Требуется активная учётная запись.")
        return fresh

    @classmethod
    def _require_actor(cls, actor, required_permission: str):
        fresh = cls._require_authenticated_actor(actor)
        if required_permission == "manage_settings":
            if not can_manage_settings(fresh):
                raise PermissionDenied("Изменять настройки может только администратор настроек.")
        elif required_permission == "manage_users":
            if not fresh.is_superuser:
                raise PermissionDenied("Изменение доступно только активному суперпользователю.")
        else:
            raise PermissionDenied("Неизвестное право настройки.")
        return fresh

    @classmethod
    def _authorize_domain_actor(cls, actor, authorize):
        fresh = cls._require_authenticated_actor(actor)
        authorize(fresh)
        return fresh

    @staticmethod
    def _is_unique_violation(exc: IntegrityError) -> bool:
        cause = exc.__cause__
        return getattr(cause, "sqlstate", None) == "23505" or getattr(
            cause, "pgcode", None
        ) == "23505"
