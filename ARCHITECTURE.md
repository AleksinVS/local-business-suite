# Architecture

`local-business-suite` is a local-first Django monorepo for internal business systems.

Core rules:

- server-driven UI with Django Templates and HTMX;
- business rules live on the server, not in templates;
- mutable rules should be stored in versioned JSON contracts;
- analytics are separated from OLTP and read from exported datasets;
- every major change should start from a task brief and a change plan.

Main layers:

- `apps/*` for domain modules;
- `config/*` for platform configuration and contracts;
- `analytics_store/*` for analytical datasets;
- `ai/*` for machine-readable delivery artifacts;
- `templates/*` and `static/*` for server-rendered UI.
