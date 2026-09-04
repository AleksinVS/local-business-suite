from __future__ import annotations

import copy
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.utils import timezone

from apps.core.contract_store import normalized_hash
from apps.core.file_locks import (
    FileLockTimeoutError,
    access_control_write_lock_path,
    exclusive_file_lock,
)
from apps.core.json_utils import (
    atomic_write_json,
    load_json_file,
)
from .document_registry import get_document_registry
from .document_repository import (
    ConfigDocumentRepository,
    load_legacy_document,
)
from .document_services import ConfigDocumentWriter
from .models import SettingsChange
from .registry import get_registry
from .services import build_masked_diff, record_settings_change


_LEGACY_ROLE_RULES_SETTINGS_NAME = "LOCAL_BUSINESS_ROLE_RULES_FILE"


def read_contract_snapshot(descriptor, *, request=None, fresh=False):
    spec = get_document_registry().get(descriptor.setting_id)
    if spec.active_backend != "legacy_file":
        repository = ConfigDocumentRepository()
        if fresh:
            return repository.get_fresh_document(spec.document_id)
        return repository.get_document(spec.document_id, request=request)
    path = _contract_path(descriptor)
    default_payload = load_json_file(Path(settings.BASE_DIR) / spec.default_path)
    payload, source = load_legacy_document(
        spec,
        default_payload=default_payload,
        path=path,
    )
    if source == "git_default" and spec.validator is not None:
        spec.validator(copy.deepcopy(payload))
    from .document_repository import RuntimeSettingSnapshot

    return RuntimeSettingSnapshot(
        document_id=spec.document_id,
        payload=payload,
        source=source,
        schema_version=spec.schema_version,
        revision=0,
        content_hash=normalized_hash(payload),
        default_hash="",
    )


def read_contract_value(descriptor, *, request=None):
    return read_contract_snapshot(descriptor, request=request).payload


def save_default_new_user_role(
    *, actor, role_name, base_hash, base_revision=None, reason=""
):
    """Атомарно изменить только роль, назначаемую новым пользователям."""

    current_actor = get_user_model().objects.filter(pk=getattr(actor, "pk", None)).first()
    if not current_actor or not current_actor.is_active or not current_actor.is_superuser:
        raise PermissionDenied(
            "Роль новых пользователей может изменять только активный суперпользователь."
        )
    role_name = str(role_name or "").strip()
    reason = str(reason or "").strip()
    if len(reason) > 1000:
        raise ValidationError("Комментарий не должен превышать 1000 символов.")
    descriptor = get_registry().get("core.contract.role_rules")
    snapshot = read_contract_snapshot(descriptor, fresh=True)
    before = snapshot.payload
    if snapshot.content_hash != str(base_hash or "").removeprefix("sha256:"):
        raise ValidationError("Контракт ролей уже изменился. Перезагрузите страницу.")
    if snapshot.source in {"database_override", "git_default"}:
        try:
            requested_revision = int(base_revision)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Ревизия контракта ролей имеет неверный формат.") from exc
        if requested_revision != snapshot.revision:
            raise ValidationError("Контракт ролей уже изменился. Перезагрузите страницу.")
    if role_name:
        if role_name.startswith("$") or not isinstance(before.get(role_name), dict):
            raise ValidationError("Выбранная роль отсутствует в рабочем контракте.")
        if not Group.objects.filter(name=role_name).exists():
            raise ValidationError(
                f"Группа роли '{role_name}' не создана. Выполните seed_roles."
            )
    after = copy.deepcopy(before)
    after["$defaults"] = {"new_user_role": role_name or None}
    if after == before:
        raise ValidationError("Роль новых пользователей не изменилась.")
    return apply_contract_payload(
        actor=current_actor,
        setting_id=descriptor.setting_id,
        raw_payload=json.dumps(after, ensure_ascii=False),
        confirmed=True,
        base_hash=base_hash,
        base_revision=snapshot.revision,
        audit_context={
            "operation": "new_user_default_role",
            "reason": reason,
            "new_user_role": role_name or None,
        },
    )


def preview_contract_payload(*, actor, setting_id: str, raw_payload: str):
    # Preview is an authorization boundary too; otherwise a user could use
    # the validation/diff endpoint as a read oracle for a protected contract.
    descriptor = get_registry().get(setting_id)
    if descriptor.write_policy != "editable":
        raise ValidationError("Предпросмотр доступен только для редактируемых настроек.")
    _require_contract_editor(actor=actor, setting_id=descriptor.setting_id, descriptor=descriptor)
    snapshot = read_contract_snapshot(descriptor)
    before = snapshot.payload
    after = parse_and_validate_payload(descriptor, raw_payload)
    return {
        "before": before,
        "after": after,
        "masked_diff": build_masked_diff(before, after),
        "validation_result": {"valid": True},
        "base_hash": snapshot.content_hash,
        "base_revision": snapshot.revision,
    }


def apply_contract_payload(
    *,
    actor,
    setting_id: str,
    raw_payload: str,
    confirmed: bool,
    base_hash: str | None = None,
    base_revision: int | None = None,
    _action=SettingsChange.Action.APPLY,
    _rollback_of=None,
    operation_fingerprint: str | None = None,
    audit_context: dict | None = None,
    locked_precondition=None,
):
    """Apply a complete contract payload."""
    return _apply_contract_payload(
        actor=actor,
        setting_id=setting_id,
        raw_payload=raw_payload,
        confirmed=confirmed,
        base_hash=base_hash,
        base_revision=base_revision,
        _action=_action,
        _rollback_of=_rollback_of,
        operation_fingerprint=operation_fingerprint,
        audit_context=audit_context,
        locked_precondition=locked_precondition,
    )


def _apply_role_definition_payload(
    *,
    actor,
    role_code: str,
    base_hash: str,
    base_revision: int | None = None,
    confirmed: bool,
    raw_payload_factory,
    preview_token: str | None = None,
    risk_confirmed: bool = False,
    operation_fingerprint: str | None = None,
    audit_context: dict | None = None,
    locked_precondition=None,
    pre_write_callback=None,
):
    """Internal transport for the signed single-role writer.

    This is intentionally not a generic delegated writer: a signed preview is
    mandatory and the transport performs an independent domain check under the
    contract lock after the caller's factory has produced the candidate.
    """
    if not preview_token:
        raise ValidationError("Изменение определения роли требует подписанного предпросмотра.")
    return _apply_contract_payload(
        actor=actor,
        setting_id="core.contract.role_rules",
        raw_payload=None,
        confirmed=confirmed,
        base_hash=base_hash,
        base_revision=base_revision,
        operation_fingerprint=operation_fingerprint,
        audit_context=audit_context,
        locked_precondition=locked_precondition,
        _allow_delegated_role_definition=True,
        _role_definition_role_code=role_code,
        _raw_payload_factory=raw_payload_factory,
        _role_definition_preview_token=preview_token,
        _role_definition_risk_confirmed=bool(risk_confirmed),
        _pre_write_callback=pre_write_callback,
    )


