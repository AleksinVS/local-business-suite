import json

from django.core.exceptions import ValidationError


REQUIRED_ROLE_KEYS = {
    "view_scope",
    "create_workorder",
    "edit_scope",
    "comment_scope",
    "upload_attachment_scope",
    "confirm_closure_scope",
    "rate_scope",
    "transition_scope",
    "transition_targets",
    "manage_inventory",
    "manage_board_columns",
    "manage_assignments",
}


def validate_role_rules_payload(payload):
    if not isinstance(payload, dict) or not payload:
        raise ValidationError("Конфигурация ролей должна быть непустым JSON-объектом.")

    for role, config in payload.items():
        if not isinstance(config, dict):
            raise ValidationError(f"Роль '{role}' должна быть JSON-объектом.")
        missing = REQUIRED_ROLE_KEYS - set(config.keys())
        if missing:
            raise ValidationError(
                f"Роль '{role}' не содержит обязательные поля: {', '.join(sorted(missing))}."
            )
        targets = config.get("transition_targets")
        if targets != "*" and not isinstance(targets, list):
            raise ValidationError(
                f"У роли '{role}' поле transition_targets должно быть списком или '*'."
            )


def pretty_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
