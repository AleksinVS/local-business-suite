import hashlib
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.contract_store import current_contract_hash
from apps.core.contract_store import get_degradation_state
from apps.core.contract_store import normalized_hash
from apps.core.file_locks import (
    FileLockTimeoutError,
    access_control_write_lock_path,
    exclusive_file_lock,
)
from apps.accounts.selectors import contract_role_names

from . import notification_events
from .models import Board, BoardAccessAudit, KanbanColumnConfig, WorkOrder, WorkOrderStatus, WorkOrderTransitionLog
from .policies import board_access_role_names, can_manage_board_access


BOARD_ACCESS_PREVIEW_SALT = "workorders.board-access-preview.v1"
BOARD_ACCESS_PREVIEW_MAX_AGE_SECONDS = 600
BOARD_ACCESS_GRANT_RISK = "Добавление роли откроет сотрудникам доступ к доске"
BOARD_ACCESS_REMOVAL_RISK = "Удаление роли может лишить сотрудников доступа к доске"
BOARD_ACCESS_EMPTY_RISK = "Пустой список закроет доску для всех обычных пользователей"
BOARD_ACCESS_BREAK_GLASS_RISK = "Резервное изменение через Django Admin"
SYSTEM_BOOTSTRAP_PREEXISTING_BOARD_SLUGS = frozenset({"main", "backlog"})


def preview_board_access(
    *,
    actor,
    board,
    selected_group_names,
    reason="",
    source=BoardAccessAudit.Source.SETTINGS_CENTER,
):
    actor = _current_board_access_actor(actor)
    source, reason = _validate_board_access_context(actor=actor, source=source, reason=reason)
    board = Board.objects.get(pk=board.pk)
    before = _board_group_names(board)
    after = _validate_board_group_names(selected_group_names)
    _require_role_contract_healthy()
    _require_existing_groups_are_contract_roles(before)
    if before == after:
        raise ValidationError("Доступ к доске не изменился.")
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    risk_markers = _board_access_risk_markers(
        after=after,
        added=added,
        removed=removed,
        source=source,
    )
    if risk_markers and not reason:
        raise ValidationError("Для изменения доступа к доске укажите причину.")
    impact = _board_access_impact(before=before, after=after)
    population_fingerprint = _board_access_population_fingerprint(before=before, after=after)
    role_contract_hash = current_contract_hash("role_rules")
    _require_role_contract_healthy()
    payload = {
        "actor_id": actor.pk,
        "actor_state": _board_access_actor_state(actor),
        "board_id": board.pk,
        "before": before,
        "after": after,
        "source": source,
        "reason": reason,
        "role_contract_hash": role_contract_hash,
        "impact_hash": normalized_hash(impact),
        "population_fingerprint": population_fingerprint,
        "nonce": str(uuid.uuid4()),
    }
    return {
        "board_id": board.pk,
        "before": before,
        "after": after,
        "added": added,
        "removed": removed,
        "impact": impact,
        "risk_markers": risk_markers,
        "requires_confirmation": bool(risk_markers),
        "source": source,
        "reason": reason,
        "preview_token": signing.dumps(
            payload,
            salt=BOARD_ACCESS_PREVIEW_SALT,
            compress=True,
        ),
    }


