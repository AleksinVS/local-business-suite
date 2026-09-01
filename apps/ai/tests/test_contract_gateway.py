import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.db import DatabaseError

from apps.ai.views import AIContractSnapshotView
from apps.ai.chat_settings import get_chat_settings
from apps.settings_center.document_hashes import document_hash
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_repository import ConfigDocumentRepository
from apps.settings_center.models import RuntimeSettingDocument
from services.agent_runtime.contract_cache import (
    AgentContractCache,
    aggregate_etag,
    content_hash,
)


pytestmark = pytest.mark.integration


class FakeRepository:
    def get_snapshot(self, document_ids, request=None):
        return {
            document_id: SimpleNamespace(
                document_id=document_id,
                schema_version=1,
                revision=1,
                payload={"document": document_id},
                content_hash=content_hash({"document": document_id}),
            )
            for document_id in document_ids
        }


def ai_policy_snapshot():
    from django.conf import settings

    root = settings.BASE_DIR
    return {
        "ai.contract.tools": {
            "payload": json.loads((root / "contracts/ai/tools.json").read_text())
        },
        "ai.contract.task_types": {
            "payload": json.loads((root / "contracts/ai/task_types.json").read_text())
        },
    }


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="gateway-secret")
class AIContractGatewayTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = AIContractSnapshotView.as_view()

    def request(self, query="ids=ai.contract.tools&ids=ai.contract.models", **headers):
        return self.factory.get(
            "/ai/gateway/contracts/?" + query,
            **{"HTTP_X_AI_GATEWAY_TOKEN": "gateway-secret", **headers},
        )

    def test_missing_identity_is_closed_and_same_as_wrong_identity(self):
        missing = self.factory.get("/ai/gateway/contracts/?ids=ai.contract.tools")
        wrong = self.factory.get(
            "/ai/gateway/contracts/?ids=ai.contract.tools",
            HTTP_X_AI_GATEWAY_TOKEN="wrong",
        )
        self.assertEqual(self.view(missing).status_code, 403)
        self.assertEqual(self.view(missing).content, self.view(wrong).content)

    def test_unknown_id_does_not_disclose_document_presence(self):
        response = self.view(self.request("ids=ai.contract.not_a_real_document"))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"not_a_real_document", response.content)

    def test_snapshot_has_strong_etag_and_304_has_no_body(self):
        with patch("apps.ai.views.ConfigDocumentRepository", return_value=FakeRepository()):
            first = self.view(self.request())
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first["ETag"].startswith('"'))
            self.assertTrue(first["ETag"].endswith('"'))
            second = self.view(self.request(HTTP_IF_NONE_MATCH=first["ETag"]))
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.content, b"")

    def test_write_method_is_not_an_endpoint(self):
        request = self.factory.post(
            "/ai/gateway/contracts/",
            data="{}",
            content_type="application/json",
            HTTP_X_AI_GATEWAY_TOKEN="gateway-secret",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 405)

    def test_200_requires_current_strong_etag_for_304(self):
        with patch("apps.ai.views.ConfigDocumentRepository", return_value=FakeRepository()):
            first = self.view(self.request())
            wrong = self.view(self.request(HTTP_IF_NONE_MATCH='"not-current"'))
            missing = self.view(self.request(HTTP_IF_NONE_MATCH=""))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(wrong.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(wrong["ETag"], first["ETag"])

    def test_server_etag_matches_runtime_algorithm_for_full_set(self):
        from apps.ai.config_documents import AI_RUNTIME_DOCUMENT_IDS
        from services.agent_runtime.contract_cache import aggregate_etag as runtime_etag

        repository = FakeRepository()
        with patch("apps.ai.views.ConfigDocumentRepository", return_value=repository):
            response = self.view(
                self.request("ids=" + "&ids=".join(AI_RUNTIME_DOCUMENT_IDS))
            )
        documents = json.loads(response.content)["documents"]
        self.assertEqual(response["ETag"], aggregate_etag(documents))
        self.assertEqual(response["ETag"], runtime_etag(documents))

    def test_unknown_duplicate_and_empty_sets_are_closed(self):
        for query in (
            "ids=ai.contract.tools&ids=ai.contract.tools",
            "ids=ai.contract.not_allowed",
            "",
        ):
            response = self.view(self.request(query))
            self.assertEqual(response.status_code, 404)
            self.assertNotIn(b"not_allowed", response.content)

    def test_repository_error_is_safe_503_without_error_details(self):
        broken = FakeRepository()
        broken.get_snapshot = lambda *args, **kwargs: (_ for _ in ()).throw(
            DatabaseError("secret database details")
        )
        with patch("apps.ai.views.ConfigDocumentRepository", return_value=broken):
            response = self.view(self.request("ids=ai.contract.tools"))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"secret database details", response.content)


