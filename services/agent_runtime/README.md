# Agent Runtime

External AI runtime for the Корпоративный портал ВОБ №3 chat/agent block.

Responsibilities:

- accept chat requests from the application;
- run a LangGraph-based tool-using agent;
- load and activate module/runtime AI skills from the Django gateway;
- call the Django AI gateway for all business reads and writes;
- return the final assistant message and tool trace.
- expose safe read-only metadata resources through MCP; user-scoped business
  tools remain on authenticated Django/AG-UI routes until MCP has a trusted
  per-request principal.

Runtime assumptions:

- Django remains the system of record;
- all writes go through the Django service and policy layer;
- the runtime never writes directly to the operational database.
- module-specific workflows live in AI skills, not in `graph.py`.

## AI contract delivery

The runtime receives one authenticated aggregate snapshot from Django at
`GET /ai/gateway/contracts/?ids=...`. The request must contain the explicit
allowlisted IDs (`registry`, `tools`, `task_types`, `models` and
`chat_settings`); the gateway never lists arbitrary Settings Center
documents. Each document envelope contains `document_id`, `schema_version`,
`revision`, `content_hash` and `payload`. The response has a strong aggregate
ETag over the sorted document metadata. A matching `If-None-Match` returns
`304` without a body.

`services/agent_runtime/contract_cache.py` validates the exact requested set,
schema version, canonical SHA-256 payload hashes and ETag before atomically
replacing the complete last-known-good (LKG) set. Network I/O is outside the
state lock, and a concurrent caller can use a fresh LKG while another caller
refreshes it. A successful `200` or `304` updates the validation timestamp;
gateway failures do not replace the LKG. The default maximum stale age is 300
seconds and can be changed with the scalar
`LOCAL_BUSINESS_AI_CONTRACT_MAX_STALE_AGE_SECONDS`. Before the first valid
snapshot, or after that age expires, delivery fails closed.

Startup and `GET /health/details` expose only safe delivery diagnostics:
`source`, `age`, `revisions`, `hashes` and an error code. Payloads, secrets and
filesystem paths are never returned. The operation graph freezes one full
snapshot and passes it to model selection, prompt construction, tools, task
policy and MCP metadata. Therefore a changed database-backed `chat_settings`
document is observed on the next operation without restarting the runtime.

Tool capabilities are fail-closed at two boundaries. The effective set is the
intersection of the static Python registry, the delivered `tools` document and
mode-compatible `task_types.allowed_tools`; the Python registry is the
security ceiling. A helper listed by both a write task and a lookup task uses
the exact/mode-compatible lookup policy, so it does not inherit write
confirmation accidentally. The runtime resolves this policy before invoking a
LangChain tool, and Django resolves it again before creating or confirming an
action. Missing, conflicting or drifting policy denies the call. A health
response with no LKG reports `age: null`, never a non-JSON infinity value.

The runtime does not read `data/contracts/ai/` and never writes to Django's
state directory. The Django gateway remains the source of truth. AG-UI and
CopilotKit stay on the approved profile `0.0.55`; no dependency or wire
contract update is part of this delivery (the newer `0.0.59` was not adopted).

Required environment:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `AI_AGENT_MODEL_NAME` or `AI_AGENT_MODEL`
- `AI_AGENT_MODEL` (default: `openai:gpt-4.1-mini`)
- `DJANGO_AI_GATEWAY_URL`
- `LOCAL_BUSINESS_AI_GATEWAY_TOKEN`

Run locally:

```bash
uvicorn services.agent_runtime.app:app --host 0.0.0.0 --port 8090 --reload
```

Endpoints:

- `GET /health`
- `GET /health/details` — safe aggregate delivery diagnostics, without paths or payloads
- `POST /ag-ui` — canonical AG-UI stream for Django and CopilotKit clients
- `MCP /mcp`

MCP resources:

- `local-business://skills/{skill_id}`
- `local-business://tools/{tool_code}`
- `local-business://modules/{source_code}/capabilities`

MCP is an external metadata facade in the current deployment. Its streamable
HTTP transport has a shared gateway credential but no verified per-request
user subject, so user-scoped project tools are intentionally not registered.
This prevents a client from selecting an arbitrary `user_id`, roles, or
session and reaching Django pending actions or business tools. The three
read-only metadata resources remain available. Django is the system of record
for chat sessions, messages and runs; native browser clients use Django's
authenticated session-specific prepare/run endpoints, while CopilotKit's Node
runtime calls `/ag-ui` directly. A future MCP project-tool surface requires a
trusted bound principal/token claim and an allowlisted service scope.

The former `/chat` and `/chat/stream` runtime endpoints are removed. Native
browser execution is `POST /ai/chat/<session>/turn/prepare/` followed by
`POST /ai/chat/<session>/turn/run/`; deploy the Django `ChatRun` migration before
enabling traffic. After changing native static assets, run
`python manage.py collectstatic --noinput` and
`python manage.py check_staticfiles --fail`.

For `z.ai` coding endpoint, set:

```bash
OPENAI_BASE_URL=https://api.z.ai/api/coding/paas/v4/
AI_AGENT_MODEL_NAME=glm-4.5-air
```