def _apply_contract_payload(
    *,
    actor,
    setting_id: str,
    raw_payload: str | None,
    confirmed: bool,
    base_hash: str | None = None,
    base_revision: int | None = None,
    _action=SettingsChange.Action.APPLY,
    _rollback_of=None,
    operation_fingerprint: str | None = None,
    audit_context: dict | None = None,
    locked_precondition=None,
    _allow_delegated_role_definition=False,
    _role_definition_role_code=None,
    _raw_payload_factory=None,
    _role_definition_preview_token=None,
    _role_definition_risk_confirmed=False,
    _pre_write_callback=None,
):
    descriptor = get_registry().get(setting_id)
    actor = _require_contract_editor(
        actor=actor,
        setting_id=setting_id,
        descriptor=descriptor,
        allow_delegated_role_definition=_allow_delegated_role_definition,
    )
    if _allow_delegated_role_definition and (
        setting_id != "core.contract.role_rules"
        or not _role_definition_role_code
        or _raw_payload_factory is None
    ):
        raise ValidationError("Некорректный ограниченный writer определения роли.")
    if _allow_delegated_role_definition and not _role_definition_preview_token:
        raise ValidationError("Изменение определения роли требует подписанного предпросмотра.")
    if descriptor.storage_kind != "runtime_contract":
        raise ValidationError("Настройка не связана с рабочим контрактом.")
    role_domain_workflow = (
        setting_id == "core.contract.role_rules"
        and descriptor.write_policy == "requires_domain_workflow"
    )
    if not descriptor.is_editable and not role_domain_workflow:
        raise ValidationError("Настройка недоступна для редактирования.")
    if not confirmed:
        raise ValidationError("Для изменения контракта нужно явное подтверждение.")
    if not base_hash:
        raise ValidationError("Не указана версия контракта. Перечитайте актуальную версию.")
    spec = get_document_registry().get(setting_id)
    if spec.active_backend == "database":
        if _action != SettingsChange.Action.APPLY or _rollback_of is not None:
            raise ValidationError("Rollback PostgreSQL-документа выполняется отдельным writer.")
        if base_revision is None:
            raise ValidationError(
                "Не указана ревизия документа. Перечитайте актуальную версию."
            )
        try:
            expected_revision = int(base_revision)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Ревизия документа имеет неверный формат.") from exc
        writer = ConfigDocumentWriter()
        if role_domain_workflow:
            def authorize_role_writer(current_actor):
                _require_contract_editor(
                    actor=current_actor,
                    setting_id=setting_id,
                    descriptor=descriptor,
                    allow_delegated_role_definition=_allow_delegated_role_definition,
                )

            def role_candidate_factory(current_actor, before):
                _assert_runtime_role_catalog_matches_git_default(
                    runtime_payload=before,
                    descriptor=descriptor,
                )
                if locked_precondition is not None:
                    locked_precondition(current_actor, before)
                candidate_raw = (
                    _raw_payload_factory(copy.deepcopy(before))
                    if _raw_payload_factory is not None
                    else raw_payload
                )
                return parse_and_validate_payload(descriptor, candidate_raw)

            def validate_role_candidate(current_actor, before, after):
                _assert_candidate_role_catalog_unchanged(
                    runtime_payload=before,
                    candidate_payload=after,
                )
                _assert_candidate_role_administration_unchanged(
                    runtime_payload=before,
                    candidate_payload=after,
                )
                _assert_role_set_transport_change(
                    runtime_payload=before,
                    candidate_payload=after,
                    constrained_role_code=(
                        _role_definition_role_code
                        if _allow_delegated_role_definition
                        else None
                    ),
                )
                if not _allow_delegated_role_definition:
                    return
                _assert_single_role_payload(
                    before=before,
                    after=after,
                    role_code=_role_definition_role_code,
                )
                from apps.accounts.access_contracts import (
                    _validate_role_definition_transport_request,
                )

                _validate_role_definition_transport_request(
                    actor=current_actor,
                    role_code=_role_definition_role_code,
                    before=before,
                    after=after,
                    preview_token=_role_definition_preview_token,
                    risk_confirmed=_role_definition_risk_confirmed,
                )

            snapshot = writer.save_constrained_document_via_domain_workflow(
                actor=actor,
                document_id=setting_id,
                expected_revision=expected_revision,
                expected_content_hash=_plain_hash(base_hash),
                authorize=authorize_role_writer,
                candidate_factory=role_candidate_factory,
                validate_candidate=validate_role_candidate,
                before_write=(
                    (lambda current_actor, after: _pre_write_callback(current_actor, after))
                    if _pre_write_callback is not None
                    else None
                ),
                operation_fingerprint=operation_fingerprint,
                audit_context=audit_context,
            )
        else:
            if any(
                (
                    _allow_delegated_role_definition,
                    _raw_payload_factory is not None,
                    _pre_write_callback is not None,
                    locked_precondition is not None,
                )
            ):
                raise ValidationError(
                    "Доменный writer разрешён только для контракта ролей."
                )
            after = parse_and_validate_payload(descriptor, raw_payload)
            snapshot = writer.save_document(
                actor=actor,
                document_id=setting_id,
                payload=after,
                expected_revision=expected_revision,
                expected_content_hash=_plain_hash(base_hash),
                operation_fingerprint=operation_fingerprint,
                audit_context=audit_context,
            )
        if snapshot.change_id is None:
            raise ValidationError("Аудит изменения документа не создан.")
        return SettingsChange.objects.get(pk=snapshot.change_id)
    _require_autocommit_boundary()
    if descriptor.sensitivity == "secret":
        raise ValidationError("Секретный контракт нельзя сохранять в журнале версий.")
    contract_relpath = _contract_relative_path(descriptor)

    try:
        with exclusive_file_lock(_contract_write_lock_path(), timeout=10.0):
            # Полномочия могли измениться между входом в сервис и получением
            # межпроцессной блокировки. Повторная проверка является частью CAS.
            actor = _require_contract_editor(
                actor=actor,
                setting_id=setting_id,
                descriptor=descriptor,
                allow_delegated_role_definition=_allow_delegated_role_definition,
            )
            _resolve_known_pending_changes(setting_id=setting_id)
            if operation_fingerprint and SettingsChange.objects.filter(
                operation_fingerprint=operation_fingerprint
            ).exists():
                raise ValidationError("Этот предпросмотр уже был применён.")
            before = read_contract_value(descriptor)
            if setting_id == "core.contract.role_rules":
                _assert_runtime_role_catalog_matches_git_default(
                    runtime_payload=before,
                    descriptor=descriptor,
                )
            if locked_precondition is not None:
                locked_precondition(actor, before)
            if normalized_hash(before) != _plain_hash(base_hash):
                raise ValidationError(
                    "Контракт уже изменён другим процессом. Перечитайте актуальную версию "
                    "и повторите изменение."
                )
            # Кросс-контрактная валидация выполняется под общей блокировкой:
            # одновременно нельзя изменить role/workflow и получить проверку
            # против промежуточной пары версий.
            if _raw_payload_factory is not None:
                raw_payload = _raw_payload_factory(copy.deepcopy(before))
            after = parse_and_validate_payload(descriptor, raw_payload)
            if setting_id == "core.contract.role_rules":
                _assert_candidate_role_catalog_unchanged(
                    runtime_payload=before,
                    candidate_payload=after,
                )
                _assert_candidate_role_administration_unchanged(
                    runtime_payload=before,
                    candidate_payload=after,
                )
                _assert_role_set_transport_change(
                    runtime_payload=before,
                    candidate_payload=after,
                    constrained_role_code=(
                        _role_definition_role_code
                        if _allow_delegated_role_definition
                        else None
                    ),
                )
            if _allow_delegated_role_definition:
                _assert_single_role_payload(
                    before=before,
                    after=after,
                    role_code=_role_definition_role_code,
                )
                from apps.accounts.access_contracts import (
                    _validate_role_definition_transport_request,
                )

                _validate_role_definition_transport_request(
                    actor=actor,
                    role_code=_role_definition_role_code,
                    before=before,
                    after=after,
                    preview_token=_role_definition_preview_token,
                    risk_confirmed=_role_definition_risk_confirmed,
                )
            if normalized_hash(before) == normalized_hash(after):
                raise ValidationError("В контракте нет изменений для применения.")
            _validate_cross_contract_candidate(setting_id=setting_id, candidate=after)
            if _pre_write_callback is not None:
                # Materialize authority-bearing DB prerequisites before the
                # contract can classify them as a role.  A hard stop here can
                # leave only an inert zero-member Group, never an active role
                # backed by an unrelated technical/AD group.
                _pre_write_callback(actor, copy.deepcopy(after))
            change = _write_validated_contract_change(
                actor=actor,
                descriptor=descriptor,
                action=_action,
                before=before,
                after=after,
                rollback_of=_rollback_of,
                contract_relpath=contract_relpath,
                operation_fingerprint=operation_fingerprint,
                audit_context=audit_context,
            )
            return change
    except FileLockTimeoutError as exc:
        raise ValidationError(
            "Контракт сейчас изменяет другой процесс. Повторите попытку позже."
        ) from exc


