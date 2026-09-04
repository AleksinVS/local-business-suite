import httpx
import json
import pytest
from threading import Event, Thread
from pathlib import Path
from unittest.mock import patch

from services.agent_runtime.contract_cache import (
    AgentContractCache,
    ContractDeliveryError,
    aggregate_etag,
    content_hash,
)

pytestmark = pytest.mark.unit


DOC_ID = "ai.contract.chat_settings"


def ai_policy_snapshot():
    root = Path(__file__).resolve().parents[3]
    return {
        "ai.contract.tools": {
            "payload": json.loads((root / "contracts/ai/tools.json").read_text())
        },
        "ai.contract.task_types": {
            "payload": json.loads((root / "contracts/ai/task_types.json").read_text())
        },
    }


def envelope(payload=None, *, revision=1, schema_version=1):
    payload = payload or {"value": 1}
    document = {
        "document_id": DOC_ID,
        "schema_version": schema_version,
        "revision": revision,
        "content_hash": content_hash(payload),
        "payload": payload,
    }
    return {"documents": [document]}, aggregate_etag([document])


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def make_cache(handler, clock=None, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AgentContractCache(
        gateway_url="http://gateway/ai/gateway",
        token="secret-token",
        requested_ids=(DOC_ID,),
        client=client,
        clock=clock or Clock(),
        **kwargs,
    )


def test_valid_snapshot_and_conditional_poll():
    body, etag = envelope()
    requests = []

    def handler(request):
        requests.append(request)
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"ETag": etag})
        return httpx.Response(200, json=body, headers={"ETag": etag})

    cache = make_cache(handler)
    assert cache.snapshot()[DOC_ID]["revision"] == 1
    assert cache.snapshot()[DOC_ID]["payload"] == {"value": 1}
    assert len(requests) == 2
    assert requests[1].headers["if-none-match"] == etag


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body["documents"].pop(),
        lambda body: body["documents"][0].update(content_hash="0" * 64),
        lambda body: body["documents"][0].update(schema_version=2),
    ],
)
def test_invalid_or_partial_snapshot_does_not_replace_lkg(mutate):
    good_body, good_etag = envelope()
    bad_body, _ = envelope({"value": 2}, revision=2)
    mutate(bad_body)
    calls = [0]

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(200, json=good_body, headers={"ETag": good_etag})
        return httpx.Response(200, json=bad_body, headers={"ETag": "\"bad\""})

    cache = make_cache(handler)
    assert cache.snapshot()[DOC_ID]["revision"] == 1
    assert cache.snapshot()[DOC_ID]["revision"] == 1
    assert cache.diagnostics()["source"] == "lkg"


def test_outage_fails_closed_after_stale_age():
    body, etag = envelope()
    clock = Clock()

    def handler(request):
        if clock.value == 0:
            return httpx.Response(200, json=body, headers={"ETag": etag})
        raise httpx.ConnectError("offline", request=request)

    cache = make_cache(handler, clock=clock, max_stale_age=300)
    cache.snapshot()
    clock.value = 301
    with pytest.raises(ContractDeliveryError):
        cache.snapshot()
    assert cache.diagnostics()["source"] == "lkg"
    assert cache.diagnostics()["age"] == 301


def test_successful_304_refreshes_validation_age_before_outage():
    body, etag = envelope()
    clock = Clock()
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=body, headers={"ETag": etag})
        if len(calls) == 2:
            return httpx.Response(304, headers={"ETag": etag})
        raise httpx.ConnectError("offline", request=request)

    cache = make_cache(handler, clock=clock, max_stale_age=300)
    cache.snapshot()
    clock.value = 100
    cache.snapshot()
    assert cache.last_validated_at == 100
    clock.value = 399
    assert cache.snapshot()[DOC_ID]["revision"] == 1
    clock.value = 401
    with pytest.raises(ContractDeliveryError):
        cache.snapshot()


