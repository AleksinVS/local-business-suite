# Executor Report: task-memory-retrieval-tool

Block: `block-ai-memory-service-2026-05-19`

Slice: `slice-retrieval-tool`

Task: `task-memory-retrieval-tool`

Status: completed

## Scope

Implemented `memory.search` as the read-only runtime access path to the memory service. The tool returns compact cited context only, keeps route decisions server-side, post-filters backend candidates through Django policy checks, and records `MemoryAccessAudit` entries.

## Subagents

- Retrieval worker: implemented `apps.memory.routing` and `apps.memory.retrieval`.
- Tool registry worker: added `memory.search` to Python/JSON tool registries and bounded task types.
- Orchestrator integration: wired `apps.ai.tooling`, synchronized local runtime contract copies in `data/contracts/ai/` for validation, added end-to-end tests, and recorded acceptance.

## Changed Files

- `apps/memory/retrieval.py`
- `apps/memory/routing.py`
- `apps/memory/tests.py`
- `apps/memory/.desc.json`
- `apps/ai/tool_definitions.py`
- `apps/ai/tooling.py`
- `apps/ai/tests.py`
- `contracts/ai/tools.json`
- `contracts/ai/task_types.json`
- `services/agent_runtime/task_types.py`
- `workflow/active/block-ai-memory-service-2026-05-19/.desc.json`
- `PROJECT_STRUCTURE.yaml`

## Implementation Notes

- `memory_search()` accepts actor, query, optional scope tokens, sensitivity, limit, and optional backend overrides for tests.
- Vector/full-text and graph results are treated as candidates only; chunks/facts are reloaded from Django and checked with `can_access_chunk()` / `can_access_graph_fact()`.
- Chunk text is read only from `data/memory/safe_corpus/`; raw snapshot paths are never returned.
- Every returned item includes `citation_ids`; response-level `citations` include source code, source object id, chunk/fact id, snapshot hash, text hash, position, and sensitivity.
- Secret and original-PII routes are denied by server-side routing policy.
- Successful and denied retrieval attempts write `MemoryAccessAudit` with query hash, returned ids, policy decision, and retrieval trace.
- `execute_tool()` now enriches `_dispatch_tool()` calls with trace context so `memory.search` receives `request_id` for audit.

## Verification

| Check | Result |
| --- | --- |
| `python3 -m json.tool contracts/ai/tools.json` | PASS |
| `python3 -m json.tool contracts/ai/task_types.json` | PASS |
| `./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests` | PASS, 70 tests |
| `./.venv/bin/python manage.py check` | PASS |
| `./.venv/bin/python manage.py validate_architecture_contracts` | PASS |

## Deferred

- Retrieval fusion is still simple candidate ordering: vector/full-text results first, graph results second.
- No cloud route dispatch was implemented.
- No external MCP/server adapter change was made in this slice.
- Richer query planning and ranking evaluation remain for the jobs/eval/admin slice.