def migrate_role_capability_catalog(
    *,
    actor,
    candidate_path,
    expected_runtime_catalog_hash: str,
    expected_git_catalog_hash: str,
    expected_runtime_hash: str,
    reason: str,
):
    """Apply one reviewed deployment-only capability-catalog migration.

    This service is intentionally separate from the Settings Center writer.  It
    has no UI/rollback caller and is the only operation allowed to replace the
    frozen ``$capabilities`` block.
    """

    actor = _require_active_superuser(actor)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Для deployment-миграции нужна причина.")
    candidate_path = Path(candidate_path)
    _require_autocommit_boundary()
    descriptor = get_registry().get("core.contract.role_rules")
    spec = get_document_registry().get(descriptor.setting_id)
    if spec.active_backend == "database":
        return _migrate_role_capability_catalog_database(
            actor=actor,
            descriptor=descriptor,
            candidate_path=candidate_path,
            expected_runtime_catalog_hash=expected_runtime_catalog_hash,
            expected_git_catalog_hash=expected_git_catalog_hash,
            expected_runtime_hash=expected_runtime_hash,
            reason=reason,
        )
    contract_relpath = _contract_relative_path(descriptor)

    try:
        with exclusive_file_lock(_contract_write_lock_path(), timeout=10.0):
            actor = _require_active_superuser(actor)
            _resolve_known_pending_changes(setting_id=descriptor.setting_id)
            before = read_contract_value(descriptor)
            git_default = _read_git_default_role_rules(descriptor=descriptor)
            candidate = load_json_file(candidate_path)
            _validate_payload_object(descriptor=descriptor, payload=before)
            _validate_payload_object(descriptor=descriptor, payload=candidate)

            runtime_catalog = _role_capability_catalog(before, label="runtime")
            git_catalog = _role_capability_catalog(git_default, label="Git-default")
            candidate_catalog = _role_capability_catalog(candidate, label="candidate")
            runtime_catalog_hash = normalized_hash(runtime_catalog)
            git_catalog_hash = normalized_hash(git_catalog)
            runtime_hash = normalized_hash(before)

            _require_matching_hash(
                expected_runtime_catalog_hash,
                runtime_catalog_hash,
                label="runtime capability catalog",
            )
            _require_matching_hash(
                expected_git_catalog_hash,
                git_catalog_hash,
                label="Git-default capability catalog",
            )
            _require_matching_hash(
                expected_runtime_hash,
                runtime_hash,
                label="full runtime role contract",
            )
            if normalized_hash(candidate_catalog) != git_catalog_hash:
                raise ValidationError(
                    "Справочник candidate не совпадает с текущим Git-default."
                )
            _assert_deployment_catalog_candidate_delta(
                runtime_payload=before,
                candidate_payload=candidate,
            )
            if normalized_hash(before) == normalized_hash(candidate):
                raise ValidationError("В deployment-кандидате нет изменений.")
            _validate_cross_contract_candidate(
                setting_id=descriptor.setting_id,
                candidate=candidate,
            )
            backup_path = _write_role_contract_backup(before)
            change = _write_validated_contract_change(
                actor=actor,
                descriptor=descriptor,
                action=SettingsChange.Action.APPLY,
                before=before,
                after=candidate,
                rollback_of=None,
                contract_relpath=contract_relpath,
                audit_context={
                    "operation": "deployment_role_capability_catalog_migration",
                    "reason": reason,
                    "runtime_catalog_hash_before": runtime_catalog_hash,
                    "git_catalog_hash_target": git_catalog_hash,
                    "backup_file": backup_path.name,
                },
            )
            return {
                "change": change,
                "backup_path": backup_path,
                "runtime_catalog_hash_before": runtime_catalog_hash,
                "git_catalog_hash_target": git_catalog_hash,
            }
    except FileLockTimeoutError as exc:
        raise ValidationError(
            "Контракт сейчас изменяет другой процесс. Повторите позже."
        ) from exc


def _migrate_role_capability_catalog_database(
    *,
    actor,
    descriptor,
    candidate_path,
    expected_runtime_catalog_hash,
    expected_git_catalog_hash,
    expected_runtime_hash,
    reason,
):
    """Обновить frozen capability catalog и Git-default hash одной DB-транзакцией."""

    snapshot = read_contract_snapshot(descriptor)
    if snapshot.source != "database_override":
        raise ValidationError(
            "Deployment-миграция capability после cutover требует существующую DB-ревизию."
        )
    audit_context = {
        "operation": "deployment_role_capability_catalog_migration",
        "reason": reason,
    }
    backup_holder = {}

    def authorize(current_actor):
        _require_active_superuser(current_actor)

    def candidate_factory(_current_actor, before):
        git_default = _read_git_default_role_rules(descriptor=descriptor)
        candidate = load_json_file(candidate_path)
        _validate_payload_object(descriptor=descriptor, payload=before)
        _validate_payload_object(descriptor=descriptor, payload=candidate)

        runtime_catalog = _role_capability_catalog(before, label="runtime")
        git_catalog = _role_capability_catalog(git_default, label="Git-default")
        candidate_catalog = _role_capability_catalog(candidate, label="candidate")
        runtime_catalog_hash = normalized_hash(runtime_catalog)
        git_catalog_hash = normalized_hash(git_catalog)
        _require_matching_hash(
            expected_runtime_catalog_hash,
            runtime_catalog_hash,
            label="runtime capability catalog",
        )
        _require_matching_hash(
            expected_git_catalog_hash,
            git_catalog_hash,
            label="Git-default capability catalog",
        )
        _require_matching_hash(
            expected_runtime_hash,
            normalized_hash(before),
            label="full runtime role contract",
        )
        if normalized_hash(candidate_catalog) != git_catalog_hash:
            raise ValidationError(
                "Справочник candidate не совпадает с текущим Git-default."
            )
        _assert_deployment_catalog_candidate_delta(
            runtime_payload=before,
            candidate_payload=candidate,
        )
        if normalized_hash(before) == normalized_hash(candidate):
            raise ValidationError("В deployment-кандидате нет изменений.")
        audit_context.update(
            {
                "runtime_catalog_hash_before": runtime_catalog_hash,
                "git_catalog_hash_target": git_catalog_hash,
            }
        )
        return candidate

    def validate_candidate(_current_actor, before, candidate):
        _assert_deployment_catalog_candidate_delta(
            runtime_payload=before,
            candidate_payload=candidate,
        )

    def before_write(_current_actor, candidate):
        del candidate
        backup_path = _write_role_contract_backup(snapshot.payload)
        backup_holder["path"] = backup_path
        audit_context["backup_file"] = backup_path.name

    written = ConfigDocumentWriter().migrate_constrained_document_default_via_domain_workflow(
        actor=actor,
        document_id=descriptor.setting_id,
        expected_revision=snapshot.revision,
        expected_content_hash=snapshot.content_hash,
        authorize=authorize,
        candidate_factory=candidate_factory,
        validate_candidate=validate_candidate,
        before_write=before_write,
        audit_context=audit_context,
    )
    if written.change_id is None or "path" not in backup_holder:
        raise ValidationError("Deployment-миграция не создала аудит или backup.")
    return {
        "change": SettingsChange.objects.get(pk=written.change_id),
        "backup_path": backup_holder["path"],
        "runtime_catalog_hash_before": audit_context["runtime_catalog_hash_before"],
        "git_catalog_hash_target": audit_context["git_catalog_hash_target"],
    }


