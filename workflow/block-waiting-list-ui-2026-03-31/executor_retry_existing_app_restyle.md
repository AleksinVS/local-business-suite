# Executor Retry Instruction (Task: task-existing-app-restyle)

Previous run stalled before returning a final result.

## Goal

Finalize `task-existing-app-restyle` using the existing task packet:

- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-existing-app-restyle.json`

## Retry Behavior

- Inspect current repo state first; some allowed files may already be modified by the previous attempt.
- Do not revert valid in-scope changes.
- Complete any missing in-scope edits required by the task packet.
- Run required checks/tests from the task packet.

## Scope Guard

- Stay strictly within task `write_files`.
- Do not touch unrelated files, workflow plans, or skill/config files.

## Required Output

Write:

- `workflow/block-waiting-list-ui-2026-03-31/EXECUTOR_REPORT.md`

with the fixed heading contract from workflow artifacts.

