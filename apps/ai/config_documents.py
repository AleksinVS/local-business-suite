from django.core.exceptions import ValidationError

from apps.ai.contracts import (
    validate_ai_chat_settings_payload,
    validate_ai_identity_model_alignment,
    validate_ai_registry_payload,
    validate_ai_task_types_payload,
    validate_ai_task_types_slot_coverage,
    validate_ai_task_types_tool_alignment,
    validate_ai_tools_drift,
    validate_ai_tools_payload,
    validate_ai_write_confirmation_alignment,
)
from apps.ai.tool_definitions import TOOLS, get_tool_registry
from apps.settings_center.document_specs import ConfigDocumentSpec


# This is deliberately a closed set.  In particular, environment settings,
# skills, access policy and arbitrary Settings Center documents must never be
# reachable through the machine-to-machine AI gateway.
AI_RUNTIME_DOCUMENT_IDS = (
    "ai.contract.registry",
    "ai.contract.tools",
    "ai.contract.task_types",
    "ai.contract.models",
    "ai.contract.chat_settings",
)
AI_RUNTIME_DOCUMENT_ALLOWLIST = frozenset(AI_RUNTIME_DOCUMENT_IDS)


def get_ai_document_snapshots(*, request=None, repository=None):
    """Read all AI documents as one request-local repository aggregate."""
    from apps.settings_center.document_repository import ConfigDocumentRepository

    repository = repository or getattr(request, "_config_document_repository", None)
    repository = repository or ConfigDocumentRepository()
    return repository.get_snapshot(AI_RUNTIME_DOCUMENT_IDS, request=request)


def get_ai_document_payloads(*, request=None, snapshot=None, repository=None):
    snapshots = (
        get_ai_document_snapshots(request=request, repository=repository)
        if snapshot is None
        else snapshot
    )
    return {
        document_id: (
            value.payload
            if hasattr(value, "payload")
            else value.get("payload", value)
            if isinstance(value, dict)
            else value
        )
        for document_id, value in snapshots.items()
    }


def validate_ai_runtime_document_ids(document_ids):
    """Return a canonical explicit id set, or raise without an oracle.

    Callers must validate the complete request before looking up a document;
    this keeps unknown ids from becoming an enumeration endpoint.
    """
    if not isinstance(document_ids, (list, tuple)) or not document_ids:
        raise ValueError("AI document ids must be an explicit non-empty list")
    ids = tuple(str(item) for item in document_ids)
    if any(not item or item not in AI_RUNTIME_DOCUMENT_ALLOWLIST for item in ids):
        raise ValueError("AI document ids are not allowed")
    if len(ids) != len(set(ids)):
        raise ValueError("AI document ids must be unique")
    return tuple(sorted(ids))


def _snapshot_payload(snapshot, document_id):
    """Return a delivered payload or fail closed at the policy boundary."""
    if not isinstance(snapshot, dict) or document_id not in snapshot:
        raise ValidationError(
            f"AI policy snapshot does not contain '{document_id}'."
        )
    value = snapshot[document_id]
    payload = value.payload if hasattr(value, "payload") else value
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload["payload"]
    if not isinstance(payload, (dict, list)):
        raise ValidationError(f"AI policy payload '{document_id}' is invalid.")
    return payload


def _delivered_tool_catalog(snapshot):
    static_registry = get_tool_registry()
    payload = _snapshot_payload(snapshot, "ai.contract.tools")
    delivered_tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(delivered_tools, list):
        raise ValidationError("Delivered AI tool policy is missing.")
    delivered_by_id = {}
    for item in delivered_tools:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValidationError("Delivered AI tool policy contains an invalid tool.")
        tool_id = item["id"]
        if tool_id in delivered_by_id:
            raise ValidationError(f"Delivered AI tool policy repeats '{tool_id}'.")
        delivered_by_id[tool_id] = item
    if not set(delivered_by_id).issubset(static_registry):
        raise ValidationError("Delivered AI tools differ from the static Python registry.")
    for tool_id, delivered_tool in delivered_by_id.items():
        static_tool = static_registry[tool_id]
        if delivered_tool.get("mode") != static_tool.get("mode"):
            raise ValidationError(f"AI tool mode drift for '{tool_id}'.")
        if bool(delivered_tool.get("requires_confirmation", False)) != bool(
            static_tool.get("requires_confirmation", False)
        ):
            raise ValidationError(f"AI tool confirmation drift for '{tool_id}'.")
    return static_registry, delivered_by_id


