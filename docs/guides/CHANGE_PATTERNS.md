# Change Patterns

## Add a new role

1. Update `contracts/role_rules.json` for defaults or `data/contracts/role_rules.json` for runtime changes.
2. Validate contracts.
3. Add or adjust tests.

## Change workflow transitions

1. Update `contracts/workflow_rules.json` for defaults or `data/contracts/workflow_rules.json` for runtime changes.
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

1. Create a task brief from `workflow/ai_artifacts/task_brief_template.json`.
2. Generate a change plan with `python manage.py generate_change_plan`.
3. Implement only after the plan is explicit.
