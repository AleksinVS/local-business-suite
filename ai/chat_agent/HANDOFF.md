# Chat Agent Handoff

This directory contains the contract layer for the chat and agent block.
The initial runtime and Django integration now exist, so the next implementation agent should continue from those concrete surfaces instead of starting from scratch.

## What Exists

- `ai/chat_agent/ARCHITECTURE.md` defines the target architecture.
- `config/ai/registry.json` declares the active runtime profile.
- `config/ai/tools.json` declares the tool catalog.
- `config/ai/task_types.json` declares the task-intent catalog.
- `config/schemas/*.schema.json` describes the JSON shape of those contracts.
- `apps/ai/*` contains the Django-side chat UI, AI session storage, action audit, and Django AI gateway.
- `services/agent_runtime/*` contains the external LangGraph-based runtime service.

## What the Next Agent Should Do First

1. Read `ai/chat_agent/ARCHITECTURE.md`.
2. Read `config/ai/registry.json`.
3. Read `config/ai/tools.json` and `config/ai/task_types.json`.
4. Read `apps/ai/views.py`, `apps/ai/tooling.py`, and `apps/ai/services.py`.
5. Read `services/agent_runtime/app.py`, `services/agent_runtime/graph.py`, and `services/agent_runtime/tools.py`.
6. Continue with the next missing pieces:
   - wire an MCP-compatible server surface in front of the Django AI gateway or agent runtime;
   - add richer tool coverage such as attachments and assignment actions;
   - connect an external chat frontend such as LibreChat to the runtime.

## Non-Goals For The First Slice

- No direct prompt-only writes to the database.
- No new business rules outside the existing service layer.
- No analytics UI work in this slice.
- No attempt to support every future integration at once.

## Delivery Principle

The chat block should remain thin:

- UI in the chat frontend;
- orchestration in the agent runtime;
- business decisions in the domain services;
- contracts in JSON and markdown.
