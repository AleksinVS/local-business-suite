"""Tests for status and priority alias normalization.

Run with: python -m pytest services/agent_runtime/tests/test_normalization.py -v
Or: python -m unittest services.agent_runtime.tests.test_normalization -v
"""

import asyncio
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch


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
        self.assertIn("corpus=\"source_data\"", section)
        self.assertIn("corpus=\"knowledge\"", section)
        self.assertIn("RRF", section)
        self.assertIn("не является отдельным сетевым сервисом", section)
        self.assertNotIn("read-only инструмент `memory.search`", section)
        self.assertNotIn("search_mode", section)
        self.assertNotIn("ranking_profile", section)
        self.assertNotIn("include_source_data", section)

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
        self.assertIn("ui.open_right_panel", prompt)
        self.assertIn("не отвечай, что у тебя нет доступа", prompt)
        self.assertIn("Модульные сценарии открытия объектов описаны в skills", prompt)
        self.assertIn("текущая запись", prompt)

    def test_build_system_prompt_includes_skill_trigger_examples(self):
        from services.agent_runtime.prompting import build_system_prompt

        prompt = build_system_prompt(
            skills_catalog=[
                {
                    "id": "workorders.open_right_panel",
                    "name": "workorders-open-right-panel",
                    "description": "Открывает заявку справа.",
                    "trigger_examples": ["Открой заявку №17"],
                }
            ]
        )

        self.assertIn("workorders.open_right_panel", prompt)
        self.assertIn("Открой заявку №17", prompt)


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
        self.assertIn("ui.open_right_panel", tool_names)
        self.assertIn("waiting_list.get", tool_names)
        self.assertIn("workorders.delete", tool_names)
        self.assertIn("memory.search", tool_names)
        self.assertIn("memory.remember", tool_names)
        self.assertIn("memory.update_personal", tool_names)
        self.assertIn("ai.skills.create_or_update", tool_names)

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
                "corpus": "source_data",
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
                "corpus": "source_data",
            },
        )

    def test_memory_search_tool_schema_excludes_removed_params(self):
        """ADR-0030 decision 6: the removed profile-selection params must not
        appear in the LangChain tool schema advertised to the LLM, since the
        Django gateway now rejects them (apps/ai/tooling.py
        _MEMORY_SEARCH_REMOVED_KEYS)."""
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def execute_tool(self, **kwargs):
                return {"ok": True}

        tools = build_tools(
            actor={"user_id": 1, "channel": "internal"},
            session_id="session-1",
            gateway_client=FakeGatewayClient(),
            conversation_id="conv-1",
            request_id="req-1",
            origin_channel="test",
            actor_version="v1",
        )
        search_tool = next(tool for tool in tools if tool.name == "memory.search")
        schema_args = set(search_tool.args)

        self.assertEqual(schema_args, {"query", "limit", "sensitivity", "corpus"})
        self.assertNotIn("search_mode", schema_args)
        self.assertNotIn("ranking_profile", schema_args)
        self.assertNotIn("include_source_data", schema_args)

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

    def test_open_right_panel_tool_forwards_safe_identifiers(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def __init__(self):
                self.calls = []

            def execute_tool(self, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True, "result": {"ui_command": {"type": "open_right_panel"}}}

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
        open_tool = next(tool for tool in tools if tool.name == "ui.open_right_panel")

        result = open_tool.invoke(
            {
                "source_code": "workorders",
                "object_type": "workorder",
                "object_id": "42",
                "mode": "view",
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(gateway.calls[0]["tool_code"], "ui.open_right_panel")
        self.assertEqual(
            gateway.calls[0]["payload"],
            {
                "source_code": "workorders",
                "object_type": "workorder",
                "object_id": "42",
                "mode": "view",
            },
        )

    def test_delete_workorder_tool_forwards_workorder_id(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def __init__(self):
                self.calls = []

            def execute_tool(self, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True, "result": {"workorder": {"id": 42, "deleted": True}}}

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
        delete_tool = next(tool for tool in tools if tool.name == "workorders.delete")

        result = delete_tool.invoke({"workorder_id": 42})

        self.assertTrue(result["ok"])
        self.assertEqual(gateway.calls[0]["tool_code"], "workorders.delete")
        self.assertEqual(gateway.calls[0]["payload"], {"workorder_id": 42})

    def test_waiting_list_get_tool_forwards_entry_id(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def __init__(self):
                self.calls = []

            def execute_tool(self, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True, "result": {"entry": {"id": 12}}}

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
        entry_tool = next(tool for tool in tools if tool.name == "waiting_list.get")

        result = entry_tool.invoke({"entry_id": 12})

        self.assertTrue(result["ok"])
        self.assertEqual(gateway.calls[0]["tool_code"], "waiting_list.get")
        self.assertEqual(gateway.calls[0]["payload"], {"entry_id": 12})

    def test_ai_skill_create_tool_forwards_instruction_only_payload(self):
        from services.agent_runtime.tools import build_tools

        class FakeGatewayClient:
            def __init__(self):
                self.calls = []

            def execute_tool(self, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True, "result": {"skill_id": "demo.skill"}}

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
        skill_tool = next(tool for tool in tools if tool.name == "ai.skills.create_or_update")

        result = skill_tool.invoke(
            {
                "skill_id": "demo.skill",
                "name": "demo-skill",
                "description": "Demo skill.",
                "required_tools": ["ui.open_right_panel"],
                "body": "Use a tool.",
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(gateway.calls[0]["tool_code"], "ai.skills.create_or_update")
        self.assertEqual(gateway.calls[0]["payload"]["skill_id"], "demo.skill")
        self.assertEqual(gateway.calls[0]["payload"]["required_tools"], ["ui.open_right_panel"])


class TestRuntimeSafeLogging(unittest.TestCase):
    """Проверяет, что runtime-логи получают только технический контекст."""

    def test_safe_chat_log_context_excludes_raw_prompt_and_actor_details(self):
        from services.agent_runtime.app import _safe_chat_log_context
        from services.agent_runtime.schemas import ActorContext, ChatRequest, HistoryMessage

        payload = ChatRequest(
            session_id="session-safe-log",
            prompt="Секретный пользовательский prompt",
            history=[HistoryMessage(role="user", content="old message")],
            model_id="test-model",
            actor=ActorContext(
                user_id=17,
                username="doctor-secret",
                roles=["role-secret"],
                channel="sidebar",
                source="django-chat",
                page_context={"context_hint": "secret-page-context"},
            ),
        )
        actor_context = payload.actor.ensure_trace_context()

        log_context = _safe_chat_log_context(payload, actor_context)
        serialized = json.dumps(log_context, ensure_ascii=False)

        self.assertEqual(log_context["prompt_length"], len(payload.prompt))
        self.assertEqual(len(log_context["prompt_sha256"]), 64)
        self.assertEqual(log_context["history_count"], 1)
        self.assertEqual(log_context["actor_user_id"], 17)
        self.assertEqual(log_context["actor_roles_count"], 1)
        self.assertTrue(log_context["page_context_present"])
        self.assertNotIn(payload.prompt, serialized)
        self.assertNotIn("doctor-secret", serialized)
        self.assertNotIn("role-secret", serialized)
        self.assertNotIn("secret-page-context", serialized)

    def test_chat_error_log_excludes_exception_text(self):
        from fastapi import HTTPException
        from services.agent_runtime.app import chat
        from services.agent_runtime.schemas import ActorContext, ChatRequest

        payload = ChatRequest(
            session_id="session-error-log",
            prompt="Секретный пользовательский prompt",
            model_id="test-model",
            actor=ActorContext(
                user_id=17,
                username="doctor-secret",
                roles=["role-secret"],
                channel="sidebar",
            ),
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "services.agent_runtime.app.run_agent",
            side_effect=RuntimeError("leaked prompt text"),
        ), self.assertLogs("services.agent_runtime.app", level="ERROR") as captured:
            with self.assertRaises(HTTPException) as raised:
                chat(payload)

        log_output = "\n".join(captured.output)
        self.assertIn("error_type=RuntimeError", log_output)
        self.assertNotIn("leaked prompt text", log_output)
        self.assertNotIn(payload.prompt, log_output)
        self.assertEqual(raised.exception.detail["error"], "agent_runtime_error")
        self.assertNotIn("leaked prompt text", json.dumps(raised.exception.detail))


class TestAGUIAdapter(unittest.TestCase):
    """Verify AG-UI event mapping for CopilotKit-compatible clients."""

    def test_run_input_extracts_latest_user_prompt_and_history(self):
        from services.agent_runtime.schemas import AGUIRunAgentInput

        run_input = AGUIRunAgentInput(
            threadId="thread-1",
            runId="run-1",
            messages=[
                {"id": "u1", "role": "user", "content": "Первый вопрос"},
                {"id": "a1", "role": "assistant", "content": "Первый ответ"},
                {"id": "u2", "role": "user", "content": [{"type": "text", "text": "Новый вопрос"}]},
            ],
        )

        self.assertEqual(run_input.latest_user_text(), "Новый вопрос")
        history = run_input.history_messages()
        self.assertEqual([(item.role, item.content) for item in history], [("user", "Первый вопрос"), ("assistant", "Первый ответ")])

    def test_text_events_have_required_ag_ui_order(self):
        from services.agent_runtime.ag_ui_adapter import text_message_events

        events = list(text_message_events(["Привет", "", " мир"], message_id="msg-1"))

        self.assertEqual([event["type"] for event in events], ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"])
        self.assertEqual(events[0]["messageId"], "msg-1")
        self.assertEqual(events[1]["delta"], "Привет")
        self.assertEqual(events[2]["delta"], " мир")

    def test_tool_trace_redacts_sensitive_args(self):
        from services.agent_runtime.ag_ui_adapter import tool_trace_events

        events = list(
            tool_trace_events(
                [
                    {
                        "tool": "demo.tool",
                        "args": {"workorder_id": 42, "api_token": "secret-token"},
                    }
                ],
                parent_message_id="msg-1",
            )
        )

        args_event = next(event for event in events if event["type"] == "TOOL_CALL_ARGS")
        self.assertEqual(json.loads(args_event["delta"]), {"workorder_id": 42, "api_token": "[redacted]"})

    def test_tool_trace_redacts_nested_sensitive_args(self):
        from services.agent_runtime.ag_ui_adapter import tool_trace_events

        events = list(
            tool_trace_events(
                [
                    {
                        "tool": "demo.tool",
                        "args": {
                            "safe": "value",
                            "nested": {"session_cookie": "secret-cookie", "items": [{"api_key": "secret-key"}]},
                        },
                    }
                ],
                parent_message_id="msg-1",
            )
        )

        args_event = next(event for event in events if event["type"] == "TOOL_CALL_ARGS")
        self.assertEqual(
            json.loads(args_event["delta"]),
            {
                "safe": "value",
                "nested": {"session_cookie": "[redacted]", "items": [{"api_key": "[redacted]"}]},
            },
        )

    def test_ui_command_maps_to_state_delta_and_custom_event(self):
        from services.agent_runtime.ag_ui_adapter import ui_command_events

        events = list(
            ui_command_events(
                [
                    {
                        "type": "open_right_panel",
                        "source_code": "workorders",
                        "object_type": "workorder",
                        "object_id": 42,
                        "mode": "view",
                        "htmx_url": "/workorders/42/",
                        "unsafe": "ignored",
                    }
                ]
            )
        )

        self.assertEqual([event["type"] for event in events], ["STATE_DELTA", "CUSTOM"])
        self.assertEqual(events[0]["delta"][0]["path"], "/localBusiness/uiCommands")
        self.assertEqual(events[0]["delta"][1]["path"], "/localBusinessUiCommands")
        self.assertNotIn("unsafe", events[0]["delta"][0]["value"][0])
        self.assertEqual(events[0]["delta"][0]["value"][0]["version"], "1.0")
        self.assertEqual(events[0]["delta"][0]["value"][0]["htmx_url"], "/workorders/42/")
        self.assertEqual(events[1]["name"], "local_business.ui_command")

    def test_ui_command_rejects_external_urls_and_clamps_mode(self):
        from services.agent_runtime.ag_ui_adapter import ui_command_events

        events = list(
            ui_command_events(
                [
                    {
                        "type": "open_right_panel",
                        "source_code": "workorders",
                        "object_type": "workorder",
                        "object_id": 42,
                        "mode": "javascript",
                        "swap": "outerHTML",
                        "htmx_url": "https://example.invalid/workorders/42/",
                    },
                    {
                        "type": "open_right_panel",
                        "source_code": "workorders",
                        "object_type": "workorder",
                        "object_id": 43,
                        "mode": "javascript",
                        "swap": "outerHTML",
                        "htmx_url": "/workorders/43/",
                    },
                ]
            )
        )

        self.assertEqual([event["type"] for event in events], ["STATE_DELTA", "CUSTOM"])
        command = events[0]["delta"][0]["value"][0]
        self.assertEqual(command["object_id"], "43")
        self.assertEqual(command["mode"], "view")
        self.assertEqual(command["swap"], "innerHTML")

    def test_ui_command_limits_batch_size(self):
        from services.agent_runtime.ag_ui_adapter import ui_command_events

        events = list(
            ui_command_events(
                [
                    {
                        "type": "open_right_panel",
                        "source_code": "workorders",
                        "object_type": "workorder",
                        "object_id": index,
                        "htmx_url": f"/workorders/{index}/",
                    }
                    for index in range(12)
                ]
            )
        )

        self.assertEqual(len(events[0]["delta"][0]["value"]), 8)


class TestAGUIRuntimeEndpoint(unittest.TestCase):
    """Verify the FastAPI AG-UI endpoint wraps the existing runtime safely."""

    def _signed_forwarded_props(self, payload, token="test-gateway-token"):
        from services.agent_runtime.app import _agui_signature_payload
        from services.agent_runtime.schemas import AGUIActorPayload

        payload = {**payload, "issued_at": int(time.time())}
        actor_payload = AGUIActorPayload.model_validate(payload)
        payload["signature"] = hmac.new(
            token.encode("utf-8"),
            _agui_signature_payload(actor_payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return payload

    async def _collect_events(self, response):
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        events = []
        for block in "".join(chunks).split("\n\n"):
            if not block.startswith("data: "):
                continue
            events.append(json.loads(block[6:]))
        return events

    def test_ag_ui_run_streams_standard_events(self):
        from services.agent_runtime.app import ag_ui_run
        from services.agent_runtime.schemas import AGUIRunAgentInput

        run_input = AGUIRunAgentInput(
            threadId="sidebar-session",
            runId="run-1",
            messages=[{"id": "u1", "role": "user", "content": "Открой заявку 42"}],
            forwardedProps=self._signed_forwarded_props(
                {
                    "session_id": "sidebar-session",
                    "model_id": "test-model",
                    "origin_channel": "copilotkit",
                    "actor_version": "copilotkit-ag-ui-v1",
                    "actor": {
                        "user_id": 17,
                        "username": "doctor",
                        "roles": ["engineer"],
                        "is_superuser": False,
                        "channel": "sidebar",
                        "source": "django-copilotkit",
                        "origin_channel": "copilotkit",
                        "actor_version": "copilotkit-ag-ui-v1",
                    },
                },
            ),
        )

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "LOCAL_BUSINESS_AI_GATEWAY_TOKEN": "test-gateway-token"},
        ), patch(
            "services.agent_runtime.app.run_agent",
            return_value={
                "assistant_message": "Открываю заявку.",
                "tool_trace": [{"tool": "ui.open_right_panel", "args": {"object_id": "42"}}],
                "ui_commands": [
                    {
                        "type": "open_right_panel",
                        "source_code": "workorders",
                        "object_type": "workorder",
                        "object_id": "42",
                        "mode": "view",
                        "htmx_url": "/workorders/42/",
                    }
                ],
            },
        ) as run_agent_mock:
            response = asyncio.run(ag_ui_run(run_input))
            events = asyncio.run(self._collect_events(response))

        self.assertEqual(events[0]["type"], "RUN_STARTED")
        self.assertEqual(events[1]["type"], "CUSTOM")
        self.assertEqual(events[1]["name"], "local_business.protocol")
        self.assertEqual(events[1]["value"]["local_business_protocol"], "1.0")
        self.assertIn("TEXT_MESSAGE_START", [event["type"] for event in events])
        self.assertIn("TEXT_MESSAGE_CONTENT", [event["type"] for event in events])
        self.assertIn("TOOL_CALL_START", [event["type"] for event in events])
        self.assertIn("STATE_DELTA", [event["type"] for event in events])
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
        run_agent_mock.assert_called_once()
        self.assertEqual(run_agent_mock.call_args.kwargs["prompt"], "Открой заявку 42")
        self.assertEqual(run_agent_mock.call_args.kwargs["session_id"], "sidebar-session")

    def test_ag_ui_run_rejects_missing_actor_signature(self):
        from services.agent_runtime.app import ag_ui_run
        from services.agent_runtime.schemas import AGUIRunAgentInput

        run_input = AGUIRunAgentInput(
            threadId="sidebar-session",
            runId="run-2",
            messages=[{"id": "u1", "role": "user", "content": "Проверка"}],
            forwardedProps={
                "session_id": "sidebar-session",
                "origin_channel": "copilotkit",
                "actor": {
                    "user_id": 17,
                    "username": "doctor",
                    "roles": [],
                    "is_superuser": False,
                    "channel": "sidebar",
                    "source": "django-copilotkit",
                },
            },
        )

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "LOCAL_BUSINESS_AI_GATEWAY_TOKEN": "test-gateway-token"},
        ), patch("services.agent_runtime.app.run_agent") as run_agent_mock:
            response = asyncio.run(ag_ui_run(run_input))
            events = asyncio.run(self._collect_events(response))

        self.assertEqual(events[0]["type"], "RUN_ERROR")
        self.assertEqual(events[0]["code"], "invalid_actor_signature")
        run_agent_mock.assert_not_called()

    def test_ag_ui_run_returns_run_error_when_llm_key_is_missing(self):
        from services.agent_runtime.app import ag_ui_run
        from services.agent_runtime.schemas import AGUIRunAgentInput

        run_input = AGUIRunAgentInput(
            threadId="sidebar-session",
            runId="run-no-key",
            messages=[{"id": "u1", "role": "user", "content": "Проверка без ключа"}],
            forwardedProps=self._signed_forwarded_props(
                {
                    "session_id": "sidebar-session",
                    "model_id": "test-model",
                    "origin_channel": "copilotkit",
                    "ui_driver": "copilotkit",
                    "actor_version": "copilotkit-ag-ui-v1",
                    "actor": {
                        "user_id": 17,
                        "username": "doctor",
                        "roles": ["engineer"],
                        "is_superuser": False,
                        "channel": "sidebar",
                        "source": "django-copilotkit",
                        "origin_channel": "copilotkit",
                        "actor_version": "copilotkit-ag-ui-v1",
                    },
                },
            ),
        )

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "", "LOCAL_BUSINESS_AI_GATEWAY_TOKEN": "test-gateway-token"},
        ), patch("services.agent_runtime.app.run_agent") as run_agent_mock:
            response = asyncio.run(ag_ui_run(run_input))
            events = asyncio.run(self._collect_events(response))

        self.assertEqual([event["type"] for event in events], ["RUN_STARTED", "CUSTOM", "RUN_ERROR"])
        self.assertEqual(events[1]["name"], "local_business.protocol")
        self.assertEqual(events[2]["code"], "service_not_configured")
        run_agent_mock.assert_not_called()


class TestMCPResources(unittest.TestCase):
    """Verify safe registry-backed MCP resources."""

    def test_skill_and_tool_resources_return_safe_json(self):
        class FakeGatewayClient:
            def __init__(self, **kwargs):
                pass

            def get_skills_catalog(self):
                return {
                    "skills": [
                        {
                            "id": "workorders.open_right_panel",
                            "name": "workorders-open-right-panel",
                            "description": "Открывает заявку справа.",
                            "source_code": "workorders",
                            "object_types": ["workorder"],
                            "required_tools": ["ui.open_right_panel"],
                            "trigger_examples": ["Открой заявку №17"],
                            "registration_source": "module",
                        }
                    ]
                }

        with patch("services.agent_runtime.mcp_server.DjangoGatewayClient", FakeGatewayClient):
            from services.agent_runtime.mcp_server import build_mcp_server

            server = build_mcp_server()
            skill_contents = asyncio.run(server.read_resource("local-business://skills/workorders.open_right_panel"))
            tool_contents = asyncio.run(server.read_resource("local-business://tools/ui.open_right_panel"))

        skill_payload = json.loads(skill_contents[0].content)
        tool_payload = json.loads(tool_contents[0].content)
        self.assertEqual(skill_payload["id"], "workorders.open_right_panel")
        self.assertNotIn("body", skill_payload)
        self.assertEqual(tool_payload["id"], "ui.open_right_panel")
        self.assertNotIn("headers", tool_payload)


class TestExtractUiCommand(unittest.TestCase):
    """Regression: the runtime used to call _extract_ui_command only on
    a plain dict, but LangChain's @tool decorator wraps the function
    return in a ToolMessage whose payload is a stringified dict in
    .content (or .artifact when response_format is set). Without the
    unwrap, ui.open_right_panel calls succeeded against the gateway
    but produced empty ui_commands and the user-facing chat claimed
    success while the right sidebar never opened.
    """

    def _import(self):
        from services.agent_runtime.graph import _extract_ui_command
        return _extract_ui_command

    def test_extracts_from_raw_dict(self):
        extract = self._import()
        result = {
            "ok": True,
            "tool": "ui.open_right_panel",
            "result": {
                "status": "ok",
                "ui_command": {
                    "type": "open_right_panel",
                    "source_code": "workorders",
                    "object_type": "workorder",
                    "object_id": "4",
                    "htmx_url": "/workorders/4/panel/",
                },
            },
        }
        cmd = extract(result)
        self.assertEqual(cmd["type"], "open_right_panel")
        self.assertEqual(cmd["object_id"], "4")
        self.assertEqual(cmd["htmx_url"], "/workorders/4/panel/")

    def test_extracts_from_tool_message_artifact(self):
        extract = self._import()
        from langchain_core.messages import ToolMessage

        original = {
            "ok": True,
            "tool": "ui.open_right_panel",
            "result": {
                "ui_command": {
                    "type": "open_right_panel",
                    "source_code": "waiting_list",
                    "object_type": "waiting_list_entry",
                    "object_id": "12",
                    "htmx_url": "/waiting-list/12/panel/",
                },
            },
        }
        msg = ToolMessage(
            content="ignored-by-extractor",
            tool_call_id="call-1",
            artifact=original,
        )
        cmd = extract(msg)
        self.assertEqual(cmd["source_code"], "waiting_list")
        self.assertEqual(cmd["object_type"], "waiting_list_entry")
        self.assertEqual(cmd["object_id"], "12")

    def test_extracts_from_tool_message_content_repr(self):
        """Modern LangChain serialises the dict return via repr() into
        .content (single quotes, not valid JSON). _extract_ui_command
        must accept that shape too."""
        extract = self._import()
        from langchain_core.messages import ToolMessage

        # repr() of a dict uses single quotes
        original_repr = (
            "{'ok': True, 'tool': 'ui.open_right_panel', "
            "'result': {'ui_command': "
            "{'type': 'open_right_panel', 'object_id': '7'}}}"
        )
        msg = ToolMessage(
            content=original_repr,
            tool_call_id="call-1",
        )
        cmd = extract(msg)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["type"], "open_right_panel")
        self.assertEqual(cmd["object_id"], "7")

    def test_extracts_from_tool_message_content_json(self):
        """Some LangChain versions use json.dumps (double quotes) in
        .content. _extract_ui_command must accept that shape too."""
        extract = self._import()
        from langchain_core.messages import ToolMessage

        original_json = json.dumps({
            "ok": True,
            "result": {
                "ui_command": {
                    "type": "open_right_panel",
                    "object_id": "9",
                },
            },
        })
        msg = ToolMessage(content=original_json, tool_call_id="call-1")
        cmd = extract(msg)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["object_id"], "9")

    def test_returns_none_for_tool_without_ui_command(self):
        extract = self._import()
        # workorders.list returns work orders, not a ui_command
        from langchain_core.messages import ToolMessage
        msg = ToolMessage(
            content="{'ok': True, 'result': {'orders': []}}",
            tool_call_id="call-1",
        )
        self.assertIsNone(extract(msg))

    def test_returns_none_for_garbage_content(self):
        extract = self._import()
        from langchain_core.messages import ToolMessage
        msg = ToolMessage(content="not a dict", tool_call_id="call-1")
        self.assertIsNone(extract(msg))


class TestChatModelDeadline(unittest.TestCase):
    """Regression: the runtime used to call model_with_tools.invoke
    directly, relying on LangChain's per-request httpx timeout. That
    timeout resets on every chunk in streaming mode, so a slow LLM
    provider that trickles one chunk every 30s could keep a call
    "alive" indefinitely and hang the uvicorn worker. The fix wraps
    the call in a ThreadPoolExecutor with an absolute wall-clock
    deadline. These tests verify that wrapper.
    """

    def _import_helper(self):
        from services.agent_runtime.graph import _invoke_chat_model_with_deadline
        return _invoke_chat_model_with_deadline

    def test_returns_result_when_call_completes_within_deadline(self):
        with patch("services.agent_runtime.graph.LLM_DEADLINE_SECONDS", 2):
            helper = self._import_helper()
            result = helper(lambda msgs: {"assistant": "ok", "msgs": msgs}, [{"role": "user"}])
        self.assertEqual(result["assistant"], "ok")
        self.assertEqual(result["msgs"], [{"role": "user"}])

    def test_raises_runtime_error_when_call_exceeds_deadline(self):
        import time
        with patch("services.agent_runtime.graph.LLM_DEADLINE_SECONDS", 1):
            helper = self._import_helper()
            def slow_call(msgs):
                time.sleep(5)  # far longer than the 1s deadline
                return {"never": "reached"}
            started = time.time()
            with self.assertRaises(RuntimeError) as ctx:
                helper(slow_call, [])
            elapsed = time.time() - started
        # Must raise within deadline + small overhead (not wait 5s).
        self.assertLess(elapsed, 3.0)
        self.assertIn("deadline", str(ctx.exception).lower())

    def test_propagates_exceptions_from_inner_call(self):
        with patch("services.agent_runtime.graph.LLM_DEADLINE_SECONDS", 5):
            helper = self._import_helper()
            def failing(msgs):
                raise ValueError("upstream broke")
            with self.assertRaises(ValueError) as ctx:
                helper(failing, [])
        self.assertEqual(str(ctx.exception), "upstream broke")


if __name__ == "__main__":
    unittest.main()
