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
    "workorders.create",
    "workorders.transition",
    "workorders.comment",
    "lookup.departments",
    "lookup.devices",
})

_TASK_TYPE_CATALOG: dict[str, TaskTypeContract] = {
    "workorders.list": TaskTypeContract(
        id="workorders.list",
        title="List work orders",
        mode=TaskMode.READ,
        description="Show work orders filtered by status or scope.",
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
    "workorders.create": TaskTypeContract(
        id="workorders.create",
        title="Create work order",
        mode=TaskMode.WRITE,
        description="Create a new work order from a conversational request.",
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
        title="Transition work order",
        mode=TaskMode.WRITE,
        description="Move a request to the next allowed status.",
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
        title="Comment on work order",
        mode=TaskMode.WRITE,
        description="Add a comment to a work order timeline.",
        allowed_tools=("workorders.comment",),
        required_slots=("workorder", "text"),
        optional_slots=(),
        requires_confirmation=False,
        output_mode=OutputMode.RESULT,
        example_requests=(
            "Добавь комментарий к заявке 7: нужен доступ в подвал",
        ),
    ),
    "lookup.departments": TaskTypeContract(
        id="lookup.departments",
        title="Lookup departments",
        mode=TaskMode.READ,
        description="Resolve a department name or tree branch.",
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
        title="Lookup devices",
        mode=TaskMode.READ,
        description="Resolve a device name or device list.",
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
