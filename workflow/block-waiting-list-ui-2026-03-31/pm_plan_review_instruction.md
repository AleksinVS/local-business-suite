# PM Plan Review Instruction (Block: block-waiting-list-ui-2026-03-31)

You are the PM (L2) for this block.

## Task

Review the architecture plan and the materialized slice task packets for this block, then produce the decision packet on disk.

Artifacts to review (repo-local paths):

- `workflow/block-waiting-list-ui-2026-03-31/ARCHITECT_PLAN.json`
- `workflow/block-waiting-list-ui-2026-03-31/SLICE_EXPORT_SPEC.json`
- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-ui-foundation.json`
- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-existing-app-restyle.json`
- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-waiting-list-domain.json`
- `workflow/block-waiting-list-ui-2026-03-31/slice-tasks/task-waiting-list-ux.json`

Reference UI:

- `drafts/waiting_list.html`

## Constraints

- This is a **plan review**, not execution. Do not change application code.
- The plan must not require UUID as the primary key for the waiting list entry. Use default integer PK per project conventions; if a UUID is needed, use a separate field (e.g. `external_id`) only if justified.
- Do not modify anything outside `workflow/block-waiting-list-ui-2026-03-31/` except writing the required decision packet file below.

## Required Output (Write To Disk)

Write `workflow/block-waiting-list-ui-2026-03-31/PM_DECISION_PACKET.md` using the exact field list contract:

- goal
- status
- files changed
- checks
- deviations
- risks
- docs updated: yes/no
- slice tasks cleared: yes/no
- decision needed

If you cannot complete the task due to environment limitations (auth, capacity, missing tools, inability to write files), write a stub decision packet to the same path with `status: returned` and describe the limitation under `risks` and `decision needed`.

