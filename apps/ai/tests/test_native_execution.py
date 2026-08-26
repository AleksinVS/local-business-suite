import json
from unittest.mock import patch

import pytest

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai.models import AgentActionLog, ChatMessage, ChatRun, ChatSession
from apps.ai.tooling import execute_tool


@pytest.mark.integration
class NativeExecutionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="native-owner", password="password")
        self.other = get_user_model().objects.create_user(username="native-other", password="password")
        self.session = ChatSession.objects.create(user=self.user, channel=ChatSession.Channel.INTERNAL)
        self.client.force_login(self.user)

    def prepare(self, run_id="run-1", prompt="Покажи мои заявки", **extra):
        return self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": self.session.external_id}),
            {"run_id": run_id, "prompt": prompt, **extra},
        )

    def run_turn(self, run_id="run-1", thread_id=None):
        return self.client.post(
            reverse("ai:chat_run", kwargs={"external_id": self.session.external_id}),
            data=json.dumps({
                "threadId": str(thread_id or self.session.external_id),
                "runId": run_id,
                "messages": [{"role": "user", "content": "browser value is ignored"}],
            }),
            content_type="application/json",
        )

    @staticmethod
    def text_upload():
        return SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")

    def test_prepare_exact_retry_is_idempotent_and_saves_attachment_once(self):
        first = self.prepare(files=self.text_upload())
        second = self.prepare(files=self.text_upload())

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["message_id"], second.json()["message_id"])
        self.assertEqual(ChatRun.objects.filter(session=self.session, run_id="run-1").count(), 1)
        message = ChatMessage.objects.get(session=self.session, role=ChatMessage.Role.USER)
        self.assertEqual(message.attachments.count(), 1)

    def test_prepare_rejects_reused_run_id_with_different_content(self):
        self.assertEqual(self.prepare(prompt="Первый текст").status_code, 201)
        response = self.prepare(prompt="Другой текст")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ChatMessage.objects.filter(session=self.session, role=ChatMessage.Role.USER).count(), 1)

    def test_prepare_rejects_foreign_and_archived_sessions(self):
        foreign = ChatSession.objects.create(user=self.other)
        response = self.client.post(
            reverse("ai:chat_prepare_turn", kwargs={"external_id": foreign.external_id}),
            {"run_id": "run-foreign", "prompt": "secret"},
        )
        self.assertEqual(response.status_code, 404)

        self.session.status = ChatSession.Status.ARCHIVED
        self.session.save(update_fields=["status"])
        self.assertEqual(self.prepare(run_id="run-archived").status_code, 404)

    def test_prepare_accepts_page_context_wrapper_and_binds_snapshot(self):
        page_context = {
            "context_hint": "ИИ-чат",
            "envelope": {
                "schema_version": "1",
                "window_id": "native-test-window",
                "page": {"path": "/ai/chat/", "title": "ИИ-чат", "module": "ai", "view": "chat"},
            },
        }
        response = self.prepare(page_context=json.dumps(page_context))
        self.assertEqual(response.status_code, 201)
        message = ChatMessage.objects.get(pk=response.json()["message_id"])
        self.assertEqual(message.metadata["page_context_status"], "bound")
        self.assertEqual(message.metadata["window_id"], "native-test-window")

    def test_prepare_rejects_forged_image_content(self):
        upload = SimpleUploadedFile("image.png", b"not-a-png", content_type="image/png")
        response = self.prepare(files=upload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ChatRun.objects.filter(session=self.session).exists())

    def test_run_rejects_forged_thread(self):
        self.assertEqual(self.prepare().status_code, 201)
        response = self.run_turn(thread_id=ChatSession.objects.create(user=self.user).external_id)
        self.assertEqual(response.status_code, 400)

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_completed_run_replay_does_not_call_runtime_twice(self, stream):
        stream.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-1"}\n\n',
            'data: {"type":"TEXT_MESSAGE_START","messageId":"m"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"m","delta":"Готово"}\n\n',
            'data: {"type":"TEXT_MESSAGE_END","messageId":"m"}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-1"}\n\n',
        ])
        self.assertEqual(self.prepare().status_code, 201)
        first_body = b"".join(self.run_turn().streaming_content)
        replay_body = b"".join(self.run_turn().streaming_content)

        self.assertEqual(stream.call_count, 1)
        self.assertEqual(first_body, replay_body)
        run = ChatRun.objects.get(run_id="run-1")
        self.assertEqual(run.status, ChatRun.Status.COMPLETED)
        self.assertEqual(run.assistant_message.content, "Готово")

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream", side_effect=RuntimeError("provider failed"))
    def test_runtime_error_is_saved_once_and_audited(self, stream):
        self.assertEqual(self.prepare().status_code, 201)
        body = b"".join(self.run_turn().streaming_content).decode("utf-8")

        self.assertIn("RUN_ERROR", body)
        run = ChatRun.objects.get(run_id="run-1")
        self.assertEqual(run.status, ChatRun.Status.FAILED)
        self.assertTrue(run.assistant_message.metadata["error"])
        self.assertTrue(run.assistant_message.metadata["technical_trace_id"])
        self.assertEqual(AgentActionLog.objects.filter(tool_code="agent_runtime.ag_ui").count(), 1)
        b"".join(self.run_turn().streaming_content)
        self.assertEqual(stream.call_count, 1)
        self.assertEqual(AgentActionLog.objects.filter(tool_code="agent_runtime.ag_ui").count(), 1)

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_stale_running_run_fails_without_reexecution(self, stream):
        self.assertEqual(self.prepare().status_code, 201)
        run = ChatRun.objects.get(run_id="run-1")
        run.status = ChatRun.Status.RUNNING
        run.started_at = timezone.now() - timezone.timedelta(hours=1)
        run.save(update_fields=["status", "started_at"])

        with self.settings(LOCAL_BUSINESS_AI_CHAT_RUN_STALE_LEASE_SECONDS=60):
            body = b"".join(self.run_turn().streaming_content).decode("utf-8")

        self.assertIn("RUN_ERROR", body)
        run.refresh_from_db()
        self.assertEqual(run.status, ChatRun.Status.FAILED)
        stream.assert_not_called()

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_second_distinct_run_is_rejected_while_other_run_is_active(self, stream):
        self.assertEqual(self.prepare(run_id="run-1").status_code, 201)
        self.assertEqual(self.prepare(run_id="run-2", prompt="Второй вопрос").status_code, 201)
        active = ChatRun.objects.get(run_id="run-1")
        active.status = ChatRun.Status.RUNNING
        active.started_at = timezone.now()
        active.save(update_fields=["status", "started_at"])

        response = self.run_turn(run_id="run-2")
        self.assertEqual(response.status_code, 409)
        stream.assert_not_called()
        self.assertEqual(ChatRun.objects.filter(session=self.session, status=ChatRun.Status.RUNNING).count(), 1)

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_stale_other_run_is_terminalized_before_current_run_starts(self, stream):
        stream.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-2"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"Готово"}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-2"}\n\n',
        ])
        self.assertEqual(self.prepare(run_id="run-1").status_code, 201)
        self.assertEqual(self.prepare(run_id="run-2", prompt="Второй вопрос").status_code, 201)
        stale = ChatRun.objects.get(run_id="run-1")
        stale.status = ChatRun.Status.RUNNING
        stale.started_at = timezone.now() - timezone.timedelta(hours=1)
        stale.save(update_fields=["status", "started_at"])

        with self.settings(LOCAL_BUSINESS_AI_CHAT_RUN_STALE_LEASE_SECONDS=60):
            body = b"".join(self.run_turn(run_id="run-2").streaming_content).decode("utf-8")
        self.assertIn("RUN_FINISHED", body)
        stale.refresh_from_db()
        self.assertEqual(stale.status, ChatRun.Status.FAILED)
        self.assertEqual(ChatRun.objects.filter(session=self.session, status=ChatRun.Status.RUNNING).count(), 0)
        self.assertEqual(ChatRun.objects.get(run_id="run-2").status, ChatRun.Status.COMPLETED)

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_out_of_order_prepared_runs_use_their_own_final_prompt(self, stream):
        stream.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-1"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"Готово"}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-1"}\n\n',
        ])
        self.assertEqual(self.prepare(run_id="run-1", prompt="prompt-1").status_code, 201)
        self.assertEqual(self.prepare(run_id="run-2", prompt="prompt-2").status_code, 201)

        list(self.run_turn(run_id="run-1").streaming_content)
        payload = stream.call_args.args[0]
        messages = payload["messages"]
        self.assertEqual(messages[-1]["content"], "prompt-1")
        self.assertNotIn("prompt-2", [message["content"] for message in messages])

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_model_id_is_frozen_at_prepare(self, stream):
        stream.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-1"}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"Готово"}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-1"}\n\n',
        ])
        self.session.metadata = {"model_id": "model-at-prepare"}
        self.session.save(update_fields=["metadata"])
        self.assertEqual(self.prepare().status_code, 201)
        self.session.refresh_from_db()
        self.session.metadata = {"model_id": "model-at-run"}
        self.session.save(update_fields=["metadata"])

        list(self.run_turn().streaming_content)
        payload = stream.call_args.args[0]
        self.assertEqual(payload["forwardedProps"]["model_id"], "model-at-prepare")
        self.assertEqual(ChatRun.objects.get(run_id="run-1").metadata["model_id"], "model-at-prepare")

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream", side_effect=RuntimeError("provider failed"))
    def test_error_audit_uses_frozen_run_model_id(self, stream):
        self.session.metadata = {"model_id": "model-at-prepare"}
        self.session.save(update_fields=["metadata"])
        self.assertEqual(self.prepare().status_code, 201)
        self.session.metadata = {"model_id": "model-at-run"}
        self.session.save(update_fields=["metadata"])

        b"".join(self.run_turn().streaming_content)
        action = AgentActionLog.objects.get(tool_code="agent_runtime.ag_ui")
        self.assertEqual(action.request_payload["model_id"], "model-at-prepare")

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_malformed_agui_order_is_persisted_as_one_safe_error(self, stream):
        stream.return_value = iter([
            'data: {"type":"RUN_FINISHED","runId":"run-1"}\n\n',
        ])
        self.assertEqual(self.prepare().status_code, 201)
        body = b"".join(self.run_turn().streaming_content).decode("utf-8")
        self.assertEqual(body.count("RUN_STARTED"), 1)
        self.assertEqual(body.count("RUN_ERROR"), 1)
        self.assertNotIn("RUN_FINISHED", body)
        run = ChatRun.objects.get(run_id="run-1")
        self.assertEqual(run.status, ChatRun.Status.FAILED)
        self.assertEqual(
            [event["type"] for event in run.metadata["events"]],
            ["RUN_STARTED", "RUN_ERROR"],
        )

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_duplicate_run_started_is_persisted_as_one_safe_error(self, stream):
        stream.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-1"}\n\n',
            'data: {"type":"RUN_STARTED","runId":"run-1"}\n\n',
        ])
        self.assertEqual(self.prepare().status_code, 201)
        body = b"".join(self.run_turn().streaming_content).decode("utf-8")
        self.assertEqual(body.count("RUN_STARTED"), 1)
        self.assertEqual(body.count("RUN_ERROR"), 1)
        run = ChatRun.objects.get(run_id="run-1")
        self.assertEqual(run.status, ChatRun.Status.FAILED)
        self.assertEqual(sum(event["type"] == "RUN_ERROR" for event in run.metadata["events"]), 1)

    def test_native_gateway_fence_rejects_archived_and_failed_runs(self):
        self.assertEqual(self.prepare().status_code, 201)
        run = ChatRun.objects.get(run_id="run-1")
        run.status = ChatRun.Status.RUNNING
        run.metadata = {**run.metadata, "request_id": "native-request"}
        run.save(update_fields=["status", "metadata"])
        native_actor = {
            "user_id": self.user.id,
            "username": self.user.username,
            "source": "django-native-ai-ui",
            "origin_channel": "native",
            "channel": self.session.channel,
        }

        self.session.status = ChatSession.Status.ARCHIVED
        self.session.save(update_fields=["status"])
        with self.assertRaises(PermissionDenied):
            execute_tool(
                tool_code="workorders.list",
                actor_context=native_actor,
                payload={},
                session_external_id=str(self.session.external_id),
                request_id="native-request",
                origin_channel="native",
            )

        self.session.status = ChatSession.Status.ACTIVE
        self.session.save(update_fields=["status"])
        run.status = ChatRun.Status.FAILED
        run.save(update_fields=["status"])
        with self.assertRaises(PermissionDenied):
            execute_tool(
                tool_code="workorders.list",
                actor_context=native_actor,
                payload={},
                session_external_id=str(self.session.external_id),
                request_id="native-request",
                origin_channel="native",
            )

    @patch("apps.ai.views.AgentRuntimeClient.ag_ui_stream")
    def test_proxy_does_not_forward_raw_tool_data_or_unknown_events(self, stream):
        stream.return_value = iter([
            'data: {"type":"RUN_STARTED","runId":"run-1"}\n\n',
            'data: {"type":"CUSTOM","name":"unknown","value":"secret-custom"}\n\n',
            'data: {"type":"TOOL_CALL_ARGS","toolCallId":"t1","delta":"password=secret"}\n\n',
            'data: {"type":"TOOL_CALL_RESULT","toolCallId":"t1","content":"secret-result"}\n\n',
            'data: {"type":"RUN_FINISHED","runId":"run-1"}\n\n',
        ])
        self.assertEqual(self.prepare().status_code, 201)
        body = b"".join(self.run_turn().streaming_content).decode("utf-8")
        self.assertNotIn("secret-custom", body)
        self.assertNotIn("password=secret", body)
        self.assertNotIn("secret-result", body)
        self.assertIn("received", body)
        self.assertIn("completed", body)
