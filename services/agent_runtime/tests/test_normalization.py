"""Tests for status and priority alias normalization.

Run with: python -m pytest services/agent_runtime/tests/test_normalization.py -v
Or: python -m unittest services.agent_runtime.tests.test_normalization -v
"""

import unittest


class TestNormalizeStatus(unittest.TestCase):
    """Tests for normalize_status()."""

    def _get_target(self):
        from services.agent_runtime.task_types import normalize_status
        return normalize_status

    def test_internal_keys_pass_through(self):
        normalize_status = self._get_target()
        for key in ("new", "accepted", "in_progress", "on_hold", "resolved", "closed", "cancelled"):
            self.assertEqual(normalize_status(key), key)

    def test_russian_labels_resolve(self):
        normalize_status = self._get_target()
        self.assertEqual(normalize_status("Новая"), "new")
        self.assertEqual(normalize_status("Принята"), "accepted")
        self.assertEqual(normalize_status("В работе"), "in_progress")
        self.assertEqual(normalize_status("Ожидание"), "on_hold")
        self.assertEqual(normalize_status("Выполнена"), "resolved")
        self.assertEqual(normalize_status("Закрыта"), "closed")
        self.assertEqual(normalize_status("Отменена"), "cancelled")

    def test_case_insensitive_russian(self):
        normalize_status = self._get_target()
        self.assertEqual(normalize_status("в работе"), "in_progress")
        self.assertEqual(normalize_status("новая"), "new")
        self.assertEqual(normalize_status("ЗАКРЫТА"), "closed")

    def test_alternative_russian_forms(self):
        normalize_status = self._get_target()
        self.assertEqual(normalize_status("на удержании"), "on_hold")
        self.assertEqual(normalize_status("На удержании"), "on_hold")
        self.assertEqual(normalize_status("выполнено"), "resolved")
        self.assertEqual(normalize_status("Выполнено"), "resolved")
        self.assertEqual(normalize_status("закрыто"), "closed")
        self.assertEqual(normalize_status("Закрыто"), "closed")
        self.assertEqual(normalize_status("отменено"), "cancelled")
        self.assertEqual(normalize_status("Отменено"), "cancelled")

    def test_unknown_values_pass_through(self):
        normalize_status = self._get_target()
        self.assertEqual(normalize_status("unknown_status"), "unknown_status")
        self.assertEqual(normalize_status("something"), "something")

    def test_empty_string(self):
        normalize_status = self._get_target()
        self.assertEqual(normalize_status(""), "")

    def test_none_returns_none(self):
        """normalize_status handles None gracefully by returning it unchanged."""
        normalize_status = self._get_target()
        self.assertIsNone(normalize_status(None))


class TestNormalizePriority(unittest.TestCase):
    """Tests for normalize_priority()."""

    def _get_target(self):
        from services.agent_runtime.task_types import normalize_priority
        return normalize_priority

    def test_internal_keys_pass_through(self):
        normalize_priority = self._get_target()
        for key in ("low", "medium", "high", "critical"):
            self.assertEqual(normalize_priority(key), key)

    def test_russian_labels_resolve(self):
        normalize_priority = self._get_target()
        self.assertEqual(normalize_priority("Низкий"), "low")
        self.assertEqual(normalize_priority("Средний"), "medium")
        self.assertEqual(normalize_priority("Высокий"), "high")
        self.assertEqual(normalize_priority("Критичный"), "critical")

    def test_case_insensitive_russian(self):
        normalize_priority = self._get_target()
        self.assertEqual(normalize_priority("низкий"), "low")
        self.assertEqual(normalize_priority("ВЫСОКИЙ"), "high")

    def test_alternative_russian_forms(self):
        normalize_priority = self._get_target()
        self.assertEqual(normalize_priority("низкая"), "low")
        self.assertEqual(normalize_priority("Низкая"), "low")
        self.assertEqual(normalize_priority("средняя"), "medium")
        self.assertEqual(normalize_priority("Средняя"), "medium")
        self.assertEqual(normalize_priority("высокая"), "high")
        self.assertEqual(normalize_priority("Высокая"), "high")
        self.assertEqual(normalize_priority("критическая"), "critical")
        self.assertEqual(normalize_priority("Критическая"), "critical")

    def test_unknown_values_pass_through(self):
        normalize_priority = self._get_target()
        self.assertEqual(normalize_priority("urgent"), "urgent")

    def test_empty_string(self):
        normalize_priority = self._get_target()
        self.assertEqual(normalize_priority(""), "")