def _task_candidates(*, tool_code, static_tool, task_payload):
    tasks = task_payload.get("task_types") if isinstance(task_payload, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise ValidationError("Delivered AI task policy is missing.")
    static_registry = get_tool_registry()
    seen_ids = set()
    candidates = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValidationError("Delivered AI task policy contains an invalid task.")
        task_id = task.get("id")
        allowed_tools = task.get("allowed_tools")
        if not isinstance(task_id, str) or not task_id:
            raise ValidationError("Delivered AI task policy contains an invalid id.")
        if task_id in seen_ids:
            raise ValidationError(f"Delivered AI task policy repeats '{task_id}'.")
        seen_ids.add(task_id)
        if not isinstance(task.get("mode"), str) or task.get("mode") not in {"read", "write"}:
            raise ValidationError(f"Task policy '{task_id}' has invalid mode.")
        if not isinstance(allowed_tools, list) or any(
            not isinstance(item, str) or not item or item not in static_registry
            for item in allowed_tools
        ):
            raise ValidationError(f"Task policy '{task_id}' has invalid allowed_tools.")
        if type(task.get("requires_confirmation")) is not bool:
            raise ValidationError(
                f"Task policy '{task_id}' has invalid confirmation policy."
            )
        if tool_code in allowed_tools and task.get("id") == tool_code:
            candidates.append(task)

    # An exact task id is authoritative.  This prevents a write task that uses
    # a read helper during its workflow from accidentally making that helper a
    # confirmation-required operation.
    if not candidates:
        candidates = [
            task
            for task in tasks
            if tool_code in task.get("allowed_tools", [])
            and task.get("mode") == static_tool.get("mode")
        ]
    if not candidates:
        raise ValidationError(f"Tool '{tool_code}' is outside delivered task policy.")
    if any(task.get("mode") != static_tool.get("mode") for task in candidates):
        raise ValidationError(f"Task mode drift for tool '{tool_code}'.")
    confirmations = {task["requires_confirmation"] for task in candidates}
    if len(confirmations) != 1:
        raise ValidationError(f"Conflicting task confirmation policies for '{tool_code}'.")
    if next(iter(confirmations)) != bool(static_tool.get("requires_confirmation", False)):
        raise ValidationError(f"Task confirmation drift for tool '{tool_code}'.")
    return sorted(candidates, key=lambda task: task["id"])


def resolve_effective_tool_policy(tool_code, *, snapshot=None):
    """Resolve one executable AI tool against static and delivered policy.

    This is deliberately called before actor/session lookup and before a
    pending action is created.  A policy mismatch is an unavailable policy,
    not a permission decision that may be bypassed by retrying the tool.
    """
    snapshot = get_ai_document_snapshots() if snapshot is None else snapshot
    static_registry, delivered_by_id = _delivered_tool_catalog(snapshot)
    static_tool = static_registry.get(tool_code)
    if static_tool is None or tool_code not in delivered_by_id:
        raise ValidationError("Инструмент не разрешен текущим снимком политики.")
    task_payload = _snapshot_payload(snapshot, "ai.contract.task_types")
    candidates = _task_candidates(
        tool_code=tool_code,
        static_tool=static_tool,
        task_payload=task_payload,
    )
    task = candidates[0]
    return {
        "tool_code": tool_code,
        "mode": static_tool.get("mode"),
        "requires_confirmation": bool(static_tool.get("requires_confirmation", False)),
        "task_type_id": task["id"],
        "task_type_title": task.get("title", ""),
        "task_type_mode": task.get("mode", ""),
        "required_slots": list(task.get("required_slots") or []),
    }


def validate_ai_registry_document(candidate):
    validate_ai_registry_payload(candidate)
    validate_ai_identity_model_alignment(candidate)


def validate_ai_tools_document(candidate):
    validate_ai_tools_payload(candidate)
    validate_ai_tools_drift(candidate, TOOLS)


def validate_ai_task_types_document(candidate):
    validate_ai_task_types_payload(candidate)
    validate_ai_task_types_slot_coverage(candidate)


def cross_validate_ai_task_types(candidate, related_payloads):
    tools = related_payloads["ai.contract.tools"]
    validate_ai_task_types_tool_alignment(candidate, tools)
    validate_ai_write_confirmation_alignment(candidate, tools)


def validate_ai_models_document(candidate):
    if not isinstance(candidate, list) or not candidate:
        raise ValidationError("Каталог моделей ИИ должен быть непустым списком.")
    ids = []
    defaults = 0
    for item in candidate:
        if not isinstance(item, dict):
            raise ValidationError("Каждая модель ИИ должна быть JSON-объектом.")
        for key in ("id", "name", "model", "base_url", "api_key_env"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValidationError(f"У модели ИИ отсутствует непустое поле '{key}'.")
        if type(item.get("default")) is not bool:
            raise ValidationError("Поле default модели ИИ должно быть boolean.")
        ids.append(item["id"])
        defaults += int(item["default"])
    if len(ids) != len(set(ids)):
        raise ValidationError("Каталог моделей ИИ содержит повторяющиеся id.")
    if defaults != 1:
        raise ValidationError("Каталог моделей ИИ должен содержать ровно одну default-модель.")


def _spec(
    document_id,
    filename,
    validator,
    storage_policy,
    *,
    write_policy="read_only",
    consumer_classes=(),
    failure_policy="fail_closed",
    cross_document_ids=(),
    cross_validator=None,
    delivery_scope="django",
):
    return ConfigDocumentSpec(
        document_id=document_id,
        domain="ai",
        storage_policy=storage_policy,
        default_path=f"contracts/ai/{filename}",
        schema_version=1,
        validator=validator,
        failure_policy=failure_policy,
        write_policy=write_policy,
        required_permission="manage_settings",
        owner="ai",
        # Git-static documents have no runtime file compatibility path.  The
        # database-override document keeps its legacy path only while a
        # deployment has not yet enabled its released DB backend.
        legacy_settings_path=(
            f"LOCAL_BUSINESS_AI_{filename[:-5].upper()}_FILE"
            if storage_policy == "database_override"
            else None
        ),
        cross_document_ids=cross_document_ids,
        cross_validator=cross_validator,
        consumer_classes=consumer_classes,
        delivery_scope=delivery_scope,
        sensitivity="restricted" if storage_policy == "git_static" else "internal",
        active_backend="git" if storage_policy == "git_static" else "legacy_file",
    )


def get_document_specs():
    return [
        _spec(
            "ai.contract.registry",
            "registry.json",
            validate_ai_registry_document,
            "git_static",
            consumer_classes=("ai",),
        ),
        _spec(
            "ai.contract.tools",
            "tools.json",
            validate_ai_tools_document,
            "git_static",
            consumer_classes=("ai", "agent_runtime"),
            delivery_scope="django+agent_runtime",
        ),
        _spec(
            "ai.contract.task_types",
            "task_types.json",
            validate_ai_task_types_document,
            "git_static",
            consumer_classes=("ai", "agent_runtime"),
            delivery_scope="django+agent_runtime",
            cross_document_ids=("ai.contract.tools",),
            cross_validator=cross_validate_ai_task_types,
        ),
        _spec(
            "ai.contract.models",
            "models.json",
            validate_ai_models_document,
            "git_static",
            consumer_classes=("ai", "agent_runtime"),
            delivery_scope="django+agent_runtime",
        ),
        _spec(
            "ai.contract.chat_settings",
            "chat_settings.json",
            validate_ai_chat_settings_payload,
            "database_override",
            write_policy="editable",
            consumer_classes=("ai",),
            failure_policy="visible_default_fallback",
        ),
    ]
