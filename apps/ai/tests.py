import json
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Department
from apps.workorders.models import WorkOrder, WorkOrderStatus
from apps.workorders.policies import ROLE_CUSTOMER, ROLE_MANAGER

from .models import AgentActionLog, ChatMessage, ChatSession
from .services import normalize_session_external_id


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="test-ai-token")
class AIViewsTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager-ai", password="pass")
        self.customer = User.objects.create_user(username="customer-ai", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        self.manager.groups.add(manager_group)
        self.customer.groups.add(customer_group)
        self.department = Department.objects.create(name="Стационар")
        self.customer_workorder = WorkOrder.objects.create(
            title="Сломан светильник",
            description="Нужна замена лампы",
            department=self.department,
            author=self.customer,
            status=WorkOrderStatus.NEW,
        )

    def test_manager_can_open_ai_hub(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("ai:hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Hub")

    def test_customer_cannot_open_ai_hub(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("ai:hub"))
        self.assertEqual(response.status_code, 403)

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

    def test_list_workorders_tool_returns_visible_items_and_logs_action(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "librechat", "user_prompt": "Покажи новые заявки"},
                    "payload": {"status": WorkOrderStatus.NEW, "limit": 10},
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["tool"], "workorders.list")
        self.assertEqual(len(payload["result"]["items"]), 1)
        self.assertEqual(payload["result"]["items"][0]["number"], self.customer_workorder.number)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(ChatSession.objects.count(), 1)

    def test_create_workorder_tool_creates_request_for_customer(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.create"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "librechat"},
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
        self.assertTrue(WorkOrder.objects.filter(title="Починить раковину", author=self.customer).exists())
        action = AgentActionLog.objects.get(tool_code="workorders.create")
        self.assertEqual(action.status, AgentActionLog.Status.SUCCEEDED)

    def test_authenticated_user_can_open_chat_surface(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("ai:chat_index"))
        self.assertEqual(response.status_code, 302)
        detail_response = self.client.get(response["Location"])
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "AI чат")

    def test_tool_gateway_accepts_non_uuid_session_id(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "librechat"},
                    "payload": {"status": WorkOrderStatus.NEW, "limit": 10},
                    "session_id": "external-session-42",
                }
            ),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        session = ChatSession.objects.get(user=self.customer)
        self.assertEqual(session.external_id, normalize_session_external_id("external-session-42"))

    @patch("apps.ai.views.AgentRuntimeClient.chat")
    def test_chat_send_stores_user_and_assistant_messages(self, chat_mock):
        chat_mock.return_value = {
            "assistant_message": "Найдено 1 новая заявка.",
            "tool_trace": [{"tool": "workorders.list"}],
        }
        self.client.force_login(self.customer)
        session = ChatSession.objects.create(user=self.customer, title="Проверка AI")
        response = self.client.post(
            reverse("ai:chat_send", kwargs={"external_id": session.external_id}),
            {"prompt": "Покажи новые заявки"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.USER).count(), 1)
        self.assertEqual(ChatMessage.objects.filter(session=session, role=ChatMessage.Role.ASSISTANT).count(), 1)
        self.assertTrue(ChatMessage.objects.filter(session=session, content__icontains="Найдено 1").exists())
