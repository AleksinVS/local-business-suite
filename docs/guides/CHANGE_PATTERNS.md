# Change Patterns

## Add a new role

1. Update `contracts/role_rules.json` for defaults or `data/contracts/role_rules.json` for runtime changes.
2. Validate contracts.
3. Add or adjust tests.

## Change workflow transitions

1. For runtime changes, open `/settings/workflow/transitions/` and edit the transition matrix. For baseline defaults, update `contracts/workflow_rules.json`.
2. Validate role targets against workflow states.
3. Update tests for allowed and rejected transitions.

## Add a new integration

1. Register it in `contracts/integrations/registry.json`.
2. Add transport-specific import or export code.
3. Add contract tests.

## Add a new analytical dataset

1. Register it in `contracts/analytics/datasets.json`.
2. Add export or transformation job.
3. Add dataset documentation and verification checks.

## Start a new implementation task

1. Check `docs/planning/backlog.md` and the relevant active plan in `docs/planning/active/`.
2. For a small task, make the backlog entry explicit enough to include goal, scope, acceptance checks, and verification commands.
3. For a larger or risky task, create or update an active plan in `docs/planning/active/`.
4. If the task changes architecture, security/privacy, contracts, storage, runtime services, or integration patterns, create or update an ADR before implementation.
5. Create a workflow block in `workflow/active/<block-id>/` only for multi-step, multi-agent, high-risk, or task-packet-driven work.
6. `python manage.py generate_change_plan` is optional and belongs to the agent workflow/orchestration path, not to every normal development task.
