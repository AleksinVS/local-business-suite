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
from apps.core.models import Department
from apps.inventory.models import MedicalDevice

from . import notification_events
from .models import (
    Board,
    BoardAccessAudit,
    KanbanColumnConfig,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderStatus,
    WorkOrderTransitionLog,
)
from .policies import (
    can_assign,
    can_comment,
    can_confirm_closure,
    can_create,
    can_edit,
    can_manage_board_columns,
    can_rate,
    can_transition,
    can_upload_attachment,
)
from .policies import board_access_role_names, can_manage_board_access
from .selectors import (
    creation_departments_queryset,
    creation_devices_queryset,
    visible_boards_queryset,
    visible_workorders_queryset,
)


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


def save_board_access(
    *,
    actor,
    board,
    selected_group_names,
    reason="",
    source=BoardAccessAudit.Source.SETTINGS_CENTER,
):
    """Проверить и сразу применить ACL доски одной web-командой."""

    preview = preview_board_access(
        actor=actor,
        board=board,
        selected_group_names=selected_group_names,
        reason=reason,
        source=source,
    )
    return apply_board_access(
        actor=actor,
        board=board,
        selected_group_names=selected_group_names,
        preview_token=preview["preview_token"],
        risk_confirmed=True,
        reason=reason,
        source=source,
    )


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
    """Клонировать структуру доски без скрытого наследования доступа.

    Lock order is actor -> source board; capability is checked after the
    actor lock so a concurrent role revoke cannot authorize the clone.
    """
    actor = _lock_active_workorder_actor(actor)
    if not can_manage_board_access(actor):
        raise PermissionDenied("Клонирование доски недоступно пользователю.")
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


