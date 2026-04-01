# Executor Instruction (Task: task-waiting-list-domain)

Implement `task-waiting-list-domain` strictly from packet:

- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-waiting-list-domain.json`

## Critical Constraint

- `Entry` must follow repository PK convention (`int`/`BigAutoField`) and must not use UUID as primary key.
- If UUID is needed, use a separate optional field like `external_id`, not primary key.

## Scope

- Stay strictly inside task `write_files`.
- Do not modify unrelated files, workflow plans, or skill/config files.

## Required Output

Write executor report to:

- `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.md`

and include required checks/tests status.