class TestGetAllowedStatuses(unittest.TestCase):
    """Tests for get_allowed_statuses()."""

    def test_returns_all_status_keys(self):
        from services.agent_runtime.task_types import get_allowed_statuses
        statuses = get_allowed_statuses()
        expected = ["new", "accepted", "in_progress", "on_hold", "resolved", "closed", "cancelled"]
        self.assertEqual(statuses, expected)


class TestGetAllowedPriorities(unittest.TestCase):
    """Tests for get_allowed_priorities()."""

    def test_returns_all_priority_keys(self):
        from services.agent_runtime.task_types import get_allowed_priorities
        priorities = get_allowed_priorities()
        expected = ["low", "medium", "high", "critical"]
        self.assertEqual(priorities, expected)


class TestStatusAliasesAlignment(unittest.TestCase):
    """Verify STATUS_ALIASES keys match workflow_rules.json statuses."""

    def test_aliases_match_workflow_statuses(self):
        import json
        from pathlib import Path
        from services.agent_runtime.task_types import STATUS_ALIASES

        config_path = Path(__file__).resolve().parents[3] / "contracts" / "workflow_rules.json"
        workflow = json.loads(config_path.read_text(encoding="utf-8"))
        workflow_statuses = set(workflow["statuses"])
        alias_keys = set(STATUS_ALIASES.keys())
        self.assertEqual(
            alias_keys,
            workflow_statuses,
            f"STATUS_ALIASES keys {alias_keys - workflow_statuses or '(extra)'} "
            f"do not match workflow statuses {workflow_statuses - alias_keys or '(missing)'}",
        )


class TestPromptAliasSection(unittest.TestCase):
    """Verify the system prompt includes the alias section."""

    def test_build_alias_section_contains_statuses(self):
        from services.agent_runtime.prompting import _build_alias_section
        section = _build_alias_section()
        self.assertIn("in_progress", section)
        self.assertIn("В работе", section)
        self.assertIn("new", section)
        self.assertIn("Новая", section)
        self.assertIn("on_hold", section)
        self.assertIn("Ожидание", section)

    def test_build_alias_section_contains_priorities(self):
        from services.agent_runtime.prompting import _build_alias_section
        section = _build_alias_section()
        self.assertIn("critical", section)
        self.assertIn("Критичный", section)

    def test_build_alias_section_contains_transitions(self):
        from services.agent_runtime.prompting import _build_alias_section
        section = _build_alias_section()
        self.assertIn("Допустимые переходы статусов", section)

    def test_build_alias_section_contains_instruction(self):
        from services.agent_runtime.prompting import _build_alias_section
        section = _build_alias_section()
        self.assertIn("внутренние ключи", section)


class TestPromptMemorySection(unittest.TestCase):
    """Verify the system prompt includes memory service guidance."""

    def test_build_memory_section_contains_tool_and_safety_rules(self):
        from services.agent_runtime.prompting import _build_memory_section

        section = _build_memory_section()

        self.assertIn("memory.search", section)
        self.assertIn("memory.remember", section)
        self.assertIn("memory.update_personal", section)
        self.assertIn("safe corpus", section)
        self.assertIn("citations", section)
        self.assertIn("source_explicit", section)
        self.assertIn("source_semantic", section)
        self.assertIn("ranking_profile", section)
        self.assertIn("knowledge_semantic", section)
        self.assertIn("не является отдельным сетевым сервисом", section)
        self.assertNotIn("read-only инструмент `memory.search`", section)

    def test_build_system_prompt_includes_memory_section(self):
        from services.agent_runtime.prompting import build_system_prompt

        prompt = build_system_prompt()

        self.assertIn("Система памяти", prompt)
        self.assertIn("memory.search", prompt)
        self.assertIn("memory.remember", prompt)
        self.assertIn("MEMORY_DEPLOYMENT.md", prompt)


