"""Audited, owner-approved migration from the implicit board viewer.

This module is deliberately a small trusted migration boundary.  It does not
add a model or a feature flag: the presence of ``viewer`` in the runtime role
contract is the only phase marker.  Normal role and board writers remain the
public product paths; the helpers below are used only while the shared access
lock is held and every mutation has an audit row.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import AccessAssignmentAudit, GroupProfile
from apps.core.contract_store import get_contract, normalized_hash
from apps.core.file_locks import access_control_write_lock_path, exclusive_file_lock
from apps.core.json_utils import atomic_write_json, load_json_file
from apps.workorders.models import Board, BoardAccessAudit
from apps.workorders.selectors import visible_boards_queryset
from apps.workorders.services import apply_viewer_migration_board_acl_locked
from apps.accounts.services import apply_viewer_migration_role_locked


VIEWER_ROLE = "viewer"
CUSTOMER_ROLE = "customer"
MANIFEST_VERSION = 1
MIGRATION_SIGNING_SALT = "settings-center.explicit-viewer-migration.v1"
PHASE_SIGNING_SALT = "settings-center.explicit-viewer-migration.phase.v1"


def _assert_viewer_migration_legacy_backend():
    """Stop the legacy viewer workflow once access uses the DB repository.

    This check intentionally runs before actor/manifest handling in every
    mutating phase.  A previously prepared legacy manifest must not be able to
    reach membership, board ACL, or legacy-contract writes after the access
    cutover.
    """

    from .document_registry import get_document_registry

    role_spec = get_document_registry().get("core.contract.role_rules")
    if role_spec.active_backend == "database":
        raise ValidationError(
            "Миграция viewer закрыта: access role_rules уже использует PostgreSQL."
        )


def migration_artifact_root() -> Path:
    root = (Path(settings.DATA_DIR) / "access-migrations").resolve()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def _private_artifact_path(path, *, allow_default=True) -> Path:
    root = migration_artifact_root()
    if path is None and allow_default:
        path = root / "latest.operation.json"
    candidate = Path(path).expanduser().resolve()
    if candidate != root and root not in candidate.parents:
        raise ValidationError("Файл операции должен находиться в data/access-migrations/.")
    if candidate == root:
        raise ValidationError("Путь операции должен быть файлом.")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.parent.chmod(0o700)
    return candidate


def _private_write(path, payload):
    path = _private_artifact_path(path)
    atomic_write_json(path, payload)
    path.chmod(0o600)
    return path


def _phase_manifest_hash(manifest):
    payload = copy.deepcopy(manifest)
    payload.pop("phase_signature", None)
    return normalized_hash(payload)


def _sign_phase_manifest(manifest, phase):
    result = copy.deepcopy(manifest)
    result["migration_phase"] = phase
    result.pop("phase_signature", None)
    result["phase_signature"] = signing.dumps(
        {
            "operation_id": result.get("operation_id"),
            "phase": phase,
            "manifest_hash": _phase_manifest_hash(result),
        },
        salt=PHASE_SIGNING_SALT,
        compress=True,
    )
    return result


def _verify_phase_manifest(manifest):
    signature = manifest.get("phase_signature")
    if not signature:
        operation_fields = {
            "migration_phase", "operation_id", "envelope", "operation_path",
            "prepared", "cutover_db_applied", "cutover", "rolled_back",
        }
        if operation_fields & set(manifest):
            raise ValidationError("Подпись этапа миграции отсутствует.")
        return manifest
    try:
        payload = signing.loads(signature, salt=PHASE_SIGNING_SALT, max_age=None)
    except signing.BadSignature as exc:
        raise ValidationError("Подпись этапа миграции недействительна.") from exc
    if (
        payload.get("operation_id") != manifest.get("operation_id")
        or payload.get("phase") != manifest.get("migration_phase")
        or payload.get("manifest_hash") != _phase_manifest_hash(manifest)
    ):
        raise ValidationError("Содержимое этапа миграции изменено после подписи.")
    return manifest


def _persist_phase(path, phase, manifest):
    signed_manifest = _sign_phase_manifest(manifest, phase)
    _private_write(path, {
        "schema_version": MANIFEST_VERSION,
        "phase": phase,
        "operation_id": signed_manifest.get("operation_id"),
        "envelope": signed_manifest.get("envelope"),
        "manifest": signed_manifest,
    })
    return signed_manifest


def _report_immutable_payload(report):
    keys = (
        "schema_version", "phase", "runtime_contract_hash", "git_contract_hash",
        "role_names", "all_active_users", "boards", "cohort_fingerprint", "viewer_definition",
    )
    return {key: copy.deepcopy(report.get(key)) for key in keys}


def _report_hash(report):
    return normalized_hash(_report_immutable_payload(report))


def _operation_envelope(*, report, actor, reason, user_choices, board_choices, operation_id=None):
    payload = {
        "operation_id": operation_id or "",
        "report_hash": report.get("report_hash"),
        "runtime_contract_hash": report.get("runtime_contract_hash"),
        "git_contract_hash": report.get("git_contract_hash"),
        "actor_id": actor.pk,
        "reason": reason,
        "user_choices": user_choices,
        "board_choices": board_choices,
        "final_access_deltas": copy.deepcopy(report.get("final_access_deltas")),
        "all_active_users": report.get("all_active_users"),
        "boards": report.get("boards"),
        "viewer_definition": report.get("viewer_definition"),
    }
    if operation_id is None:
        payload["operation_id"] = hashlib.sha256(
            json.dumps({key: value for key, value in payload.items() if key != "operation_id"}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    return payload, signing.dumps(payload, salt=MIGRATION_SIGNING_SALT, compress=True)


def _verify_envelope(envelope):
    try:
        payload = signing.loads(envelope, salt=MIGRATION_SIGNING_SALT, max_age=None)
    except signing.BadSignature as exc:
        raise ValidationError("Подпись migration-операции недействительна.") from exc
    if not isinstance(payload, dict) or not payload.get("operation_id"):
        raise ValidationError("Migration envelope имеет неверный формат.")
    return payload


def _validate_envelope_binding(manifest, actor, reason):
    envelope = manifest.get("envelope")
    if not envelope:
        raise ValidationError("Подписанный operation envelope отсутствует.")
    payload = _verify_envelope(envelope)
    if payload.get("operation_id") != manifest.get("operation_id") or payload.get("actor_id") != actor.pk:
        raise ValidationError("Operation envelope не связан с actor или operation_id.")
    if payload.get("reason") != reason or payload.get("report_hash") != manifest.get("report_hash"):
        raise ValidationError("Причина или report hash изменены после подписи.")
    expected_users = {str(row["id"]): row.get("choice") for row in manifest.get("users", [])}
    expected_boards = {str(row["id"]): row.get("add_viewer") for row in manifest.get("customer_open_boards", [])}
    if payload.get("user_choices") != expected_users or payload.get("board_choices") != expected_boards:
        raise ValidationError("Owner choices изменены после подписи operation envelope.")
    if payload.get("final_access_deltas") != manifest.get("final_access_deltas"):
        raise ValidationError("Итоговое влияние на доступ изменено после подписи.")
    final_deltas = manifest.get("final_access_deltas")
    expected_delta_ids = {row.get("id") for row in manifest.get("users", [])}
    if (
        not isinstance(final_deltas, list)
        or {row.get("user_id") for row in final_deltas if isinstance(row, dict)} != expected_delta_ids
        or any(
            not isinstance(row, dict)
            or row.get("board_ids_after") is None
            or row.get("board_ids_added") is None
            or row.get("board_ids_removed") is None
            or row.get("requires_board_choices") is not False
            for row in final_deltas
        )
    ):
        raise ValidationError("Подписанный итог влияния на доступ неполон.")
    if payload.get("runtime_contract_hash") != manifest.get("runtime_contract_hash") or payload.get("git_contract_hash") != manifest.get("git_contract_hash"):
        raise ValidationError("Contract hashes изменены после подписи.")
    return payload


def _git_role_contract():
    payload = load_json_file(Path(settings.BASE_DIR) / "contracts" / "role_rules.json")
    if not isinstance(payload, dict) or not isinstance(payload.get(VIEWER_ROLE), dict):
        raise ValidationError("Git-default role contract has no valid viewer role.")
    return payload


def _role_names(contract):
    return {
        key for key, value in contract.items()
        if isinstance(key, str) and not key.startswith("$") and isinstance(value, dict)
    }


def _fresh_superuser(actor):
    User = get_user_model()
    if not getattr(actor, "pk", None):
        raise PermissionDenied("An active superuser is required.")
    current = User.objects.filter(pk=actor.pk, is_active=True, is_superuser=True).first()
    if current is None:
        raise PermissionDenied("Only an active superuser may run viewer migration.")
    return current


def _user_state(user, role_names):
    groups = sorted(user.groups.values_list("name", flat=True))
    return {
        "id": user.pk,
        "username": user.username,
        "is_active": bool(user.is_active),
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "department_id": user.department_id,
        "roles": sorted(set(groups) & role_names),
        "technical_groups": sorted(set(groups) - role_names),
    }


def _active_user_states(role_names):
    User = get_user_model()
    users = (
        User.objects.filter(is_active=True)
        .prefetch_related("groups")
        .order_by("pk")
    )
    return [_user_state(user, role_names) for user in users]


def _base_user_states_ignoring_staged_viewer(role_names):
    """Reconstruct the report-era state while ``viewer`` is still inert."""
    states = _active_user_states(role_names)
    for state in states:
        state["technical_groups"] = [
            name for name in state["technical_groups"] if name != VIEWER_ROLE
        ]
    return states


def _roleless_users(role_names):
    User = get_user_model()
    users = (
        User.objects.filter(is_active=True)
        .prefetch_related("groups")
        .order_by("pk")
    )
    return [user for user in users if not set(user.groups.values_list("name", flat=True)) & role_names]


def _board_state(board):
    groups = sorted(board.allowed_groups.values_list("name", flat=True))
    state = {
        "id": board.pk,
        "title": board.title,
        "slug": board.slug,
        "groups": groups,
    }
    state["state_hash"] = normalized_hash(state)
    return state


def _board_states(role_names):
    boards = Board.objects.prefetch_related("allowed_groups").order_by("pk")
    states = []
    for board in boards:
        state = _board_state(board)
        unknown = sorted(set(state["groups"]) - role_names)
        if unknown:
            raise ValidationError(
                f"Board {board.pk} contains unknown or technical ACL groups: {', '.join(unknown)}."
            )
        states.append(state)
    return states


def _base_board_states_ignoring_staged_viewer(role_names):
    """Reconstruct board snapshots before staged viewer ACL entries."""
    states = _board_states(set(role_names) | {VIEWER_ROLE})
    for state in states:
        if VIEWER_ROLE in state["groups"]:
            state["groups"] = [name for name in state["groups"] if name != VIEWER_ROLE]
            state["state_hash"] = normalized_hash(
                {key: value for key, value in state.items() if key != "state_hash"}
            )
    return states


def _viewer_member_ids():
    return sorted(
        get_user_model().objects.filter(groups__name=VIEWER_ROLE).values_list("pk", flat=True)
    )


def _cohort_fingerprint(users, boards):
    return normalized_hash({"users": users, "boards": boards})


def _visible_board_ids(user):
    """Use the production selector for the current fail-closed access snapshot."""
    return sorted(visible_boards_queryset(user).values_list("pk", flat=True))


def _candidate_board_ids(*, user_state, choice, boards, viewer_board_ids=None):
    all_board_ids = {row["id"] for row in boards}
    if user_state.get("is_superuser"):
        return sorted(all_board_ids)
    if choice == "no_role":
        return []
    if choice == VIEWER_ROLE:
        return None if viewer_board_ids is None else sorted(set(viewer_board_ids))
    return sorted(row["id"] for row in boards if choice in row.get("groups", []))


def _board_access_delta(*, before_ids, after_ids):
    before = sorted(set(before_ids))
    if after_ids is None:
        return {
            "board_ids_before": before,
            "board_ids_after": None,
            "board_ids_added": None,
            "board_ids_removed": None,
            "requires_board_choices": True,
        }
    after = sorted(set(after_ids))
    return {
        "board_ids_before": before,
        "board_ids_after": after,
        "board_ids_added": sorted(set(after) - set(before)),
        "board_ids_removed": sorted(set(before) - set(after)),
        "requires_board_choices": False,
    }


def _finalize_manifest_access_deltas(manifest):
    """Derive exact signed before/after Board access from all owner choices.

    ``prepare`` is inert, so the resulting signed artifact can be reviewed
    before cutover.  No caller-provided delta is trusted.
    """
    result = copy.deepcopy(manifest)
    states = {row["id"]: row for row in result.get("all_active_users", [])}
    boards = result.get("boards", [])
    viewer_board_ids = sorted(
        row["id"]
        for row in result.get("customer_open_boards", [])
        if row.get("add_viewer") is True
    )
    board_choice_rows = result.get("customer_open_boards", [])
    if any(type(row.get("add_viewer")) is not bool for row in board_choice_rows):
        raise ValidationError("Каждая доска требует явного решения по роли viewer.")

    final_rows = []
    for row in result.get("users", []):
        user_id = row.get("id")
        state = states.get(user_id)
        choice = row.get("choice")
        if state is None or choice not in set(result.get("role_names", [])) | {VIEWER_ROLE, "no_role"}:
            raise ValidationError(f"User {user_id} has no exactly-one allowed role choice.")
        before_ids = (
            sorted(board["id"] for board in boards)
            if state.get("is_superuser")
            else []
        )
        after_ids = _candidate_board_ids(
            user_state=state,
            choice=choice,
            boards=boards,
            viewer_board_ids=viewer_board_ids,
        )
        delta = {
            "user_id": user_id,
            "choice": choice,
            **_board_access_delta(before_ids=before_ids, after_ids=after_ids),
        }
        row["selected_delta"] = copy.deepcopy(delta)
        row.setdefault("deltas", {})[choice] = {
            **row.get("deltas", {}).get(choice, {}),
            **{key: value for key, value in delta.items() if key not in {"user_id", "choice"}},
        }
        final_rows.append(delta)
    result["final_access_deltas"] = sorted(final_rows, key=lambda item: item["user_id"])
    return result


def _viewer_group_config(contract):
    config = contract.get(VIEWER_ROLE)
    if not isinstance(config, dict):
        raise ValidationError("Viewer definition is missing from Git-default role contract.")
    return config


def _validate_existing_viewer_group(viewer_config):
    group = Group.objects.filter(name=VIEWER_ROLE).first()
    if group is None:
        return None
    profile = GroupProfile.objects.filter(group=group).first()
    if (
        profile is None
        or not profile.is_predefined
        or profile.title != str(viewer_config.get("display_name", ""))
        or profile.description != str(viewer_config.get("description", ""))
    ):
        raise ValidationError("Existing viewer group/profile is unrelated or drifted.")
    if group.permissions.exists():
        raise ValidationError("Existing viewer group has Django permissions.")
    return group


def _ensure_viewer_group(viewer_config):
    group = Group.objects.create(name=VIEWER_ROLE)
    GroupProfile.objects.create(
        group=group,
        title=str(viewer_config.get("display_name", "")),
        description=str(viewer_config.get("description", "")),
        is_predefined=True,
    )
    return group


def _report_locked():
    runtime = get_contract("role_rules")
    role_names = _role_names(runtime)
    if VIEWER_ROLE in runtime:
        phase = "active"
    else:
        phase = "compatibility"
    users = _active_user_states(role_names)
    roleless = [row for row in users if not row["roles"]]
    roleless_objects = {
        user.pk: user
        for user in get_user_model().objects.filter(pk__in=[row["id"] for row in roleless])
    }
    boards = _board_states(role_names)
    customer_boards = [row for row in boards if CUSTOMER_ROLE in row["groups"]]
    options = sorted(role_names | {VIEWER_ROLE, "no_role"})
    user_rows = []
    for row in roleless:
        before_board_ids = _visible_board_ids(roleless_objects[row["id"]])
        deltas = {}
        for choice in options:
            after = [] if choice == "no_role" else [choice]
            after_board_ids = _candidate_board_ids(
                user_state=row,
                choice=choice,
                boards=boards,
                viewer_board_ids=None,
            )
            deltas[choice] = {
                "roles_after": after,
                "technical_flags_unchanged": True,
                "role_change": {"before": [], "after": after},
                **_board_access_delta(
                    before_ids=before_board_ids,
                    after_ids=after_board_ids,
                ),
                "viewer_candidate_board_ids": [row["id"] for row in customer_boards],
            }
        user_rows.append({
            **row,
            "technical_only": bool(row["technical_groups"]),
            "allowed_choices": options,
            "choice": None,
            "deltas": deltas,
        })
    board_rows = [
        {
            **row,
            "allowed_choices": [True, False],
            "add_viewer": None,
            "delta_if_added": {
                "groups_before": row["groups"],
                "groups_after": sorted(set(row["groups"]) | {VIEWER_ROLE}),
            },
            "delta_if_not_added": {"groups_before": row["groups"], "groups_after": row["groups"]},
        }
        for row in customer_boards
    ]
    report = {
        "schema_version": MANIFEST_VERSION,
        "phase": phase,
        "runtime_contract_hash": normalized_hash(runtime),
        "git_contract_hash": normalized_hash(_git_role_contract()),
        "role_names": sorted(role_names),
        "users": user_rows,
        "all_active_users": users,
        "boards": boards,
        "customer_open_boards": board_rows,
        "cohort_fingerprint": _cohort_fingerprint(users, boards),
        "viewer_definition": copy.deepcopy(_viewer_group_config(_git_role_contract())),
    }
    report["report_hash"] = _report_hash(report)
    return report


def report_roleless_users(*, output_path=None):
    """Read-only report; no roles, groups, ACLs, or contracts are changed."""
    with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
        report = _report_locked()
    if output_path is not False:
        path = _private_artifact_path(output_path)
        _private_write(path, report)
        report["report_path"] = str(path)
    return report


def _manifest_choices(manifest, key, ids):
    rows = manifest.get(key)
    if not isinstance(rows, list):
        raise ValidationError(f"Manifest field '{key}' must be a list.")
    mapping = {}
    for row in rows:
        if not isinstance(row, dict) or isinstance(row.get("id"), bool):
            raise ValidationError(f"Manifest field '{key}' contains an invalid row.")
        item_id = row.get("id")
        if not isinstance(item_id, int) or item_id in mapping:
            raise ValidationError(f"Manifest field '{key}' contains duplicate or invalid IDs.")
        mapping[item_id] = row
    if set(mapping) != set(ids):
        raise ValidationError(f"Manifest field '{key}' must classify the complete current cohort.")
    return mapping


def _load_manifest(manifest):
    if isinstance(manifest, (str, Path)):
        manifest = load_json_file(manifest)
    if isinstance(manifest, dict) and manifest.get("manifest") and manifest.get("envelope"):
        wrapper = manifest
        envelope = _verify_envelope(wrapper["envelope"])
        if envelope.get("operation_id") != wrapper.get("operation_id"):
            raise ValidationError("Migration envelope operation_id does not match artifact.")
        inner = wrapper["manifest"]
        if not isinstance(inner, dict) or not inner.get("phase_signature"):
            raise ValidationError("Внутреннее содержимое файла операции не подписано.")
        inner = _verify_phase_manifest(inner)
        if (
            inner.get("operation_id") != wrapper.get("operation_id")
            or inner.get("envelope") != wrapper.get("envelope")
            or inner.get("migration_phase") != wrapper.get("phase")
        ):
            raise ValidationError("Внешняя и внутренняя части файла операции не совпадают.")
        manifest = inner
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_VERSION:
        raise ValidationError("Unsupported viewer migration manifest.")
    return copy.deepcopy(_verify_phase_manifest(manifest))


def _prepare_manifest_input(manifest):
    manifest = _load_manifest(manifest)
    users = manifest.get("users")
    boards = (
        manifest["customer_open_boards"]
        if "customer_open_boards" in manifest
        else manifest.get("boards")
    )
    if not isinstance(users, list) or not isinstance(boards, list):
        raise ValidationError("Manifest must contain users and customer-open boards.")
    return manifest


def _validate_manifest_against_current(manifest):
    runtime = get_contract("role_rules")
    if VIEWER_ROLE in runtime:
        raise ValidationError("Viewer migration is already cut over.")
    role_names = _role_names(runtime)
    if manifest.get("report_hash") != _report_hash(manifest):
        raise ValidationError("Отчёт изменён: immutable report hash не совпал.")
    if manifest.get("runtime_contract_hash") != normalized_hash(runtime):
        raise ValidationError("Runtime role contract changed since report generation.")
    git = _git_role_contract()
    if manifest.get("git_contract_hash") != normalized_hash(git):
        raise ValidationError("Git-дефолт ролей изменился после формирования отчёта.")
    viewer_config = _viewer_group_config(git)
    if manifest.get("viewer_definition") != viewer_config:
        raise ValidationError("Manifest viewer definition does not match Git-default.")
    current_users = _base_user_states_ignoring_staged_viewer(role_names)
    current_roleless = [row for row in current_users if not row["roles"]]
    current_boards = _base_board_states_ignoring_staged_viewer(role_names)
    if (
        manifest.get("all_active_users") != current_users
        or manifest.get("boards") != current_boards
        or manifest.get("cohort_fingerprint")
        != _cohort_fingerprint(current_users, current_boards)
    ):
        raise ValidationError(
            "Пользователи или ACL досок изменились после формирования отчёта."
        )
    listed_users = manifest.get("users", [])
    listed_ids = {row.get("id") for row in listed_users if isinstance(row, dict)}
    listed_boards = manifest.get("customer_open_boards", [])
    listed_board_ids = {row.get("id") for row in listed_boards if isinstance(row, dict)}
    expected_user_ids = {row["id"] for row in current_roleless}
    expected_board_rows = [row for row in current_boards if CUSTOMER_ROLE in row["groups"]]
    expected_board_ids = {row["id"] for row in expected_board_rows}
    if listed_ids != expected_user_ids or listed_board_ids != expected_board_ids:
        raise ValidationError("Roleless cohort or customer-open board cohort changed.")
    current_by_id = {row["id"]: row for row in current_roleless}
    for row in listed_users:
        # Accept reports from the command (flat rows) and prepared manifests
        # (nested snapshots), but never silently accept a stale identity.
        snapshot = row.get("snapshot")
        if snapshot is None:
            snapshot = {key: row.get(key) for key in current_by_id[row["id"]]}
        if snapshot != current_by_id[row["id"]]:
            raise ValidationError(f"User {row['id']} changed since the report.")
    current_board_by_id = {row["id"]: row for row in current_boards}
    for row in listed_boards:
        current = current_board_by_id[row["id"]]
        snapshot = row.get("snapshot")
        if snapshot is None:
            snapshot = {key: row.get(key) for key in current}
        if snapshot != current:
            raise ValidationError(f"Board {row['id']} changed since the report.")
    choices = _manifest_choices(manifest, "users", expected_user_ids)
    board_choices = _manifest_choices(manifest, "customer_open_boards", expected_board_ids)
    for user_id, row in choices.items():
        choice = row.get("choice")
        if choice not in role_names | {VIEWER_ROLE, "no_role"}:
            raise ValidationError(f"User {user_id} has no exactly-one allowed role choice.")
    for board_id, row in board_choices.items():
        if type(row.get("add_viewer")) is not bool:
            raise ValidationError(f"Board {board_id} requires an explicit ACL choice.")
    return runtime, role_names, current_users, current_boards, choices, board_choices, viewer_config


def prepare_explicit_viewer_migration(*, actor, manifest, reason="", output_path=None):
    """Stage the exact owner choices while viewer remains inert."""
    _assert_viewer_migration_legacy_backend()
    actor = _fresh_superuser(actor)
    manifest = _prepare_manifest_input(manifest)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Нужно указать причину миграции.")
    if manifest.get("prepared"):
        _validate_envelope_binding(manifest, actor, reason)
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            _fresh_superuser(actor)
            _validate_prepared_state(manifest)
        return manifest
    manifest = _finalize_manifest_access_deltas(manifest)
    user_choice_rows = manifest.get("users", [])
    board_choice_rows = manifest.get("customer_open_boards", [])
    user_choices = {str(row["id"]): row.get("choice") for row in user_choice_rows}
    board_choices = {str(row["id"]): row.get("add_viewer") for row in board_choice_rows}
    envelope_payload, signed_envelope = _operation_envelope(
        report=manifest,
        actor=actor,
        reason=reason,
        user_choices=user_choices,
        board_choices=board_choices,
    )
    operation_path = _private_artifact_path(
        output_path or migration_artifact_root() / f"{envelope_payload['operation_id']}.operation.json"
    )
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            actor = _fresh_superuser(actor)
            if operation_path.exists():
                existing_artifact = load_json_file(operation_path)
                existing_operation = existing_artifact.get("operation_id") if isinstance(existing_artifact, dict) else None
                if existing_operation and existing_operation != envelope_payload["operation_id"]:
                    raise ValidationError("Файл уже принадлежит другой операции миграции.")
                if existing_operation == envelope_payload["operation_id"]:
                    existing_manifest = _load_manifest(existing_artifact)
                    existing_phase = existing_manifest.get("migration_phase")
                    if existing_phase == "prepared":
                        _validate_envelope_binding(existing_manifest, actor, reason)
                        _validate_prepared_state(existing_manifest)
                        return existing_manifest
                    if existing_phase not in {"prepare_pending", None}:
                        raise ValidationError(
                            "Операция уже перешла на более поздний этап; возвращаться к подготовке нельзя."
                        )
            pending_manifest = copy.deepcopy(manifest)
            pending_manifest.update({
                "operation_id": envelope_payload["operation_id"],
                "envelope": signed_envelope,
                "operation_path": str(operation_path),
            })
            _persist_phase(operation_path, "prepare_pending", pending_manifest)
            with transaction.atomic():
                runtime, role_names, current_users, current_boards, choices, board_choices, viewer_config = _validate_manifest_against_current(manifest)
                viewer_group = _validate_existing_viewer_group(viewer_config)
                if viewer_group is None:
                    viewer_group = _ensure_viewer_group(viewer_config)
                User = get_user_model()
                required_group_names = {VIEWER_ROLE}
                required_group_names.update(
                    selected["choice"] for selected in choices.values()
                    if selected["choice"] != "no_role"
                )
                required_group_names.update(
                    group_name
                    for row in current_boards
                    if CUSTOMER_ROLE in row["groups"]
                    for group_name in row["groups"]
                )
                role_groups = {
                    name: Group.objects.filter(name=name).first()
                    for name in required_group_names
                }
                if any(group is None for group in role_groups.values()):
                    missing = sorted(name for name, group in role_groups.items() if group is None)
                    raise ValidationError("Required role groups are not seeded: " + ", ".join(missing))
                added_users = []
                by_id = {row["id"]: row for row in current_users}
                for user_id, selected in sorted(choices.items()):
                    user = User.objects.select_for_update().get(pk=user_id)
                    before = by_id[user_id]["roles"]
                    choice = selected["choice"]
                    after = [] if choice == "no_role" else [choice]
                    prepared_after = [VIEWER_ROLE] if choice == VIEWER_ROLE else before
                    if choice == VIEWER_ROLE:
                        apply_viewer_migration_role_locked(
                            actor=actor, target_user=user, role_name=VIEWER_ROLE,
                            operation_id=envelope_payload["operation_id"],
                            expected_before=before, expected_after=prepared_after,
                            reason=reason,
                        )
                    added_users.append({"id": user_id, "choice": choice, "roles_before": before, "roles_after": prepared_after, "cutover_roles_after": after})
                added_boards = []
                current_by_id = {row["id"]: row for row in current_boards}
                for board_id, selected in sorted(board_choices.items()):
                    before = current_by_id[board_id]["groups"]
                    after = sorted(set(before) | {VIEWER_ROLE}) if selected["add_viewer"] else before
                    if selected["add_viewer"]:
                        apply_viewer_migration_board_acl_locked(
                            actor=actor, board=Board.objects.get(pk=board_id),
                            operation_id=envelope_payload["operation_id"],
                            expected_before=before, expected_after=after,
                            reason=reason,
                        )
                    added_boards.append({"id": board_id, "add_viewer": selected["add_viewer"], "groups_before": before, "groups_after": after})
                expected_viewer_users = sorted(
                    user_id for user_id, selected in choices.items()
                    if selected["choice"] == VIEWER_ROLE
                )
                actual_viewer_boards = sorted(
                    Board.objects.filter(allowed_groups=viewer_group).values_list("pk", flat=True)
                )
                expected_viewer_boards = sorted(
                    board_id for board_id, selected in board_choices.items()
                    if selected["add_viewer"]
                )
                if _viewer_member_ids() != expected_viewer_users:
                    raise ValidationError("Состав роли «Наблюдатель» не совпадает с подписанным планом.")
                if actual_viewer_boards != expected_viewer_boards:
                    raise ValidationError("Доступ роли «Наблюдатель» к доскам не совпадает с подписанным планом.")
                prepared_users = _active_user_states(role_names | {VIEWER_ROLE})
                prepared_boards = _board_states(role_names | {VIEWER_ROLE})
                result = copy.deepcopy(manifest)
                result.update({
                    "prepared": True,
                    "prepared_at": timezone.now().isoformat(),
                    "prepared_by": actor.pk,
                    "prepared_contract_hash": normalized_hash(runtime),
                    "prepared_users": prepared_users,
                    "prepared_boards": prepared_boards,
                    "prepared_viewer_members": _viewer_member_ids(),
                    "added_users": added_users,
                    "added_boards": added_boards,
                    "prepared_state_fingerprint": _cohort_fingerprint(prepared_users, prepared_boards),
                    "operation_id": envelope_payload["operation_id"],
                    "envelope": signed_envelope,
                    "operation_path": str(operation_path),
                })
    except OSError as exc:
        raise ValidationError("Could not acquire the access migration lock.") from exc
    return _persist_phase(operation_path, "prepared", result)


def _validate_prepared_state(manifest):
    runtime = get_contract("role_rules")
    if VIEWER_ROLE in runtime:
        raise ValidationError("Viewer is already active; prepared state cannot be reused.")
    role_names = _role_names(runtime)
    if manifest.get("prepared_contract_hash") != normalized_hash(runtime):
        raise ValidationError("Prepared runtime contract changed before cutover.")
    current_users = _active_user_states(role_names | {VIEWER_ROLE})
    current_boards = _board_states(role_names | {VIEWER_ROLE})
    if current_users != manifest.get("prepared_users") or current_boards != manifest.get("prepared_boards"):
        raise ValidationError("Prepared users, departments, flags, memberships, or ACLs drifted.")
    if _viewer_member_ids() != manifest.get("prepared_viewer_members"):
        raise ValidationError("Prepared viewer membership drifted.")
    if _validate_existing_viewer_group(manifest.get("viewer_definition") or {}) is None:
        raise ValidationError("Prepared viewer group/profile is missing or drifted.")
    return runtime, current_users, current_boards


def _expected_cutover_user_states(manifest):
    expected = copy.deepcopy(manifest.get("prepared_users") or [])
    by_id = {row["id"]: row for row in expected}
    for change in manifest.get("added_users", []):
        if change["id"] not in by_id:
            raise ValidationError("План миграции ссылается на отсутствующего пользователя.")
        by_id[change["id"]]["roles"] = sorted(
            change.get("cutover_roles_after", change.get("roles_after", []))
        )
    return expected


def _validate_cutover_recoverable_state(manifest):
    """Accept an untouched or partially applied DB phase, never unrelated drift."""
    runtime = get_contract("role_rules")
    if VIEWER_ROLE in runtime:
        raise ValidationError("Роль «Наблюдатель» уже активна в рабочем контракте.")
    role_names = _role_names(runtime)
    if manifest.get("prepared_contract_hash") != normalized_hash(runtime):
        raise ValidationError("Рабочий контракт ролей изменился после подготовки.")
    _validate_existing_viewer_group(manifest.get("viewer_definition") or {})
    current_users = _active_user_states(role_names | {VIEWER_ROLE})
    prepared_users = manifest.get("prepared_users") or []
    expected_users = _expected_cutover_user_states(manifest)
    if {row["id"] for row in current_users} != {row["id"] for row in prepared_users}:
        raise ValidationError("Состав активных пользователей изменился после подготовки.")
    prepared_by_id = {row["id"]: row for row in prepared_users}
    expected_by_id = {row["id"]: row for row in expected_users}
    for current in current_users:
        before = prepared_by_id[current["id"]]
        after = expected_by_id[current["id"]]
        current_without_roles = {key: value for key, value in current.items() if key != "roles"}
        before_without_roles = {key: value for key, value in before.items() if key != "roles"}
        if current_without_roles != before_without_roles:
            raise ValidationError(f"Данные пользователя {current['id']} изменились после подготовки.")
        if current["roles"] not in (before["roles"], after["roles"]):
            raise ValidationError(f"Роли пользователя {current['id']} не соответствуют плану миграции.")
    current_boards = _board_states(role_names | {VIEWER_ROLE})
    if current_boards != manifest.get("prepared_boards"):
        raise ValidationError("Доступ к доскам изменился после подготовки.")
    if _viewer_member_ids() != manifest.get("prepared_viewer_members"):
        raise ValidationError("Состав роли «Наблюдатель» изменился после подготовки.")
    return runtime, current_users, current_boards


def cutover_explicit_viewer(*, actor, manifest, reason=""):
    _assert_viewer_migration_legacy_backend()
    from .contract_services import (
        _resolve_known_pending_changes,
        apply_explicit_viewer_contract_cutover_locked,
    )

    actor = _fresh_superuser(actor)
    manifest = _load_manifest(manifest)
    if not manifest.get("prepared"):
        raise ValidationError("Only a prepared manifest can be cut over.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A migration reason is required.")
    _validate_envelope_binding(manifest, actor, reason)
    with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
        actor = _fresh_superuser(actor)
        from .models import SettingsChange
        _resolve_known_pending_changes(setting_id="core.contract.role_rules")
        operation_fingerprint = normalized_hash({"operation_id": manifest.get("operation_id"), "operation": "cutover"})
        active_change = SettingsChange.objects.filter(operation_fingerprint=operation_fingerprint, status=SettingsChange.Status.APPLIED).first()
        runtime_now = get_contract("role_rules")
        if VIEWER_ROLE in runtime_now and active_change is not None:
            if normalized_hash(runtime_now) != active_change.after_hash:
                raise ValidationError("Рабочий контракт ролей изменился после включения роли.")
            expected_post_users = _expected_cutover_user_states(manifest)
            if _active_user_states(_role_names(runtime_now)) != expected_post_users:
                raise ValidationError("После cutover обнаружен drift пользователей или ролей.")
            if _board_states(_role_names(runtime_now)) != manifest.get("prepared_boards"):
                raise ValidationError("После включения роли изменился доступ к доскам.")
            if _validate_existing_viewer_group(manifest.get("viewer_definition") or {}) is None:
                raise ValidationError("Группа «Наблюдатель» отсутствует.")
            if _viewer_member_ids() != manifest.get("prepared_viewer_members"):
                raise ValidationError("Состав роли «Наблюдатель» изменился после включения.")
            result = copy.deepcopy(manifest)
            result.update({
                "cutover": True,
                "cutover_change_id": active_change.pk,
                "post_cutover_contract_hash": active_change.after_hash,
                "post_cutover_users": expected_post_users,
                "post_cutover_boards": copy.deepcopy(manifest.get("prepared_boards")),
            })
            return _persist_phase(Path(result["operation_path"]), "cutover", result)
        runtime, current_users, current_boards = _validate_cutover_recoverable_state(manifest)
        role_names = _role_names(runtime)
        with transaction.atomic():
            for row in manifest.get("added_users", []):
                choice = row.get("choice")
                if choice in {VIEWER_ROLE, "no_role"}:
                    continue
                apply_viewer_migration_role_locked(
                    actor=actor,
                    target_user=get_user_model().objects.get(pk=row["id"]),
                    role_name=choice,
                    operation_id=manifest["operation_id"],
                    expected_before=row.get("roles_after", []),
                    expected_after=row.get("cutover_roles_after", [choice]),
                    reason=reason,
                )
        post_users = _active_user_states(role_names | {VIEWER_ROLE})
        post_manifest = copy.deepcopy(manifest)
        post_manifest.update({
            "cutover_db_applied": True,
            "post_cutover_users": post_users,
            "post_cutover_boards": current_boards,
        })
        post_manifest = _persist_phase(
            Path(manifest["operation_path"]), "cutover_db_applied", post_manifest
        )
        change = SettingsChange.objects.filter(operation_fingerprint=operation_fingerprint, status=SettingsChange.Status.APPLIED).first()
        if change is None:
            change = apply_explicit_viewer_contract_cutover_locked(
                actor=actor,
                expected_runtime_hash=normalized_hash(runtime),
                viewer_config=manifest["viewer_definition"],
                reason=reason,
                operation_fingerprint=operation_fingerprint,
            )
    result = copy.deepcopy(post_manifest)
    result.update({
        "cutover": True,
        "cutover_at": timezone.now().isoformat(),
        "cutover_change_id": change.pk,
        "post_cutover_contract_hash": change.after_hash,
    })
    return _persist_phase(Path(result["operation_path"]), "cutover", result)


def _validate_rollback_recoverable_state(manifest, runtime):
    """Allow only exact pre/post states for each migration-owned DB change."""
    role_names = _role_names(runtime) | {VIEWER_ROLE}
    if _validate_existing_viewer_group(manifest.get("viewer_definition") or {}) is None:
        raise ValidationError("Группа «Наблюдатель» отсутствует.")
    if not set(_viewer_member_ids()).issubset(set(manifest.get("prepared_viewer_members") or [])):
        raise ValidationError("В роли «Наблюдатель» обнаружены посторонние пользователи.")
    current_users = _active_user_states(role_names)
    original_users = manifest.get("all_active_users") or []
    post_users = _expected_cutover_user_states(manifest)
    if {row["id"] for row in current_users} != {row["id"] for row in original_users}:
        raise ValidationError("Состав активных пользователей изменился после миграции.")
    original_by_id = {row["id"]: row for row in original_users}
    post_by_id = {row["id"]: row for row in post_users}
    changed_ids = {row["id"] for row in manifest.get("added_users", []) if row.get("choice") != "no_role"}
    for current in current_users:
        original = original_by_id[current["id"]]
        post = post_by_id[current["id"]]
        current_without_roles = {key: value for key, value in current.items() if key != "roles"}
        original_without_roles = {key: value for key, value in original.items() if key != "roles"}
        if current_without_roles != original_without_roles:
            raise ValidationError(f"Данные пользователя {current['id']} изменились после миграции.")
        allowed_roles = (original["roles"], post["roles"]) if current["id"] in changed_ids else (original["roles"],)
        if current["roles"] not in allowed_roles:
            raise ValidationError(f"Роли пользователя {current['id']} не соответствуют откату.")

    current_boards = _board_states(role_names)
    original_boards = manifest.get("boards") or []
    post_boards = manifest.get("prepared_boards") or []
    if {row["id"] for row in current_boards} != {row["id"] for row in original_boards}:
        raise ValidationError("Состав досок изменился после миграции.")
    original_board_by_id = {row["id"]: row for row in original_boards}
    post_board_by_id = {row["id"]: row for row in post_boards}
    changed_board_ids = {
        row["id"] for row in manifest.get("added_boards", []) if row.get("add_viewer")
    }
    for current in current_boards:
        original = original_board_by_id[current["id"]]
        post = post_board_by_id[current["id"]]
        current_identity = {key: value for key, value in current.items() if key not in {"groups", "state_hash"}}
        original_identity = {key: value for key, value in original.items() if key not in {"groups", "state_hash"}}
        if current_identity != original_identity:
            raise ValidationError(f"Доска {current['id']} изменилась после миграции.")
        allowed_groups = (original["groups"], post["groups"]) if current["id"] in changed_board_ids else (original["groups"],)
        if current["groups"] not in allowed_groups:
            raise ValidationError(f"Доступ к доске {current['id']} не соответствует откату.")
    return current_users, current_boards


def rollback_explicit_viewer(*, actor, manifest, reason=""):
    _assert_viewer_migration_legacy_backend()
    from .contract_services import (
        _resolve_known_pending_changes,
        rollback_explicit_viewer_contract_locked,
    )

    actor = _fresh_superuser(actor)
    manifest = _load_manifest(manifest)
    if not manifest.get("prepared") or not manifest.get("cutover"):
        raise ValidationError("Only a completed viewer cutover can be rolled back.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A migration reason is required.")
    _validate_envelope_binding(manifest, actor, reason)
    from .models import SettingsChange

    cutover = SettingsChange.objects.filter(
        pk=manifest.get("cutover_change_id"),
        setting_id="core.contract.role_rules",
        action=SettingsChange.Action.APPLY,
        status=SettingsChange.Status.APPLIED,
    ).first()
    if cutover is None:
        raise ValidationError("The audited viewer cutover change is missing or incomplete.")
    with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
        actor = _fresh_superuser(actor)
        _resolve_known_pending_changes(setting_id="core.contract.role_rules")
        runtime = get_contract("role_rules")
        rollback_fingerprint = normalized_hash({"operation_id": manifest.get("operation_id"), "operation": "rollback"})
        change = SettingsChange.objects.filter(operation_fingerprint=rollback_fingerprint, status=SettingsChange.Status.APPLIED).first()
        if VIEWER_ROLE in runtime:
            if normalized_hash(runtime) != manifest.get("post_cutover_contract_hash"):
                raise ValidationError("Runtime contract drifted after cutover; rollback is refused.")
            current_users = _active_user_states(_role_names(runtime))
            current_boards = _board_states(_role_names(runtime))
            if current_users != manifest.get("post_cutover_users") or current_boards != manifest.get("post_cutover_boards"):
                raise ValidationError("Viewer membership, role, or board ACL drifted after cutover.")
            if _viewer_member_ids() != manifest.get("prepared_viewer_members"):
                raise ValidationError("Viewer membership drifted after cutover; rollback is refused.")
            if _validate_existing_viewer_group(manifest.get("viewer_definition") or {}) is None:
                raise ValidationError("Группа «Наблюдатель» отсутствует или изменена.")
            if change is not None:
                raise ValidationError("Журнал отката не соответствует текущей версии контракта.")
            change = rollback_explicit_viewer_contract_locked(
                actor=actor,
                expected_post_cutover_hash=manifest["post_cutover_contract_hash"],
                expected_before=cutover.before_snapshot,
                cutover_change=cutover,
                reason=reason,
                operation_fingerprint=rollback_fingerprint,
            )
        elif change is None or normalized_hash(runtime) != cutover.before_hash:
            raise ValidationError("Rollback contract state is incomplete or drifted.")
        _validate_rollback_recoverable_state(manifest, runtime)
        with transaction.atomic():
            for row in manifest.get("added_users", []):
                choice = row.get("choice")
                if choice == "no_role":
                    continue
                user = get_user_model().objects.get(pk=row["id"])
                apply_viewer_migration_role_locked(
                    actor=actor,
                    target_user=user, role_name=choice, operation_id=manifest["operation_id"],
                    expected_before=row.get("cutover_roles_after", row.get("roles_after", [])),
                    expected_after=row.get("roles_before", []),
                    reason=reason, remove=True,
                )
            for row in manifest.get("added_boards", []):
                if not row.get("add_viewer"):
                    continue
                apply_viewer_migration_board_acl_locked(
                    actor=actor, board=Board.objects.get(pk=row["id"]),
                    operation_id=manifest["operation_id"],
                    expected_before=row.get("groups_after"), expected_after=row.get("groups_before"),
                    reason=reason, remove=True,
                )
        if _active_user_states(_role_names(runtime) | {VIEWER_ROLE}) != manifest.get("all_active_users"):
            raise ValidationError("После отката роли пользователей не вернулись в исходное состояние.")
        if _board_states(_role_names(runtime) | {VIEWER_ROLE}) != manifest.get("boards"):
            raise ValidationError("После отката доступ к доскам не вернулся в исходное состояние.")
    result = copy.deepcopy(manifest)
    result.update({"rolled_back": True, "rolled_back_at": timezone.now().isoformat(), "rollback_change_id": change.pk})
    return _persist_phase(Path(result["operation_path"]), "rolled_back", result)
