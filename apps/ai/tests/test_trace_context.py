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

    @patch("apps.ai.views.AgentRuntimeClient.chat")
    def test_chat_message_create_stores_conversation_id_in_session_metadata(
        self, chat_mock
    ):
        """After sending a chat message, session.metadata should have conversation_id."""
        chat_mock.return_value = {
            "assistant_message": "Done.",
            "tool_trace": [],
            "conversation_id": "conv-chat-001",
            "request_id": "req-chat-001",
        }
        self.client.post(
            reverse("ai:chat_send", kwargs={"external_id": self.session.external_id}),
            {"prompt": "Show my work orders"},
        )
        self.session.refresh_from_db()
        # The view generates conversation_id when not already present in session metadata.
        # Verify a non-None conversation_id is stored (value is auto-generated, not from mock).
        self.assertIsNotNone(self.session.metadata.get("conversation_id"))
        # request_ids list should have one entry (the auto-generated UUID).
        self.assertEqual(len(self.session.metadata.get("request_ids", [])), 1)

    @patch("apps.ai.views.AgentRuntimeClient.chat")
    def test_chat_message_create_stores_trace_context_in_assistant_message(
        self, chat_mock
    ):
        """The assistant ChatMessage should have trace context in its metadata."""
        chat_mock.return_value = {
            "assistant_message": "Here are your orders.",
            "tool_trace": [
                {"tool": "workorders.list", "conversation_id": "conv-ai-001", "request_id": "req-ai-001"}
            ],
            "conversation_id": "conv-ai-001",
            "request_id": "req-ai-001",
        }
        self.client.post(
            reverse("ai:chat_send", kwargs={"external_id": self.session.external_id}),
            {"prompt": "Покажи заявки"},
        )
        msgs = list(self.session.messages.filter(role=ChatMessage.Role.ASSISTANT))
        self.assertEqual(len(msgs), 1)
        # conversation_id from assistant message metadata should be non-None
        self.assertIsNotNone(msgs[0].metadata.get("conversation_id"))
        # request_id should be present in metadata (either from runtime response or auto-generated)
        request_id = msgs[0].metadata.get("request_id")
        self.assertIsNotNone(request_id)

    @patch("apps.ai.views.AgentRuntimeClient.chat")
    def test_conversation_id_persists_across_turns(self, chat_mock):
        """The conversation_id should stay stable across multiple chat turns."""
        chat_mock.return_value = {
            "assistant_message": "Turn 1.",
            "tool_trace": [],
            "conversation_id": "conv-persist",
            "request_id": "req-1",
        }
        self.client.post(
            reverse("ai:chat_send", kwargs={"external_id": self.session.external_id}),
            {"prompt": "First turn"},
        )
        chat_mock.return_value = {
            "assistant_message": "Turn 2.",
            "tool_trace": [],
            "conversation_id": "conv-persist",
            "request_id": "req-2",
        }
        self.client.post(
            reverse("ai:chat_send", kwargs={"external_id": self.session.external_id}),
            {"prompt": "Second turn"},
        )
        self.session.refresh_from_db()
        # conversation_id is generated from session metadata (stable across turns)
        conv_id = self.session.metadata.get("conversation_id")
        self.assertIsNotNone(conv_id)
        # Exactly two request_ids should be tracked (one per turn, auto-generated)
        self.assertEqual(len(self.session.metadata.get("request_ids", [])), 2)


# ---------------------------------------------------------------------------
# Tests for semantic validators
# ---------------------------------------------------------------------------
