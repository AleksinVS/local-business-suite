PM acceptance task.

Context:
- Block: `block-waiting-list-ui-2026-03-31`
- Slice/task: `slice-existing-app-restyle` / `task-existing-app-restyle`

Read these files:
- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-existing-app-restyle.json`
- `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.md`
- `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.task-existing-app-restyle.md`

Verify:
- changes are inside task write scope;
- no business-logic changes;
- checks are present in report:
  - `./.venv/bin/python manage.py check`
  - `./.venv/bin/python manage.py test apps.core.tests apps.inventory.tests apps.workorders.tests apps.analytics.tests`

Output requirement:
- Write `workflow/block-waiting-list-ui-2026-03-31/PM_DECISION_PACKET.md`
- Use fields exactly:
  - goal
  - status
  - files changed
  - checks
  - deviations
  - risks
  - docs updated: yes/no
  - slice tasks cleared: yes/no
  - decision needed

Constraints:
- Do not edit code files.
- If tool/runtime limits prevent full validation, still write the packet and mention limits in `risks`.

