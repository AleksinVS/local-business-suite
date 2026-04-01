# PM Acceptance Instruction (Slice: ui-foundation, Task: task-ui-foundation)

You are the PM (L2). This is an acceptance review of completed work for:

- block: `block-waiting-list-ui-2026-03-31`
- slice: `slice-ui-foundation`
- task: `task-ui-foundation`

## What Changed

Expected write scope for this task:

- `templates/base.html`
- `static/src/css/app.css`

Executor report:

- `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.task-ui-foundation.md`

## What To Verify

- Changes are limited to the allowed write scope.
- `templates/base.html` still preserves HTMX CSRF header + existing block structure + workorders drawer contract.
- CSS additions are consistent with reference UI style intent (from `drafts/waiting_list.html`) and do not obviously regress existing pages.
- Required check for this task: `./.venv/bin/python manage.py check`
  - If you cannot run commands in this environment, rely on the executor report and record the limitation in the decision packet.

## Required Output (Write To Disk)

Write `workflow/block-waiting-list-ui-2026-03-31/PM_DECISION_PACKET.md` using the exact contract fields:

- goal
- status
- files changed
- checks
- deviations
- risks
- docs updated: yes/no
- slice tasks cleared: yes/no
- decision needed

Keep it short.

