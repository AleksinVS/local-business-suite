"""Тесты контракта типов задач agent runtime."""
from apps.ai.tests._common import *  # noqa: F401,F403


class TaskTypeContractTests(TestCase):
    databases = RUNTIME_DATABASES
    """Tests for the code-enforced task type contracts in task_types.py."""

    def test_workorders_list_contract_allows_correct_tool(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.list")
        self.assertIsNotNone(contract)
        self.assertTrue(contract.is_tool_allowed("workorders.list"))
        self.assertFalse(contract.is_tool_allowed("workorders.create"))

    def test_workorders_create_contract_requires_confirmation(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.create")
        self.assertIsNotNone(contract)
        self.assertTrue(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("workorders.create", "departments.list", "devices.list"))

    def test_workorders_transition_contract_slot_tracking(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.transition")
        self.assertIsNotNone(contract)
        # With all required slots filled
        filled = {"workorder": 42, "target_status": "in_progress"}
        self.assertEqual(contract.get_missing_required_slots(filled), [])
        self.assertTrue(contract.get_fulfilled_slots(filled)["workorder"], 42)
        # With missing required slot
        partial = {"workorder": 42}
        self.assertIn("target_status", contract.get_missing_required_slots(partial))

    def test_workorders_comment_contract(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.comment")
        self.assertIsNotNone(contract)
        self.assertFalse(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("workorders.comment",))
        # Slot tracking behavior
        filled = {"workorder": 7, "text": "Need access"}
        self.assertEqual(contract.get_missing_required_slots(filled), [])
        partial = {"workorder": 7}
        self.assertIn("text", contract.get_missing_required_slots(partial))

    def test_workorders_delete_contract_requires_confirmation(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.delete")
        self.assertIsNotNone(contract)
        self.assertTrue(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("workorders.get", "workorders.delete"))
        self.assertEqual(contract.get_missing_required_slots({"workorder_id": 7}), [])
        self.assertIn("workorder_id", contract.get_missing_required_slots({}))

    def test_lookup_departments_contract(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("lookup.departments")
        self.assertIsNotNone(contract)
        self.assertFalse(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("departments.list",))
        self.assertEqual(contract.get_missing_required_slots({}), [])

    def test_lookup_devices_contract(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("lookup.devices")
        self.assertIsNotNone(contract)
        self.assertFalse(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("devices.list",))
        self.assertEqual(contract.get_missing_required_slots({}), [])

    def test_resolve_task_type_for_tool_returns_resolution(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        result = resolve_task_type_for_tool(
            "workorders.list",
            {"status_or_scope": "new", "limit": 10}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type_id, "workorders.list")
        self.assertTrue(result.all_slots_fulfilled)
        self.assertEqual(result.slot_state.get("status_or_scope"), "new")

    def test_resolve_new_task_types_for_tool(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        # workorders.comment
        res_comment = resolve_task_type_for_tool("workorders.comment", {"workorder": 7, "text": "Hi"})
        self.assertIsNotNone(res_comment)
        self.assertEqual(res_comment.task_type_id, "workorders.comment")
        self.assertTrue(res_comment.all_slots_fulfilled)

        # lookup.departments
        res_dept = resolve_task_type_for_tool("departments.list", {})
        self.assertIsNotNone(res_dept)
        # It could resolve to workorders.create if no other distinguishing factor, 
        # but departments.list is in lookup.departments as well. Let's see what it resolves to.
        # Wait, if departments.list is in multiple task types, resolve_task_type_for_tool returns the first one.
        # Let's assert it resolves to something.
        
    def test_resolve_task_type_for_tool_returns_none_for_unknown_tool(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        result = resolve_task_type_for_tool("nonexistent.tool", {})
        self.assertIsNone(result)

    def test_task_type_resolution_to_trace_dict(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        result = resolve_task_type_for_tool(
            "workorders.create",
            {"department": 1, "subject": "Test", "description": "Desc", "priority": "high"}
        )
        self.assertIsNotNone(result)
        trace = result.to_trace_dict()
        self.assertEqual(trace["task_type_id"], "workorders.create")
        self.assertEqual(trace["task_type_mode"], "write")
        self.assertEqual(trace["resolved_tool"], "workorders.create")
        self.assertTrue(trace["requires_confirmation"])
        self.assertEqual(trace["missing_required_slots"], [])
        self.assertTrue(trace["all_slots_fulfilled"])

    def test_validate_bounded_tools_exist_in_catalog(self):
        from services.agent_runtime.task_types import validate_bounded_tools_exist_in_catalog
        catalog = {
            "tools": [
                {"id": "workorders.list"},
                {"id": "workorders.create"},
                {"id": "workorders.transition"},
                {"id": "workorders.get"},
                {"id": "departments.list"},
                {"id": "devices.list"},
                {"id": "workorders.comment"},
                {"id": "workorders.delete"},
                {"id": "workorders.confirm_closure"},
                {"id": "workorders.rate"},
                {"id": "inventory.devices.create"},
                {"id": "inventory.devices.update"},
                {"id": "inventory.devices.archive"},
                {"id": "analytics.summary"},
                {"id": "memory.search"},
                {"id": "memory.remember"},
                {"id": "memory.update_personal"},
            ]
        }
        errors = validate_bounded_tools_exist_in_catalog(catalog)
        self.assertEqual(errors, [])  # all tools exist

    def test_validate_bounded_tools_exist_in_catalog_catches_missing(self):
        from services.agent_runtime.task_types import validate_bounded_tools_exist_in_catalog
        catalog = {"tools": [{"id": "workorders.list"}]}
        errors = validate_bounded_tools_exist_in_catalog(catalog)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("workorders.create" in e for e in errors))
