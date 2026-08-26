"""Тесты представлений AI-чата, стриминга и прав доступа."""
import threading

import pytest

from django.db import close_old_connections
from django.test import Client, TransactionTestCase

from apps.ai.tests._common import *  # noqa: F401,F403
from apps.ai.models import ChatRun


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="test-ai-token")
@pytest.mark.integration
class AIViewsTests(TestCase):
    databases = RUNTIME_DATABASES
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(username="manager-ai", password="pass")
        cls.customer = User.objects.create_user(username="customer-ai", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        cls.manager.groups.add(manager_group)
        cls.customer.groups.add(customer_group)
        cls.department = Department.objects.create(name="Стационар")
        cls.manager.department = cls.department
        cls.customer.department = cls.department
        cls.manager.save(update_fields=["department"])
        cls.customer.save(update_fields=["department"])
        cls.board, _created = Board.objects.get_or_create(
            slug="main",
            defaults={"title": "Test Board"},
        )
        cls.board.allowed_groups.add(manager_group, customer_group)
        cls.customer_workorder = WorkOrder.objects.create(
            title="Сломан светильник",
            description="Нужна замена лампы",
            department=cls.department,
            author=cls.customer,
            board=cls.board,
            status=WorkOrderStatus.NEW,
        )

    def test_manager_can_open_ai_hub(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("ai:hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ИИ-центр")
        self.assertContains(response, "Список заявок")
        self.assertContains(response, "workorders.list")

    def test_customer_cannot_open_ai_hub(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("ai:hub"))
        self.assertEqual(response.status_code, 403)

    def test_staff_flag_alone_cannot_open_ai_hub(self):
        staff = User.objects.create_user(username="staff-only-ai", password="pass", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("ai:hub"))
        self.assertEqual(response.status_code, 403)

    def test_copilotkit_config_is_feature_flagged(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("ai:copilotkit_config"))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["enabled"])

    def test_copilotkit_config_returns_signed_actor_payload(self):
        from ..views import sign_copilotkit_actor_payload

        self.client.force_login(self.customer)
        with self.settings(
            LOCAL_BUSINESS_COPILOTKIT_ENABLED=True,
            LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL="/copilotkit",
            LOCAL_BUSINESS_COPILOTKIT_AGENT_ID="local_business",
        ):
            response = self.client.get(reverse("ai:copilotkit_config"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        forwarded = payload["forwarded_props"]
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["runtime_url"], "/copilotkit")
        self.assertEqual(payload["agent_id"], "local_business")
        self.assertEqual(payload["driver"], "copilotkit")
        self.assertEqual(forwarded["session_id"], payload["thread_id"])
        self.assertEqual(forwarded["ui_driver"], "copilotkit")
        self.assertEqual(forwarded["actor"]["user_id"], self.customer.id)
        self.assertEqual(forwarded["actor"]["source"], "django-copilotkit")
        self.assertEqual(forwarded["signature"], sign_copilotkit_actor_payload(forwarded))
        self.assertTrue(
            ChatSession.objects.filter(
                user=self.customer,
                external_id=forwarded["session_id"],
                channel=ChatSession.Channel.SIDEBAR,
            ).exists()
        )

    def test_default_ai_ui_driver_is_native(self):
        self.assertEqual(configured_ai_ui_driver(), "native")

    def test_legacy_copilotkit_flag_still_enables_copilotkit_when_driver_is_implicit(self):
        with self.settings(LOCAL_BUSINESS_COPILOTKIT_ENABLED=True):
            self.assertEqual(configured_ai_ui_driver(), "copilotkit")

    def test_ai_ui_new_session_creates_clean_copilotkit_thread(self):
        from ..views import sign_copilotkit_actor_payload

        self.client.force_login(self.customer)
        existing = ChatSession.objects.create(
            user=self.customer,
            channel=ChatSession.Channel.SIDEBAR,
            title="Старый боковой чат",
            metadata={"surface": "sidebar", "model_id": "test-model"},
        )
        ChatMessage.objects.create(
            session=existing,
            role=ChatMessage.Role.USER,
            content="Старое сообщение",
        )

        with self.settings(
            LOCAL_BUSINESS_AI_UI_DRIVER="copilotkit",
            LOCAL_BUSINESS_AI_UI_DRIVER_EXPLICIT=True,
            LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL="/copilotkit",
            LOCAL_BUSINESS_COPILOTKIT_AGENT_ID="local_business",
        ):
            response = self.client.post(
                reverse("ai:ui_session_new"),
                data="{}",
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        forwarded = payload["forwarded_props"]
        existing.refresh_from_db()
        new_session = ChatSession.objects.get(external_id=payload["thread_id"])
        self.assertEqual(existing.status, ChatSession.Status.ARCHIVED)
        self.assertEqual(new_session.status, ChatSession.Status.ACTIVE)
        self.assertEqual(new_session.channel, ChatSession.Channel.SIDEBAR)
        self.assertEqual(new_session.metadata["model_id"], "test-model")
        self.assertEqual(new_session.metadata["previous_sidebar_session_id"], str(existing.external_id))
        self.assertEqual(new_session.messages.count(), 0)
        self.assertNotEqual(str(existing.external_id), payload["thread_id"])
        self.assertEqual(forwarded["session_id"], payload["thread_id"])
        self.assertEqual(forwarded["ui_driver"], "copilotkit")
        self.assertEqual(forwarded["signature"], sign_copilotkit_actor_payload(forwarded))

    def test_native_ai_ui_config_keeps_actor_payload_server_side(self):
        from services.agent_runtime.protocols.common import AI_CHAT_UNAVAILABLE_MESSAGE

        self.client.force_login(self.customer)
        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native"):
            response = self.client.get(reverse("ai:ui_config"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["driver"], "native")
        self.assertNotIn("forwarded_props", payload)
        session = ChatSession.objects.get(external_id=payload["thread_id"])
        self.assertEqual(
            payload["runtime_url"],
            reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
        )
        self.assertEqual(
            payload["prepare_url"],
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
        )
        self.assertEqual(payload["labels"]["error"], AI_CHAT_UNAVAILABLE_MESSAGE)

    def test_native_ai_ui_config_includes_sidebar_history_models_and_urls(self):
        self.client.force_login(self.customer)
        models = [
            {"id": "test-model", "name": "Test Model", "default": False},
            {"id": "fallback-model", "name": "Fallback Model", "default": True},
        ]
        session = ChatSession.objects.create(
            user=self.customer,
            channel=ChatSession.Channel.SIDEBAR,
            title="Боковой чат",
            metadata={"surface": "sidebar", "model_id": "test-model"},
        )
        ChatMessage.objects.create(session=session, role=ChatMessage.Role.USER, content="Старый вопрос")
        ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.ASSISTANT,
            content="Старый ответ",
            metadata={"error": True},
        )

        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native", LOCAL_BUSINESS_AI_MODELS=models):
            response = self.client.get(reverse("ai:ui_config"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["thread_id"], str(session.external_id))
        self.assertEqual(payload["current_model_id"], "test-model")
        self.assertEqual(payload["messages"][0]["role"], ChatMessage.Role.USER)
        self.assertEqual(payload["messages"][0]["content"], "Старый вопрос")
        self.assertEqual(payload["messages"][1]["content"], "Старый ответ")
        self.assertTrue(payload["messages"][1]["error"])
        self.assertRegex(payload["messages"][0]["created_at_display"], r"^\d{2}:\d{2}$")
        self.assertEqual(payload["models"][0]["id"], "test-model")
        self.assertTrue(payload["models"][0]["selected"])
        self.assertEqual(
            payload["urls"]["model_update_url"],
            reverse("ai:chat_update_model", kwargs={"external_id": session.external_id}),
        )
        self.assertEqual(payload["urls"]["clear_session_url"], reverse("ai:ui_session_clear"))
        self.assertEqual(
            payload["urls"]["full_chat_url"],
            reverse("ai:chat_detail", kwargs={"external_id": session.external_id}),
        )

    def test_native_sidebar_config_exposes_oldest_prepared_run_for_recovery(self):
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, channel=ChatSession.Channel.SIDEBAR)
        first = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "recover-first", "prompt": "Первый вопрос", "surface": "sidebar"},
        )
        second = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "recover-second", "prompt": "Второй вопрос", "surface": "sidebar"},
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native"):
            payload = self.client.get(reverse("ai:ui_config")).json()
        self.assertEqual(payload["recoverable_run"]["run_id"], "recover-first")
        self.assertEqual(payload["recoverable_run"]["status"], "prepared")

    def test_native_full_page_config_exposes_prepared_run_but_not_running_run(self):
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, channel=ChatSession.Channel.INTERNAL)
        prepared = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "recover-full", "prompt": "Продолжить", "surface": "full_page"},
        )
        self.assertEqual(prepared.status_code, 201)
        payload = self.client.get(
            reverse("ai:chat_config", kwargs={"external_id": session.external_id})
        ).json()
        self.assertEqual(payload["recoverable_run"]["run_id"], "recover-full")
        ChatRun.objects.filter(session=session, run_id="recover-full").update(status=ChatRun.Status.RUNNING)
        payload = self.client.get(
            reverse("ai:chat_config", kwargs={"external_id": session.external_id})
        ).json()
        self.assertIsNone(payload["recoverable_run"])

    def test_native_ai_ui_new_session_returns_native_thread(self):
        self.client.force_login(self.customer)
        existing = ChatSession.objects.create(
            user=self.customer,
            channel=ChatSession.Channel.SIDEBAR,
            title="Старый native чат",
            metadata={"surface": "sidebar", "model_id": "test-model"},
        )
        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native"):
            response = self.client.post(
                reverse("ai:ui_session_new"),
                data="{}",
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        existing.refresh_from_db()
        new_session = ChatSession.objects.get(external_id=payload["thread_id"])
        self.assertEqual(existing.status, ChatSession.Status.ARCHIVED)
        self.assertEqual(new_session.channel, ChatSession.Channel.SIDEBAR)
        self.assertEqual(new_session.metadata["model_id"], "test-model")
        self.assertEqual(payload["driver"], "native")
        self.assertEqual(
            payload["runtime_url"],
            reverse("ai:chat_run", kwargs={"external_id": new_session.external_id}),
        )
        self.assertNotIn("forwarded_props", payload)

    def test_native_ai_ui_clear_session_returns_clean_config(self):
        self.client.force_login(self.customer)
        models = [{"id": "test-model", "name": "Test Model", "default": True}]
        session = ChatSession.objects.create(
            user=self.customer,
            channel=ChatSession.Channel.SIDEBAR,
            title="Боковой чат",
            metadata={"surface": "sidebar", "model_id": "test-model", "sidebar_summary": {"text": "старое резюме"}},
            last_message_at=timezone.now(),
        )
        ChatMessage.objects.create(session=session, role=ChatMessage.Role.USER, content="Старый вопрос")
        ChatMessage.objects.create(session=session, role=ChatMessage.Role.ASSISTANT, content="Старый ответ")

        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native", LOCAL_BUSINESS_AI_MODELS=models):
            response = self.client.post(
                reverse("ai:ui_session_clear"),
                data="{}",
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        new_session = ChatSession.objects.get(external_id=payload["thread_id"])
        self.assertNotEqual(new_session.external_id, session.external_id)
        self.assertEqual(payload["messages"], [])
        self.assertEqual(payload["current_model_id"], "test-model")
        session.refresh_from_db()
        self.assertEqual(session.status, ChatSession.Status.ARCHIVED)
        self.assertEqual(ChatMessage.objects.filter(session=session).count(), 2)
        self.assertEqual(new_session.channel, ChatSession.Channel.SIDEBAR)
        self.assertEqual(new_session.metadata.get("model_id"), "test-model")
        self.assertEqual(new_session.metadata.get("previous_sidebar_session_id"), str(session.external_id))

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_native_ai_ui_run_uses_owned_canonical_session(self, stream_mock):
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, channel=ChatSession.Channel.SIDEBAR)
        stream_mock.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-1"}\n\n',
            'data: {"type":"TEXT_MESSAGE_START","messageId":"msg"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg","delta":"Ответ"}\n\n',
            'data: {"type":"TEXT_MESSAGE_END","messageId":"msg"}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-1"}\n\n',
        ])
        prepared = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "run-1", "prompt": "Проверка", "surface": "sidebar"},
        )
        self.assertEqual(prepared.status_code, 201)
        response = self.client.post(
            reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
            data=json.dumps({"threadId": str(session.external_id), "runId": "run-1"}),
            content_type="application/json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("RUN_FINISHED", body)
        stream_mock.assert_called_once()
        payload = stream_mock.call_args.args[0]
        self.assertEqual(payload["threadId"], str(session.external_id))
        self.assertEqual(payload["forwardedProps"]["actor"]["user_id"], self.customer.id)

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_native_ai_ui_run_persists_assistant_message_from_agui_stream(self, stream_mock):
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, channel=ChatSession.Channel.SIDEBAR)
        stream_mock.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-2"}\n\n',
            'data: {"type":"TEXT_MESSAGE_START","messageId":"msg"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg","delta":"Ответ"}\n\n',
            'data: {"type":"TEXT_MESSAGE_END","messageId":"msg"}\n\n',
            'data: {"type":"TOOL_CALL_START","toolCallId":"tool-1","toolCallName":"workorders.open_right_panel"}\n\n',
            'data: {"type":"TOOL_CALL_END","toolCallId":"tool-1"}\n\n',
            'data: {"type":"STATE_DELTA","delta":[{"op":"replace","path":"/localBusiness/uiCommands","value":[{"type":"open_right_panel","htmx_url":"/workorders/1/","target":"#global-right-panel-content"}]}]}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-2"}\n\n',
        ])
        prepared = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "run-2", "prompt": "Открой заявку", "surface": "sidebar"},
        )
        self.assertEqual(prepared.status_code, 201)
        response = self.client.post(
            reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
            data=json.dumps({"threadId": str(session.external_id), "runId": "run-2"}),
            content_type="application/json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("TEXT_MESSAGE_CONTENT", body)
        assistant = ChatMessage.objects.get(session=session, role=ChatMessage.Role.ASSISTANT)
        self.assertEqual(assistant.content, "Ответ")
        self.assertEqual(assistant.metadata["tool_trace"][0]["tool"], "workorders.open_right_panel")
        self.assertEqual(assistant.metadata["ui_commands"][0]["type"], "open_right_panel")
    def test_tool_gateway_rejects_invalid_token(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id},
                    "payload": {"status": WorkOrderStatus.NEW},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_tool_gateway_rejects_actor_mismatch_for_existing_session(self):
        session = ChatSession.objects.create(user=self.customer)
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.manager.id, "channel": "internal"},
                    "payload": {"status": WorkOrderStatus.NEW},
                    "session_id": str(session.external_id),
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 403)

    def test_tool_gateway_rejects_username_mismatch(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {
                        "user_id": self.customer.id,
                        "username": self.manager.username,
                        "channel": "internal",
                    },
                    "payload": {"status": WorkOrderStatus.NEW},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("не совпадает", response.json()["error"])

    def test_tool_gateway_rejects_invalid_actor_user_id(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": "not-a-number", "channel": "internal"},
                    "payload": {"status": WorkOrderStatus.NEW},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("некорректный user_id", response.json()["error"])

    def test_tool_gateway_rejects_wrong_token(self):
        # Непустой, но неверный токен шлюза должен отклоняться так же, как
        # отсутствующий (hmac.compare_digest, apps/ai/views.py:gateway_token_is_valid).
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {"status": WorkOrderStatus.NEW},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="wrong-token",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_tool_gateway_rejects_nonexistent_user_id(self):
        # Валидный токен, но user_id, которого нет в базе: actor не должен
        # быть привязан к несуществующему пользователю (validate_gateway_actor).
        missing_user_id = self.customer.id + self.manager.id + 100000
        self.assertFalse(User.objects.filter(pk=missing_user_id).exists())
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": missing_user_id, "channel": "internal"},
                    "payload": {"status": WorkOrderStatus.NEW},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("не найден", response.json()["error"])
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_tool_gateway_rejects_inactive_user(self):
        # Валидный токен и существующий, но деактивированный пользователь:
        # gateway обязан отклонить (User.objects.filter(is_active=True)).
        inactive_user = User.objects.create_user(
            username="inactive-ai", password="pass", is_active=False
        )
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": inactive_user.id, "channel": "internal"},
                    "payload": {"status": WorkOrderStatus.NEW},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("не найден", response.json()["error"])
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_list_workorders_tool_returns_visible_items_and_logs_action(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal", "user_prompt": "Покажи новые заявки"},
                    "payload": {"status": WorkOrderStatus.NEW, "limit": 10},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool"], "workorders.list")
        self.assertEqual(payload["errors"], [])
        self.assertIn("meta", payload)
        self.assertEqual(len(payload["result"]["items"]), 1)
        self.assertEqual(payload["result"]["items"][0]["number"], self.customer_workorder.number)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(ChatSession.objects.count(), 1)

    def test_open_right_panel_tool_returns_ui_command_for_visible_workorder(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "ui.open_right_panel"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {
                        "source_code": "workorders",
                        "object_type": "workorder",
                        "object_id": str(self.customer_workorder.pk),
                        "mode": "view",
                    },
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        command = payload["result"]["ui_command"]
        self.assertEqual(command["type"], "open_right_panel")
        self.assertEqual(command["source_code"], "workorders")
        self.assertEqual(command["object_id"], str(self.customer_workorder.pk))
        self.assertEqual(command["target"], "#global-right-panel-content")
        self.assertTrue(command["htmx_url"].startswith("/"))

    def test_open_right_panel_tool_denies_foreign_workorder(self):
        private_group, _ = Group.objects.get_or_create(name="private-ai-panel")
        private_board = Board.objects.create(title="Private Board", slug="private-ai-panel")
        private_board.allowed_groups.add(private_group)
        foreign = WorkOrder.objects.create(
            title="Чужая заявка",
            description="Недоступна",
            department=self.department,
            author=self.manager,
            board=private_board,
            status=WorkOrderStatus.NEW,
        )
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "ui.open_right_panel"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {
                        "source_code": "workorders",
                        "object_type": "workorder",
                        "object_id": str(foreign.pk),
                    },
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["result"])

    def test_access_explain_and_editor_are_read_only_audited_and_do_not_create_pending_actions(self):
        before_pending = PendingAction.objects.count()

        explain_response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "access.users.explain"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id, "channel": "internal"},
                "payload": {"user_id": self.customer.id},
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(explain_response.status_code, 200)
        self.assertTrue(explain_response.json()["ok"])
        self.assertEqual(PendingAction.objects.count(), before_pending)
        self.assertEqual(
            AgentActionLog.objects.filter(tool_code="access.users.explain").latest("id").status,
            AgentActionLog.Status.SUCCEEDED,
        )

        denied_explain = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "access.users.explain"}),
            data=json.dumps({
                "actor": {"user_id": self.customer.id, "channel": "internal"},
                "payload": {"user_id": self.manager.id},
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(denied_explain.status_code, 400)
        self.assertEqual(
            AgentActionLog.objects.filter(tool_code="access.users.explain").latest("id").status,
            AgentActionLog.Status.DENIED,
        )
        self.assertEqual(PendingAction.objects.count(), before_pending)

        editor_response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "access.open_editor"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id, "channel": "internal"},
                "payload": {"target_type": "user", "target_id": str(self.customer.id)},
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(editor_response.status_code, 200)
        self.assertTrue(editor_response.json()["ok"])
        self.assertEqual(PendingAction.objects.count(), before_pending)
        self.assertEqual(
            AgentActionLog.objects.filter(tool_code="access.open_editor").latest("id").status,
            AgentActionLog.Status.SUCCEEDED,
        )

        denied_editor = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "access.open_editor"}),
            data=json.dumps({
                "actor": {"user_id": self.customer.id, "channel": "internal"},
                "payload": {"target_type": "user", "target_id": str(self.manager.id)},
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(denied_editor.status_code, 400)
        self.assertEqual(
            AgentActionLog.objects.filter(tool_code="access.open_editor").latest("id").status,
            AgentActionLog.Status.DENIED,
        )
        self.assertEqual(PendingAction.objects.count(), before_pending)

    def test_generic_right_panel_rejects_edit_mode_at_gateway_boundary(self):
        root = User.objects.create_superuser(username="access-generic-root", password="pass")
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "ui.open_right_panel"}),
            data=json.dumps({
                "actor": {"user_id": root.id, "channel": "internal"},
                "payload": {
                    "source_code": "settings_center",
                    "object_type": "user",
                    "object_id": str(self.customer.id),
                    "mode": "edit",
                },
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("только режим просмотра", response.json()["errors"][0])
        self.assertEqual(
            AgentActionLog.objects.filter(tool_code="ui.open_right_panel").latest("id").status,
            AgentActionLog.Status.FAILED,
        )
        self.assertFalse(PendingAction.objects.filter(tool_code="ui.open_right_panel").exists())

    def test_skill_catalog_includes_module_skills(self):
        response = self.client.get(
            reverse("ai:skill_catalog"),
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )

        self.assertEqual(response.status_code, 200)
        skill_ids = {item["id"] for item in response.json()["skills"]}
        self.assertIn("ai.skill_creator", skill_ids)
        self.assertIn("workorders.open_right_panel", skill_ids)
        self.assertIn("waiting_list.open_right_panel", skill_ids)

    def test_runtime_contract_skill_is_discovered_without_restart(self):
        from ..skills_service import clear_skill_catalog_cache, discover_skills, load_skill_content

        with TemporaryDirectory() as tmpdir:
            runtime_contracts = Path(tmpdir) / "contracts"
            skill_dir = runtime_contracts / "ai" / "skills" / "demo.runtime_skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: demo-runtime-skill",
                        "description: Runtime skill for tests.",
                        "source_code: demo",
                        "object_types: record",
                        "required_tools: ui.open_right_panel",
                        "trigger_examples: Open demo",
                        "---",
                        "Use ui.open_right_panel for demo records.",
                    ]
                ),
                encoding="utf-8",
            )

            with override_settings(RUNTIME_CONTRACTS_DIR=runtime_contracts):
                clear_skill_catalog_cache()
                skill_ids = {item["id"] for item in discover_skills(use_cache=False)}
                body = load_skill_content("demo.runtime_skill")

        self.assertIn("demo.runtime_skill", skill_ids)
        self.assertIn("ui.open_right_panel", body)

    def test_admin_can_create_runtime_skill_after_confirmation(self):
        self.manager.is_superuser = True
        self.manager.save(update_fields=["is_superuser"])

        with TemporaryDirectory() as tmpdir:
            runtime_contracts = Path(tmpdir) / "contracts"
            with override_settings(RUNTIME_CONTRACTS_DIR=runtime_contracts):
                result = execute_tool(
                    tool_code="ai.skills.create_or_update",
                    actor_context={"user_id": self.manager.id, "channel": "internal"},
                    payload={
                        "skill_id": "demo.created_skill",
                        "name": "demo-created-skill",
                        "description": "Creates a narrow demo skill.",
                        "source_code": "demo",
                        "object_types": ["record"],
                        "required_tools": ["ui.open_right_panel"],
                        "trigger_examples": ["Open demo"],
                        "body": "Use ui.open_right_panel only for visible demo records.",
                    },
                    request_id="req-skill-create",
                )
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["meta"]["awaiting_confirmation"])
                confirm = execute_pending_action(
                    token=result["meta"]["pending_action_token"],
                    confirmed=True,
                    actor_context={"user_id": self.manager.id, "channel": "internal"},
                    request_id="req-skill-create-confirm",
                )

                target = runtime_contracts / "ai" / "skills" / "demo.created_skill" / "SKILL.md"
                self.assertTrue(confirm["ok"], confirm)
                self.assertTrue(target.exists())
                self.assertIn("demo-created-skill", target.read_text(encoding="utf-8"))

        action = AgentActionLog.objects.filter(tool_code="ai.skills.create_or_update", status=AgentActionLog.Status.PENDING).first()
        self.assertIsNotNone(action)
        self.assertIn("<SKILL_BODY_REDACTED", json.dumps(action.request_payload))
        self.assertNotIn("visible demo records", json.dumps(action.request_payload))

    def test_processing_cleanup_uses_its_own_lease_and_requires_reconciliation(self):
        pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.customer,
            payload={},
            status=PendingAction.Status.PROCESSING,
            expires_at=timezone.now() - timezone.timedelta(minutes=5),
            processing_started_at=timezone.now(),
            processing_expires_at=timezone.now() + timezone.timedelta(minutes=5),
        )

        call_command("cleanup_expired_ai_actions", verbosity=0)
        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingAction.Status.PROCESSING)

        pending.processing_expires_at = timezone.now() - timezone.timedelta(seconds=1)
        pending.save(update_fields=["processing_expires_at"])
        call_command("cleanup_expired_ai_actions", verbosity=0)
        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingAction.Status.RECONCILIATION_REQUIRED)

    def test_pending_confirmation_requires_actor_identity_at_service_boundary(self):
        pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.customer,
            payload={},
        )

        result = execute_pending_action(
            token=pending.token,
            confirmed=True,
            actor_context={},
        )

        self.assertFalse(result["ok"])
        self.assertIn("идентификатор пользователя", result["errors"][0])

    def test_record_action_recursively_redacts_identity_fields(self):
        from apps.ai.services import record_action

        audit = record_action(
            actor=self.manager,
            tool_code="test.identity-redaction",
            action_kind="read",
            status=AgentActionLog.Status.SUCCEEDED,
            request_payload={
                "id": 41,
                "username": "request-user",
                "nested": [{"email": "request@example.test", "status": "ok"}],
            },
            response_payload={
                "id": 42,
                "author": "response-author",
                "items": ({"assignee": "response-assignee"},),
            },
        )

        audit.refresh_from_db()
        self.assertEqual(audit.status, AgentActionLog.Status.SUCCEEDED)
        self.assertEqual(audit.request_payload["id"], 41)
        self.assertEqual(audit.request_payload["username"], "***")
        self.assertEqual(audit.request_payload["nested"][0]["email"], "***")
        self.assertEqual(audit.request_payload["nested"][0]["status"], "ok")
        self.assertEqual(audit.response_payload["id"], 42)
        self.assertEqual(audit.response_payload["author"], "***")
        self.assertEqual(audit.response_payload["items"][0]["assignee"], "***")

    def test_execute_tool_rejects_confirmed_token_before_dispatch(self):
        with patch("apps.ai.tooling._dispatch_tool") as dispatch:
            with self.assertRaisesMessage(ValidationError, "только через сохранённое ожидающее действие"):
                execute_tool(
                    tool_code="workorders.create",
                    actor_context={"user_id": self.customer.id, "channel": "internal"},
                    payload={
                        "department_id": self.department.id,
                        "subject": "Не должно выполниться",
                        "description": "Невалидное подтверждение",
                    },
                    confirmed_token=uuid.uuid4(),
                )

        dispatch.assert_not_called()
        self.assertFalse(WorkOrder.objects.filter(title="Не должно выполниться").exists())

    def test_execute_tool_rejects_inactive_actor_before_dispatch(self):
        inactive_root = User.objects.create_superuser(username="inactive-ai-root")
        inactive_root.is_active = False
        inactive_root.save(update_fields=["is_active"])

        with patch("apps.ai.tooling._dispatch_tool") as dispatch:
            with self.assertRaisesMessage(PermissionDenied, "отключена"):
                execute_tool(
                    tool_code="access.users.list",
                    actor_context={"user_id": inactive_root.id, "channel": "internal"},
                    payload={},
                )

        dispatch.assert_not_called()

    def test_ai_access_mutation_tools_are_not_registered_or_dispatchable(self):
        from apps.ai.tool_definitions import get_tool_registry

        registry = get_tool_registry()
        self.assertNotIn("access.update_role_permissions", registry)
        self.assertNotIn("access.users.update", registry)
        contract = json.loads(Path("contracts/ai/tools.json").read_text(encoding="utf-8"))
        contract_ids = {item["id"] for item in contract["tools"]}
        self.assertNotIn("access.update_role_permissions", contract_ids)
        self.assertNotIn("access.users.update", contract_ids)
        for tool_code in ("access.update_role_permissions", "access.users.update"):
            with self.subTest(tool_code=tool_code):
                with self.assertRaises(UnknownToolError):
                    execute_tool(
                        tool_code=tool_code,
                        actor_context={"user_id": self.manager.id, "channel": "internal"},
                        payload={"user_id": self.customer.id},
                    )

    def test_removed_access_pending_actions_fail_closed_without_dispatch_or_mutation(self):
        before = {
            "department_id": self.customer.department_id,
            "is_active": self.customer.is_active,
            "groups": set(self.customer.groups.values_list("name", flat=True)),
        }
        for tool_code in ("access.update_role_permissions", "access.users.update"):
            with self.subTest(tool_code=tool_code):
                pending = PendingAction.objects.create(
                    tool_code=tool_code,
                    action_kind="write",
                    actor=self.manager,
                    session=ChatSession.objects.create(user=self.manager),
                    payload={
                        "user_id": self.customer.id,
                        "role_name": "customer",
                        "permissions_map": {"view_analytics": True},
                        "is_active": False,
                        "department_id": self.department.id,
                    },
                    status=PendingAction.Status.PENDING,
                )
                with patch("apps.ai.tooling._dispatch_tool") as dispatch:
                    result = execute_pending_action(
                        token=pending.token,
                        confirmed=True,
                        actor_context={
                            "user_id": self.manager.id,
                            "channel": "internal",
                        },
                    )

                self.assertFalse(result["ok"])
                self.assertIn("no longer available", result["errors"][0])
                dispatch.assert_not_called()
                pending.refresh_from_db()
                self.assertEqual(pending.status, PendingAction.Status.FAILED)
                audit = AgentActionLog.objects.get(
                    tool_code=tool_code,
                    status=AgentActionLog.Status.FAILED,
                )
                self.assertEqual(
                    audit.response_payload["error"],
                    "Tool no longer available.",
                )
                self.customer.refresh_from_db()
                self.assertEqual(self.customer.department_id, before["department_id"])
                self.assertEqual(self.customer.is_active, before["is_active"])
                self.assertEqual(
                    set(self.customer.groups.values_list("name", flat=True)),
                    before["groups"],
                )

    def test_non_admin_cannot_confirm_runtime_skill_creation(self):
        with TemporaryDirectory() as tmpdir:
            runtime_contracts = Path(tmpdir) / "contracts"
            with override_settings(RUNTIME_CONTRACTS_DIR=runtime_contracts):
                result = execute_tool(
                    tool_code="ai.skills.create_or_update",
                    actor_context={"user_id": self.customer.id, "channel": "internal"},
                    payload={
                        "skill_id": "demo.denied_skill",
                        "name": "demo-denied-skill",
                        "description": "Denied demo skill.",
                        "required_tools": ["ui.open_right_panel"],
                        "body": "Use ui.open_right_panel.",
                    },
                )
                confirm = execute_pending_action(
                    token=result["meta"]["pending_action_token"],
                    confirmed=True,
                    actor_context={"user_id": self.customer.id, "channel": "internal"},
                )

                target = runtime_contracts / "ai" / "skills" / "demo.denied_skill" / "SKILL.md"
                self.assertFalse(confirm["ok"])
                self.assertFalse(target.exists())
                self.assertIn("недоступно управление навыками ИИ", confirm["errors"][0])

    def test_runtime_skill_authoring_rejects_unknown_required_tool(self):
        from ..skill_authoring import build_runtime_skill_document

        with self.assertRaises(ValidationError):
            build_runtime_skill_document(
                {
                    "skill_id": "demo.bad_tool",
                    "name": "demo-bad-tool",
                    "description": "Bad tool demo.",
                    "required_tools": ["missing.tool"],
                    "body": "Use a missing tool.",
                }
            )

    def test_workorders_search_tool_uses_memory_source_adapter_index(self):
        self.customer_workorder.description = "Маркер ai-wrapper-workorder-gamma для поиска."
        self.customer_workorder.save(update_fields=["description", "updated_at"])

        with TemporaryDirectory() as tmpdir:
            with self.settings(DATA_DIR=Path(tmpdir) / "data", LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND="disabled"):
                call_command("source_adapter_reconcile", source_code="workorders", target="memory", backend="fulltext", verbosity=0)
                response = self.client.post(
                    reverse("ai:tool_execute", kwargs={"tool_code": "workorders.search"}),
                    data=json.dumps(
                        {
                            "actor": {"user_id": self.manager.id, "channel": "internal"},
                            "payload": {"query": "ai wrapper workorder gamma", "limit": 5},
                        }
                    ),
                    content_type="application/json",
                    HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool"], "workorders.search")
        self.assertEqual(payload["result"]["items"][0]["source_code"], "workorders")

    def test_page_context_update_resolves_workorder_and_recomputes_capabilities(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("ai:page_context_update"),
            data=json.dumps(
                {
                    "schema_version": "1",
                    "window_id": "window-ai-test-1",
                    "page": {"module": "workorders", "view": "board", "path": "/workorders/"},
                    "selection": {
                        "object_type": "workorder",
                        "object_id": str(self.customer_workorder.pk),
                        "source_code": "workorders",
                        "display": "Client supplied title",
                    },
                    "capabilities": {"can_transition": True},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        snapshot = AIWindowContextSnapshot.objects.get(window_id="window-ai-test-1")
        self.assertEqual(snapshot.resolved_summary["selection"]["object_id"], str(self.customer_workorder.pk))
        self.assertEqual(snapshot.resolved_summary["selection"]["title"], self.customer_workorder.title)
        self.assertIn("transition_targets", snapshot.resolved_summary["capabilities"])

    def test_page_context_update_preserves_bounded_repeated_filters(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("ai:page_context_update"),
            data=json.dumps(
                {
                    "schema_version": "1",
                    "window_id": "window-ai-filter-arrays",
                    "page": {"module": "workorders", "view": "board"},
                    "filters": {
                        "department": ["10", "20", "20", "x" * 200, {"nested": "rejected"}],
                        "status": [f"status-{index}" for index in range(25)],
                        "invalid": {"nested": True},
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        snapshot = AIWindowContextSnapshot.objects.get(
            window_id="window-ai-filter-arrays"
        )
        self.assertEqual(
            snapshot.sanitized_envelope["filters"]["department"][:2],
            ["10", "20"],
        )
        self.assertEqual(len(snapshot.sanitized_envelope["filters"]["department"][2]), 120)
        self.assertEqual(
            len(snapshot.sanitized_envelope["filters"]["status"]),
            20,
        )
        self.assertNotIn("invalid", snapshot.sanitized_envelope["filters"])
        self.assertEqual(
            snapshot.resolved_summary["filters"],
            snapshot.sanitized_envelope["filters"],
        )

    def test_page_context_update_requires_valid_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager)
        url = reverse("ai:page_context_update")
        payload = json.dumps(
            {
                "schema_version": "1",
                "window_id": "window-ai-csrf",
                "page": {"module": "workorders", "view": "board"},
                "filters": {"department": [str(self.department.pk)]},
            }
        )

        rejected = csrf_client.post(url, data=payload, content_type="application/json")
        self.assertEqual(rejected.status_code, 403)

        page = csrf_client.get(reverse("workorders:board"))
        self.assertEqual(page.status_code, 200)
        token = csrf_client.cookies["csrftoken"].value
        accepted = csrf_client.post(
            url,
            data=payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 200)

    def test_ai_ui_post_endpoints_reject_missing_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager)

        response = csrf_client.post(
            reverse("ai:ui_session_new"),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_page_context_update_rejects_payload_over_total_limit(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("ai:page_context_update"),
            data=json.dumps(
                {
                    "schema_version": "1",
                    "window_id": "window-ai-too-large",
                    "page": {"module": "workorders", "view": "board"},
                    "filters": {
                        f"filter-{index}": "x" * 120
                        for index in range(180)
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_page_context_update_rejects_foreign_workorder(self):
        private_group, _ = Group.objects.get_or_create(name="private-board-group")
        private_board = Board.objects.create(title="Private Board", slug="private-board-ai")
        private_board.allowed_groups.add(private_group)
        foreign = WorkOrder.objects.create(
            title="Чужая заявка",
            description="Недоступна текущему пользователю",
            department=self.department,
            author=self.manager,
            board=private_board,
            status=WorkOrderStatus.NEW,
        )
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("ai:page_context_update"),
            data=json.dumps(
                {
                    "schema_version": "1",
                    "window_id": "window-ai-test-foreign",
                    "page": {"module": "workorders", "view": "board"},
                    "selection": {
                        "object_type": "workorder",
                        "object_id": str(foreign.pk),
                        "source_code": "workorders",
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_page_context_update_resolves_waiting_list_entry(self):
        # Просмотр листа ожидания требует отдельного capability; авторство
        # разрешает изменение записи, но само по себе не открывает список.
        doctor_group, _created = Group.objects.get_or_create(name="doctor")
        self.customer.groups.add(doctor_group)
        entry = create_entry(
            author=self.customer,
            patient_name="Контекстный Пациент",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("ai:page_context_update"),
            data=json.dumps(
                {
                    "schema_version": "1",
                    "window_id": "window-waiting-list-test",
                    "page": {"module": "waiting_list", "view": "detail"},
                    "selection": {
                        "object_type": "waiting_list_entry",
                        "object_id": str(entry.pk),
                        "source_code": "waiting_list",
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        snapshot = AIWindowContextSnapshot.objects.get(window_id="window-waiting-list-test")
        self.assertEqual(snapshot.resolved_summary["selection"]["object_id"], str(entry.pk))
        self.assertEqual(snapshot.resolved_summary["selection"]["service_id"], "s1")
        self.assertIn("can_transition", snapshot.resolved_summary["capabilities"])

    def test_chat_message_submit_binds_immutable_page_context_snapshot(self):
        self.client.force_login(self.manager)
        session = ChatSession.objects.create(user=self.manager)
        first = update_window_context_snapshot(
            self.manager,
            {
                "schema_version": "1",
                "window_id": "window-bind-test",
                "page": {"module": "workorders", "view": "board"},
                "selection": {
                    "object_type": "workorder",
                    "object_id": str(self.customer_workorder.pk),
                    "source_code": "workorders",
                },
            },
        ).snapshot
        second_workorder = WorkOrder.objects.create(
            title="Вторая заявка",
            description="Для проверки гонки контекста",
            department=self.department,
            author=self.customer,
            board=self.board,
            status=WorkOrderStatus.NEW,
        )
        update_window_context_snapshot(
            self.manager,
            {
                "schema_version": "1",
                "window_id": "window-bind-test",
                "page": {"module": "workorders", "view": "board"},
                "selection": {
                    "object_type": "workorder",
                    "object_id": str(second_workorder.pk),
                    "source_code": "workorders",
                },
            },
        )

        response = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {
                "run_id": "context-bind-run",
                "prompt": "Что с этой заявкой?",
                "window_id": "window-bind-test",
                "context_version": first.context_version,
                "context_hint": "workorders / first",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 201)
        message = session.messages.get(role=ChatMessage.Role.USER)
        self.assertEqual(message.metadata["page_context_status"], "bound")
        self.assertEqual(message.metadata["context_snapshot_id"], first.id)

        result = execute_tool(
            tool_code="ui.get_current_context",
            actor_context={
                "user_id": self.manager.id,
                "page_context": {"context_snapshot_id": first.id, "page_context_present": True},
            },
            payload={},
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["result"]["context"]["selection"]["object_id"],
            str(self.customer_workorder.pk),
        )

    def test_chat_settings_surface_overrides_default_sidebar_limit(self):
        self.assertEqual(get_chat_settings("sidebar")["recent_message_limit"], 8)
        self.assertEqual(get_chat_settings("full_page")["recent_message_limit"], 20)

    def test_create_workorder_tool_creates_request_for_customer(self):
        # Step 1: request without confirmation token → returns pending envelope
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.create"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {
                        "department_id": self.department.id,
                        "subject": "Починить раковину",
                        "description": "Протекает умывальник в процедурной",
                    },
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        pending_payload = response.json()
        self.assertTrue(pending_payload["ok"])
        self.assertEqual(pending_payload["tool"], "workorders.create")
        self.assertTrue(pending_payload["meta"]["awaiting_confirmation"])
        self.assertIn("pending_action_token", pending_payload["meta"])
        token = pending_payload["meta"]["pending_action_token"]
        self.assertFalse(WorkOrder.objects.filter(title="Починить раковину", author=self.customer).exists())

        # Step 2: confirm with token → executes the write
        confirm_response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": token}),
            data=json.dumps(
                {
                    "confirmed": True,
                    "actor": {"user_id": self.customer.id},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(confirm_response.status_code, 200, confirm_response.json())
        confirm_payload = confirm_response.json()
        self.assertTrue(confirm_payload["ok"])
        self.assertEqual(confirm_payload["tool"], "workorders.create")
        self.assertEqual(confirm_payload["meta"]["pending_action_status"], "confirmed")
        self.assertIsNotNone(confirm_payload["result"])
        self.assertTrue(WorkOrder.objects.filter(title="Починить раковину", author=self.customer).exists())
        action = AgentActionLog.objects.filter(tool_code="workorders.create", status=AgentActionLog.Status.SUCCEEDED).first()
        self.assertIsNotNone(action)

    def test_authenticated_user_can_open_chat_surface(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("ai:chat_index"))
        self.assertEqual(response.status_code, 302)
        detail_response = self.client.get(response["Location"])
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "ИИ-чат")
        self.assertContains(detail_response, 'class="ai-session-sidebar"')
        self.assertNotContains(detail_response, 'id="sidebar-ai-chat"')

    def test_chat_delete_archives_session_with_memory_links(self):
        from apps.memory.models import MemoryKnowledgeItem

        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Удаляемый чат")
        ChatMessage.objects.create(session=session, role=ChatMessage.Role.USER, content="Запомни это")
        MemoryKnowledgeItem.objects.create(
            memory_id="chat:personal:user-memory-link-test:abc123",
            scope=MemoryKnowledgeItem.Scope.PERSONAL,
            owner_user=self.customer,
            kind=MemoryKnowledgeItem.Kind.FACT,
            text_hash="hash-memory-link-test",
            sensitivity="internal",
            scope_tokens=[f"user:{self.customer.id}"],
            source_session=session,
            created_by=self.customer,
        )

        response = self.client.post(
            reverse("ai:chat_delete", kwargs={"external_id": session.external_id}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        session.refresh_from_db()
        self.assertEqual(session.status, ChatSession.Status.ARCHIVED)
        self.assertEqual(session.metadata["archive_reason"], "user_deleted")
        self.assertTrue(session.messages.exists())
        # Chat archive (not delete) must not disturb the knowledge item's link.
        self.assertTrue(MemoryKnowledgeItem.objects.filter(source_session=session).exists())

    def test_chat_mutations_hide_foreign_and_archived_sessions(self):
        self.client.force_login(self.customer)
        foreign = ChatSession.objects.create(user=self.manager, title="Чужой чат")
        archived = ChatSession.objects.create(
            user=self.customer,
            title="Архивный чат",
            status=ChatSession.Status.ARCHIVED,
        )
        endpoints = (
            ("ai:chat_update_model", {"model_id": ""}),
            ("ai:chat_update_title", {"title": "Новое имя"}),
            ("ai:chat_generate_title", {}),
            ("ai:chat_delete", {}),
        )
        for url_name, payload in endpoints:
            for session in (foreign, archived):
                with self.subTest(url_name=url_name, session=session.pk):
                    response = self.client.post(
                        reverse(url_name, kwargs={"external_id": session.external_id}),
                        data=json.dumps(payload),
                        content_type="application/json",
                    )
                    self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        archived.refresh_from_db()
        self.assertEqual(foreign.title, "Чужой чат")
        self.assertEqual(archived.status, ChatSession.Status.ARCHIVED)

    def test_chat_mutations_reject_non_string_model_and_title(self):
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Исходный")
        for url_name, payload in (
            ("ai:chat_update_model", {"model_id": 123}),
            ("ai:chat_update_title", {"title": {"unexpected": "object"}}),
        ):
            with self.subTest(url_name=url_name):
                response = self.client.post(
                    reverse(url_name, kwargs={"external_id": session.external_id}),
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
        session.refresh_from_db()
        self.assertEqual(session.title, "Исходный")

    def test_chat_sidebar_lists_only_active_sessions(self):
        self.client.force_login(self.customer)
        active = ChatSession.objects.create(user=self.customer, title="Активный чат")
        ChatSession.objects.create(
            user=self.customer,
            title="Архивный чат",
            status=ChatSession.Status.ARCHIVED,
        )

        response = self.client.get(reverse("ai:chat_detail", kwargs={"external_id": active.external_id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Активный чат")
        self.assertNotContains(response, "Архивный чат")

    def test_copilotkit_driver_replaces_full_page_chat_entrypoint(self):
        self.client.force_login(self.customer)
        with self.settings(
            LOCAL_BUSINESS_AI_UI_DRIVER="copilotkit",
            LOCAL_BUSINESS_AI_UI_DRIVER_EXPLICIT=True,
            LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL="/copilotkit",
        ):
            response = self.client.get(reverse("ai:chat_index"))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], reverse("ai:copilotkit_chat_page"))
            page_response = self.client.get(response["Location"])

        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, 'id="copilotkit-page-root"')
        self.assertContains(page_response, 'data-copilotkit-root="true"')
        self.assertContains(page_response, 'data-new-session-url="' + reverse("ai:ui_session_new") + '"')
        self.assertContains(page_response, "copilotkit-island.js?v=20260610-copilotkit-page")
        self.assertContains(page_response, "copilotkit-island.css?v=20260610-copilotkit-page")
        self.assertNotContains(page_response, 'class="ai-session-sidebar"')
        self.assertNotContains(page_response, 'id="sidebar-ai-chat"')

    def test_default_driver_mounts_native_sidebar_assets_and_config(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("workorders:board"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="native-ai-sidebar-root"')
        self.assertContains(response, 'data-config-url="' + reverse("ai:ui_config") + '"')
        self.assertContains(response, 'data-new-session-url="' + reverse("ai:ui_session_new") + '"')
        self.assertContains(response, "native_ai.css?v=20260826-unified-native-chat")
        self.assertContains(response, "native_ai.js?v=20260826-unified-native-chat")
        self.assertNotContains(response, 'id="copilotkit-sidebar-root"')
        self.assertNotContains(response, reverse("ai:copilotkit_config"))

    def test_tool_gateway_accepts_non_uuid_session_id(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {"status": WorkOrderStatus.NEW, "limit": 10},
                    "session_id": "external-session-42",
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        session = ChatSession.objects.get(user=self.customer)
        self.assertEqual(session.external_id, normalize_session_external_id("external-session-42"))

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_canonical_prepare_and_run_store_user_and_assistant_messages(self, stream_mock):
        stream_mock.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-canonical"}\n\n',
            'data: {"type":"TEXT_MESSAGE_START","messageId":"msg"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg","delta":"Найдено 1 новая заявка."}\n\n',
            'data: {"type":"TEXT_MESSAGE_END","messageId":"msg"}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-canonical"}\n\n',
        ])
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Проверка AI")
        prepared = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "run-canonical", "prompt": "Покажи новые заявки"},
        )
        self.assertEqual(prepared.status_code, 201)
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.USER).count(), 1)
        response = self.client.post(
            reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
            data=json.dumps({"threadId": str(session.external_id), "runId": "run-canonical"}),
            content_type="application/json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("Найдено 1", body)
        assistant = ChatMessage.objects.get(session=session, role=ChatMessage.Role.ASSISTANT)
        self.assertEqual(assistant.content, "Найдено 1 новая заявка.")
        self.assertEqual(assistant.metadata["runtime_method"], "ag_ui")

    def test_prepare_does_not_perform_runtime_call(self):
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Без runtime")
        with patch("apps.ai.views.AgentRuntimeClient") as client_class:
            response = self.client.post(
                reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
                {"run_id": "prepare-only", "prompt": "Проверь память"},
            )
        self.assertEqual(response.status_code, 201)
        client_class.assert_not_called()
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.USER).count(), 1)
        self.assertFalse(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.ASSISTANT).exists())

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream", side_effect=RuntimeError("runtime exploded"))
    def test_canonical_runtime_error_is_returned_saved_and_audited(self, stream_mock):
        from services.agent_runtime.protocols.common import AI_CHAT_UNAVAILABLE_MESSAGE

        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Проверка AG-UI")
        prepared = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "run-error", "prompt": "Найди в памяти концентратор"},
        )
        self.assertEqual(prepared.status_code, 201)
        response = self.client.post(
            reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
            data=json.dumps({"threadId": str(session.external_id), "runId": "run-error"}),
            content_type="application/json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(AI_CHAT_UNAVAILABLE_MESSAGE, body)
        self.assertNotIn("runtime exploded", body)
        action = AgentActionLog.objects.get(tool_code="agent_runtime.ag_ui")
        self.assertEqual(action.status, AgentActionLog.Status.FAILED)
        self.assertIn("runtime exploded", action.error_message)

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_canonical_runtime_error_payload_is_saved_as_error_not_partial_success(self, stream_mock):
        from services.agent_runtime.protocols.common import AI_CHAT_UNAVAILABLE_MESSAGE

        stream_mock.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-partial"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"Частичный ответ"}\n\n',
            'data: {"type":"RUN_ERROR","runId":"run-partial","message":"секретная причина"}\n\n',
        ])
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Ошибка AG-UI")
        prepared = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
            {"run_id": "run-partial", "prompt": "Проверь ответ"},
        )
        self.assertEqual(prepared.status_code, 201)
        response = self.client.post(
            reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
            data=json.dumps({"threadId": str(session.external_id), "runId": "run-partial"}),
            content_type="application/json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn(AI_CHAT_UNAVAILABLE_MESSAGE, body)
        self.assertNotIn("секретная причина", body)
        assistant = ChatMessage.objects.get(session=session, role=ChatMessage.Role.ASSISTANT)
        self.assertTrue(assistant.metadata["error"])
        self.assertTrue(assistant.metadata["partial"])
        self.assertTrue(AgentActionLog.objects.filter(
            session=session, tool_code="agent_runtime.ag_ui", status=AgentActionLog.Status.FAILED
        ).exists())
    def test_workorders_transition_requires_confirmation_without_token(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.transition"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.manager.id, "channel": "internal"},
                    "payload": {
                        "workorder_id": self.customer_workorder.id,
                        "target_status": "in_progress",
                    },
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["meta"]["awaiting_confirmation"])
        self.assertIn("pending_action_token", payload["meta"])
        # Status not yet changed
        self.customer_workorder.refresh_from_db()
        self.assertEqual(self.customer_workorder.status, WorkOrderStatus.NEW)
        pending = PendingAction.objects.filter(tool_code="workorders.transition").first()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, PendingAction.Status.PENDING)

    def test_workorders_transition_executes_with_valid_confirmation(self):
        # Use a workorder in ACCEPTED state so accepted->in_progress is a valid transition.
        # Per workflow_rules.json: "new" only allows accepted/cancelled, not in_progress.
        accepted_workorder = WorkOrder.objects.create(
            title="Accepted workorder for transition test",
            description="Testing valid transition",
            department=self.department,
            author=self.customer,
            board=self.board,
            status=WorkOrderStatus.ACCEPTED,
        )
        pending = PendingAction.objects.create(
            tool_code="workorders.transition",
            action_kind="write",
            actor=self.manager,
            session=ChatSession.objects.create(user=self.manager),
            payload={"workorder_id": accepted_workorder.id, "target_status": "in_progress"},
            status=PendingAction.Status.PENDING,
        )
        confirm_response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": pending.token}),
            data=json.dumps({"confirmed": True, "actor": {"user_id": self.manager.id}}),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(confirm_response.status_code, 200)
        confirm_payload = confirm_response.json()
        self.assertTrue(confirm_payload["ok"])
        self.assertEqual(confirm_payload["tool"], "workorders.transition")
        self.assertEqual(confirm_payload["meta"]["pending_action_status"], "confirmed")
        accepted_workorder.refresh_from_db()
        self.assertEqual(accepted_workorder.status, WorkOrderStatus.IN_PROGRESS)
        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingAction.Status.CONFIRMED)

    def test_pending_action_cancelled_does_not_execute(self):
        # Create pending create
        pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.customer,
            payload={
                "department_id": self.department.id,
                "subject": "Should not be created",
                "description": "Cancelling this",
            },
            status=PendingAction.Status.PENDING,
        )
        cancel_response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": pending.token}),
            data=json.dumps({"confirmed": False, "actor": {"user_id": self.customer.id}}),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(cancel_response.status_code, 200)
        cancel_payload = cancel_response.json()
        self.assertTrue(cancel_payload["ok"])
        self.assertEqual(cancel_payload["meta"]["pending_action_status"], "cancelled")
        self.assertFalse(WorkOrder.objects.filter(title="Should not be created").exists())
        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingAction.Status.CANCELLED)
        action = AgentActionLog.objects.filter(
            tool_code="workorders.create", status=AgentActionLog.Status.DENIED
        ).first()
        self.assertIsNotNone(action)

    def test_pending_action_invalid_token_returns_error(self):
        fake_token = uuid.uuid4()
        response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": fake_token}),
            data=json.dumps({"confirmed": True, "actor": {"user_id": self.customer.id}}),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("не найдено", payload["errors"][0])

    def test_pending_action_already_confirmed_returns_error(self):
        # Create and confirm a pending action
        pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.customer,
            payload={
                "department_id": self.department.id,
                "subject": "Already confirmed",
                "description": "Testing double confirm",
            },
            status=PendingAction.Status.CONFIRMED,
        )
        response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": pending.token}),
            data=json.dumps({"confirmed": True, "actor": {"user_id": self.customer.id}}),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("уже имеет статус", payload["errors"][0])

    def test_pending_action_expired_does_not_execute(self):
        pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.customer,
            payload={
                "department_id": self.department.id,
                "subject": "Expired action",
                "description": "Should not execute",
            },
            status=PendingAction.Status.PENDING,
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": pending.token}),
            data=json.dumps({"confirmed": True, "actor": {"user_id": self.customer.id}}),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("истек", payload["errors"][0])
        self.assertFalse(WorkOrder.objects.filter(title="Expired action").exists())

    def test_pending_action_rejects_actor_mismatch(self):
        pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.customer,
            payload={
                "department_id": self.department.id,
                "subject": "Wrong actor",
                "description": "Should not execute",
            },
            status=PendingAction.Status.PENDING,
        )
        response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": pending.token}),
            data=json.dumps({"confirmed": True, "actor": {"user_id": self.manager.id}}),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("own", payload["errors"][0])
        self.assertFalse(WorkOrder.objects.filter(title="Wrong actor").exists())

    def test_read_tool_does_not_require_confirmation(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {"status": WorkOrderStatus.NEW},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["meta"].get("awaiting_confirmation", False))
        # No PendingAction created for read tools
        self.assertEqual(PendingAction.objects.count(), 0)


# ---------------------------------------------------------------------------
# Tests for identity/correlation propagation and task type resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class PendingActionConcurrencyTests(TransactionTestCase):
    databases = RUNTIME_DATABASES
    reset_sequences = True

    def setUp(self):
        self.actor = User.objects.create_user(username="pending-concurrency")
        self.pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.actor,
            payload={"subject": "Однократная команда"},
        )

    def test_concurrent_confirmation_dispatches_once_and_writes_one_terminal_audit(self):
        from apps.ai import tooling as ai_tooling

        start = threading.Barrier(3)
        dispatch_lock = threading.Lock()
        dispatch_count = 0
        results = []

        def fake_dispatch(**kwargs):
            nonlocal dispatch_count
            with dispatch_lock:
                dispatch_count += 1
            return {"id": 1}

        def confirm():
            close_old_connections()
            start.wait()
            try:
                results.append(
                    execute_pending_action(
                        token=self.pending.token,
                        confirmed=True,
                        actor_context={"user_id": self.actor.pk},
                    )
                )
            finally:
                close_old_connections()

        with patch.object(ai_tooling, "_dispatch_tool", side_effect=fake_dispatch):
            workers = [threading.Thread(target=confirm), threading.Thread(target=confirm)]
            for worker in workers:
                worker.start()
            start.wait()
            for worker in workers:
                worker.join(timeout=10)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(dispatch_count, 1)
        self.assertEqual(sum(bool(result["ok"]) for result in results), 1)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingAction.Status.CONFIRMED)
        self.assertEqual(
            AgentActionLog.objects.filter(
                tool_code=self.pending.tool_code,
                status=AgentActionLog.Status.SUCCEEDED,
            ).count(),
            1,
        )

    def test_terminal_failure_after_dispatch_requires_reconciliation_and_is_audited(self):
        from apps.ai import tooling as ai_tooling

        with (
            patch.object(ai_tooling, "_dispatch_tool", return_value={"id": 7}),
            patch.object(
                ai_tooling,
                "_finalize_pending_action_success",
                side_effect=RuntimeError("terminal audit unavailable"),
            ),
        ):
            result = execute_pending_action(
                token=self.pending.token,
                confirmed=True,
                actor_context={"user_id": self.actor.pk},
            )

        self.assertFalse(result["ok"])
        self.pending.refresh_from_db()
        self.assertEqual(
            self.pending.status,
            PendingAction.Status.RECONCILIATION_REQUIRED,
        )
        audit = AgentActionLog.objects.get(
            tool_code=self.pending.tool_code,
            status=AgentActionLog.Status.FAILED,
        )
        self.assertTrue(audit.response_payload["dispatch_succeeded"])
        self.assertTrue(audit.response_payload["reconciliation_required"])
        self.assertFalse(
            AgentActionLog.objects.filter(
                tool_code=self.pending.tool_code,
                status=AgentActionLog.Status.SUCCEEDED,
            ).exists()
        )

    def test_manual_reconciliation_records_observation_without_closing_unknown_outcome(self):
        self.pending.status = PendingAction.Status.RECONCILIATION_REQUIRED
        self.pending.save(update_fields=["status"])
        operator = User.objects.create_superuser(username="reconciliation-operator")

        call_command(
            "reconcile_ai_action",
            token=str(self.pending.token),
            outcome="succeeded",
            reason="Предметный эффект проверен оператором по журналу.",
            operator=operator.username,
            verbosity=0,
        )

        self.pending.refresh_from_db()
        self.assertEqual(
            self.pending.status,
            PendingAction.Status.RECONCILIATION_REQUIRED,
        )
        audit = AgentActionLog.objects.get(
            tool_code=self.pending.tool_code,
            status=AgentActionLog.Status.PENDING,
        )
        self.assertEqual(audit.actor, operator)
        self.assertTrue(audit.response_payload["manual_reconciliation"])
        self.assertFalse(audit.response_payload["state_closed"])

    def test_skill_authoring_rechecks_active_actor(self):
        from ..skill_authoring import can_manage_ai_skills, create_or_update_runtime_skill_for_actor

        inactive = User.objects.create_user(username="inactive-skill-author", is_active=False)
        self.assertFalse(can_manage_ai_skills(inactive))
        with self.assertRaises(PermissionDenied):
            create_or_update_runtime_skill_for_actor(
                actor=inactive,
                payload={"skill_id": "inactive-test", "name": "x", "description": "x", "body": "x"},
            )

    def test_skill_authoring_rejects_symlinked_target_directory(self):
        from ..skill_authoring import create_or_update_runtime_skill_for_actor

        actor = User.objects.create_user(username="symlink-skill-author")
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside:
            runtime_root = Path(tmpdir) / "contracts"
            skills_root = runtime_root / "ai" / "skills"
            skills_root.mkdir(parents=True)
            (skills_root / "escape").symlink_to(Path(outside), target_is_directory=True)
            with override_settings(RUNTIME_CONTRACTS_DIR=runtime_root), patch(
                "apps.ai.skill_authoring.can_manage_ai_skills", return_value=True
            ):
                with self.assertRaises(ValidationError):
                    create_or_update_runtime_skill_for_actor(
                        actor=actor,
                        payload={"skill_id": "escape", "name": "x", "description": "x", "body": "x"},
                    )

    def test_skill_authoring_rejects_symlinked_parent_directory(self):
        from ..skill_authoring import create_or_update_runtime_skill_for_actor

        actor = User.objects.create_user(username="symlink-parent-skill-author")
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside:
            runtime_root = Path(tmpdir) / "contracts"
            runtime_root.mkdir(parents=True)
            (runtime_root / "ai").symlink_to(Path(outside), target_is_directory=True)
            with override_settings(RUNTIME_CONTRACTS_DIR=runtime_root), patch(
                "apps.ai.skill_authoring.can_manage_ai_skills", return_value=True
            ):
                with self.assertRaises(ValidationError):
                    create_or_update_runtime_skill_for_actor(
                        actor=actor,
                        payload={"skill_id": "escape", "name": "x", "description": "x", "body": "x"},
                    )

    def test_skill_authoring_rejects_existing_symlinked_skill_file(self):
        from ..skill_authoring import create_or_update_runtime_skill_for_actor

        actor = User.objects.create_user(username="symlink-file-author")
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside:
            runtime_root = Path(tmpdir) / "contracts"
            skill_dir = runtime_root / "ai" / "skills" / "safe"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").symlink_to(Path(outside) / "SKILL.md")
            with override_settings(RUNTIME_CONTRACTS_DIR=runtime_root), patch(
                "apps.ai.skill_authoring.can_manage_ai_skills", return_value=True
            ):
                with self.assertRaises(ValidationError):
                    create_or_update_runtime_skill_for_actor(
                        actor=actor,
                        payload={"skill_id": "safe", "name": "x", "description": "x", "body": "x"},
                    )
