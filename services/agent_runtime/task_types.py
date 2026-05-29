"""
Executable task-type contract layer, bounded to:
  workorders.list, workorders.create, workorders.transition

Provides:
  - In-code task type catalog (derived from task_types.json)
  - Task type resolution during agent runtime
  - Slot-state tracking for required/optional slots
  - Enforcement of allowed_tools and required-slot checks
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Status and priority alias mappings
#
# These mappings let the agent resolve Russian-language user input
# (e.g. "В работе") to internal keys (e.g. "in_progress") that the
# Django backend expects.  The first alias in each list is the canonical
# Russian label shown on the Kanban board.
# ---------------------------------------------------------------------------

STATUS_ALIASES: dict[str, list[str]] = {
    "new": ["Новая", "новая", "new"],
    "accepted": ["Принята", "принята", "accepted"],
    "in_progress": ["В работе", "в работе", "in_progress", "в работе"],
    "on_hold": ["Ожидание", "ожидание", "on_hold", "на удержании", "На удержании"],
    "resolved": ["Выполнена", "выполнена", "resolved", "выполнено", "Выполнено"],
    "closed": ["Закрыта", "закрыта", "closed", "закрыто", "Закрыто"],
    "cancelled": ["Отменена", "отменена", "cancelled", "отменено", "Отменено"],
}

PRIORITY_ALIASES: dict[str, list[str]] = {
    "low": ["Низкий", "низкий", "low", "низкая", "Низкая"],
    "medium": ["Средний", "средний", "medium", "средняя", "Средняя"],
    "high": ["Высокий", "высокий", "high", "высокая", "Высокая"],
    "critical": ["Критичный", "критичный", "critical", "критическая", "Критическая"],
}

# Status transitions — mirrors config/workflow_rules.json so the agent
# runtime can reference allowed transitions without importing Django.
STATUS_TRANSITIONS: dict[str, list[str]] = {
    "new": ["accepted", "cancelled"],
    "accepted": ["in_progress", "on_hold", "cancelled"],
    "in_progress": ["on_hold", "resolved", "cancelled"],
    "on_hold": ["in_progress", "cancelled"],
    "resolved": ["closed", "in_progress"],
    "closed": [],
    "cancelled": [],
}


def _build_reverse_lookup(
    aliases: dict[str, list[str]],
) -> dict[str, str]:
    """Build a case-insensitive reverse lookup from alias to internal key."""
    result: dict[str, str] = {}
    for internal_key, alias_list in aliases.items():
        for alias in alias_list:
            result[alias.lower()] = internal_key
    return result


_STATUS_LOOKUP = _build_reverse_lookup(STATUS_ALIASES)
_PRIORITY_LOOKUP = _build_reverse_lookup(PRIORITY_ALIASES)


def normalize_status(value: str) -> str:
    """Resolve a status value (possibly a Russian alias) to its internal key.

    - Internal keys pass through unchanged.
    - Known aliases (case-insensitive) resolve to their internal key.
    - Unknown values pass through (Django will reject them).
    """
    if not value:
        return value
    if value in STATUS_ALIASES:
        return value
    return _STATUS_LOOKUP.get(value.lower(), value)


def normalize_priority(value: str) -> str:
    """Resolve a priority value (possibly a Russian alias) to its internal key."""
    if not value:
        return value
    if value in PRIORITY_ALIASES:
        return value
    return _PRIORITY_LOOKUP.get(value.lower(), value)


def get_allowed_statuses() -> list[str]:
    """Return the list of valid internal status keys."""
    return list(STATUS_ALIASES.keys())


def get_allowed_priorities() -> list[str]:
    """Return the list of valid internal priority keys."""
    return list(PRIORITY_ALIASES.keys())


class TaskMode(str, Enum):
    READ = "read"
    WRITE = "write"


class OutputMode(str, Enum):
    STRUCTURED_LIST = "structured_list"
    CONFIRMATION_THEN_RESULT = "confirmation_then_result"
    RESULT = "result"


@dataclass(frozen=True)
class TaskTypeSlot:
    name: str
    description: str = ""
    required: bool = True


@dataclass(frozen=True)
class TaskTypeContract:
    """
    Code-enforced representation of a bounded task type.

    This is the canonical in-memory contract derived from task_types.json.
    The runtime uses these contracts to:
      - resolve which task type a user request maps to
      - validate that the selected tool is in allowed_tools
      - report slot state (which required/optional slots were filled)
      - enforce confirmation semantics for write task types
    """

    id: str
    title: str
    mode: TaskMode
    description: str
    allowed_tools: tuple[str, ...]
    required_slots: tuple[str, ...]
    optional_slots: tuple[str, ...]
    requires_confirmation: bool
    output_mode: OutputMode
    example_requests: tuple[str, ...]

    def is_tool_allowed(self, tool_id: str) -> bool:
        return tool_id in self.allowed_tools

    def get_missing_required_slots(self, slot_values: dict[str, Any]) -> list[str]:
        """Return list of required slots that are missing or empty from slot_values."""
        missing = []
        for slot in self.required_slots:
            value = slot_values.get(slot)
            if value is None or value == "":
                missing.append(slot)
        return missing

    def get_fulfilled_slots(self, slot_values: dict[str, Any]) -> dict[str, Any]:
        """Return the subset of slot_values that are non-empty."""
        return {k: v for k, v in slot_values.items() if v is not None and v != ""}


# ---------------------------------------------------------------------------
# Bounded catalog — six task types in scope
# ---------------------------------------------------------------------------

BOUNDED_TASK_TYPE_IDS = frozenset({
    "workorders.list",
    "workorders.get.detail",
    "workorders.create",
    "workorders.transition",
    "workorders.comment",
    "workorders.confirm_closure",
    "workorders.rate",
    "lookup.departments",
    "lookup.devices",
    "inventory.devices.create",
    "inventory.devices.update",
    "inventory.devices.archive",
    "analytics.summary.status",
    "analytics.summary.departments",
    "analytics.summary.assignees",
    "memory.search",
    "memory.remember",
    "memory.update_personal",
})

_TASK_TYPE_CATALOG: dict[str, TaskTypeContract] = {
    "workorders.list": TaskTypeContract(
        id="workorders.list",
        title="Список заявок",
        mode=TaskMode.READ,
        description="Показать заявки с фильтром по статусу или области видимости.",
        allowed_tools=("workorders.list",),
        required_slots=(),
        optional_slots=("status_or_scope", "limit"),
        requires_confirmation=False,
        output_mode=OutputMode.STRUCTURED_LIST,
        example_requests=(
            "Покажи новые заявки",
            "Какие заявки в работе у меня сейчас?",
        ),
    ),
    "workorders.get.detail": TaskTypeContract(
        id="workorders.get.detail",
        title="Подробности заявки",
        mode=TaskMode.READ,
        description="Показать одну заявку подробно по ID или номеру.",
        allowed_tools=("workorders.get",),
        required_slots=(),
        optional_slots=("workorder_id", "number"),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=(
            "Покажи подробности заявки 123",
            "Что с заявкой номер REQ-456?",
        ),
    ),
    "workorders.create": TaskTypeContract(
        id="workorders.create",
        title="Создать заявку",
        mode=TaskMode.WRITE,
        description="Создать новую заявку из запроса в диалоге.",
        allowed_tools=("workorders.create", "departments.list", "devices.list"),
        required_slots=("department", "subject", "description"),
        optional_slots=("device", "priority"),
        requires_confirmation=True,
        output_mode=OutputMode.CONFIRMATION_THEN_RESULT,
        example_requests=(
            "Создай заявку на починку раковины в стационаре",
            "Нужна заявка на светильник в поликлинике",
        ),
    ),
    "workorders.transition": TaskTypeContract(
        id="workorders.transition",
        title="Изменить статус заявки",
        mode=TaskMode.WRITE,
        description="Перевести заявку в следующий разрешенный статус.",
        allowed_tools=("workorders.get", "workorders.transition"),
        required_slots=("workorder", "target_status"),
        optional_slots=(),
        requires_confirmation=True,
        output_mode=OutputMode.CONFIRMATION_THEN_RESULT,
        example_requests=(
            "Переведи заявку 12 в работу",
            "Закрой заявку 18",
        ),
    ),
    "workorders.comment": TaskTypeContract(
        id="workorders.comment",
        title="Комментарий к заявке",
        mode=TaskMode.WRITE,
        description="Добавить комментарий в историю заявки.",
        allowed_tools=("workorders.comment",),
        required_slots=("workorder", "text"),
        optional_slots=(),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=(
            "Добавь комментарий к заявке 7: нужен доступ в подвал",
        ),
    ),
    "workorders.confirm_closure": TaskTypeContract(
        id="workorders.confirm_closure",
        title="Подтвердить закрытие заявки",
        mode=TaskMode.WRITE,
        description="Подтвердить закрытие выполненной заявки.",
        allowed_tools=("workorders.confirm_closure",),
        required_slots=("workorder_id",),
        optional_slots=(),
        requires_confirmation=True,
        output_mode=OutputMode.CONFIRMATION_THEN_RESULT,
        example_requests=(
            "Подтверди закрытие заявки 123",
            "Заявка 456 выполнена, закрывай",
        ),
    ),
    "workorders.rate": TaskTypeContract(
        id="workorders.rate",
        title="Оценить заявку",
        mode=TaskMode.WRITE,
        description="Поставить оценку закрытой заявке.",
        allowed_tools=("workorders.rate",),
        required_slots=("workorder_id", "rating"),
        optional_slots=(),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=(
            "Оцени заявку 123 на 5",
            "Поставь 4 звезды за заявку 456",
        ),
    ),
    "lookup.departments": TaskTypeContract(
        id="lookup.departments",
        title="Поиск подразделений",
        mode=TaskMode.READ,
        description="Найти подразделение по названию или ветке дерева.",
        allowed_tools=("departments.list",),
        required_slots=(),
        optional_slots=(),
        requires_confirmation=False,
        output_mode=OutputMode.STRUCTURED_LIST,
        example_requests=(
            "Покажи подразделения",
            "Какие есть отделения в дереве?",
        ),
    ),
    "lookup.devices": TaskTypeContract(
        id="lookup.devices",
        title="Поиск медизделий",
        mode=TaskMode.READ,
        description="Найти медизделие по названию или показать список.",
        allowed_tools=("devices.list",),
        required_slots=(),
        optional_slots=(),
        requires_confirmation=False,
        output_mode=OutputMode.STRUCTURED_LIST,
        example_requests=(
            "Покажи медизделия",
            "Найди КТ аппарат",
        ),
    ),
    "inventory.devices.create": TaskTypeContract(
        id="inventory.devices.create",
        title="Создать медизделие",
        mode=TaskMode.WRITE,
        description="Создать новое медицинское изделие.",
        allowed_tools=("inventory.devices.create", "departments.list"),
        required_slots=("name", "department_id"),
        optional_slots=("model", "serial_number"),
        requires_confirmation=True,
        output_mode=OutputMode.CONFIRMATION_THEN_RESULT,
        example_requests=(
            "Добавь новый тонометр в кардиологию",
        ),
    ),
    "inventory.devices.update": TaskTypeContract(
        id="inventory.devices.update",
        title="Обновить медизделие",
        mode=TaskMode.WRITE,
        description="Обновить существующее медицинское изделие.",
        allowed_tools=("inventory.devices.update", "departments.list", "devices.list"),
        required_slots=("device_id",),
        optional_slots=("name", "department_id", "model", "serial_number"),
        requires_confirmation=True,
        output_mode=OutputMode.CONFIRMATION_THEN_RESULT,
        example_requests=(
            "Измени серийный номер у тонометра 123",
        ),
    ),
    "inventory.devices.archive": TaskTypeContract(
        id="inventory.devices.archive",
        title="Архивировать медизделие",
        mode=TaskMode.WRITE,
        description="Перенести медицинское изделие в архив.",
        allowed_tools=("inventory.devices.archive", "devices.list"),
        required_slots=("device_id",),
        optional_slots=(),
        requires_confirmation=True,
        output_mode=OutputMode.CONFIRMATION_THEN_RESULT,
        example_requests=(
            "Спиши аппарат 123",
            "Отправь в архив рентген",
        ),
    ),
    "analytics.summary.status": TaskTypeContract(
        id="analytics.summary.status",
        title="Аналитика по статусам",
        mode=TaskMode.READ,
        description="Показать сводку заявок с группировкой по статусам.",
        allowed_tools=("analytics.summary",),
        required_slots=(),
        optional_slots=("summary_type",),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=("Покажи статистику по статусам",),
    ),
    "analytics.summary.departments": TaskTypeContract(
        id="analytics.summary.departments",
        title="Аналитика по подразделениям",
        mode=TaskMode.READ,
        description="Показать сводку заявок с группировкой по подразделениям.",
        allowed_tools=("analytics.summary",),
        required_slots=(),
        optional_slots=("summary_type",),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=("Покажи статистику по отделениям",),
    ),
    "analytics.summary.assignees": TaskTypeContract(
        id="analytics.summary.assignees",
        title="Аналитика по исполнителям",
        mode=TaskMode.READ,
        description="Показать сводку заявок с группировкой по исполнителям.",
        allowed_tools=("analytics.summary",),
        required_slots=(),
        optional_slots=("summary_type",),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=("Покажи статистику по исполнителям",),
    ),
    "memory.search": TaskTypeContract(
        id="memory.search",
        title="Поиск в памяти",
        mode=TaskMode.READ,
        description="Искать в индексированном контексте памяти с источниками.",
        allowed_tools=("memory.search",),
        required_slots=("query",),
        optional_slots=("limit", "sensitivity", "search_mode", "ranking_profile", "include_source_data"),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=(
            "Найди в памяти сведения о правилах обработки заявок",
            "Поищи в базе знаний инструкции по медизделиям",
        ),
    ),
    "memory.remember": TaskTypeContract(
        id="memory.remember",
        title="Запомнить из чата",
        mode=TaskMode.WRITE,
        description="Поставить выбранные сообщения чата в очередь сохранения в личную или общую память.",
        allowed_tools=("memory.remember",),
        required_slots=(),
        optional_slots=("session_id", "message_ids", "target_scope", "user_note", "importance"),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=(
            "Запомни это для меня",
            "Запомни это для всей организации",
        ),
    ),
    "memory.update_personal": TaskTypeContract(
        id="memory.update_personal",
        title="Обновить личную память",
        mode=TaskMode.WRITE,
        description="Изменить или удалить одну запись личной памяти пользователя.",
        allowed_tools=("memory.update_personal",),
        required_slots=("memory_id", "operation"),
        optional_slots=("new_text",),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=(
            "Исправь то, что ты обо мне помнишь",
            "Забудь этот факт из моей памяти",
        ),
    ),
}


def get_task_type_contract(task_type_id: str) -> TaskTypeContract | None:
    """Return the task type contract for a bounded task type, or None if out of scope."""
    if task_type_id not in BOUNDED_TASK_TYPE_IDS:
        return None
    return _TASK_TYPE_CATALOG.get(task_type_id)


def get_all_bounded_task_types() -> dict[str, TaskTypeContract]:
    """Return the full catalog of bounded task type contracts."""
    return dict(_TASK_TYPE_CATALOG)


@dataclass
class TaskTypeResolution:
    """Result of resolving a request to a task type at runtime."""

    task_type_id: str
    contract: TaskTypeContract
    resolved_tool: str
    slot_state: dict[str, Any] = field(default_factory=dict)
    missing_required_slots: list[str] = field(default_factory=list)
    all_slots_fulfilled: bool = False

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "task_type_id": self.task_type_id,
            "task_type_title": self.contract.title,
            "task_type_mode": self.contract.mode.value,
            "resolved_tool": self.resolved_tool,
            "requires_confirmation": self.contract.requires_confirmation,
            "slot_state": self.slot_state,
            "missing_required_slots": self.missing_required_slots,
            "all_slots_fulfilled": self.all_slots_fulfilled,
        }


def resolve_task_type_for_tool(tool_id: str, slot_values: dict[str, Any] | None = None) -> TaskTypeResolution | None:
    """
    Resolve which task type contract applies for a given tool call.

    This is the core runtime hook — given a tool_id and optional slot values,
    it finds the matching bounded task type, validates the tool is allowed,
    and reports slot fulfillment state.

    Returns None if the tool is not covered by any bounded task type.
    """
    slot_values = slot_values or {}
    for contract in _TASK_TYPE_CATALOG.values():
        if tool_id in contract.allowed_tools:
            missing = contract.get_missing_required_slots(slot_values)
            fulfilled = contract.get_fulfilled_slots(slot_values)
            return TaskTypeResolution(
                task_type_id=contract.id,
                contract=contract,
                resolved_tool=tool_id,
                slot_state=fulfilled,
                missing_required_slots=missing,
                all_slots_fulfilled=len(missing) == 0,
            )
    return None


def validate_tool_allowed_for_bounded_scope(tool_id: str) -> tuple[bool, str]:
    """
    Validate that a tool_id is allowed within the bounded task type scope.

    Returns (is_valid, reason).
    """
    for contract in _TASK_TYPE_CATALOG.values():
        if tool_id in contract.allowed_tools:
            return True, ""
    return False, f"Tool '{tool_id}' is not in the allowed_tools of any bounded task type."


def validate_bounded_tools_exist_in_catalog(
    tool_catalog: dict[str, dict],
) -> list[str]:
    """
    Validate that every allowed_tool declared in bounded task types exists
    in the tool catalog.

    Returns a list of error messages (empty if all tools exist).
    """
    errors = []
    catalog_by_id = {tool["id"]: tool for tool in tool_catalog.get("tools", [])}
    for contract in _TASK_TYPE_CATALOG.values():
        for tool_id in contract.allowed_tools:
            if tool_id not in catalog_by_id:
                errors.append(
                    f"Task type '{contract.id}' declares allowed_tool '{tool_id}' "
                    f"but it does not exist in the tool catalog."
                )
    return errors


def get_bounded_task_type_ids() -> frozenset[str]:
    """Return the set of task type IDs that are in the bounded scope."""
    return BOUNDED_TASK_TYPE_IDS