def migrate_role_administration_metadata(
    *, actor, expected_runtime_hash: str, expected_git_hash: str, reason: str
):
    """Remove only inert legacy ``$administration`` during deployment."""

    actor = _require_active_superuser(actor)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Для deployment-миграции нужна причина.")
    _require_autocommit_boundary()
    descriptor = _role_administration_descriptor()
    if _role_administration_active_backend(descriptor) == "database":
        return _migrate_role_administration_metadata_database(
            actor=actor,
            descriptor=descriptor,
            expected_runtime_hash=expected_runtime_hash,
            expected_git_hash=expected_git_hash,
            reason=reason,
        )
    contract_relpath = _contract_relative_path(descriptor)
    legacy_contract_path = _role_legacy_migration_path()
    try:
        with exclusive_file_lock(_contract_write_lock_path(), timeout=10.0):
            actor = _require_active_superuser(actor)
            _resolve_known_pending_changes(setting_id=descriptor.setting_id)
            before = load_json_file(legacy_contract_path)
            git_default = _read_git_default_role_rules(descriptor=descriptor)
            _validate_role_payload_for_migration(before)
            runtime_hash = normalized_hash(before)
            git_hash = normalized_hash(git_default)
            _require_matching_hash(expected_runtime_hash, runtime_hash, label="runtime role contract")
            _require_matching_hash(expected_git_hash, git_hash, label="Git-default role contract")
            if "$administration" in git_default:
                raise ValidationError(
                    "Git-default всё ещё содержит legacy $administration."
                )
            if "$administration" not in before:
                raise ValidationError("Runtime уже не содержит $administration.")
            _assert_runtime_role_catalog_matches_git_default(
                runtime_payload=before, descriptor=descriptor
            )
            after = copy.deepcopy(before)
            after.pop("$administration")
            _validate_role_payload_for_migration(after)
            if {key: value for key, value in before.items() if key != "$administration"} != after:
                raise ValidationError("Migration candidate содержит посторонние изменения.")
            backup_path = _write_role_contract_backup(before)
            change = _write_validated_contract_change(
                actor=actor,
                descriptor=descriptor,
                action=SettingsChange.Action.APPLY,
                before=before,
                after=after,
                rollback_of=None,
                contract_relpath=contract_relpath,
                contract_path=legacy_contract_path,
                audit_context={
                    "operation": "deployment_remove_role_administration",
                    "reason": reason,
                    "git_default_hash": git_hash,
                    "backup_file": backup_path.name,
                },
            )
            return {"change": change, "backup_path": backup_path}
    except FileLockTimeoutError as exc:
        raise ValidationError(
            "Контракт сейчас изменяет другой процесс. Повторите позже."
        ) from exc


def _role_administration_descriptor():
    """Resolve the role descriptor even in a minimal legacy migration sandbox."""

    try:
        return get_registry().get("core.contract.role_rules")
    except ValueError:
        # The legacy migration tests intentionally provide only role_rules.json
        # under a temporary BASE_DIR.  Do not weaken normal registry validation:
        # this fallback is allowed only when the unrelated integration default
        # is absent and the overridden legacy role file exists.
        integration_default = Path(settings.BASE_DIR) / "contracts" / "integrations" / "registry.json"
        role_path = Path(getattr(settings, _LEGACY_ROLE_RULES_SETTINGS_NAME, ""))
        if integration_default.exists() or not role_path.is_file():
            raise
        from apps.core.settings_descriptors import get_settings_descriptors

        return next(
            descriptor
            for descriptor in get_settings_descriptors()
            if descriptor.setting_id == "core.contract.role_rules"
        )


def _role_legacy_migration_path() -> Path:
    path = Path(getattr(settings, _LEGACY_ROLE_RULES_SETTINGS_NAME, ""))
    if not path.is_file():
        raise ValidationError("Legacy-файл role_rules.json недоступен.")
    return path


def _role_administration_active_backend(descriptor):
    try:
        return get_document_registry().get(descriptor.setting_id).active_backend
    except ValueError:
        integration_default = Path(settings.BASE_DIR) / "contracts" / "integrations" / "registry.json"
        role_path = Path(getattr(settings, _LEGACY_ROLE_RULES_SETTINGS_NAME, ""))
        if integration_default.exists() or not role_path.is_file():
            raise
        return "legacy_file"


def _migrate_role_administration_metadata_database(
    *, actor, descriptor, expected_runtime_hash, expected_git_hash, reason
):
    """DB deployment writer for the inert ``$administration`` cleanup.

    The candidate is constructed from the row locked by the constrained
    writer, so a request snapshot or a pre-lock read cannot authorize a stale
    revision.  The writer owns the access lock, PostgreSQL advisory locks,
    row locks, transaction and SettingsChange audit; the backup is created in
    that same guarded callback and removed if the transaction is rolled back.
    """

    snapshot = read_contract_snapshot(descriptor, fresh=True)
    if snapshot.source != "database_override":
        raise ValidationError(
            "Deployment-миграция $administration требует существующую DB-ревизию."
        )
    audit_context = {
        "operation": "deployment_remove_role_administration",
        "reason": reason,
        "runtime_hash_before": snapshot.content_hash,
    }
    backup_holder = {}

    def authorize(current_actor):
        _require_active_superuser(current_actor)

    def candidate_factory(_current_actor, before):
        backup_holder["before"] = copy.deepcopy(before)
        git_default = _read_git_default_role_rules(descriptor=descriptor)
        runtime_hash = normalized_hash(before)
        git_hash = normalized_hash(git_default)
        _require_matching_hash(
            expected_runtime_hash, runtime_hash, label="runtime role contract"
        )
        _require_matching_hash(
            expected_git_hash, git_hash, label="Git-default role contract"
        )
        if "$administration" in git_default:
            raise ValidationError(
                "Git-default всё ещё содержит legacy $administration."
            )
        if "$administration" not in before:
            raise ValidationError("Runtime уже не содержит $administration.")
        _assert_runtime_role_catalog_matches_git_default(
            runtime_payload=before, descriptor=descriptor
        )
        after = copy.deepcopy(before)
        after.pop("$administration")
        expected_after = {
            key: value for key, value in before.items() if key != "$administration"
        }
        if after != expected_after:
            raise ValidationError(
                "Migration candidate может удалить только $administration."
            )
        audit_context.update(
            {
                "runtime_hash_before": runtime_hash,
                "git_default_hash": git_hash,
            }
        )
        return after

    def validate_candidate(_current_actor, before, candidate):
        expected_after = {
            key: value for key, value in before.items() if key != "$administration"
        }
        if candidate != expected_after:
            raise ValidationError(
                "Migration candidate может удалить только $administration."
            )

    def before_write(_current_actor, _candidate):
        backup_path = _write_role_contract_backup(backup_holder["before"])
        backup_holder["path"] = backup_path
        audit_context["backup_file"] = backup_path.name

    try:
        written = ConfigDocumentWriter().migrate_constrained_document_default_via_domain_workflow(
            actor=actor,
            document_id=descriptor.setting_id,
            expected_revision=snapshot.revision,
            expected_content_hash=snapshot.content_hash,
            authorize=authorize,
            candidate_factory=candidate_factory,
            validate_candidate=validate_candidate,
            before_write=before_write,
            audit_context=audit_context,
        )
    except Exception:
        backup_path = backup_holder.get("path")
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)
        raise
    if written.change_id is None or "path" not in backup_holder:
        raise ValidationError("Deployment-миграция не создала аудит или backup.")
    return {
        "change": SettingsChange.objects.get(pk=written.change_id),
        "backup_path": backup_holder["path"],
    }


