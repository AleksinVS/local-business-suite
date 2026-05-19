# Task Acceptance: task-memory-retrieval-tool

Block: `block-ai-memory-service-2026-05-19`

Task: `task-memory-retrieval-tool`

Decision: accepted

## Acceptance Review

The task satisfies the declared scope:

- `memory.search` is declared as a read-only AI tool without confirmation.
- Python and JSON tool registries are aligned.
- Bounded task type support exists for `memory.search`.
- Runtime dispatcher executes `memory.search` through the memory retrieval service.
- Successful responses include citations.
- Forbidden scope requests return no context.
- Secret-route requests are denied and audited.
- Backend retrieval results are post-filtered by Django policy and safe-corpus path checks.

## Required Checks

All required checks passed:

- `./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests`
- `./.venv/bin/python manage.py check`
- `./.venv/bin/python manage.py validate_architecture_contracts`

Additional checks passed:

- `python3 -m json.tool contracts/ai/tools.json`
- `python3 -m json.tool contracts/ai/task_types.json`

## Notes

The next implementation candidate is `task-memory-jobs-eval-admin`: source/index job orchestration, smoke/security evals, and admin/operator surfaces around the now-existing contracts, privacy pipeline, indexing, and retrieval tool.