def apply_board_access(
    *,
    actor,
    board,
    selected_group_names,
    preview_token,
    risk_confirmed=False,
    reason="",
    source=BoardAccessAudit.Source.SETTINGS_CENTER,
):
    """Сериализовать ACL доски с изменениями членства в контрактных ролях."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _apply_board_access_locked(
                actor=actor,
                board=board,
                selected_group_names=selected_group_names,
                preview_token=preview_token,
                risk_confirmed=risk_confirmed,
                reason=reason,
                source=source,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _apply_board_access_locked(
    *,
    actor,
    board,
    selected_group_names,
    preview_token,
    risk_confirmed=False,
    reason="",
    source=BoardAccessAudit.Source.SETTINGS_CENTER,
):
    after = _validate_board_group_names(selected_group_names)
    signed_preview = _load_board_access_preview(preview_token)
    if signed_preview.get("actor_id") != actor.pk or signed_preview.get("board_id") != board.pk:
        raise ValidationError("Предпросмотр относится к другой доске или администратору.")
    if signed_preview.get("after") != after:
        raise ValidationError("Выбранные роли изменились после предпросмотра.")

    User = get_user_model()
    locked_actor = User.objects.select_for_update().get(pk=actor.pk)
    _require_board_access_manager(locked_actor)
    if signed_preview.get("actor_state") != _board_access_actor_state(locked_actor):
        raise ValidationError("Права администратора изменились после предпросмотра.")
    source, reason = _validate_board_access_context(
        actor=locked_actor,
        source=source,
        reason=reason,
    )
    if signed_preview.get("source") != source or signed_preview.get("reason") != reason:
        raise ValidationError("Источник или причина изменились после предпросмотра.")
    role_contract_hash = current_contract_hash("role_rules")
    _require_role_contract_healthy()
    if signed_preview.get("role_contract_hash") != role_contract_hash:
        raise ValidationError("Контракт ролей изменился после предпросмотра.")

    locked_board = Board.objects.select_for_update().get(pk=board.pk)
    before = _board_group_names(locked_board)
    _require_existing_groups_are_contract_roles(before)
    if signed_preview.get("before") != before:
        raise ValidationError("Доступ к доске уже изменился. Выполните предпросмотр снова.")
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    risk_markers = _board_access_risk_markers(
        after=after,
        added=added,
        removed=removed,
        source=source,
    )
    if risk_markers and not risk_confirmed:
        raise ValidationError("Изменение доступа к доске требует явного подтверждения риска.")
    current_impact = _board_access_impact(before=before, after=after)
    if signed_preview.get("impact_hash") != normalized_hash(current_impact) or signed_preview.get(
        "population_fingerprint"
    ) != _board_access_population_fingerprint(before=before, after=after):
        raise ValidationError(
            "Состав сотрудников или влияние изменения изменились. Выполните предпросмотр снова."
        )

    groups = list(Group.objects.filter(name__in=after).order_by("name"))
    existing_names = {group.name for group in groups}
    missing = sorted(set(after) - existing_names)
    if missing:
        raise ValidationError(
            "Группы ролей ещё не созданы: " + ", ".join(missing) + ". Выполните seed_roles."
        )
    preview_fingerprint = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()
    if BoardAccessAudit.objects.filter(preview_fingerprint=preview_fingerprint).exists():
        raise ValidationError("Этот предпросмотр уже был применён.")

    locked_board.allowed_groups.set(groups)
    try:
        audit = BoardAccessAudit.objects.create(
            board=locked_board,
            actor=locked_actor,
            groups_before=before,
            groups_after=after,
            groups_added=added,
            groups_removed=removed,
            risk_markers=risk_markers,
            risk_confirmed=bool(risk_markers and risk_confirmed),
            source=source,
            reason=reason,
            role_contract_hash=role_contract_hash,
            preview_fingerprint=preview_fingerprint,
        )
    except IntegrityError as exc:
        raise ValidationError("Этот предпросмотр уже был применён.") from exc
    return locked_board, audit


@transaction.atomic
def clone_board(*, actor, board, new_title=None, new_slug=None, reason=""):
    """Клонировать структуру доски без скрытого наследования доступа."""
    actor = _current_board_access_actor(actor)
    source_board = Board.objects.select_for_update().get(pk=board.pk)
    cloned = Board.objects.create(
        title=new_title or f"{source_board.title} (копия)",
        slug=_unique_board_slug(new_slug or f"{source_board.slug}-copy"),
    )
    KanbanColumnConfig.objects.bulk_create(
        [
            KanbanColumnConfig(
                board=cloned,
                code=column.code,
                title=column.title,
                position=column.position,
                statuses=list(column.statuses),
                wip_limit=column.wip_limit,
            )
            for column in source_board.columns.all()
        ]
    )
    return cloned


def initialize_board_access_for_bootstrap(
    *, board, selected_group_names, reason, board_was_created
):
    """Однократная и аудируемая инициализация ACL новой демонстрационной доски."""
    if not str(reason or "").strip():
        raise ValidationError("Для bootstrap-доступа к доске требуется причина.")
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _initialize_board_access_for_bootstrap_locked(
                board=board,
                selected_group_names=selected_group_names,
                reason=reason,
                board_was_created=board_was_created,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _initialize_board_access_for_bootstrap_locked(
    *, board, selected_group_names, reason, board_was_created
):
    after = _validate_board_group_names(selected_group_names)
    _require_role_contract_healthy()
    locked = Board.objects.select_for_update().get(pk=board.pk)
    before = _board_group_names(locked)
    if before:
        # Bootstrap не владеет уже существующим ACL и никогда его не
        # выравнивает под демонстрационный набор.
        return locked, None
    if locked.access_audits.exists():
        raise ValidationError("Доступ к доске уже имеет историю и не может быть bootstrap-изменением.")
    if (
        not board_was_created
        and locked.slug not in SYSTEM_BOOTSTRAP_PREEXISTING_BOARD_SLUGS
    ):
        raise ValidationError(
            "Bootstrap-доступ разрешён только для новой или канонической системной доски."
        )
    groups = list(Group.objects.filter(name__in=after))
    locked.allowed_groups.set(groups)
    audit = BoardAccessAudit.objects.create(
        board=locked,
        actor=None,
        groups_before=[],
        groups_after=after,
        groups_added=after,
        groups_removed=[],
        risk_markers=[BOARD_ACCESS_GRANT_RISK] if after else [],
        risk_confirmed=False,
        source=BoardAccessAudit.Source.SYSTEM_BOOTSTRAP,
        reason=str(reason).strip(),
        role_contract_hash=current_contract_hash("role_rules"),
    )
    return locked, audit


def _current_board_access_actor(actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Требуется вход в систему.")
    current = get_user_model().objects.get(pk=actor.pk)
    _require_board_access_manager(current)
    return current


def _require_board_access_manager(actor):
    if not can_manage_board_access(actor):
        raise PermissionDenied("Недостаточно прав для управления доступом к доскам.")


def _board_access_actor_state(actor):
    return {
        "is_active": bool(actor.is_active),
        "is_superuser": bool(actor.is_superuser),
        "roles": sorted(actor.groups.values_list("name", flat=True)),
    }


def _validate_board_access_context(*, actor, source, reason):
    valid_sources = {
        BoardAccessAudit.Source.SETTINGS_CENTER,
        BoardAccessAudit.Source.DJANGO_ADMIN_BREAK_GLASS,
    }
    if source not in valid_sources:
        raise ValidationError("Неизвестный источник изменения доступа к доске.")
    reason = str(reason or "").strip()
    if len(reason) > 1000:
        raise ValidationError("Причина не должна превышать 1000 символов.")
    if source == BoardAccessAudit.Source.DJANGO_ADMIN_BREAK_GLASS:
        if not actor.is_active or not actor.is_superuser:
            raise PermissionDenied("Резервное изменение доступно только активному суперпользователю.")
        if not reason:
            raise ValidationError("Для резервного изменения укажите причину.")
    return source, reason


def _validate_board_group_names(group_names):
    if not isinstance(group_names, (list, tuple, set)) or not all(
        isinstance(name, str) and name.strip() for name in group_names
    ):
        raise ValidationError("Роли доски должны быть списком.")
    normalized = tuple(sorted({name.strip() for name in group_names}))
    unknown = sorted(set(normalized) - set(board_access_role_names()))
    if unknown:
        raise ValidationError("Для доски недопустимы группы: " + ", ".join(unknown) + ".")
    _require_seeded_board_groups(normalized)
    return list(normalized)


def _require_existing_groups_are_contract_roles(group_names):
    unknown = sorted(set(group_names) - set(board_access_role_names()))
    if unknown:
        raise ValidationError(
            "Доска содержит устаревшие или технические группы: "
            + ", ".join(unknown)
            + ". Сначала разберите их вручную."
        )


def _require_seeded_board_groups(group_names):
    existing = set(Group.objects.filter(name__in=group_names).values_list("name", flat=True))
    missing = sorted(set(group_names) - existing)
    if missing:
        raise ValidationError(
            "Группы ролей ещё не созданы: " + ", ".join(missing) + ". Выполните seed_roles."
        )


def _board_group_names(board):
    return list(board.allowed_groups.order_by("name").values_list("name", flat=True))


def _board_access_risk_markers(*, after, added, removed, source):
    markers = []
    if added:
        markers.append(BOARD_ACCESS_GRANT_RISK)
    if removed:
        markers.append(BOARD_ACCESS_REMOVAL_RISK)
    if not after:
        markers.append(BOARD_ACCESS_EMPTY_RISK)
    if source == BoardAccessAudit.Source.DJANGO_ADMIN_BREAK_GLASS:
        markers.append(BOARD_ACCESS_BREAK_GLASS_RISK)
    return markers


def _board_access_impact(*, before, after):
    before_ids = _board_access_user_ids(before)
    after_ids = _board_access_user_ids(after)
    return {
        "active_gain_count": len(after_ids - before_ids),
        "active_loss_count": len(before_ids - after_ids),
        "active_retained_count": len(before_ids & after_ids),
    }


def _board_access_population_fingerprint(*, before, after):
    return normalized_hash(
        {
            "before_user_ids": sorted(_board_access_user_ids(before)),
            "after_user_ids": sorted(_board_access_user_ids(after)),
        }
    )


def _board_access_user_ids(group_names):
    user_model = get_user_model()
    group_names = set(group_names)
    user_ids = set(
        user_model.objects.filter(
            is_active=True,
            is_superuser=False,
            groups__name__in=group_names,
        )
        .values_list("pk", flat=True)
        .distinct()
    )
    # Пользователь без предметной роли использует базовый профиль customer.
    if "customer" in group_names:
        fallback_ids = (
            user_model.objects.filter(is_active=True, is_superuser=False)
            .exclude(groups__name__in=contract_role_names())
            .values_list("pk", flat=True)
            .distinct()
        )
        user_ids.update(fallback_ids)
    return user_ids


def _require_role_contract_healthy():
    if "role_rules" in get_degradation_state().get("contracts", {}):
        raise ValidationError(
            "Контракт ролей работает в режиме деградации. Изменение доступа к доске запрещено."
        )


def _load_board_access_preview(token):
    if not token:
        raise ValidationError("Сначала выполните предпросмотр изменения.")
    try:
        return signing.loads(
            token,
            salt=BOARD_ACCESS_PREVIEW_SALT,
            max_age=BOARD_ACCESS_PREVIEW_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError("Срок предпросмотра истёк. Выполните его снова.") from exc
    except signing.BadSignature as exc:
        raise ValidationError("Предпросмотр изменения недействителен.") from exc


def _unique_board_slug(base_slug):
    candidate = str(base_slug)[:50]
    counter = 2
    while Board.objects.filter(slug=candidate).exists():
        suffix = f"-{counter}"
        candidate = f"{str(base_slug)[: 50 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def create_workorder(
    *,
    author,
    title: str,
    description: str,
    department,
    priority,
    device_id=None,
    assignee=None,
    board=None,
) -> WorkOrder:
    if not board:
        board = Board.objects.filter(slug="main").first()
    workorder = WorkOrder.objects.create(
        author=author,
        title=title,
        description=description,
        department=department,
        priority=priority,
        device_id=device_id,
        assignee=assignee,
        board=board,
    )
    notification_events.notify_workorder_created(workorder, actor=author)
    return workorder


def transition_workorder(*, workorder: WorkOrder, user, to_status: str) -> WorkOrder:
    previous_status = workorder.status
    workorder.status = to_status
    if to_status != WorkOrderStatus.CLOSED:
        workorder.closure_confirmed = False
        workorder.closure_confirmed_at = None
    workorder.save(
        update_fields=[
            "status",
            "updated_at",
            "resolved_at",
            "closed_at",
            "closure_confirmed",
            "closure_confirmed_at",
        ]
    )
    WorkOrderTransitionLog.objects.create(
        workorder=workorder,
        from_status=previous_status,
        to_status=to_status,
        actor=user,
    )
    notification_events.notify_workorder_status_changed(
        workorder,
        actor=user,
        previous_status=previous_status,
    )
    return workorder


def confirm_closure(*, workorder: WorkOrder, user) -> WorkOrder:
    previous_status = workorder.status
    workorder.status = WorkOrderStatus.CLOSED
    workorder.closure_confirmed = True
    workorder.closure_confirmed_at = timezone.now()
    workorder.save(
        update_fields=[
            "status",
            "updated_at",
            "closed_at",
            "closure_confirmed",
            "closure_confirmed_at",
        ]
    )
    WorkOrderTransitionLog.objects.create(
        workorder=workorder,
        from_status=previous_status,
        to_status=WorkOrderStatus.CLOSED,
        actor=user,
    )
    notification_events.notify_workorder_status_changed(
        workorder,
        actor=user,
        previous_status=previous_status,
    )
    return workorder


def rate_workorder(*, workorder: WorkOrder, user, rating: int) -> WorkOrder:
    workorder.rating = rating
    workorder.save(update_fields=["rating"])
    return workorder