def apply_explicit_viewer_contract_cutover_locked(
    *, actor, expected_runtime_hash: str, viewer_config: dict, reason: str,
    operation_fingerprint: str | None = None,
):
    """Atomically add only the Git-defined ``viewer`` role.

    The caller owns ``access_control_write_lock_path`` and has already
    validated the migration manifest and database state.  Keeping this small
    primitive here makes the contract replacement use the same staged
    ``SettingsChange``/backup/hash protocol as every other runtime contract
    write without opening the generic role-set writer to callers.
    """
    actor = _require_active_superuser(actor)
    descriptor = get_registry().get("core.contract.role_rules")
    _resolve_known_pending_changes(setting_id=descriptor.setting_id)
    before = read_contract_value(descriptor)
    git_default = _read_git_default_role_rules(descriptor=descriptor)
    _validate_payload_object(descriptor=descriptor, payload=before)
    if normalized_hash(before) != str(expected_runtime_hash or "").removeprefix("sha256:"):
        raise ValidationError("Runtime role contract changed before viewer cutover.")
    if "viewer" in before:
        raise ValidationError("Runtime viewer role is already present.")
    if git_default.get("viewer") != viewer_config:
        raise ValidationError("Viewer definition does not match the Git-default contract.")
    if normalized_hash(before.get("$capabilities")) != normalized_hash(git_default.get("$capabilities")):
        raise ValidationError("Runtime capability catalog differs from Git-default.")
    after = copy.deepcopy(before)
    after["viewer"] = copy.deepcopy(git_default["viewer"])
    _validate_payload_object(descriptor=descriptor, payload=after)
    backup_path = _write_role_contract_backup(before)
    return _write_validated_contract_change(
        actor=actor,
        descriptor=descriptor,
        action=SettingsChange.Action.APPLY,
        before=before,
        after=after,
        rollback_of=None,
        contract_relpath=_contract_relative_path(descriptor),
        operation_fingerprint=operation_fingerprint,
        audit_context={
            "operation": "explicit_viewer_cutover",
            "reason": str(reason or "").strip(),
            "backup_file": backup_path.name,
            "viewer_role_hash": normalized_hash(after["viewer"]),
        },
    )


def rollback_explicit_viewer_contract_locked(
    *, actor, expected_post_cutover_hash: str, expected_before: dict,
    cutover_change: SettingsChange, reason: str,
    operation_fingerprint: str | None = None,
):
    """Atomically remove exactly the migration-added runtime ``viewer`` role."""
    actor = _require_active_superuser(actor)
    descriptor = get_registry().get("core.contract.role_rules")
    _resolve_known_pending_changes(setting_id=descriptor.setting_id)
    before = read_contract_value(descriptor)
    if normalized_hash(before) != str(expected_post_cutover_hash or "").removeprefix("sha256:"):
        raise ValidationError("Runtime contract drifted after viewer cutover; rollback is refused.")
    if not isinstance(expected_before, dict) or set(before) != set(expected_before) | {"viewer"}:
        raise ValidationError("Runtime role set drifted after viewer cutover; rollback is refused.")
    if before.get("viewer") != cutover_change.after_snapshot.get("viewer"):
        raise ValidationError("Runtime viewer definition drifted after cutover; rollback is refused.")
    after = copy.deepcopy(expected_before)
    if normalized_hash(before) == normalized_hash(after) or "viewer" in after:
        raise ValidationError("Rollback candidate is not the exact pre-cutover contract.")
    _validate_payload_object(descriptor=descriptor, payload=after)
    backup_path = _write_role_contract_backup(before)
    return _write_validated_contract_change(
        actor=actor,
        descriptor=descriptor,
        action=SettingsChange.Action.ROLLBACK,
        before=before,
        after=after,
        rollback_of=cutover_change,
        contract_relpath=_contract_relative_path(descriptor),
        operation_fingerprint=operation_fingerprint,
        audit_context={
            "operation": "explicit_viewer_rollback",
            "reason": str(reason or "").strip(),
            "backup_file": backup_path.name,
        },
    )


def preview_contract_rollback(*, actor, change_id: int):
    source, descriptor = _rollback_source(actor=actor, change_id=change_id)
    snapshot = read_contract_snapshot(descriptor)
    current = snapshot.payload
    current_hash = snapshot.content_hash
    if current_hash != source.after_hash:
        raise ValidationError(
            "После выбранной версии контракт уже изменялся. Восстановление старой версии запрещено."
        )
    restored = copy.deepcopy(source.before_snapshot)
    # Снимок повторно проходит текущую версию валидатора: старый допустимый
    # payload не получает автоматического права обойти новые инварианты.
    parse_and_validate_payload(descriptor, json.dumps(restored, ensure_ascii=False))
    return {
        "change_id": source.pk,
        "before": current,
        "after": restored,
        "base_hash": current_hash,
        "base_revision": snapshot.revision,
        "masked_diff": build_masked_diff(current, restored),
        "validation_result": {"valid": True},
    }


def rollback_contract_change(
    *,
    actor,
    change_id: int,
    confirmed: bool,
    base_hash: str | None = None,
    base_revision: int | None = None,
):
    preview = preview_contract_rollback(actor=actor, change_id=change_id)
    if not confirmed:
        raise ValidationError("Для восстановления версии нужно явное подтверждение.")
    if not base_hash or _plain_hash(base_hash) != preview["base_hash"]:
        raise ValidationError("Предпросмотр восстановления устарел. Повторите проверку.")
    source = SettingsChange.objects.get(pk=change_id)
    spec = get_document_registry().get(source.setting_id)
    if spec.active_backend == "database":
        descriptor = get_registry().get(source.setting_id)
        try:
            requested_revision = int(base_revision) if base_revision is not None else None
        except (TypeError, ValueError) as exc:
            raise ValidationError("Ревизия документа имеет неверный формат.") from exc
        if requested_revision != preview["base_revision"]:
            raise ValidationError("Предпросмотр восстановления устарел. Повторите проверку.")
        role_domain_workflow = source.setting_id == "core.contract.role_rules"

        def authorize_role_rollback(current_actor):
            _require_contract_editor(
                actor=current_actor,
                setting_id=source.setting_id,
                descriptor=descriptor,
            )

        def validate_role_rollback(_current_actor, before, after):
            _assert_runtime_role_catalog_matches_git_default(
                runtime_payload=before,
                descriptor=descriptor,
            )
            _assert_candidate_role_catalog_unchanged(
                runtime_payload=before,
                candidate_payload=after,
            )
            _assert_candidate_role_administration_unchanged(
                runtime_payload=before,
                candidate_payload=after,
            )
            _assert_role_set_transport_change(
                runtime_payload=before,
                candidate_payload=after,
            )

        snapshot = ConfigDocumentWriter().rollback_document(
            actor=actor,
            document_id=source.setting_id,
            source_change_id=source.pk,
            expected_revision=preview["base_revision"],
            expected_content_hash=preview["base_hash"],
            authorize=(authorize_role_rollback if role_domain_workflow else None),
            validate_candidate=(
                validate_role_rollback if role_domain_workflow else None
            ),
        )
        if snapshot.change_id is None:
            raise ValidationError("Аудит восстановления документа не создан.")
        return SettingsChange.objects.get(pk=snapshot.change_id)
    return apply_contract_payload(
        actor=actor,
        setting_id=source.setting_id,
        raw_payload=json.dumps(preview["after"], ensure_ascii=False),
        confirmed=True,
        base_hash=preview["base_hash"],
        _action=SettingsChange.Action.ROLLBACK,
        _rollback_of=source,
    )


