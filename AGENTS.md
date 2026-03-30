# AGENTS.md

## Purpose

Short execution protocol for agents working in this repo.
Use bounded slices. Prefer enforced contracts over prompt-only assumptions.

## Sources Of Truth

- Tool definitions: `apps/ai/tool_definitions.py`
  `config/ai/tools.json` is generated from code.
- Tool execution and confirmation flow: `apps/ai/tooling.py`
- Pending confirmation state: `apps/ai/models.py` (`PendingAction`, `AgentActionLog`)
- Bounded task-type contracts: `services/agent_runtime/task_types.py`
- Contract validation: `apps/core/json_utils.py` and `python manage.py validate_architecture_contracts`

Do not treat `config/ai/tools.json` as hand-edited source of truth.

## Bootstrap

```bash
make venv
make install
make check
make test
make contracts
```

If the slice adds migrations, also run:

```bash
./.venv/bin/python manage.py migrate
```

## Slice Workflow

1. Pick one bounded architectural slice.
2. Change code first, then generated/derived artifacts.
3. Keep runtime, gateway, tests, and docs in sync.
4. If tool signatures change, regenerate and revalidate contracts before finishing.
5. If behavior changes materially, update `PROJECT_HANDOFF.md` and this file if protocol changed.

## Verification

Minimum before completion:

```bash
make check
make test
make contracts
```

When touching AI/runtime code, also run:

```bash
./.venv/bin/python -m py_compile services/agent_runtime/*.py apps/ai/*.py apps/core/*.py
```

## AI Contract Rules

- Edit tool definitions in `apps/ai/tool_definitions.py`, then sync generated registry:

```bash
./.venv/bin/python manage.py sync_ai_tool_registry
make contracts
```

- Bounded executable task types currently cover:
  - `workorders` (list, detail, create, transition, comment, confirm_closure, rate)
  - `lookup` (departments, devices)
  - `inventory` (devices.create, devices.update, devices.archive)
  - `analytics` (summary.status, summary.departments, summary.assignees)
- Keep task-type logic aligned with:
  - `config/ai/task_types.json`
  - `services/agent_runtime/task_types.py`
  - `apps/ai/tooling.py`

## Write Safety

- Write tools must respect confirmation flow.
- `workorders.create` and `workorders.transition` must go through `PendingAction`.
- Do not bypass confirmation by directly executing write-paths.
- Keep trace fields flowing through the stack:
  - `conversation_id`
  - `request_id`
  - `origin_channel`
  - `actor_version`

## Handoff

- `PROJECT_HANDOFF.md` is the human/project overview.
- `AGENTS.md` is the short execution protocol for future agents.
- If you change enforced AI behavior, update both when needed.