class TestPromptUiContextSection(unittest.TestCase):
    """Verify context-aware sidebar guidance is present."""

    def test_build_system_prompt_includes_ui_context_tool(self):
        from services.agent_runtime.prompting import build_system_prompt

        prompt = build_system_prompt()

        self.assertIn("ui.get_current_context", prompt)
        self.assertIn("эта заявка", prompt)


class TestRuntimeMemoryTool(unittest.TestCase):
    """Verify the LangGraph runtime exposes memory tools to the model."""

    def test_build_tools_includes_memory_tools(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def execute_tool(self, **kwargs):
                return {"ok": True, "kwargs": kwargs}

        tools = build_tools(
            actor={"user_id": 1, "channel": "internal"},
            session_id="session-1",
            gateway_client=FakeGatewayClient(),
            conversation_id="conv-1",
            request_id="req-1",
            origin_channel="test",
            actor_version="v1",
        )

        tool_names = {tool.name for tool in tools}
        self.assertIn("ui.get_current_context", tool_names)
        self.assertIn("memory.search", tool_names)
        self.assertIn("memory.remember", tool_names)
        self.assertIn("memory.update_personal", tool_names)

    def test_memory_search_tool_forwards_search_options(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def __init__(self):
                self.calls = []

            def execute_tool(self, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True, "kwargs": kwargs}

        gateway = FakeGatewayClient()
        tools = build_tools(
            actor={"user_id": 1, "channel": "internal"},
            session_id="session-1",
            gateway_client=gateway,
            conversation_id="conv-1",
            request_id="req-1",
            origin_channel="test",
            actor_version="v1",
        )
        search_tool = next(tool for tool in tools if tool.name == "memory.search")

        result = search_tool.invoke(
            {
                "query": "manualftsneedle_xlsx_260526",
                "limit": 3,
                "sensitivity": "internal",
                "search_mode": "source_explicit",
                "ranking_profile": "source_semantic",
                "include_source_data": True,
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(gateway.calls[0]["tool_code"], "memory.search")
        self.assertEqual(gateway.calls[0]["session_id"], "session-1")
        self.assertEqual(
            gateway.calls[0]["payload"],
            {
                "query": "manualftsneedle_xlsx_260526",
                "limit": 3,
                "sensitivity": "internal",
                "search_mode": "source_explicit",
                "ranking_profile": "source_semantic",
                "include_source_data": True,
            },
        )

    def test_memory_remember_tool_uses_current_session_by_default(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def __init__(self):
                self.calls = []

            def execute_tool(self, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True, "kwargs": kwargs}

        gateway = FakeGatewayClient()
        tools = build_tools(
            actor={"user_id": 1, "channel": "internal"},
            session_id="session-1",
            gateway_client=gateway,
            conversation_id="conv-1",
            request_id="req-1",
            origin_channel="test",
            actor_version="v1",
        )
        remember_tool = next(tool for tool in tools if tool.name == "memory.remember")

        result = remember_tool.invoke({"user_note": "Запомнить: тестовый факт"})

        self.assertTrue(result["ok"])
        self.assertEqual(gateway.calls[0]["tool_code"], "memory.remember")
        self.assertEqual(gateway.calls[0]["session_id"], "session-1")
        self.assertEqual(gateway.calls[0]["payload"]["session_id"], "session-1")
        self.assertEqual(gateway.calls[0]["payload"]["target_scope"], "personal")

    def test_ui_context_tool_forwards_actor_context(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def __init__(self):
                self.calls = []

            def execute_tool(self, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True, "result": {"status": "ok"}}

        gateway = FakeGatewayClient()
        actor = {
            "user_id": 1,
            "channel": "sidebar",
            "page_context": {"context_snapshot_id": 17, "page_context_present": True},
        }
        tools = build_tools(
            actor=actor,
            session_id="session-1",
            gateway_client=gateway,
            conversation_id="conv-1",
            request_id="req-1",
            origin_channel="sidebar",
            actor_version="v1",
        )
        context_tool = next(tool for tool in tools if tool.name == "ui.get_current_context")

        result = context_tool.invoke({})

        self.assertTrue(result["ok"])
        self.assertEqual(gateway.calls[0]["tool_code"], "ui.get_current_context")
        self.assertEqual(gateway.calls[0]["actor"]["page_context"]["context_snapshot_id"], 17)


if __name__ == "__main__":
    unittest.main()
