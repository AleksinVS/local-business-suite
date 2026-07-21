# PM Decision Packet

- goal: Review the architecture plan and slice task packets for block-waiting-list-ui-2026-03-31.
- status: accepted
- files changed: none
- checks:
    - ARCHITECT_PLAN.json contains required PK constraint (int/BigAutoField, no UUID as PK).
    - SLICE_EXPORT_SPEC.json correctly materializes task packets.
    - Task packets (task-ui-foundation, task-existing-app-restyle, task-waiting-list-domain, task-waiting-list-ux) are consistent with the plan.
    - Reference UI (drafts/waiting_list.html) is reviewed and mapped to tasks.
- deviations: none
- risks:
    - restyle regression: Restyling existing screens (inventory, workorders, analytics) in `slice-existing-app-restyle` carries a risk of visual or HTMX selector regressions.
    - progressive enhancement: Keyboard shortcuts and input masks must be implemented carefully to ensure they don't break standard form behavior.
- docs updated: no
- slice tasks cleared: no
- decision needed: none
