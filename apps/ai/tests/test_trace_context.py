"""Тесты trace-контекста запроса чата."""
from apps.ai.tests._common import *  # noqa: F401,F403


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="test-ai-token")
class ChatViewTraceContextTests(TestCase):
    databases = RUNTIME_DATABASES
    """Verify that AIChatMessageCreateView generates and stores trace context."""

    def setUp(self):
        self.user = User.objects.create_user(username="chat-trace-user", password="pass")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user)

    def _run_turn(self, stream_mock, prompt, assistant_text):
        """Полный ход диалога в streaming-only архитектуре: /send/ (AJAX)
        сохраняет сообщение пользователя и биндит request-контекст, а
        /stream/ (SSE) отдаёт и сохраняет ответ ассистента вместе с
        trace-контекстом сессии. Возвращает id пользовательского сообщения."""
        stream_mock.return_value = [
            f'data: {{"content": "{assistant_text}"}}',
            "data: [DONE]",
        ]
        send = self.client.post(
            reverse("ai:chat_send", kwargs={"external_id": self.session.external_id}),
            {"prompt": prompt},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        msg_id = send.json()["message_id"]
        stream = self.client.post(
            reverse("ai:chat_stream", kwargs={"external_id": self.session.external_id}),
            data=json.dumps({"msg_id": msg_id}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        b"".join(stream.streaming_content)  # прогоняем генератор, чтобы отработали DB-записи
        return msg_id

    @patch("apps.ai.views.AgentRuntimeClient.chat_stream")
    def test_chat_stream_stores_conversation_id_in_session_metadata(self, stream_mock):
        """После полного хода (send+stream) session.metadata несёт conversation_id."""
        self._run_turn(stream_mock, "Show my work orders", "Done.")
        self.session.refresh_from_db()
        # conversation_id генерируется и сохраняется на сессии (значение
        # автогенерируется, стриминговый путь пишет его в session.metadata).
        self.assertIsNotNone(self.session.metadata.get("conversation_id"))
        # ровно один request_id на ход (стриминговый запрос)
        self.assertEqual(len(self.session.metadata.get("request_ids", [])), 1)

    @patch("apps.ai.views.AgentRuntimeClient.chat_stream")
    def test_chat_stream_stores_trace_context_in_assistant_message(self, stream_mock):
        """Ассистентское сообщение несёт trace-контекст в metadata."""
        self._run_turn(stream_mock, "Покажи заявки", "Here are your orders.")
        msgs = list(self.session.messages.filter(role=ChatMessage.Role.ASSISTANT))
        self.assertEqual(len(msgs), 1)
        self.assertIsNotNone(msgs[0].metadata.get("conversation_id"))
        self.assertIsNotNone(msgs[0].metadata.get("request_id"))

    @patch("apps.ai.views.AgentRuntimeClient.chat_stream")
    def test_conversation_id_persists_across_turns(self, stream_mock):
        """conversation_id стабилен между ходами; request_ids накапливаются."""
        self._run_turn(stream_mock, "First turn", "Turn 1.")
        self.session.refresh_from_db()
        first_conv = self.session.metadata.get("conversation_id")
        self._run_turn(stream_mock, "Second turn", "Turn 2.")
        self.session.refresh_from_db()
        conv_id = self.session.metadata.get("conversation_id")
        self.assertIsNotNone(conv_id)
        # conversation_id, записанный на первом ходе, переиспользуется на втором
        self.assertEqual(conv_id, first_conv)
        # ровно два request_id (по одному стриминговому запросу на ход)
        self.assertEqual(len(self.session.metadata.get("request_ids", [])), 2)


# ---------------------------------------------------------------------------
# Tests for semantic validators
# ---------------------------------------------------------------------------