def reconcile_pending_contract_changes(*, apply: bool, setting_id: str | None = None):
    """Классифицировать незавершённые записи без изменения содержимого файлов."""
    _require_autocommit_boundary()
    reports = []
    with exclusive_file_lock(_contract_write_lock_path(), timeout=10.0):
        changes = SettingsChange.objects.filter(
            storage_kind="runtime_contract",
            action__in=(SettingsChange.Action.APPLY, SettingsChange.Action.ROLLBACK),
            status__in=(SettingsChange.Status.PENDING, SettingsChange.Status.INCONSISTENT),
        ).order_by("id")
        if setting_id:
            changes = changes.filter(setting_id=setting_id)
        for change in changes:
            report = _classify_pending_change(change)
            reports.append(report)
            if apply and report["classification"] not in {"unreadable", "path_changed"}:
                _apply_reconciliation(change=change, classification=report["classification"])
    return reports


def _require_contract_editor(
    *, actor, setting_id, descriptor=None, allow_delegated_role_definition=False
):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Требуется вход в систему.")
    actor_state = get_user_model().objects.filter(pk=actor.pk).first()
    if not actor_state or not actor_state.is_active:
        raise PermissionDenied("Требуется активная учетная запись.")
    if setting_id == "core.contract.role_rules":
        from apps.accounts.access_contracts import (
            ROLE_DEFINITION_EDITOR_DENIED_MESSAGE,
            can_edit_role_definitions,
        )

        if allow_delegated_role_definition:
            rules_snapshot = None
            if get_document_registry().get(setting_id).active_backend == "database":
                rules_snapshot = read_contract_snapshot(
                    get_registry().get(setting_id), fresh=True
                ).payload
            if not can_edit_role_definitions(
                actor_state, rules_snapshot=rules_snapshot
            ):
                raise PermissionDenied(ROLE_DEFINITION_EDITOR_DENIED_MESSAGE)
        elif not actor_state.is_superuser:
            raise PermissionDenied(
                "Полную запись контракта ролей может выполнять только активный суперпользователь."
            )
        return actor_state
    required_permission = getattr(descriptor, "required_permission", "manage_settings")
    if required_permission == "manage_users":
        if not actor_state.is_superuser:
            raise PermissionDenied("Изменение доступно только суперпользователю.")
    elif required_permission == "manage_settings":
        from .policies import can_manage_settings

        if not can_manage_settings(actor_state):
            raise PermissionDenied("Изменять рабочие настройки может только администратор настроек.")
    else:
        # Descriptor permissions are an explicit closed vocabulary.  Do not
        # fall back to Django ``has_perm``: an accidental/legacy string must
        # never become a second product authorization path.
        raise PermissionDenied("Неизвестное право настройки.")
    return actor_state


def _assert_single_role_payload(*, before, after, role_code):
    """Fail closed if a delegated factory touches anything except one role."""
    if (
        not isinstance(role_code, str)
        or not role_code
        or role_code.startswith("$")
        or not isinstance(before, dict)
        or not isinstance(after, dict)
    ):
        raise ValidationError("Ограниченный writer получил некорректный контракт ролей.")
    creating = role_code not in before
    expected_after_keys = set(before) | ({role_code} if creating else set())
    if (
        set(after) != expected_after_keys
        or not isinstance(after.get(role_code), dict)
        or (not creating and not isinstance(before.get(role_code), dict))
    ):
        raise ValidationError(
            "Ограниченный writer может изменить одну роль или создать одну новую роль."
        )
    changed_top_level = sorted(
        key for key in before if key != role_code and before.get(key) != after.get(key)
    )
    if changed_top_level:
        raise ValidationError(
            "Ограниченный writer не может изменять соседние роли или служебные блоки: "
            + ", ".join(changed_top_level)
            + "."
        )


def parse_and_validate_payload(descriptor, raw_payload: str):
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Некорректный JSON: {exc.msg}.") from exc
    payload = copy.deepcopy(payload)
    validator = get_document_registry().get(descriptor.setting_id).validator
    if validator is None:
        raise ValidationError("Для документа не зарегистрирован callable validator.")
    validator(payload)
    return payload


def _validate_payload_object(*, descriptor, payload) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("Контракт ролей должен быть JSON-объектом.")
    validator = get_document_registry().get(descriptor.setting_id).validator
    if validator is None:
        raise ValidationError("Для документа не зарегистрирован callable validator.")
    validator(copy.deepcopy(payload))


def _role_capability_catalog(payload, *, label: str):
    if not isinstance(payload, dict):
        raise ValidationError(f"Контракт {label} должен быть JSON-объектом.")
    catalog = payload.get("$capabilities")
    if not isinstance(catalog, dict) or not catalog:
        raise ValidationError(f"Контракт {label} не содержит валидный $capabilities.")
    if not all(
        isinstance(code, str)
        and code
        and not code.startswith("$")
        and isinstance(metadata, dict)
        for code, metadata in catalog.items()
    ):
        raise ValidationError(f"Справочник $capabilities в {label} некорректен.")
    return catalog


