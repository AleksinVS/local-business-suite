"""Тесты представлений AI-чата, стриминга и прав доступа."""
from apps.ai.tests._common import *  # noqa: F401,F403


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="test-ai-token")
class AIViewsTests(TestCase):
    databases = RUNTIME_DATABASES
    def setUp(self):
        self.manager = User.objects.create_user(username="manager-ai", password="pass")
        self.customer = User.objects.create_user(username="customer-ai", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        self.manager.groups.add(manager_group)
        self.customer.groups.add(customer_group)
        self.department = Department.objects.create(name="Стационар")
        self.manager.department = self.department
        self.customer.department = self.department
        self.manager.save(update_fields=["department"])
        self.customer.save(update_fields=["department"])
        self.board = Board.objects.create(title="Test Board", slug="test-board-ai")
        self.board.allowed_groups.add(manager_group, customer_group)
        self.customer_workorder = WorkOrder.objects.create(
            title="Сломан светильник",
            description="Нужна замена лампы",
            department=self.department,
            author=self.customer,
            board=self.board,
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

    def test_native_ai_ui_config_returns_signed_actor_payload(self):
        from ..views import sign_copilotkit_actor_payload

        self.client.force_login(self.customer)
        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native"):
            response = self.client.get(reverse("ai:ui_config"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        forwarded = payload["forwarded_props"]
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["driver"], "native")
        self.assertEqual(payload["runtime_url"], reverse("ai:ui_ag_ui_run"))
        self.assertEqual(forwarded["ui_driver"], "native")
        self.assertEqual(forwarded["actor"]["source"], "django-native-ai-ui")
        self.assertEqual(forwarded["signature"], sign_copilotkit_actor_payload(forwarded))

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
        self.assertEqual(payload["runtime_url"], reverse("ai:ui_ag_ui_run"))
        self.assertEqual(payload["forwarded_props"]["ui_driver"], "native")

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
        self.assertEqual(payload["thread_id"], str(session.external_id))
        self.assertEqual(payload["messages"], [])
        self.assertEqual(payload["current_model_id"], "test-model")
        self.assertEqual(ChatMessage.objects.filter(session=session).count(), 0)
        session.refresh_from_db()
        self.assertIsNone(session.last_message_at)
        self.assertEqual(session.metadata.get("model_id"), "test-model")
        self.assertNotIn("sidebar_summary", session.metadata)

    def test_native_ai_ui_proxy_overwrites_client_actor_payload(self):
        self.client.force_login(self.customer)
        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native"), patch("apps.ai.views.AgentRuntimeClient") as client_class:
            client = client_class.return_value
            client.ag_ui_stream.return_value = ['data: {"type":"RUN_STARTED"}\n\n']
            response = self.client.post(
                reverse("ai:ui_ag_ui_run"),
                data=json.dumps(
                    {
                        "threadId": "forged-thread",
                        "runId": "run-1",
                        "messages": [{"id": "u1", "role": "user", "content": "Проверка"}],
                        "forwardedProps": {
                            "actor": {"user_id": self.manager.id},
                            "signature": "invalid",
                            "page_context": {
                                "context_hint": "workorders / board",
                                "envelope": {
                                    "schema_version": "1",
                                    "window_id": "native-test-window",
                                    "page": {"module": "workorders", "view": "board", "path": "/workorders/"},
                                },
                            },
                        },
                    }
                ),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("RUN_STARTED", body)
        run_payload = client.ag_ui_stream.call_args.args[0]
        forwarded = run_payload["forwardedProps"]
        self.assertNotEqual(run_payload["threadId"], "forged-thread")
        self.assertEqual(forwarded["actor"]["user_id"], self.customer.id)
        self.assertEqual(forwarded["ui_driver"], "native")
        self.assertEqual(forwarded["actor"]["conversation_id"], ChatSession.objects.get(external_id=run_payload["threadId"]).metadata["conversation_id"])
        self.assertEqual(forwarded["page_context"]["page_context_status"], "bound")
        self.assertEqual(forwarded["page_context"]["digest"]["module"], "workorders")
        self.assertRegex(forwarded["signature"], r"^[a-f0-9]{64}$")
        session = ChatSession.objects.get(external_id=run_payload["threadId"])
        self.assertEqual(session.messages.filter(role=ChatMessage.Role.USER, content="Проверка").count(), 1)

    def test_native_ai_ui_proxy_persists_assistant_message_from_agui_stream(self):
        self.client.force_login(self.customer)
        with self.settings(LOCAL_BUSINESS_AI_UI_DRIVER="native"), patch("apps.ai.views.AgentRuntimeClient") as client_class:
            client = client_class.return_value
            client.ag_ui_stream.return_value = [
                'data: {"type":"RUN_STARTED","threadId":"thread","runId":"run"}\n\n',
                'data: {"type":"TEXT_MESSAGE_START","messageId":"msg","role":"assistant"}\n\n',
                'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg","delta":"Ответ"}\n\n',
                'data: {"type":"TOOL_CALL_START","toolCallId":"tool-1","toolCallName":"workorders.open_right_panel"}\n\n',
                'data: {"type":"TOOL_CALL_END","toolCallId":"tool-1"}\n\n',
                'data: {"type":"STATE_DELTA","delta":[{"op":"replace","path":"/localBusiness/uiCommands","value":[{"type":"open_right_panel","htmx_url":"/workorders/1/","target":"#global-right-panel-content"}]}]}\n\n',
                'data: {"type":"RUN_FINISHED","threadId":"thread","runId":"run"}\n\n',
            ]
            response = self.client.post(
                reverse("ai:ui_ag_ui_run"),
                data=json.dumps(
                    {
                        "runId": "run-2",
                        "messages": [{"id": "u1", "role": "user", "content": "Открой заявку"}],
                        "forwardedProps": {},
                    }
                ),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("TEXT_MESSAGE_CONTENT", body)
        session = ChatSession.objects.get(user=self.customer, channel=ChatSession.Channel.SIDEBAR)
        messages = list(session.messages.order_by("created_at", "id"))
        self.assertEqual(messages[0].role, ChatMessage.Role.USER)
        self.assertEqual(messages[0].content, "Открой заявку")
        self.assertEqual(messages[1].role, ChatMessage.Role.ASSISTANT)
        self.assertEqual(messages[1].content, "Ответ")
        self.assertEqual(messages[1].metadata["tool_trace"][0]["tool"], "workorders.open_right_panel")
        self.assertEqual(messages[1].metadata["ui_commands"][0]["type"], "open_right_panel")

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

    def test_admin_role_update_tool_uses_settings_center_audit(self):
        from apps.core.json_utils import load_json_file
        from apps.settings_center.models import SettingsChange

        self.manager.is_superuser = True
        self.manager.save(update_fields=["is_superuser"])

        with TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            role_rules = load_json_file("contracts/role_rules.json")
            role_file.write_text(json.dumps(role_rules, ensure_ascii=False), encoding="utf-8")
            first_role = next(role for role in role_rules if role != "$schema")

            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                LOCAL_BUSINESS_ROLE_RULES=role_rules,
            ):
                result = execute_tool(
                    tool_code="access.update_role_permissions",
                    actor_context={"user_id": self.manager.id, "channel": "internal"},
                    payload={
                        "role_name": first_role,
                        "permissions_map": {"display_name": "AI audited role"},
                    },
                    request_id="req-ai-role-update",
                )
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["meta"]["awaiting_confirmation"])

                confirm = execute_pending_action(
                    token=result["meta"]["pending_action_token"],
                    confirmed=True,
                    actor_context={"user_id": self.manager.id, "channel": "internal"},
                    request_id="req-ai-role-update-confirm",
                )

                self.assertTrue(confirm["ok"], confirm)
                self.assertEqual(load_json_file(role_file)[first_role]["display_name"], "AI audited role")
                self.assertEqual(
                    SettingsChange.objects.filter(setting_id="core.contract.role_rules").count(),
                    1,
                )
                self.assertEqual(
                    confirm["result"]["settings_change_id"],
                    SettingsChange.objects.get(setting_id="core.contract.role_rules").id,
                )

        action = AgentActionLog.objects.filter(
            tool_code="access.update_role_permissions",
            status=AgentActionLog.Status.PENDING,
        ).first()
        self.assertIsNotNone(action)
        self.assertEqual(action.request_payload["command"]["confirmation_state"], "pending_required")
        self.assertEqual(action.request_payload["command"]["tool_code"], "access.update_role_permissions")

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
            reverse("ai:chat_send", kwargs={"external_id": session.external_id}),
            {
                "prompt": "Что с этой заявкой?",
                "window_id": "window-bind-test",
                "context_version": first.context_version,
                "context_hint": "workorders / first",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
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
        self.assertEqual(confirm_response.status_code, 200)
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
        self.assertContains(response, "native_ai.css?v=20260610-native-ag-ui-chat")
        self.assertContains(response, "native_ai.js?v=20260610-native-ag-ui-chat")
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

    @patch("apps.ai.views.AgentRuntimeClient.chat_stream")
    def test_chat_send_and_stream_store_user_and_assistant_messages(self, stream_mock):
        # Нормальный ход диалога хранит ОБА сообщения, но через два шага:
        # /send/ (AJAX) сохраняет только сообщение пользователя и отдаёт
        # message_id, а ответ ассистента появляется на стриминговом пути.
        stream_mock.return_value = [
            'data: {"content": "Найдено 1 новая заявка."}',
            "data: [DONE]",
        ]
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Проверка AI")

        send_response = self.client.post(
            reverse("ai:chat_send", kwargs={"external_id": session.external_id}),
            {"prompt": "Покажи новые заявки"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(send_response.status_code, 200)
        send_payload = send_response.json()
        self.assertEqual(send_payload["status"], "ok")
        message_id = send_payload["message_id"]
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.USER).count(), 1)
        self.assertFalse(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.ASSISTANT).exists())

        stream_response = self.client.post(
            reverse("ai:chat_stream", kwargs={"external_id": session.external_id}),
            data=json.dumps({"msg_id": message_id}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        body = b"".join(stream_response.streaming_content).decode("utf-8")
        self.assertEqual(stream_response.status_code, 200)
        self.assertIn("Найдено 1", body)
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.USER).count(), 1)
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.ASSISTANT).count(), 1)
        assistant = ChatMessage.objects.get(session=session, role=ChatMessage.Role.ASSISTANT)
        self.assertEqual(assistant.content, "Найдено 1 новая заявка.")
        self.assertTrue(assistant.metadata.get("streamed"))

    def test_chat_send_does_not_perform_synchronous_llm_call(self):
        # Регрессия: /send/ больше НЕ делает синхронный LLM-вызов. Раньше это
        # был синхронный вызов AgentRuntimeClient.chat с таймаутом 90s, который
        # при рассинхроне с LLM_DEADLINE (300s) мог осиротить write-инструмент.
        # Ответ ассистента (в т.ч. user-safe ошибки, см.
        # test_chat_stream_runtime_error_is_returned_saved_and_audited) теперь
        # приходит только со стримингового пути.
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Без синхронного LLM")
        with patch("apps.ai.views.AgentRuntimeClient") as client_class:
            response = self.client.post(
                reverse("ai:chat_send", kwargs={"external_id": session.external_id}),
                {"prompt": "Проверь память"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("message_id", payload)
        # Клиент рантайма не конструируется и LLM не вызывается на /send/.
        client_class.assert_not_called()
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.USER).count(), 1)
        self.assertFalse(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.ASSISTANT).exists())
        self.assertFalse(AgentActionLog.objects.filter(session=session).exists())

    @patch("apps.ai.views.AgentRuntimeClient.chat_stream")
    def test_chat_stream_runtime_error_is_returned_saved_and_audited(self, stream_mock):
        stream_mock.side_effect = AgentRuntimeError("runtime stream exploded")
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Проверка stream")
        user_message = ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.USER,
            content="Найди в памяти концентратор",
        )

        with self.assertLogs("apps.ai.views", level="WARNING") as captured:
            response = self.client.post(
                reverse("ai:chat_stream", kwargs={"external_id": session.external_id}),
                data=json.dumps({"msg_id": user_message.id}),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("runtime stream exploded", "\n".join(captured.output))
        self.assertIn("Не удалось получить ответ от ИИ-сервиса", body)
        self.assertIn("request_id", body)
        self.assertNotIn("runtime stream exploded", body)
        action = AgentActionLog.objects.get(tool_code="agent_runtime.chat_stream")
        self.assertEqual(action.status, AgentActionLog.Status.FAILED)
        self.assertIn("runtime stream exploded", action.error_message)
        assistant_message = ChatMessage.objects.filter(session=session, role=ChatMessage.Role.ASSISTANT).get()
        self.assertTrue(assistant_message.metadata["error"])
        self.assertEqual(assistant_message.metadata["technical_trace_id"], action.id)
        session.refresh_from_db()
        self.assertEqual(session.metadata["last_error_action_id"], action.id)

    def test_workorder_get_with_invalid_id_returns_error_envelope(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.get"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {"workorder_id": 99999},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["tool"], "workorders.get")
        self.assertIsNone(payload["result"])
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("meta", payload)
        self.assertIn("session_id", payload["meta"])
        action = AgentActionLog.objects.filter(tool_code="workorders.get").first()
        self.assertEqual(action.status, AgentActionLog.Status.FAILED)

    def test_workorders_create_requires_confirmation_without_token(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.create"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "internal"},
                    "payload": {
                        "department_id": self.department.id,
                        "subject": "Test pending",
                        "description": "Testing pending flow",
                    },
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool"], "workorders.create")
        self.assertTrue(payload["meta"]["awaiting_confirmation"])
        self.assertIn("pending_action_token", payload["meta"])
        self.assertIsNone(payload["result"])
        self.assertEqual(len(payload["errors"]), 0)
        # No workorder created yet
        self.assertFalse(WorkOrder.objects.filter(title="Test pending").exists())
        # PendingAction record created
        pending = PendingAction.objects.filter(tool_code="workorders.create").first()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, PendingAction.Status.PENDING)
        # Action logged as pending
        action = AgentActionLog.objects.filter(tool_code="workorders.create", status=AgentActionLog.Status.PENDING).first()
        self.assertIsNotNone(action)

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
