# LibreChat Integration

This directory contains the isolated local integration layer for running LibreChat
on top of the existing `web + agent-runtime` stack.

## What It Does

- starts LibreChat as a separate service;
- starts MongoDB and Meilisearch required by LibreChat;
- mounts a `librechat.yaml` that points LibreChat to the existing MCP endpoint:
  - `http://agent-runtime:8090/mcp`

It does not change Django business logic or the agent runtime architecture.

## Quick Start

1. Prepare the main project env:

```bash
cp .env.example .env
```

2. Prepare LibreChat env:

```bash
cp services/librechat/.env.example services/librechat/.env
```

Or generate secrets automatically:

```bash
bash services/librechat/generate-env.sh
```

3. Fill the required provider variables in `.env` and `services/librechat/.env`:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
AI_AGENT_MODEL_NAME=...
```

4. Start the full local AI stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.librechat.yml up --build
```

5. Open LibreChat:

```text
http://localhost:3080
```

## Notes

- `docker-compose.yml` still owns `web` and `agent-runtime`.
- `docker-compose.librechat.yml` only layers the external chat client and its dependencies.
- If upstream LibreChat image tags change, override `LIBRECHAT_IMAGE` in your shell or `.env`.
- LibreChat will see the Local Business Suite MCP server at `agent-runtime:8090/mcp`.

### Z.AI Example

For `z.ai` coding endpoint, use:

```bash
OPENAI_BASE_URL=https://api.z.ai/api/coding/paas/v4/
AI_AGENT_MODEL_NAME=glm-4.5-air
```