def _read_git_default_role_rules(*, descriptor):
    # Never derive this path from LOCAL_BUSINESS_ROLE_RULES_FILE or another
    # runtime/env override: the deployment comparison is against repository
    # semantics, not against a second alias of the mutable file.
    path = Path(settings.BASE_DIR) / "contracts" / "role_rules.json"
    try:
        payload = load_json_file(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("Не удалось прочитать Git-default role_rules.json.") from exc
    _validate_role_payload_for_migration(payload)
    _role_capability_catalog(payload, label="Git-default")
    return payload


def _validate_role_payload_for_migration(payload) -> None:
    """Validate role payload without requiring unrelated registry defaults."""

    from apps.workorders.contracts import validate_role_rules_payload

    validate_role_rules_payload(copy.deepcopy(payload))


def _assert_runtime_role_catalog_matches_git_default(*, runtime_payload, descriptor) -> None:
    _validate_role_payload_for_migration(runtime_payload)
    runtime_catalog = _role_capability_catalog(runtime_payload, label="runtime")
    git_default = _read_git_default_role_rules(descriptor=descriptor)
    git_catalog = _role_capability_catalog(git_default, label="Git-default")
    if normalized_hash(runtime_catalog) != normalized_hash(git_catalog):
        raise ValidationError(
            "Runtime $capabilities расходится с Git-default; обычная запись "
            "закрыта до deployment-миграции справочника."
        )


def _assert_candidate_role_catalog_unchanged(*, runtime_payload, candidate_payload) -> None:
    runtime_catalog = _role_capability_catalog(runtime_payload, label="runtime")
    candidate_catalog = _role_capability_catalog(candidate_payload, label="candidate")
    if normalized_hash(candidate_catalog) != normalized_hash(runtime_catalog):
        raise ValidationError(
            "$capabilities нельзя изменять через обычную запись или rollback."
        )


def _assert_candidate_role_administration_unchanged(
    *, runtime_payload, candidate_payload
) -> None:
    missing = object()
    if runtime_payload.get("$administration", missing) != candidate_payload.get(
        "$administration", missing
    ):
        raise ValidationError(
            "$administration нельзя изменять через обычную запись или rollback."
        )


def _assert_role_set_transport_change(
    *, runtime_payload, candidate_payload, constrained_role_code=None
) -> None:
    runtime_roles = {
        key for key, value in runtime_payload.items()
        if isinstance(key, str) and not key.startswith("$") and isinstance(value, dict)
    }
    candidate_roles = {
        key for key, value in candidate_payload.items()
        if isinstance(key, str) and not key.startswith("$") and isinstance(value, dict)
    }
    if constrained_role_code:
        allowed = (runtime_roles, runtime_roles | {constrained_role_code})
        if candidate_roles in allowed:
            return
    elif candidate_roles == runtime_roles:
        return
    raise ValidationError(
        "Набор ролей нельзя менять через generic writer или rollback; "
        "используйте предметную операцию создания роли."
    )


def _assert_deployment_catalog_candidate_delta(*, runtime_payload, candidate_payload) -> None:
    runtime_catalog = _role_capability_catalog(runtime_payload, label="runtime")
    candidate_catalog = _role_capability_catalog(candidate_payload, label="candidate")
    runtime_roles = {key for key in runtime_payload if not key.startswith("$")}
    candidate_roles = {key for key in candidate_payload if not key.startswith("$")}
    if runtime_roles != candidate_roles:
        raise ValidationError("Deployment-миграция capability не может менять набор ролей.")

    runtime_service = {key: value for key, value in runtime_payload.items() if key.startswith("$")}
    candidate_service = {key: value for key, value in candidate_payload.items() if key.startswith("$")}
    runtime_service.pop("$capabilities", None)
    candidate_service.pop("$capabilities", None)
    if runtime_service != candidate_service:
        raise ValidationError(
            "Deployment-миграция capability не может менять служебные блоки контракта."
        )

    changed_capabilities = {
        code
        for code in set(runtime_catalog) | set(candidate_catalog)
        if runtime_catalog.get(code) != candidate_catalog.get(code)
    }
    for role_code in sorted(runtime_roles):
        before_role = runtime_payload.get(role_code)
        after_role = candidate_payload.get(role_code)
        if not isinstance(before_role, dict) or not isinstance(after_role, dict):
            raise ValidationError(f"Роль '{role_code}' должна быть JSON-объектом.")
        before_stable = {
            key: value for key, value in before_role.items() if key not in changed_capabilities
        }
        after_stable = {
            key: value for key, value in after_role.items() if key not in changed_capabilities
        }
        if before_stable != after_stable:
            raise ValidationError(
                f"Deployment-миграция capability изменяет несвязанные поля роли '{role_code}'."
            )


def _require_matching_hash(expected, actual, *, label: str) -> None:
    expected = _plain_hash(expected)
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected.lower()):
        raise ValidationError(f"Ожидаемый хеш {label} имеет неверный формат.")
    if expected.lower() != actual.lower():
        raise ValidationError(f"Хеш {label} не совпал с фактическим.")


