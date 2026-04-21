# Agent Runtime

External AI runtime for the Корпоративный портал ВОБ №3 chat/agent block.

Responsibilities:

- accept chat requests from the application;
- run a LangGraph-based tool-using agent;
- call the Django AI gateway for all business reads and writes;
- return the final assistant message and tool trace.
- expose the same business tools through an MCP server for external chat clients.

Runtime assumptions:

- Django remains the system of record;
- all writes go through the Django service and policy layer;
- the runtime never writes directly to the operational database.

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
- `POST /chat`
- `MCP /mcp`

LibreChat MCP example:

- [librechat.mcp.example.yaml](/home/abc/.openclaw/workspace/projects/local-business-suite/services/agent_runtime/librechat.mcp.example.yaml)

End-to-end local stack:

- [services/librechat/README.md](/home/abc/.openclaw/workspace/projects/local-business-suite/services/librechat/README.md)

For `z.ai` coding endpoint, set:

```bash
OPENAI_BASE_URL=https://api.z.ai/api/coding/paas/v4/
AI_AGENT_MODEL_NAME=glm-4.5-air
```