def _create_workorder_unchecked(
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


def _transition_workorder_unchecked(*, workorder: WorkOrder, user, to_status: str) -> WorkOrder:
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


def _confirm_closure_unchecked(*, workorder: WorkOrder, user) -> WorkOrder:
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


def _rate_workorder_unchecked(*, workorder: WorkOrder, user, rating: int) -> WorkOrder:
    workorder.rating = rating
    workorder.save(update_fields=["rating"])
    return workorder


# These command functions are the single mutation boundary for the workorder
# domain.  HTTP and AI are adapters: they validate transport data, then call
# one command which re-reads the actor and the target under the same lock.
WORKORDER_UPDATE_FIELDS = (
    "board",
    "title",
    "description",
    "department",
    "priority",
    "device",
    "assignee",
)


def _lock_active_workorder_actor(actor):
    user_model = get_user_model()
    locked_actor = user_model.objects.select_for_update().filter(
        pk=getattr(actor, "pk", None), is_active=True
    ).first()
    if locked_actor is None:
        raise PermissionDenied("Учетная запись исполнителя отключена или не найдена.")
    return locked_actor


def _coerce_pk(value):
    return getattr(value, "pk", value)


def _creation_department(actor, value):
    department_id = creation_departments_queryset(actor).filter(
        pk=_coerce_pk(value)
    ).values_list("pk", flat=True).first()
    if department_id is None:
        raise PermissionDenied("Недоступно выбранное подразделение.")
    department = Department.objects.select_for_update().filter(pk=department_id).first()
    if department is None or not creation_departments_queryset(actor).filter(
        pk=department.pk
    ).exists():
        raise PermissionDenied("Подразделение стало недоступно.")
    return department


def _creation_device(actor, value, *, department):
    if value in (None, ""):
        return None
    device_id = creation_devices_queryset(actor).filter(
        pk=_coerce_pk(value), department_id=department.pk
    ).values_list("pk", flat=True).first()
    if device_id is None:
        raise PermissionDenied("Недоступно выбранное медицинское изделие.")
    device = MedicalDevice.objects.select_for_update().filter(pk=device_id).first()
    if device is None or not creation_devices_queryset(actor).filter(
        pk=device.pk, department_id=department.pk
    ).exists():
        raise PermissionDenied("Медицинское изделие стало недоступно.")
    return device


def _lock_assignee(value):
    """Lock and return an active, canonical assignee or fail closed."""
    if value in (None, ""):
        return None
    assignee = (
        get_user_model().objects.select_for_update().filter(
            pk=_coerce_pk(value), is_active=True
        ).first()
    )
    if assignee is None:
        raise PermissionDenied("Недоступен выбранный исполнитель.")
    return assignee


def create_workorder_command(*, actor, payload):
    """Create a workorder after fresh actor, board and relation checks."""
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        if not can_create(current_actor):
            raise PermissionDenied("Пользователю недоступно создание заявок.")
        board_filter = (
            {"pk": _coerce_pk(payload.get("board"))}
            if payload.get("board") not in (None, "")
            else {"slug": "main"}
        )
        board = Board.objects.select_for_update().filter(**board_filter).first()
        if board is None or not visible_boards_queryset(current_actor).filter(
            pk=board.pk
        ).exists():
            raise PermissionDenied("Недоступна выбранная доска.")
        # Mutation lock order: actor -> boards(sorted) -> departments(sorted)
        # -> devices -> assignee.  Authorization is repeated after locks.
        department = _creation_department(
            current_actor,
            payload.get("department", payload.get("department_id")),
        )
        device = _creation_device(
            current_actor,
            payload.get("device", payload.get("device_id")),
            department=department,
        )
        workorder = _create_workorder_unchecked(
            author=current_actor,
            title=payload.get("title", ""),
            description=payload.get("description", ""),
            department=department,
            priority=payload.get("priority", "medium"),
            device_id=device.pk if device else None,
            assignee=None,
            board=board,
        )
    return workorder


def _locked_visible_workorder(current_actor, workorder_id, *, additional_board_id=None):
    # Mutation lock order is actor -> boards(sorted) -> workorder.  Board ids
    # are read before authorization/locks only to establish the lock set; all
    # relations and visibility are re-read after the locks are held.
    target_board_id = WorkOrder.objects.filter(pk=workorder_id).values_list(
        "board_id", flat=True
    ).first()
    if target_board_id is None:
        raise PermissionDenied("Заявка недоступна текущему пользователю.")
    board_ids = {target_board_id}
    if additional_board_id not in (None, ""):
        board_ids.add(_coerce_pk(additional_board_id))
    locked_boards = {
        board.pk: board
        for board in Board.objects.select_for_update().filter(
            pk__in=sorted(board_ids)
        ).order_by("pk")
    }
    workorder = WorkOrder.objects.select_for_update().filter(pk=workorder_id).first()
    if workorder is None:
        raise PermissionDenied("Заявка недоступна текущему пользователю.")
    board = locked_boards.get(workorder.board_id)
    if board is None:
        raise PermissionDenied("Доска заявки недоступна.")
    visible_id = visible_workorders_queryset(current_actor).filter(
        pk=workorder.pk
    ).values_list("pk", flat=True).first()
    if visible_id is None:
        raise PermissionDenied("Заявка недоступна текущему пользователю.")
    workorder.board = board
    return workorder


def update_workorder_command(*, actor, workorder_id, payload):
    """Update only the allow-listed workorder fields under an object lock."""
    unknown = set(payload) - set(WORKORDER_UPDATE_FIELDS)
    if unknown:
        raise ValidationError("Недопустимые поля заявки: " + ", ".join(sorted(unknown)))
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        requested_board = payload.get("board") if "board" in payload else None
        workorder = _locked_visible_workorder(
            current_actor,
            workorder_id,
            additional_board_id=requested_board,
        )
        if not can_edit(current_actor, workorder):
            raise PermissionDenied("Пользователю недоступно редактирование заявки.")
        changed = set(payload)
        if "board" in changed:
            board = Board.objects.filter(pk=_coerce_pk(payload["board"])).first()
            if board is None or not visible_boards_queryset(current_actor).filter(
                pk=board.pk
            ).exists():
                raise PermissionDenied("Недоступна выбранная доска.")
            workorder.board = board
        if "department" in changed:
            value = payload["department"]
            if _coerce_pk(value) != workorder.department_id:
                department = _creation_department(current_actor, value)
                if "device" not in changed and workorder.device_id:
                    if workorder.device_id and workorder.device and workorder.device.department_id != department.pk:
                        raise ValidationError(
                            "При смене подразделения выберите медицинское изделие из нового подразделения."
                        )
                workorder.department = department
        if "device" in changed:
            value = payload["device"]
            if _coerce_pk(value) != workorder.device_id:
                workorder.device = _creation_device(
                    current_actor,
                    value,
                    department=workorder.department,
                )
        if "assignee" in changed:
            assignee = payload["assignee"]
            if _coerce_pk(assignee) != workorder.assignee_id:
                if not can_assign(current_actor, workorder):
                    raise PermissionDenied("Пользователю недоступно назначение исполнителей.")
                if assignee in (None, ""):
                    workorder.assignee = None
                else:
                    workorder.assignee = _lock_assignee(assignee)
        for field in ("title", "description", "priority"):
            if field in changed:
                setattr(workorder, field, payload[field])
        workorder.save(update_fields=list(changed) + ["updated_at"])
    return workorder


def add_workorder_comment_command(*, actor, workorder_id, body):
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        workorder = _locked_visible_workorder(current_actor, workorder_id)
        if not can_comment(current_actor, workorder):
            raise PermissionDenied("Пользователю недоступно комментирование.")
        comment = workorder.comments.create(author=current_actor, body=body)
        workorder.updated_at = timezone.now()
        workorder.save(update_fields=["updated_at"])
        notification_events.notify_workorder_comment_created(
            workorder,
            actor=current_actor,
        )
    return comment


def add_workorder_attachment_command(*, actor, workorder_id, uploaded_file):
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        workorder = _locked_visible_workorder(current_actor, workorder_id)
        if not can_upload_attachment(current_actor, workorder):
            raise PermissionDenied("Загрузка файлов запрещена.")
        attachment = WorkOrderAttachment.objects.create(
            workorder=workorder,
            uploaded_by=current_actor,
            file=uploaded_file,
            content_type=getattr(uploaded_file, "content_type", ""),
        )
    return attachment


def transition_workorder_command(*, actor, workorder_id, target_status):
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        workorder = _locked_visible_workorder(current_actor, workorder_id)
        if not can_transition(current_actor, workorder, target_status):
            raise PermissionDenied("Переход статуса запрещен.")
        return _transition_workorder_unchecked(
            workorder=workorder, user=current_actor, to_status=target_status
        )


def move_workorder_command(*, actor, workorder_id, column_code):
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        workorder = _locked_visible_workorder(current_actor, workorder_id)
        column = KanbanColumnConfig.objects.filter(
            board=workorder.board, code=column_code
        ).first()
        if column is None:
            raise PermissionDenied("Недоступна выбранная колонка.")
        old_status = workorder.status
        if old_status not in column.statuses:
            target_status = next(
                (status for status in column.statuses if can_transition(current_actor, workorder, status)),
                None,
            )
            if target_status is None:
                raise PermissionDenied("Перемещение в колонку запрещено.")
            workorder = _transition_workorder_unchecked(
                workorder=workorder, user=current_actor, to_status=target_status
            )
    return workorder, old_status, column


def confirm_workorder_closure_command(*, actor, workorder_id):
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        workorder = _locked_visible_workorder(current_actor, workorder_id)
        if not can_confirm_closure(current_actor, workorder):
            raise PermissionDenied("Подтверждение закрытия запрещено.")
        return _confirm_closure_unchecked(workorder=workorder, user=current_actor)


def rate_workorder_command(*, actor, workorder_id, rating):
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        raise ValidationError("Оценка должна быть целым числом от 1 до 5.")
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        workorder = _locked_visible_workorder(current_actor, workorder_id)
        if not can_rate(current_actor, workorder):
            raise PermissionDenied("Пользователю недоступна оценка заявки.")
        return _rate_workorder_unchecked(workorder=workorder, user=current_actor, rating=rating)


def update_board_column_command(*, actor, column_id, payload):
    """Изменить только разрешённые поля колонки видимой доски."""
    allowed_fields = {"title", "wip_limit"}
    unknown = set(payload) - allowed_fields
    if unknown:
        raise ValidationError("Недопустимые поля колонки: " + ", ".join(sorted(unknown)))
    with transaction.atomic():
        current_actor = _lock_active_workorder_actor(actor)
        if not can_manage_board_columns(current_actor):
            raise PermissionDenied("Изменение колонок запрещено.")
        column_board_id = KanbanColumnConfig.objects.filter(pk=column_id).values_list(
            "board_id", flat=True
        ).first()
        if column_board_id is None:
            raise PermissionDenied("Колонка недоступна.")
        # Keep one lock order for all board mutations: actor -> board ->
        # dependent row. The preliminary id lookup is not an authorization
        # decision; both rows and their relation are re-read under locks.
        board = Board.objects.select_for_update().filter(pk=column_board_id).first()
        if board is None or not visible_boards_queryset(current_actor).filter(
            pk=board.pk
        ).exists():
            raise PermissionDenied("Доска колонки недоступна.")
        column = KanbanColumnConfig.objects.select_for_update().filter(
            pk=column_id,
            board_id=board.pk,
        ).first()
        if column is None:
            raise PermissionDenied("Колонка недоступна.")
        for field, value in payload.items():
            setattr(column, field, value)
        if payload:
            column.save(update_fields=list(payload))
    return column


def apply_viewer_migration_board_acl_locked(
    *, actor, board, operation_id, expected_before, expected_after, reason, remove=False,
):
    """Trusted migration-only viewer ACL adapter with deterministic audit."""
    User = get_user_model()
    actor = User.objects.filter(pk=getattr(actor, "pk", None), is_active=True, is_superuser=True).first()
    if actor is None:
        raise PermissionDenied("Требуется активный суперпользователь.")
    locked = Board.objects.select_for_update().filter(pk=board.pk).first()
    if locked is None:
        raise ValidationError("Доска отсутствует.")
    before = sorted(locked.allowed_groups.values_list("name", flat=True))
    fingerprint = hashlib.sha256(
        f"viewer-migration:{operation_id}:board:{locked.pk}:{'remove' if remove else 'add'}".encode()
    ).hexdigest()
    existing = BoardAccessAudit.objects.filter(preview_fingerprint=fingerprint).first()
    if existing:
        expected_marker = "explicit_viewer_migration_rollback" if remove else "explicit_viewer_migration"
        if (
            existing.board_id != locked.pk
            or existing.actor_id != actor.pk
            or existing.source != BoardAccessAudit.Source.SETTINGS_CENTER
            or existing.reason != reason
            or existing.groups_before != sorted(expected_before)
            or existing.groups_after != sorted(expected_after)
            or existing.groups_added != sorted(set(expected_after) - set(expected_before))
            or existing.groups_removed != sorted(set(expected_before) - set(expected_after))
            or existing.risk_markers != [expected_marker]
            or not existing.risk_confirmed
            or existing.role_contract_hash != current_contract_hash("role_rules")
        ):
            raise ValidationError("Детерминированный board audit не совпадает с повтором.")
        if before != sorted(expected_after):
            raise ValidationError("Аудит операции найден, но текущий доступ к доске ему не соответствует.")
        return existing
    if before != sorted(expected_before):
        raise ValidationError("Доступ к доске изменился до операции миграции.")
    viewer = Group.objects.filter(name="viewer").first()
    if viewer is None:
        raise ValidationError("Группа viewer отсутствует.")
    if remove:
        locked.allowed_groups.remove(viewer)
    else:
        locked.allowed_groups.add(viewer)
    after = sorted(locked.allowed_groups.values_list("name", flat=True))
    if after != sorted(expected_after):
        raise ValidationError("Результат migration ACL не совпал с планом.")
    marker = "explicit_viewer_migration_rollback" if remove else "explicit_viewer_migration"
    return BoardAccessAudit.objects.create(
        board=locked,
        actor=actor,
        groups_before=sorted(expected_before),
        groups_after=sorted(expected_after),
        groups_added=sorted(set(expected_after) - set(expected_before)),
        groups_removed=sorted(set(expected_before) - set(expected_after)),
        risk_markers=[marker],
        risk_confirmed=True,
        source=BoardAccessAudit.Source.SETTINGS_CENTER,
        reason=reason,
        role_contract_hash=current_contract_hash("role_rules"),
        preview_fingerprint=fingerprint,
    )
