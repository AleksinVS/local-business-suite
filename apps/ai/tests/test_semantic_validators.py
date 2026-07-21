"""Тесты семантических кросс-валидаторов контрактов AI."""
from apps.ai.tests._common import *  # noqa: F401,F403


class SemanticValidatorsTests(TestCase):
    databases = RUNTIME_DATABASES
    """Tests for the cross-cut semantic validators in json_utils."""

    def test_validate_ai_task_types_tool_alignment_catches_missing_tool(self):
        from apps.ai.contracts import validate_ai_task_types_tool_alignment
        from django.core.exceptions import ValidationError

        tools_payload = {
            "tools": [{"id": "workorders.list", "title": "List", "domain": "wo",
                       "mode": "read", "execution_mode": "read", "description": "d",
                       "inputs": [], "outputs": [], "required_role_scope": "v"}]
        }
        task_types_payload = {
            "task_types": [{
                "id": "workorders.list",
                "title": "List",
                "mode": "read",
                "description": "d",
                "allowed_tools": ["workorders.list", "nonexistent.tool"],
                "requires_confirmation": False,
                "output_mode": "structured_list",
                "example_requests": ["Show orders"],
            }]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_task_types_tool_alignment(task_types_payload, tools_payload)
        self.assertIn("nonexistent.tool", str(ctx.exception))

    def test_validate_ai_write_confirmation_alignment_catches_mismatch(self):
        from apps.ai.contracts import validate_ai_write_confirmation_alignment
        from django.core.exceptions import ValidationError

        tools_payload = {
            "tools": [
                {
                    "id": "workorders.create", "title": "Create", "domain": "wo",
                    "mode": "write", "execution_mode": "service", "description": "d",
                    "inputs": [], "outputs": [], "required_role_scope": "c",
                    "requires_confirmation": True,
                }
            ]
        }
        task_types_payload = {
            "task_types": [{
                "id": "workorders.create",
                "title": "Create",
                "mode": "write",
                "description": "d",
                "allowed_tools": ["workorders.create"],
                "requires_confirmation": False,  # mismatched!
                "output_mode": "confirmation_then_result",
                "example_requests": ["Create order"],
            }]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_write_confirmation_alignment(task_types_payload, tools_payload)
        self.assertIn("requires_confirmation", str(ctx.exception))

    def test_validate_ai_task_types_slot_coverage_catches_overlap(self):
        from apps.ai.contracts import validate_ai_task_types_slot_coverage
        from django.core.exceptions import ValidationError

        task_types_payload = {
            "task_types": [{
                "id": "workorders.create",
                "title": "Create",
                "mode": "write",
                "description": "d",
                "allowed_tools": ["workorders.create"],
                "required_slots": ["department", "subject"],  # overlaps
                "optional_slots": ["subject", "description"],  # with this
                "requires_confirmation": True,
                "output_mode": "confirmation_then_result",
                "example_requests": ["Create order"],
            }]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_task_types_slot_coverage(task_types_payload)
        self.assertIn("both required and optional", str(ctx.exception))

    def test_validate_ai_task_types_slot_coverage_passes_valid_payload(self):
        from apps.ai.contracts import validate_ai_task_types_slot_coverage

        task_types_payload = {
            "task_types": [{
                "id": "workorders.create",
                "title": "Create",
                "mode": "write",
                "description": "d",
                "allowed_tools": ["workorders.create"],
                "required_slots": ["department", "subject", "description"],
                "optional_slots": ["device", "priority"],
                "requires_confirmation": True,
                "output_mode": "confirmation_then_result",
                "example_requests": ["Create order"],
            }]
        }
        # Should not raise
        validate_ai_task_types_slot_coverage(task_types_payload)


# ---------------------------------------------------------------------------
# Tests for task type contract layer
# ---------------------------------------------------------------------------
