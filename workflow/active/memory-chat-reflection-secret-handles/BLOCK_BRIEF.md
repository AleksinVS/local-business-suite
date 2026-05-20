# Workflow brief: chat-derived memory, reflection and secret handles

## Goal

Implement the missing chat-derived memory contour for the AI memory system:

- personal memory by default;
- organization memory by explicit permission or reviewed candidate promotion;
- queued `memory.remember`;
- sleep-time reflection;
- personal edit/delete through chat;
- secret handles instead of secret values in prompts, memory indexes and logs.

## Business value

The AI bot becomes useful across conversations without turning raw chat transcripts into unmanaged memory. Organization knowledge grows through governed review instead of silent shared-memory mutation.

## Read scope

- `apps/ai/`;
- `apps/memory/`;
- `apps/core/json_utils.py`;
- `contracts/ai/`;
- `contracts/schemas/`;
- `docs/adr/`;
- `docs/architecture/`;
- `docs/guides/`;
- `docs/deployment/`;
- `docs/planning/`;
- `workflow/active/memory-chat-reflection-secret-handles/`.

## Write scope

Implementation tasks may write:

- `apps/memory/`;
- `apps/ai/tool_definitions.py`;
- `contracts/ai/tools.json`;
- `contracts/schemas/` if contracts change;
- `apps/core/json_utils.py` if validators change;
- docs and tests related to memory;
- generated structure files after `.desc.json` updates.

Do not write runtime data under `data/` except through tests or documented dry-run/eval commands. Do not write temporary artifacts outside `.local/`.

## Non-goals

- No direct indexing of all chat history.
- No secret values in LLM prompts, tool traces, memory chunks, safe corpus, indexes or ordinary logs.
- No mandatory PostgreSQL migration.
- No production cloud LLM/OCR for sensitive data.

## Acceptance

- User can ask the bot to remember a fact and receive queued/accepted status.
- Personal memory is isolated and editable/deletable by the owner.
- Organization candidates from reflection require knowledge owner / graph owner review.
- Direct organization memory writes require explicit target and permission.
- Secret spans become handles; non-secret text continues ingestion.
- Tests cover scope isolation, candidate review, idempotent reflection and secret leakage.
