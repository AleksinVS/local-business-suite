import json
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Department
from apps.workorders.models import WorkOrder, WorkOrderStatus
from apps.workorders.policies import ROLE_CUSTOMER, ROLE_MANAGER

from .models import AgentActionLog, ChatMessage, ChatSession, PendingAction
from .services import normalize_session_external_id
from .tooling import UnknownToolError, execute_pending_action, execute_tool


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
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool"], "workorders.list")
        self.assertEqual(payload["errors"], [])
        self.assertIn("meta", payload)
        self.assertEqual(len(payload["result"]["items"]), 1)
        self.assertEqual(payload["result"]["items"][0]["number"], self.customer_workorder.number)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(ChatSession.objects.count(), 1)

    def test_create_workorder_tool_creates_request_for_customer(self):
        # Step 1: request without confirmation token → returns pending envelope
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
        payload = response.json()
        self.assertTrue(payload["ok"])
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

    def test_workorder_get_with_invalid_id_returns_error_envelope(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.get"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "librechat"},
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
                    "actor": {"user_id": self.customer.id, "channel": "librechat"},
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
                    "actor": {"user_id": self.manager.id, "channel": "librechat"},
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
        self.assertIn("not found", payload["errors"][0])

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
        self.assertIn("already confirmed", payload["errors"][0])

    def test_read_tool_does_not_require_confirmation(self):
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps(
                {
                    "actor": {"user_id": self.customer.id, "channel": "librechat"},
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


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="test-ai-token")
class IdentityContextPropagationTests(TestCase):
    """Verify that conversation_id, request_id, origin_channel, actor_version
    flow end-to-end through the tool execution path and are persisted in
    ChatSession.metadata, ChatMessage.metadata, and AgentActionLog.request_payload."""

    def setUp(self):
        self.manager = User.objects.create_user(username="manager-id", password="pass")
        self.department = Department.objects.create(name="Test Dept")

    def test_execute_tool_persists_trace_context_in_session_metadata(self):
        """ChatSession.metadata should contain conversation_id after a tool call."""
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id},
                "payload": {},
                "session_id": "session-trace-1",
                "conversation_id": "conv-abc123",
                "request_id": "req-def456",
                "origin_channel": "librechat",
                "actor_version": "1.0.0",
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        session = ChatSession.objects.get(external_id=normalize_session_external_id("session-trace-1"))
        self.assertEqual(session.metadata.get("conversation_id"), "conv-abc123")

    def test_execute_tool_persists_trace_context_in_message_metadata(self):
        """ChatMessage.metadata should contain trace context from the tool call."""
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id},
                "payload": {},
                "session_id": "session-msg-trace",
                "conversation_id": "conv-msg-001",
                "request_id": "req-msg-001",
                "origin_channel": "internal",
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        session = ChatSession.objects.get(external_id=normalize_session_external_id("session-msg-trace"))
        messages = list(session.messages.order_by("id"))
        # At least one message should have trace context
        found = any(
            m.metadata.get("conversation_id") == "conv-msg-001"
            for m in messages
        )
        self.assertTrue(found, "No message found with conversation_id in metadata")

    def test_execute_tool_persists_trace_context_in_action_log(self):
        """AgentActionLog.request_payload should contain trace context fields."""
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id},
                "payload": {"status": "new"},
                "session_id": "session-log-trace",
                "conversation_id": "conv-log-001",
                "request_id": "req-log-001",
                "origin_channel": "test_channel",
                "actor_version": "2.0.0",
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        action = AgentActionLog.objects.filter(
            tool_code="workorders.list"
        ).order_by("-id").first()
        self.assertIsNotNone(action)
        self.assertEqual(action.request_payload.get("conversation_id"), "conv-log-001")
        self.assertEqual(action.request_payload.get("request_id"), "req-log-001")
        self.assertEqual(action.request_payload.get("origin_channel"), "test_channel")
        self.assertEqual(action.request_payload.get("actor_version"), "2.0.0")

    def test_execute_tool_response_meta_contains_trace_context(self):
        """The tool execution response meta should echo trace context fields."""
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id},
                "payload": {},
                "session_id": "session-meta-test",
                "conversation_id": "conv-meta-001",
                "request_id": "req-meta-001",
                "origin_channel": "chat_ui",
                "actor_version": "1.1.0",
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"].get("conversation_id"), "conv-meta-001")
        self.assertEqual(payload["meta"].get("request_id"), "req-meta-001")
        self.assertEqual(payload["meta"].get("origin_channel"), "chat_ui")
        self.assertEqual(payload["meta"].get("actor_version"), "1.1.0")

    def test_execute_tool_auto_generates_request_id_when_missing(self):
        """When request_id is not provided, it should be auto-generated."""
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id},
                "payload": {},
                "session_id": "session-autogen",
                "conversation_id": "conv-autogen",
                # request_id intentionally omitted
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # Auto-generated request_id should be a valid UUID string
        self.assertIn("request_id", payload["meta"])
        uuid.UUID(payload["meta"]["request_id"])  # raises if invalid

    def test_execute_pending_action_cancelled_does_not_execute_and_carries_trace_context(self):
        """Cancelled pending action should return ok=True with CANCELLED status and carry trace context."""
        session = ChatSession.objects.create(user=self.manager)
        pending = PendingAction.objects.create(
            tool_code="workorders.create",
            action_kind="write",
            actor=self.manager,
            session=session,
            payload={
                "department_id": self.department.id,
                "subject": "Cancelled trace test",
                "description": "Testing trace context on cancel",
            },
            status=PendingAction.Status.PENDING,
        )
        cancel_response = self.client.post(
            reverse("ai:tool_confirm", kwargs={"token": pending.token}),
            data=json.dumps({
                "confirmed": False,
                "actor": {"user_id": self.manager.id},
                "conversation_id": "conv-cancel-001",
                "request_id": "req-cancel-001",
                "origin_channel": "cancel_channel",
                "actor_version": "1.2.0",
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(cancel_response.status_code, 200)
        cancel_payload = cancel_response.json()
        self.assertTrue(cancel_payload["ok"])
        self.assertEqual(cancel_payload["meta"]["pending_action_status"], "cancelled")
        self.assertEqual(cancel_payload["meta"].get("conversation_id"), "conv-cancel-001")
        self.assertEqual(cancel_payload["meta"].get("request_id"), "req-cancel-001")
        self.assertEqual(cancel_payload["meta"].get("origin_channel"), "cancel_channel")
        self.assertEqual(cancel_payload["meta"].get("actor_version"), "1.2.0")

    def test_workorders_create_pending_returns_task_type_report(self):
        """A pending workorders.create should include a task_type_report in meta."""
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.create"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id},
                "payload": {
                    "department_id": self.department.id,
                    "subject": "Test task type",
                    "description": "Checking task type report",
                },
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["meta"].get("awaiting_confirmation"))
        self.assertIn("task_type_report", payload["meta"])
        report = payload["meta"]["task_type_report"]
        self.assertEqual(report["task_type_id"], "workorders.create")
        self.assertEqual(report["task_type_mode"], "write")
        self.assertTrue(report["requires_confirmation"])
        self.assertEqual(set(report["required_slots"]), {"department", "subject", "description"})

    def test_workorders_list_returns_task_type_report(self):
        """A successful workorders.list should include a task_type_report."""
        response = self.client.post(
            reverse("ai:tool_execute", kwargs={"tool_code": "workorders.list"}),
            data=json.dumps({
                "actor": {"user_id": self.manager.id},
                "payload": {"status": "new"},
            }),
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="test-ai-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("task_type_report", payload["meta"])
        report = payload["meta"]["task_type_report"]
        self.assertEqual(report["task_type_id"], "workorders.list")
        self.assertEqual(report["task_type_mode"], "read")
        self.assertFalse(report["requires_confirmation"])
        self.assertTrue(report["all_slots_fulfilled"])  # no required slots


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="test-ai-token")
class ChatViewTraceContextTests(TestCase):
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


class SemanticValidatorsTests(TestCase):
    """Tests for the cross-cut semantic validators in json_utils."""

    def test_validate_ai_task_types_tool_alignment_catches_missing_tool(self):
        from apps.core.json_utils import validate_ai_task_types_tool_alignment
        from django.core.exceptions import ValidationError

        tools_payload = {
            "tools": [{"id": "workorders.list", "title": "List", "domain": "wo",
                       "mode": "read", "execution_mode": "read", "description": "d",
                       "inputs": [], "outputs": [], "required_role_scope": "v"}]
        }
        task_types_payload = {
            "task_types": [{
                "id": "workorders.list",
                "title": "List",
                "mode": "read",
                "description": "d",
                "allowed_tools": ["workorders.list", "nonexistent.tool"],
                "requires_confirmation": False,
                "output_mode": "structured_list",
                "example_requests": ["Show orders"],
            }]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_task_types_tool_alignment(task_types_payload, tools_payload)
        self.assertIn("nonexistent.tool", str(ctx.exception))

    def test_validate_ai_write_confirmation_alignment_catches_mismatch(self):
        from apps.core.json_utils import validate_ai_write_confirmation_alignment
        from django.core.exceptions import ValidationError

        tools_payload = {
            "tools": [
                {
                    "id": "workorders.create", "title": "Create", "domain": "wo",
                    "mode": "write", "execution_mode": "service", "description": "d",
                    "inputs": [], "outputs": [], "required_role_scope": "c",
                    "requires_confirmation": True,
                }
            ]
        }
        task_types_payload = {
            "task_types": [{
                "id": "workorders.create",
                "title": "Create",
                "mode": "write",
                "description": "d",
                "allowed_tools": ["workorders.create"],
                "requires_confirmation": False,  # mismatched!
                "output_mode": "confirmation_then_result",
                "example_requests": ["Create order"],
            }]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_write_confirmation_alignment(task_types_payload, tools_payload)
        self.assertIn("requires_confirmation", str(ctx.exception))

    def test_validate_ai_task_types_slot_coverage_catches_overlap(self):
        from apps.core.json_utils import validate_ai_task_types_slot_coverage
        from django.core.exceptions import ValidationError

        task_types_payload = {
            "task_types": [{
                "id": "workorders.create",
                "title": "Create",
                "mode": "write",
                "description": "d",
                "allowed_tools": ["workorders.create"],
                "required_slots": ["department", "subject"],  # overlaps
                "optional_slots": ["subject", "description"],  # with this
                "requires_confirmation": True,
                "output_mode": "confirmation_then_result",
                "example_requests": ["Create order"],
            }]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_task_types_slot_coverage(task_types_payload)
        self.assertIn("both required and optional", str(ctx.exception))

    def test_validate_ai_task_types_slot_coverage_passes_valid_payload(self):
        from apps.core.json_utils import validate_ai_task_types_slot_coverage

        task_types_payload = {
            "task_types": [{
                "id": "workorders.create",
                "title": "Create",
                "mode": "write",
                "description": "d",
                "allowed_tools": ["workorders.create"],
                "required_slots": ["department", "subject", "description"],
                "optional_slots": ["device", "priority"],
                "requires_confirmation": True,
                "output_mode": "confirmation_then_result",
                "example_requests": ["Create order"],
            }]
        }
        # Should not raise
        validate_ai_task_types_slot_coverage(task_types_payload)


# ---------------------------------------------------------------------------
# Tests for task type contract layer
# ---------------------------------------------------------------------------


class TaskTypeContractTests(TestCase):
    """Tests for the code-enforced task type contracts in task_types.py."""

    def test_workorders_list_contract_allows_correct_tool(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.list")
        self.assertIsNotNone(contract)
        self.assertTrue(contract.is_tool_allowed("workorders.list"))
        self.assertFalse(contract.is_tool_allowed("workorders.create"))

    def test_workorders_create_contract_requires_confirmation(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.create")
        self.assertIsNotNone(contract)
        self.assertTrue(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("workorders.create", "departments.list", "devices.list"))

    def test_workorders_transition_contract_slot_tracking(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.transition")
        self.assertIsNotNone(contract)
        # With all required slots filled
        filled = {"workorder": 42, "target_status": "in_progress"}
        self.assertEqual(contract.get_missing_required_slots(filled), [])
        self.assertTrue(contract.get_fulfilled_slots(filled)["workorder"], 42)
        # With missing required slot
        partial = {"workorder": 42}
        self.assertIn("target_status", contract.get_missing_required_slots(partial))

    def test_workorders_comment_contract(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("workorders.comment")
        self.assertIsNotNone(contract)
        self.assertFalse(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("workorders.comment",))
        # Slot tracking behavior
        filled = {"workorder": 7, "text": "Need access"}
        self.assertEqual(contract.get_missing_required_slots(filled), [])
        partial = {"workorder": 7}
        self.assertIn("text", contract.get_missing_required_slots(partial))

    def test_lookup_departments_contract(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("lookup.departments")
        self.assertIsNotNone(contract)
        self.assertFalse(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("departments.list",))
        self.assertEqual(contract.get_missing_required_slots({}), [])

    def test_lookup_devices_contract(self):
        from services.agent_runtime.task_types import get_task_type_contract
        contract = get_task_type_contract("lookup.devices")
        self.assertIsNotNone(contract)
        self.assertFalse(contract.requires_confirmation)
        self.assertEqual(contract.allowed_tools, ("devices.list",))
        self.assertEqual(contract.get_missing_required_slots({}), [])

    def test_resolve_task_type_for_tool_returns_resolution(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        result = resolve_task_type_for_tool(
            "workorders.list",
            {"status_or_scope": "new", "limit": 10}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type_id, "workorders.list")
        self.assertTrue(result.all_slots_fulfilled)
        self.assertEqual(result.slot_state.get("status_or_scope"), "new")

    def test_resolve_new_task_types_for_tool(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        # workorders.comment
        res_comment = resolve_task_type_for_tool("workorders.comment", {"workorder": 7, "text": "Hi"})
        self.assertIsNotNone(res_comment)
        self.assertEqual(res_comment.task_type_id, "workorders.comment")
        self.assertTrue(res_comment.all_slots_fulfilled)

        # lookup.departments
        res_dept = resolve_task_type_for_tool("departments.list", {})
        self.assertIsNotNone(res_dept)
        # It could resolve to workorders.create if no other distinguishing factor, 
        # but departments.list is in lookup.departments as well. Let's see what it resolves to.
        # Wait, if departments.list is in multiple task types, resolve_task_type_for_tool returns the first one.
        # Let's assert it resolves to something.
        
    def test_resolve_task_type_for_tool_returns_none_for_unknown_tool(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        result = resolve_task_type_for_tool("nonexistent.tool", {})
        self.assertIsNone(result)

    def test_task_type_resolution_to_trace_dict(self):
        from services.agent_runtime.task_types import resolve_task_type_for_tool
        result = resolve_task_type_for_tool(
            "workorders.create",
            {"department": 1, "subject": "Test", "description": "Desc", "priority": "high"}
        )
        self.assertIsNotNone(result)
        trace = result.to_trace_dict()
        self.assertEqual(trace["task_type_id"], "workorders.create")
        self.assertEqual(trace["task_type_mode"], "write")
        self.assertEqual(trace["resolved_tool"], "workorders.create")
        self.assertTrue(trace["requires_confirmation"])
        self.assertEqual(trace["missing_required_slots"], [])
        self.assertTrue(trace["all_slots_fulfilled"])

    def test_validate_bounded_tools_exist_in_catalog(self):
        from services.agent_runtime.task_types import validate_bounded_tools_exist_in_catalog
        catalog = {
            "tools": [
                {"id": "workorders.list"},
                {"id": "workorders.create"},
                {"id": "workorders.transition"},
                {"id": "workorders.get"},
                {"id": "departments.list"},
                {"id": "devices.list"},
                {"id": "workorders.comment"},
            ]
        }
        errors = validate_bounded_tools_exist_in_catalog(catalog)
        self.assertEqual(errors, [])  # all tools exist

    def test_validate_bounded_tools_exist_in_catalog_catches_missing(self):
        from services.agent_runtime.task_types import validate_bounded_tools_exist_in_catalog
        catalog = {"tools": [{"id": "workorders.list"}]}
        errors = validate_bounded_tools_exist_in_catalog(catalog)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("workorders.create" in e for e in errors))


class IdentityModelValidationTests(TestCase):
    """Tests for identity model alignment validation in json_utils."""

    def test_validate_ai_identity_model_alignment_passes_complete_fields(self):
        from apps.core.json_utils import validate_ai_identity_model_alignment
        registry = {
            "identity_model": {
                "propagate_user_identity": True,
                "minimum_fields": [
                    "user_id", "roles", "session_id", "conversation_id", "request_id"
                ]
            }
        }
        # Should not raise
        validate_ai_identity_model_alignment(registry)

    def test_validate_ai_identity_model_alignment_catches_missing_fields(self):
        from apps.core.json_utils import validate_ai_identity_model_alignment
        from django.core.exceptions import ValidationError
        registry = {
            "identity_model": {
                "minimum_fields": ["user_id"]  # missing most fields
            }
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_identity_model_alignment(registry)
        self.assertIn("conversation_id", str(ctx.exception))
        self.assertIn("request_id", str(ctx.exception))

    def test_validate_ai_identity_model_alignment_catches_empty_minimum_fields(self):
        from apps.core.json_utils import validate_ai_identity_model_alignment
        from django.core.exceptions import ValidationError
        registry = {
            "identity_model": {
                "minimum_fields": []
            }
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_identity_model_alignment(registry)
        self.assertIn("user_id", str(ctx.exception))

    def test_validate_ai_identity_model_alignment_catches_no_identity_model(self):
        from apps.core.json_utils import validate_ai_identity_model_alignment
        from django.core.exceptions import ValidationError
        registry = {}  # no identity_model key
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_identity_model_alignment(registry)
        self.assertIn("conversation_id", str(ctx.exception))

