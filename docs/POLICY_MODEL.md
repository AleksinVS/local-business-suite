# Policy Model

Policy decisions follow four rules:

1. `models.py` stores data and local invariants.
2. `policies.py` answers who can do what.
3. `services.py` performs state changes and audit logging.
4. `views.py` orchestrates requests and chooses responses.

Role capabilities are defined in [config/role_rules.json](/home/abc/.openclaw/workspace/projects/local-business-suite/config/role_rules.json).

Workflow transitions are defined in [config/workflow_rules.json](/home/abc/.openclaw/workspace/projects/local-business-suite/config/workflow_rules.json).

This allows policy changes without rewriting view logic and keeps UI conditions secondary to server-side checks.
