# PM Acceptance Instruction (Slice: existing-app-restyle, Task: task-existing-app-restyle)

You are PM (L2). Review completed work for:

- block: `block-waiting-list-ui-2026-03-31`
- slice: `slice-existing-app-restyle`
- task: `task-existing-app-restyle`

## Artifacts

- task packet: `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-existing-app-restyle.json`
- executor report (canonical): `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.md`
- executor report archive: `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.task-existing-app-restyle.md`

## Verify

- Changes stay within task `write_files` scope.
- Existing screens are restyled toward waiting-list visual system without changing business logic.
- Required checks are covered:
  - `./.venv/bin/python manage.py check`
  - `./.venv/bin/python manage.py test apps.core.tests apps.inventory.tests apps.workorders.tests apps.analytics.tests`
- If PM environment cannot execute shell commands, rely on report evidence and record limitation.

## Required Output (Write To Disk)

Write `workflow/block-waiting-list-ui-2026-03-31/PM_DECISION_PACKET.md` with exact contract fields:

- goal
- status
- files changed
- checks
- deviations
- risks
- docs updated: yes/no
- slice tasks cleared: yes/no
- decision needed

