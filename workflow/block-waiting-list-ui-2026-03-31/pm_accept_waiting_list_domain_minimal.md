PM acceptance task.

Context:
- Block: `block-waiting-list-ui-2026-03-31`
- Slice/task: `slice-waiting-list-domain` / `task-waiting-list-domain`

Read:
- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-waiting-list-domain.json`
- `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.md`
- `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.task-waiting-list-domain.md`

Verify:
- `Entry` PK is int/BigAutoField (UUID is NOT primary key);
- scope stays inside task write_files;
- checks are present/passed in report:
  - `./.venv/bin/python manage.py check`
  - `./.venv/bin/python manage.py test apps.waiting_list.tests`

Output:
- Write `workflow/block-waiting-list-ui-2026-03-31/PM_DECISION_PACKET.md`
- Use exact fields:
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
- If runtime/tool limits prevent deeper validation, mention it in `risks` and still write the packet.

