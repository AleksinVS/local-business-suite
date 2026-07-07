"""Тесты видимости tool-сообщений в истории чата."""
from apps.ai.tests._common import *  # noqa: F401,F403


class ChatToolMessageVisibilityTests(TestCase):
    """Tool execution feedback ('Tool X executed successfully.') must not
    be rendered in the user-facing chat. The TOOL ChatMessage rows are
    still kept in the DB so the runtime can read them via
    serialize_session_history and feed them to the LLM as part of
    multi-turn tool-using conversation context.
    """
    databases = RUNTIME_DATABASES

    TOOL_CONTENT = "Tool workorders.list executed successfully."
    TOOL_NAME = "workorders.list"

    def setUp(self):
        self.user = User.objects.create_user(username="chat-tool-user", password="pass")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="Tool chat")
        # One full conversation turn: user → tool (hidden) → assistant.
        ChatMessage.objects.create(
            session=self.session, role=ChatMessage.Role.USER,
            content="Покажи список нарядов",
        )
        ChatMessage.objects.create(
            session=self.session, role=ChatMessage.Role.TOOL,
            tool_name=self.TOOL_NAME, content=self.TOOL_CONTENT,
        )
        ChatMessage.objects.create(
            session=self.session, role=ChatMessage.Role.ASSISTANT,
            content="Вот 7 активных нарядов…",
        )

    def test_chat_detail_hides_tool_messages(self):
        response = self.client.get(
            reverse("ai:chat_detail", kwargs={"external_id": self.session.external_id})
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        # Tool content must not appear in the user-facing HTML.
        self.assertNotIn(self.TOOL_CONTENT, body)
        # The old yellow tool badge class is gone.
        self.assertNotIn("bg-amber-100", body)
        # Tool name must not appear as a visible label either.
        self.assertNotIn("workorders.list", body)
        # But the user and assistant messages do appear.
        self.assertIn("Покажи список нарядов", body)
        self.assertIn("Вот 7 активных нарядов", body)
        # The TOOL row is still in the DB.
        self.assertEqual(
            ChatMessage.objects.filter(
                session=self.session, role=ChatMessage.Role.TOOL
            ).count(),
            1,
        )

    def test_sidebar_summary_skips_tool_messages(self):
        """The condensed sidebar summary that the runtime uses as
        LLM context for new turns must not include 'Инструмент: Tool
        X executed successfully.' lines. Only user/assistant lines
        should be summarised."""
        from ..services import _build_sidebar_summary_text

        sidebar_session = ChatSession.objects.create(
            user=self.user,
            channel=ChatSession.Channel.SIDEBAR,
            title="Summary test",
        )
        ChatMessage.objects.create(
            session=sidebar_session, role=ChatMessage.Role.USER,
            content="Вопрос",
        )
        ChatMessage.objects.create(
            session=sidebar_session, role=ChatMessage.Role.TOOL,
            tool_name="workorders.list", content="Tool workorders.list executed successfully.",
        )
        ChatMessage.objects.create(
            session=sidebar_session, role=ChatMessage.Role.ASSISTANT,
            content="Ответ",
        )

        summary = _build_sidebar_summary_text(list(sidebar_session.messages.all()))
        self.assertIn("Пользователь: Вопрос", summary)
        self.assertIn("Ассистент: Ответ", summary)
        self.assertNotIn("Инструмент", summary)
        self.assertNotIn("executed successfully", summary)
