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
        self.assertIn("safe corpus", section)
        self.assertIn("citations", section)
        self.assertIn("не является отдельным сетевым сервисом", section)

    def test_build_system_prompt_includes_memory_section(self):
        from services.agent_runtime.prompting import build_system_prompt

        prompt = build_system_prompt()

        self.assertIn("Система памяти", prompt)
        self.assertIn("memory.search", prompt)
        self.assertIn("MEMORY_DEPLOYMENT.md", prompt)


class TestRuntimeMemoryTool(unittest.TestCase):
    """Verify the LangGraph runtime exposes memory.search to the model."""

    def test_build_tools_includes_memory_search(self):
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

        self.assertIn("memory.search", {tool.name for tool in tools})


if __name__ == "__main__":
    unittest.main()
