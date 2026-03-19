# Change Patterns

## Add a new role

1. Update `config/role_rules.json`.
2. Validate contracts.
3. Add or adjust tests.

## Change workflow transitions

1. Update `config/workflow_rules.json`.
2. Validate role targets against workflow states.
3. Update tests for allowed and rejected transitions.

## Add a new integration

1. Register it in `config/integrations/registry.json`.
2. Add transport-specific import or export code.
3. Add contract tests.

## Add a new analytical dataset

1. Register it in `analytics_store/datasets.json`.
2. Add export or transformation job.
3. Add dataset documentation and verification checks.

## Start a new implementation task

1. Create a task brief from `ai/task_briefs/template.json`.
2. Generate a change plan with `python manage.py generate_change_plan`.
3. Implement only after the plan is explicit.