class AIPolicyExecutionTests(SimpleTestCase):
    def test_django_execution_rejects_tool_outside_delivered_task_policy(self):
        from django.core.exceptions import ValidationError

        from apps.ai.tooling import execute_tool

        snapshot = ai_policy_snapshot()
        snapshot["ai.contract.task_types"]["payload"] = {
            "task_types": [
                {
                    "id": "only.lookup",
                    "title": "Only lookup",
                    "mode": "read",
                    "allowed_tools": ["workorders.list"],
                    "requires_confirmation": False,
                }
            ]
        }
        with self.assertRaises(ValidationError):
            execute_tool(
                tool_code="workorders.create",
                actor_context={},
                payload={},
                contract_snapshot=snapshot,
            )

    def test_django_confirmation_policy_is_read_from_delivered_snapshot(self):
        from apps.ai.config_documents import resolve_effective_tool_policy

        policy = resolve_effective_tool_policy(
            "workorders.create", snapshot=ai_policy_snapshot()
        )
        self.assertTrue(policy["requires_confirmation"])


@override_settings(LOCAL_BUSINESS_AI_GATEWAY_TOKEN="gateway-secret")
class AIChatSettingsDatabaseTests(TestCase):
    """The released DB override is observed by Django without a restart."""

    databases = {"default"}

    def test_chat_settings_change_is_visible_on_next_repository_snapshot(self):
        with self.settings(
            LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=("ai.contract.chat_settings",)
        ):
            get_document_registry.cache_clear()
            try:
                repository = ConfigDocumentRepository()
                default = repository.get_document("ai.contract.chat_settings")
                payload = dict(default.payload)
                payload["defaults"] = dict(payload["defaults"])
                payload["defaults"]["recent_message_limit"] = 11
                payload["surfaces"] = dict(payload["surfaces"])
                payload["surfaces"]["full_page"] = dict(payload["surfaces"]["full_page"])
                payload["surfaces"]["full_page"]["recent_message_limit"] = 11
                RuntimeSettingDocument.objects.create(
                    document_id=default.document_id,
                    schema_version=default.schema_version,
                    payload=payload,
                    revision=1,
                    content_hash=document_hash(payload),
                    default_hash=default.default_hash,
                )
                self.assertEqual(
                    get_chat_settings()["recent_message_limit"],
                    11,
                )

                payload["defaults"]["recent_message_limit"] = 17
                payload["surfaces"]["full_page"]["recent_message_limit"] = 17
                row = RuntimeSettingDocument.objects.get(pk=default.document_id)
                row.payload = payload
                row.revision = 2
                row.content_hash = document_hash(payload)
                row.save(update_fields=["payload", "revision", "content_hash", "updated_at"])
                self.assertEqual(
                    get_chat_settings()["recent_message_limit"],
                    17,
                )
            finally:
                get_document_registry.cache_clear()

    def test_persistent_db_document_reaches_runtime_cache_through_django_transport(self):
        """Exercise DB row -> Django view -> real cache, including 304."""
        with self.settings(
            LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=("ai.contract.chat_settings",)
        ):
            get_document_registry.cache_clear()
            try:
                repository = ConfigDocumentRepository()
                default = repository.get_document("ai.contract.chat_settings")
                payload = deepcopy(default.payload)
                payload["defaults"] = dict(payload["defaults"])
                payload["defaults"]["recent_message_limit"] = 13
                payload["surfaces"] = dict(payload["surfaces"])
                payload["surfaces"]["full_page"] = dict(payload["surfaces"]["full_page"])
                payload["surfaces"]["full_page"]["recent_message_limit"] = 13
                RuntimeSettingDocument.objects.create(
                    document_id=default.document_id,
                    schema_version=default.schema_version,
                    payload=payload,
                    revision=1,
                    content_hash=document_hash(payload),
                    default_hash=default.default_hash,
                )
                self.assertEqual(
                    ConfigDocumentRepository().get_document("ai.contract.chat_settings").revision,
                    1,
                )

                requests = []

                class RecordingDjangoTransport(httpx.BaseTransport):
                    def __init__(self):
                        self.client = self._make_client()

                    @staticmethod
                    def _make_client():
                        from django.test import Client

                        return Client()

                    def handle_request(self, request):
                        query = request.url.query.decode("ascii")
                        path = request.url.path
                        if query:
                            path += "?" + query
                        response = self.client.generic(
                            request.method,
                            path,
                            data=request.content,
                            headers=dict(request.headers),
                        )
                        requests.append(response.status_code)
                        return httpx.Response(
                            response.status_code,
                            headers=dict(response.headers),
                            content=response.content,
                            request=request,
                        )

                transport = RecordingDjangoTransport()
                client = httpx.Client(transport=transport, base_url="http://testserver")
                cache = AgentContractCache(
                    gateway_url="http://testserver/ai/gateway",
                    token="gateway-secret",
                    requested_ids=("ai.contract.chat_settings",),
                    client=client,
                )
                try:
                    first = cache.snapshot()
                    self.assertEqual(requests, [200])
                    self.assertEqual(first["ai.contract.chat_settings"]["revision"], 1)
                    first_hash = first["ai.contract.chat_settings"]["content_hash"]

                    payload["defaults"]["recent_message_limit"] = 19
                    payload["surfaces"]["full_page"]["recent_message_limit"] = 19
                    row = RuntimeSettingDocument.objects.get(pk=default.document_id)
                    row.payload = payload
                    row.revision = 2
                    row.content_hash = document_hash(payload)
                    row.save(update_fields=["payload", "revision", "content_hash", "updated_at"])

                    second = cache.snapshot()
                    self.assertEqual(requests, [200, 200])
                    self.assertEqual(second["ai.contract.chat_settings"]["revision"], 2)
                    self.assertNotEqual(
                        second["ai.contract.chat_settings"]["content_hash"], first_hash
                    )
                    third = cache.snapshot()
                    self.assertEqual(requests, [200, 200, 304])
                    self.assertEqual(third, second)
                finally:
                    client.close()
            finally:
                get_document_registry.cache_clear()


def test_ai_descriptor_presentation_and_write_policy_match_document_specs():
    from apps.ai.settings_descriptors import get_settings_descriptors
    from apps.settings_center.document_registry import get_document_registry

    descriptors = {item.setting_id: item for item in get_settings_descriptors()}
    specs = {
        item.document_id: item
        for item in get_document_registry().all()
        if item.domain == "ai"
    }
    static_ids = {
        "ai.contract.registry",
        "ai.contract.tools",
        "ai.contract.task_types",
        "ai.contract.models",
    }
    for document_id in static_ids:
        assert descriptors[document_id].widget == "json_viewer"
        assert descriptors[document_id].write_policy == "read_only"
        assert specs[document_id].storage_policy == "git_static"
        assert specs[document_id].write_policy == "read_only"
    assert descriptors["ai.contract.chat_settings"].widget == "json_editor"
    assert descriptors["ai.contract.chat_settings"].write_policy == "editable"
    assert specs["ai.contract.chat_settings"].storage_policy == "database_override"

    for document_id in static_ids | {"ai.contract.chat_settings"}:
        assert "settings_path" not in descriptors[document_id].metadata