def _require_active_superuser(actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Требуется вход в систему.")
    actor_state = get_user_model().objects.filter(pk=actor.pk).first()
    if not actor_state or not actor_state.is_active or not actor_state.is_superuser:
        raise PermissionDenied("Deployment-миграция доступна только активному суперпользователю.")
    return actor_state


def _write_role_contract_backup(payload) -> Path:
    backup_root = Path(settings.DATA_DIR) / "contracts" / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = timezone.now().strftime("%Y%m%dT%H%M%S%fZ")
    payload_hash = normalized_hash(payload)
    backup_path = backup_root / f"role_rules.{stamp}.{payload_hash[:12]}.json"
    atomic_write_json(backup_path, payload)
    try:
        written = load_json_file(backup_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("Резервную копию role_rules.json не удалось проверить.") from exc
    if normalized_hash(written) != payload_hash:
        raise ValidationError("Хеш резервной копии role_rules.json не совпал.")
    return backup_path


def _contract_path(descriptor):
    try:
        spec = get_document_registry().get(descriptor.setting_id)
    except ValueError:
        # A legacy deployment migration may run from a minimal unpacked
        # sandbox that contains only role_rules.json.  Keep this compatibility
        # path narrow; ordinary writers must still use the validated registry.
        integration_default = Path(settings.BASE_DIR) / "contracts" / "integrations" / "registry.json"
        role_path = Path(getattr(settings, _LEGACY_ROLE_RULES_SETTINGS_NAME, ""))
        if (
            descriptor.setting_id != "core.contract.role_rules"
            or integration_default.exists()
            or not role_path.is_file()
        ):
            raise
        spec = None
    if spec is not None and spec.active_backend != "legacy_file":
        raise ValidationError(
            "Файловый compatibility writer отключён после переключения документа."
        )
    setting_name = descriptor.metadata.get("settings_path")
    if not setting_name:
        raise ValidationError("Дескриптор не задает settings_path.")
    return getattr(settings, setting_name)


def _contract_write_lock_path() -> Path:
    return access_control_write_lock_path()


def _plain_hash(value: str) -> str:
    value = str(value or "")
    return value.removeprefix("sha256:")


def _require_autocommit_boundary() -> None:
    # TestCase оборачивает каждый тест в служебный atomic. Он не отражает
    # производственный вызывающий контур и безопасно исключается из проверки.
    atomic_blocks = list(getattr(connection, "atomic_blocks", ()))
    is_testcase_transaction = any(
        getattr(block, "_from_testcase", False) for block in atomic_blocks
    )
    if not is_testcase_transaction and (atomic_blocks or not connection.get_autocommit()):
        raise ValidationError(
            "Запись рабочего контракта нельзя выполнять внутри транзакции базы данных."
        )


def _create_pending_contract_change(
    *,
    actor,
    descriptor,
    action,
    before,
    after,
    rollback_of,
    contract_relpath,
    operation_fingerprint=None,
    audit_context=None,
):
    return SettingsChange.objects.create(
        actor=actor,
        setting_id=descriptor.setting_id,
        domain=descriptor.domain,
        storage_kind=descriptor.storage_kind,
        action=action,
        status=SettingsChange.Status.PENDING,
        before_hash=normalized_hash(before),
        after_hash=normalized_hash(after),
        before_snapshot=copy.deepcopy(before),
        after_snapshot=copy.deepcopy(after),
        contract_relpath=contract_relpath,
        operation_fingerprint=operation_fingerprint,
        masked_diff=build_masked_diff(before, after),
        validation_result={"valid": True, **copy.deepcopy(audit_context or {})},
        requires_restart=descriptor.requires_restart,
        requires_reindex=descriptor.requires_reindex,
        rollback_of=rollback_of,
    )


def _write_validated_contract_change(
    *,
    actor,
    descriptor,
    action,
    before,
    after,
    rollback_of,
    contract_relpath,
    contract_path=None,
    operation_fingerprint=None,
    audit_context=None,
):
    """Use the shared staged audit/atomic-write protocol for a validated payload."""

    change = _create_pending_contract_change(
        actor=actor,
        descriptor=descriptor,
        action=action,
        before=before,
        after=after,
        rollback_of=rollback_of,
        contract_relpath=contract_relpath,
        operation_fingerprint=operation_fingerprint,
        audit_context=audit_context,
    )
    try:
        atomic_write_json(contract_path or _contract_path(descriptor), after)
    except Exception:
        _classify_failed_write(change=change, descriptor=descriptor)
        raise

    try:
        written = load_json_file(contract_path) if contract_path is not None else read_contract_value(descriptor)
    except Exception:
        SettingsChange.objects.filter(
            pk=change.pk,
            status=SettingsChange.Status.PENDING,
        ).update(failure_code="post_write_read_failed")
        raise
    if normalized_hash(written) != change.after_hash:
        SettingsChange.objects.filter(
            pk=change.pk,
            status=SettingsChange.Status.PENDING,
        ).update(
            status=SettingsChange.Status.INCONSISTENT,
            failure_code="post_write_hash_mismatch",
        )
        raise ValidationError(
            "После записи хеш контракта не совпал с ожидаемым. Изменение требует разбора."
        )

    now = timezone.now()
    _finalize_contract_change(change=change, now=now)
    change.refresh_from_db()
    return change


def _safe_current_hash(descriptor):
    try:
        return normalized_hash(read_contract_value(descriptor))
    except Exception:
        return None


def _finalize_contract_change(*, change, now) -> None:
    updated = SettingsChange.objects.filter(
        pk=change.pk,
        status=SettingsChange.Status.PENDING,
    ).update(
        status=SettingsChange.Status.APPLIED,
        file_written_at=now,
        applied_at=now,
        failure_code="",
    )
    if updated != 1:
        raise RuntimeError("Не удалось завершить журналирование записи контракта.")


def _classify_failed_write(*, change, descriptor) -> None:
    actual_hash = _safe_current_hash(descriptor)
    update = {"failure_code": "write_failed_unreadable"}
    if actual_hash == change.before_hash:
        update = {
            "status": SettingsChange.Status.FAILED,
            "failure_code": "write_not_observed",
        }
    elif actual_hash == change.after_hash:
        update = {
            "file_written_at": timezone.now(),
            "failure_code": "finalization_required",
        }
    elif actual_hash is not None:
        update = {
            "status": SettingsChange.Status.INCONSISTENT,
            "failure_code": "unexpected_file_version",
        }
    try:
        SettingsChange.objects.filter(
            pk=change.pk,
            status=SettingsChange.Status.PENDING,
        ).update(**update)
    except Exception:
        # Исходная ошибка записи важнее вторичной ошибки диагностической БД.
        pass


def _classify_pending_change(change):
    try:
        descriptor = get_registry().get(change.setting_id)
        if descriptor.storage_kind != "runtime_contract":
            raise LookupError
        try:
            current_relpath = _contract_relative_path(descriptor)
        except ValidationError:
            current_relpath = None
        if current_relpath is None or (
            change.contract_relpath and change.contract_relpath != current_relpath
        ):
            return {
                "id": change.pk,
                "setting_id": change.setting_id,
                "classification": "path_changed",
                "before_hash": change.before_hash[:12],
                "after_hash": change.after_hash[:12],
                "actual_hash": "",
            }
        actual_hash = _safe_current_hash(descriptor)
    except LookupError:
        actual_hash = None
    if actual_hash is None:
        classification = "unreadable"
    elif actual_hash == change.after_hash:
        classification = "applied"
    elif actual_hash == change.before_hash:
        classification = "not_written"
    else:
        classification = "divergent"
    return {
        "id": change.pk,
        "setting_id": change.setting_id,
        "classification": classification,
        "before_hash": change.before_hash[:12],
        "after_hash": change.after_hash[:12],
        "actual_hash": actual_hash[:12] if actual_hash else "",
    }


def _apply_reconciliation(*, change, classification):
    now = timezone.now()
    updates = {"reconciled_at": now}
    if classification == "applied":
        updates.update(
            status=SettingsChange.Status.APPLIED,
            file_written_at=change.file_written_at or now,
            applied_at=change.applied_at or now,
            failure_code="",
        )
    elif classification == "not_written":
        updates.update(
            status=SettingsChange.Status.FAILED,
            failure_code="write_not_observed",
        )
    elif classification == "divergent":
        updates.update(
            status=SettingsChange.Status.INCONSISTENT,
            failure_code="unexpected_file_version",
        )
    SettingsChange.objects.filter(
        pk=change.pk,
        status__in=(SettingsChange.Status.PENDING, SettingsChange.Status.INCONSISTENT),
    ).update(**updates)


def _resolve_known_pending_changes(*, setting_id):
    pending = list(
        SettingsChange.objects.filter(
            setting_id=setting_id,
            storage_kind="runtime_contract",
            action__in=(SettingsChange.Action.APPLY, SettingsChange.Action.ROLLBACK),
            status__in=(SettingsChange.Status.PENDING, SettingsChange.Status.INCONSISTENT),
        ).order_by("id")
    )
    for change in pending:
        report = _classify_pending_change(change)
        if report["classification"] in {"unreadable", "path_changed"}:
            raise ValidationError("Есть незавершённое изменение, которое нельзя сверить автоматически.")
        _apply_reconciliation(change=change, classification=report["classification"])
        if report["classification"] == "divergent":
            raise ValidationError("Есть незавершённое изменение с неизвестной версией файла.")


def _rollback_source(*, actor, change_id):
    try:
        source = SettingsChange.objects.get(pk=change_id)
    except SettingsChange.DoesNotExist as exc:
        raise ValidationError("Изменение для восстановления не найдено.") from exc
    descriptor = get_registry().get(source.setting_id)
    _require_contract_editor(actor=actor, setting_id=source.setting_id, descriptor=descriptor)
    spec = get_document_registry().get(source.setting_id)
    expected_storage_kind = (
        "runtime_document" if spec.active_backend == "database" else "runtime_contract"
    )
    if source.storage_kind != expected_storage_kind or source.action not in {
        SettingsChange.Action.APPLY,
        SettingsChange.Action.ROLLBACK,
    }:
        raise ValidationError("Это изменение не является версией рабочего контракта.")
    if source.status != SettingsChange.Status.APPLIED:
        raise ValidationError("Восстанавливать можно только успешно применённую версию.")
    if source.before_snapshot is None or source.after_snapshot is None:
        raise ValidationError("Для этой версии нет безопасного снимка восстановления.")
    role_domain_workflow = (
        source.setting_id == "core.contract.role_rules"
        and descriptor.write_policy == "requires_domain_workflow"
    )
    if (
        not descriptor.is_editable
        and not role_domain_workflow
    ) or descriptor.sensitivity == "secret":
        raise ValidationError("Этот контракт нельзя восстановить через интерфейс.")
    latest = (
        SettingsChange.objects.filter(
            setting_id=source.setting_id,
            storage_kind=expected_storage_kind,
            action__in=(SettingsChange.Action.APPLY, SettingsChange.Action.ROLLBACK),
            status=SettingsChange.Status.APPLIED,
        )
        .order_by("-id")
        .first()
    )
    if latest is None or latest.pk != source.pk:
        raise ValidationError("Восстанавливать можно только последнюю применённую версию.")
    return source, descriptor


def _contract_relative_path(descriptor) -> str:
    root = Path(getattr(settings, "RUNTIME_CONTRACTS_DIR", Path(settings.DATA_DIR) / "contracts"))
    root = root.resolve()
    target = Path(_contract_path(descriptor)).resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValidationError(
            "Settings Center может изменять контракты только внутри data/contracts."
        ) from exc
    return relative.as_posix()


def _validate_cross_contract_candidate(*, setting_id, candidate):
    document_registry = get_document_registry()
    scope = document_registry.connected_validation_scope((setting_id,))
    descriptors = get_registry()
    payloads = {}
    for document_id in scope:
        payloads[document_id] = (
            copy.deepcopy(candidate)
            if document_id == setting_id
            else read_contract_value(descriptors.get(document_id))
        )
    for document_id in scope:
        spec = document_registry.get(document_id)
        if spec.validator is not None:
            spec.validator(copy.deepcopy(payloads[document_id]))
        if spec.cross_validator is not None:
            related = {
                dependency: copy.deepcopy(payloads[dependency])
                for dependency in spec.cross_document_ids
            }
            spec.cross_validator(copy.deepcopy(payloads[document_id]), related)
