"""Тесты семантических кросс-валидаторов контрактов AI."""
import json
from pathlib import Path

import pytest

from apps.ai.tests._common import *  # noqa: F401,F403


@pytest.mark.unit
class SemanticValidatorsTests(SimpleTestCase):
    """Tests for the cross-cut semantic validators in json_utils."""

    def test_access_mutation_tools_are_absent_from_python_and_git_catalogs(self):
        from apps.ai.tool_definitions import get_registry_payload

        removed = {"access.update_role_permissions", "access.users.update"}
        self.assertTrue(
            removed.isdisjoint({tool["id"] for tool in get_registry_payload()["tools"]})
        )
        contract = json.loads(Path("contracts/ai/tools.json").read_text(encoding="utf-8"))
        self.assertTrue(removed.isdisjoint({tool["id"] for tool in contract["tools"]}))

    def test_access_explain_and_editor_are_read_only_tools(self):
        from apps.ai.tool_definitions import get_registry_payload

        tools = {tool["id"]: tool for tool in get_registry_payload()["tools"]}
        self.assertEqual(tools["access.users.explain"]["mode"], "read")
        self.assertEqual(tools["access.open_editor"]["mode"], "read")
        self.assertFalse(tools["access.open_editor"]["requires_confirmation"])

    def test_runtime_validator_rejects_any_new_access_write_tool(self):
        from apps.ai.contracts import validate_ai_tools_payload
        from django.core.exceptions import ValidationError

        contract = json.loads(Path("contracts/ai/tools.json").read_text(encoding="utf-8"))
        contract["tools"].append({
            "id": "access.future_write",
            "title": "Forbidden",
            "domain": "access",
            "mode": "write",
            "execution_mode": "service_layer",
            "description": "Must remain unavailable.",
            "inputs": [],
            "outputs": [],
            "required_role_scope": "manage_roles",
        })
        with self.assertRaisesMessage(ValidationError, "запрещённые инструменты"):
            validate_ai_tools_payload(contract)

    def test_runtime_validator_rejects_non_read_access_modes(self):
        from apps.ai.contracts import validate_ai_tools_payload
        from django.core.exceptions import ValidationError

        base = json.loads(Path("contracts/ai/tools.json").read_text(encoding="utf-8"))
        access_tool = next(tool for tool in base["tools"] if tool["domain"] == "access")
        for mode in ("write", "execute", None):
            with self.subTest(mode=mode):
                contract = json.loads(json.dumps(base))
                candidate = next(tool for tool in contract["tools"] if tool["id"] == access_tool["id"])
                if mode is None:
                    candidate.pop("mode")
                else:
                    candidate["mode"] = mode
                with self.assertRaises(ValidationError):
                    validate_ai_tools_payload(contract)

    def test_runtime_validator_rejects_retired_access_mutation_tools(self):
        from apps.ai.contracts import validate_ai_tools_payload

        contract = json.loads(Path("contracts/ai/tools.json").read_text(encoding="utf-8"))
        retired = {
            "id": "access.users.update",
            "title": "Retired access mutation",
            "domain": "access",
            "mode": "write",
            "execution_mode": "service_layer",
            "description": "Must remain unavailable.",
            "inputs": ["user_id"],
            "outputs": ["user"],
            "required_role_scope": "superuser",
        }
        contract["tools"].append(retired)

        with self.assertRaisesMessage(ValidationError, "запрещённые инструменты"):
            validate_ai_tools_payload(contract)

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
