# Agent Runtime

External AI runtime for the Корпоративный портал ВОБ №3 chat/agent block.

Responsibilities:

- accept chat requests from the application;
- run a LangGraph-based tool-using agent;
- load and activate module/runtime AI skills from the Django gateway;
- call the Django AI gateway for all business reads and writes;
- return the final assistant message and tool trace.
- expose business tools and safe read-only resources through an MCP server for external chat clients.

Runtime assumptions:

- Django remains the system of record;
- all writes go through the Django service and policy layer;
- the runtime never writes directly to the operational database.
- module-specific workflows live in AI skills, not in `graph.py`.

## AI contracts (tools/task types/models)

`tools.json`, `task_types.json` and `models.json` are read from
`data/contracts/ai/` (the Settings Center working copy) when present,
falling back to the packaged default in `contracts/ai/` (see
`services/agent_runtime/config.py:_resolve_contract` / `_contract_path`
and ADR-0031). Path resolution is re-run on every read — nothing about
*which* file to use is cached — so a working copy created or changed
after this process started is picked up on the next read; only the
parsed JSON *content* behind a given resolved path is cached, and that
cache is invalidated by `(st_mtime_ns, st_size, st_ino)`
(`services/agent_runtime/contract_cache.py`), the same key used by the
Django-side contract store. In practice this means Settings Center
edits reach a running agent-runtime process without a restart.

In Docker, `docker-compose.yml` and `docker-compose.prod.yml` mount
`./data` into the `agent-runtime` container **read-only**
(`./data:/app/data:ro`) — this is a deliberate one-way delivery: the
runtime must never be able to write to Django's state directory. If
that mount is missing (or `data/contracts/ai/*.json` has not been
created yet, e.g. on the very first `docker compose up`, before
Django's own contract bootstrap has run), the runtime falls back to
the packaged default and logs a `WARNING` naming the missing file at
startup. Local (non-Docker) runs read `data/contracts/` directly off
the same filesystem, so `make ai-runtime` / `uvicorn --reload` behave
exactly as before this delivery mechanism was introduced.

At startup (and via `GET /health/details`) the runtime reports which
source (`override` / `runtime` / `default`) and path it actually used
for each contract — see `config.describe_contract_sources()` and
`app._log_contract_sources_at_startup()`. Treat a `default` source (or
`contracts_degraded: true` in `/health/details`) in a Docker deployment
as a configuration bug: it means Settings Center edits are silently not
reaching the agent.

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
- `GET /health/details` — includes the resolved contract sources/paths
- `POST /ag-ui` — canonical AG-UI stream for Django and CopilotKit clients
- `MCP /mcp`

MCP resources:

- `local-business://skills/{skill_id}`
- `local-business://tools/{tool_code}`
- `local-business://modules/{source_code}/capabilities`

MCP is an external facade. Django is the system of record for chat sessions,
messages and runs; native browser clients use Django's session-specific
prepare/run endpoints, while CopilotKit's Node runtime calls `/ag-ui` directly.

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
