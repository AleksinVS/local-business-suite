"""Тесты trace-контекста канонического prepare/run пути чата."""
import json
from unittest.mock import patch

import pytest

from apps.ai.tests._common import *  # noqa: F401,F403


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="test-ai-token")
@pytest.mark.integration
class ChatViewTraceContextTests(TestCase):
    databases = RUNTIME_DATABASES

    def setUp(self):
        self.user = User.objects.create_user(username="chat-trace-user", password="pass")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user)
        self.turn_number = 0

    def _run_turn(self, stream_mock, prompt, assistant_text):
        self.turn_number += 1
        run_id = f"trace-run-{self.turn_number}"
        stream_mock.return_value = iter([
            f'data: {{"type":"RUN_STARTED","runId":"{run_id}"}}\n\n',
            'data: {"type":"TEXT_MESSAGE_START","messageId":"assistant"}\n\n',
            f'data: {{"type":"TEXT_MESSAGE_CONTENT","messageId":"assistant","delta":"{assistant_text}"}}\n\n',
            'data: {"type":"TEXT_MESSAGE_END","messageId":"assistant"}\n\n',
            f'data: {{"type":"RUN_FINISHED","runId":"{run_id}"}}\n\n',
        ])
        prepared = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": self.session.external_id}),
            {"run_id": run_id, "prompt": prompt},
        )
        self.assertEqual(prepared.status_code, 201)
        run = self.client.post(
            reverse("ai:chat_run", kwargs={"external_id": self.session.external_id}),
            data=json.dumps({"threadId": str(self.session.external_id), "runId": run_id}),
            content_type="application/json",
        )
        b"".join(run.streaming_content)
        return prepared.json()["message_id"]

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_canonical_run_stores_conversation_id_in_session_metadata(self, stream_mock):
        self._run_turn(stream_mock, "Show my work orders", "Done.")
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.metadata.get("conversation_id"))
        self.assertEqual(len(self.session.metadata.get("request_ids", [])), 1)

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_canonical_run_stores_trace_context_in_assistant_message(self, stream_mock):
        self._run_turn(stream_mock, "Покажи заявки", "Here are your orders.")
        assistant = self.session.messages.get(role=ChatMessage.Role.ASSISTANT)
        self.assertIsNotNone(assistant.metadata.get("conversation_id"))
        self.assertIsNotNone(assistant.metadata.get("request_id"))

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_conversation_id_persists_across_turns(self, stream_mock):
        self._run_turn(stream_mock, "First turn", "Turn 1.")
        self.session.refresh_from_db()
        first_conv = self.session.metadata.get("conversation_id")
        self._run_turn(stream_mock, "Second turn", "Turn 2.")
        self.session.refresh_from_db()
        self.assertEqual(self.session.metadata.get("conversation_id"), first_conv)
        self.assertEqual(len(self.session.metadata.get("request_ids", [])), 2)


# ---------------------------------------------------------------------------
# Tests for semantic validators
# ---------------------------------------------------------------------------