def test_missing_or_mismatched_etag_never_enters_or_replaces_lkg():
    body, etag = envelope()
    calls = [0]

    def missing_handler(request):
        return httpx.Response(200, json=body)

    with pytest.raises(ContractDeliveryError):
        make_cache(missing_handler).snapshot()

    def mismatch_handler(request):
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(200, json=body, headers={"ETag": etag})
        return httpx.Response(304, headers={"ETag": '"wrong"'})

    cache = make_cache(mismatch_handler)
    cache.snapshot()
    assert cache.snapshot()[DOC_ID]["revision"] == 1
    assert cache.diagnostics()["error"] == "invalid_gateway_snapshot"


def test_revision_only_change_changes_aggregate_etag():
    first, first_etag = envelope({"same": True}, revision=1)
    second, second_etag = envelope({"same": True}, revision=2)
    assert first["documents"][0]["content_hash"] == second["documents"][0]["content_hash"]
    assert first_etag != second_etag


def test_all_five_document_hash_and_etag_parity():
    from services.agent_runtime.contract_cache import AI_DOCUMENT_IDS

    documents = []
    for index, document_id in enumerate(AI_DOCUMENT_IDS, start=1):
        payload = {"document_id": document_id, "value": index}
        documents.append(
            {
                "document_id": document_id,
                "schema_version": 1,
                "revision": index,
                "content_hash": content_hash(payload),
                "payload": payload,
            }
        )
    body = {"documents": documents}
    client_etag = aggregate_etag(documents)

    def handler(request):
        return httpx.Response(200, json=body, headers={"ETag": client_etag})

    cache = AgentContractCache(
        gateway_url="http://gateway/ai/gateway",
        token="secret-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    snapshot = cache.snapshot()
    assert tuple(snapshot) == tuple(sorted(AI_DOCUMENT_IDS))
    assert cache.diagnostics()["hashes"] == {
        document["document_id"]: document["content_hash"] for document in documents
    }


def test_fresh_lkg_caller_does_not_wait_for_inflight_network_refresh():
    first, first_etag = envelope({"value": 1}, revision=1)
    second, second_etag = envelope({"value": 2}, revision=2)
    calls = [0]
    refresh_started = Event()
    release_refresh = Event()

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(200, json=first, headers={"ETag": first_etag})
        refresh_started.set()
        release_refresh.wait(timeout=2)
        return httpx.Response(200, json=second, headers={"ETag": second_etag})

    cache = make_cache(handler)
    assert cache.snapshot()[DOC_ID]["revision"] == 1
    leader_result = []
    leader = Thread(target=lambda: leader_result.append(cache.snapshot()))
    leader.start()
    assert refresh_started.wait(timeout=1)
    result = cache.snapshot()
    assert result[DOC_ID]["revision"] == 1
    release_refresh.set()
    leader.join(timeout=2)
    assert not leader.is_alive()
    assert leader_result[0][DOC_ID]["revision"] == 2


def test_token_rotation_uses_separate_cache_state():
    from services.agent_runtime import contract_cache

    contract_cache.clear()
    first = contract_cache.get_gateway_cache(
        gateway_url="http://gateway/ai/gateway", token="old-token", requested_ids=(DOC_ID,)
    )
    second = contract_cache.get_gateway_cache(
        gateway_url="http://gateway/ai/gateway", token="new-token", requested_ids=(DOC_ID,)
    )
    assert first is not second


def test_effective_policy_rejects_tool_outside_delivered_task_policy():
    from services.agent_runtime.config import RuntimePolicyError, resolve_effective_tool_policy

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
    with pytest.raises(RuntimePolicyError):
        resolve_effective_tool_policy("workorders.create", snapshot=snapshot)


def test_effective_policy_rejects_tool_omitted_from_delivered_catalog():
    from services.agent_runtime.config import RuntimePolicyError, resolve_effective_tool_policy

    snapshot = ai_policy_snapshot()
    tools = snapshot["ai.contract.tools"]["payload"]["tools"]
    snapshot["ai.contract.tools"]["payload"] = {
        "tools": [item for item in tools if item["id"] != "workorders.create"]
    }
    with pytest.raises(RuntimePolicyError, match="delivered runtime policy"):
        resolve_effective_tool_policy("workorders.create", snapshot=snapshot)


def test_effective_policy_confirmation_comes_from_mode_compatible_task_snapshot():
    from services.agent_runtime.config import resolve_effective_tool_policy

    policies = __import__(
        "services.agent_runtime.config", fromlist=["get_effective_tool_policies"]
    ).get_effective_tool_policies(snapshot=ai_policy_snapshot())
    assert policies["workorders.create"]["requires_confirmation"] is True
    # departments.list is also a helper in write tasks, but its standalone
    # read task is the only mode-compatible authorization for the read tool.
    assert policies["departments.list"]["requires_confirmation"] is False
    assert resolve_effective_tool_policy(
        "workorders.create", snapshot=ai_policy_snapshot()
    )["requires_confirmation"] is True


def test_build_tools_is_filtered_by_effective_task_policy():
    from services.agent_runtime.tools import build_tools

    class Gateway:
        pass

    tools = build_tools(
        actor={},
        session_id="session",
        gateway_client=Gateway(),
        contract_snapshot=ai_policy_snapshot(),
    )
    names = {item.name for item in tools}
    assert "workorders.list" in names
    assert "workorders.create" in names
    assert "workorders.search" not in names
    assert "access.open_editor" not in names


def test_migrated_runtime_consumers_have_no_ai_file_resolver_or_path_diagnostics():
    from services.agent_runtime import app, config

    config_source = Path(config.__file__).read_text(encoding="utf-8")
    app_source = Path(app.__file__).read_text(encoding="utf-8")
    for token in (
        "_resolve_contract",
        "_contract_path",
        "ai_tools_path",
        "ai_task_types_path",
        "ai_models_path",
        "describe_contract_sources",
    ):
        assert token not in config_source
    assert "describe_contract_sources" not in app_source
    with patch.object(
        app,
        "get_ai_contract_diagnostics",
        return_value={"source": "lkg", "age": 1, "revisions": {}, "hashes": {}, "error": ""},
    ):
        assert "path" not in app.health_details().get("contracts", {})


def test_health_details_http_serializes_null_age_without_lkg():
    from fastapi.testclient import TestClient
    from services.agent_runtime import app

    diagnostics = {
        "source": "unavailable",
        "age": None,
        "revisions": {},
        "hashes": {},
        "error": "gateway_unavailable",
    }
    with patch.object(app, "load_ai_contract_snapshot", side_effect=ContractDeliveryError("offline")), patch.object(
        app, "get_ai_contract_diagnostics", return_value=diagnostics
    ):
        with TestClient(app.app) as client:
            response = client.get("/health/details")
    assert response.status_code == 200
    assert response.json()["contracts"]["age"] is None


def test_changed_delivered_task_types_update_aliases_and_tool_policy_without_restart():
    from services.agent_runtime.config import (
        normalize_status,
        resolve_task_type_for_snapshot,
    )

    first = {
        "ai.contract.task_types": {
            "payload": {
                "task_types": [
                    {
                        "id": "custom.lookup",
                        "title": "Custom lookup",
                        "mode": "read",
                        "allowed_tools": ["workorders.list"],
                        "required_slots": ["scope"],
                        "status_aliases": {"custom_status": ["Особый статус"]},
                    }
                ]
            }
        }
    }
    second = {
        "ai.contract.task_types": {
            "payload": {
                "task_types": [
                    {
                        "id": "custom.transition",
                        "title": "Custom transition",
                        "mode": "write",
                        "allowed_tools": ["workorders.transition"],
                        "required_slots": ["target"],
                        "status_aliases": {"new_status": ["Новый статус"]},
                    }
                ]
            }
        }
    }

    assert normalize_status("Особый статус", snapshot=first) == "custom_status"
    assert resolve_task_type_for_snapshot(
        "workorders.list", {"scope": "all"}, snapshot=first
    )["task_type_id"] == "custom.lookup"
    assert normalize_status("Особый статус", snapshot=second) == "Особый статус"
    assert normalize_status("Новый статус", snapshot=second) == "new_status"
    assert resolve_task_type_for_snapshot(
        "workorders.list", {"scope": "all"}, snapshot=second
    ) is None
    assert resolve_task_type_for_snapshot(
        "workorders.transition", {"target": "new"}, snapshot=second
    )["requires_confirmation"] is False
