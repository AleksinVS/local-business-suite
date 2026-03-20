# Project Map

Top-level areas:

- `apps/core`: shared dictionaries, dashboard, settings forms and AI-first utilities;
- `apps/ai`: chat-agent control plane, tool gateway and AI audit trail;
- `apps/accounts`: auth-related helpers and role seeding;
- `apps/inventory`: directory of managed assets;
- `apps/workorders`: workflow-heavy request module;
- `apps/analytics`: operational dashboards inside Django;
- `config`: runtime configuration and JSON contracts;
- `config/ai`: declarative runtime profile, tool catalog and task-type catalog for chat-agent integration;
- `analytics_store`: exported analytical datasets and marts;
- `ai`: machine-readable task briefs and change plans;
- `templates` and `static`: server-rendered frontend.

High-value files:

- `config/settings.py`
- `config/role_rules.json`
- `config/workflow_rules.json`
- `config/integrations/registry.json`
- `config/ai/registry.json`
- `config/ai/tools.json`
- `config/ai/task_types.json`
- `analytics_store/datasets.json`
- `apps/ai/views.py`
- `apps/ai/tooling.py`
- `apps/workorders/policies.py`
- `apps/workorders/services.py`
- `services/agent_runtime/app.py`
