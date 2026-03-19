# Project Map

Top-level areas:

- `apps/core`: shared dictionaries, dashboard, settings forms and AI-first utilities;
- `apps/accounts`: auth-related helpers and role seeding;
- `apps/inventory`: directory of managed assets;
- `apps/workorders`: workflow-heavy request module;
- `apps/analytics`: operational dashboards inside Django;
- `config`: runtime configuration and JSON contracts;
- `analytics_store`: exported analytical datasets and marts;
- `ai`: machine-readable task briefs and change plans;
- `templates` and `static`: server-rendered frontend.

High-value files:

- `config/settings.py`
- `config/role_rules.json`
- `config/workflow_rules.json`
- `config/integrations/registry.json`
- `analytics_store/datasets.json`
- `apps/workorders/policies.py`
- `apps/workorders/services.py`
