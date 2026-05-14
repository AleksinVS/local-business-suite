# AGENTS.md

## Dual-Use Context

This project is both a **production system** and a **learning platform** for the owner. Topics of study: Python, backend engineering, DevSecOps. When discussing or implementing solutions related to these areas, the agent must:

1. **Provide a brief methodological note first** — a concise explanation of the concept, pattern, or mechanism at play (what it is, why it exists, how it works in principle).
2. **Then proceed with the implementation** as usual.
3. **Detailed breakdown available on request** — if the owner asks, expand the explanation with step-by-step analysis, trade-offs, and alternatives.

This applies to: security hardening, architecture decisions, dependency management, deployment patterns, database operations, API design, authentication/authorization, logging/observability, and any other backend/DevSecOps topic that arises in context.

## Purpose

Short execution protocol for agents working in this repo.
Use bounded slices. Prefer enforced contracts over prompt-only assumptions.

## Sources Of Truth

- Tool definitions: `apps/ai/tool_definitions.py`
  `config/ai/tools.json` is generated from code.
- Tool execution and confirmation flow: `apps/ai/tooling.py`
- Pending confirmation state: `apps/ai/models.py` (`PendingAction`, `AgentActionLog`)
- Bounded task-type contracts: `services/agent_runtime/task_types.py`
- Contract validation: `apps/core/json_utils.py` and `python manage.py validate_architecture_contracts`

Do not treat `config/ai/tools.json` as hand-edited source of truth.

## Bootstrap

```bash
make venv
make install
make check
make test
make contracts
```

If the slice adds migrations, also run:

```bash
./.venv/bin/python manage.py migrate
```

## Slice Workflow

1. Pick one bounded architectural slice.
2. Change code first, then generated/derived artifacts.
3. Keep runtime, gateway, tests, and docs in sync.
4. If tool signatures change, regenerate and revalidate contracts before finishing.
5. If behavior changes materially, update `archive/PROJECT_HANDOFF.md` and this file if protocol changed.

## Verification

Minimum before completion:

```bash
make check
make test
make contracts
```

When touching AI/runtime code, also run:

```bash
./.venv/bin/python -m py_compile services/agent_runtime/*.py apps/ai/*.py apps/core/*.py
```

## File Organization

Root directory must stay clean. Follow these rules:

| Category | Location | Examples |
|---|---|---|
| Project overview & entry points | Root (`/`) | `README.md`, `AGENTS.md`, `PROJECT_MAP.md`, `Makefile`, `manage.py`, `requirements.txt` |
| Reference documentation | `docs/` | Architecture, domain models, deployment guides, integration specs |
| Completed/historical docs | `archive/` | Bugfix reports, completed migration notes, one-off plans, handoff records |
| Architecture decisions | `adr/` | ADR records (`ADR-NNNN-*.md`) |
| Agent/AI configs & templates | `ai/` | Change plan schemas, task brief templates, agent architecture docs |
| Deployment configs | Root (`/`) | `Dockerfile`, `docker-compose*.yml`, `Caddyfile`, `deploy.sh`, `.env.example` |
| Django project config | `config/` | `settings.py`, `urls.py`, `wsgi.py`, `asgi.py` |
| Django apps | `apps/` | `accounts/`, `ai/`, `analytics/`, `core/`, `inventory/`, `waiting_list/`, `workorders/` |
| Services (standalone processes) | `services/` | `agent_runtime/` |
| Database files | `db/` | SQLite databases |
| HTML templates | `templates/` | Per-app subdirectories |
| Static source assets | `static/src/` | CSS, JS source files |
| Collected static files | `staticfiles/` | `collectstatic` output (gitignored) |
| Scripts & tooling | `scripts/` | PowerShell helpers, setup scripts |
| Workflow snapshots | `workflow/` | Per-feature workflow dirs |
| Drafts & WIP | `drafts/` | Unfinished plans, prototype HTML |
| VOB3 (IIS deployment) | `VOB3/` | Gitignored — see `DEPLOY_PRIVATE.md` for setup |
| Runtime logs | — | Never committed; gitignored (`*.log`, `server_log.txt`) |
| Temp/session artifacts | `.tmp/`, `.playwright-mcp/` | Gitignored; auto-generated, never track |

**Rules:**
- Do not create markdown files in root unless they are `README.md`, `AGENTS.md`, or `PROJECT_MAP.md`.
- Bugfix reports, completed task docs, and one-off plans go to `archive/`.
- Reference docs (architecture, models, deployment) go to `docs/`.
- Logs are gitignored. Never commit `*.log` or `server_log.txt`.
- `VOB3/` is gitignored — IIS deployment configs live in a separate private repo. See `DEPLOY_PRIVATE.md` for clone instructions.
- Never commit `.playwright-mcp/` or `.tmp/` contents.

## IIS Deployment Specifics

IIS deployment configs live in a separate private repository. See `DEPLOY_PRIVATE.md` for clone instructions and contents overview.

When working with IIS deployment (Windows Server), be aware of:

1. **Python Version**: Must use Python 3.11.9 (3.13+ is incompatible with wfastcgi 3.0.0)
2. **PATH_INFO Fix**: Project includes `apps/core/middleware.PathInfoDebugMiddleware` to fix IIS FastCGI PATH_INFO issues
3. **Secret Storage**: Use `.env` file, not `web.config` (see `docs/SECURE_SECRETS.md` → now in `archive/`)
4. **Authentication**: Windows Authentication SSO with LDAP fallback (see `docs/IIS_SSO.md`)
5. **Debug Logging**: In DEBUG mode, middleware logs to a local debug file — never commit logs

## AI Contract Rules

- Edit tool definitions in `apps/ai/tool_definitions.py`, then sync generated registry:

```bash
./.venv/bin/python manage.py sync_ai_tool_registry
make contracts
```

- Bounded executable task types currently cover:
  - `workorders` (list, detail, create, transition, comment, confirm_closure, rate)
  - `lookup` (departments, devices)
  - `inventory` (devices.create, devices.update, devices.archive)
  - `analytics` (summary.status, summary.departments, summary.assignees)
- Keep task-type logic aligned with:
  - `config/ai/task_types.json`
  - `services/agent_runtime/task_types.py`
  - `apps/ai/tooling.py`

## Write Safety

- Write tools must respect confirmation flow.
- `workorders.create` and `workorders.transition` must go through `PendingAction`.
- Do not bypass confirmation by directly executing write-paths.
- Keep trace fields flowing through the stack:
  - `conversation_id`
  - `request_id`
  - `origin_channel`
  - `actor_version`

## Handoff

- `archive/PROJECT_HANDOFF.md` is the human/project overview (historical).
- `AGENTS.md` is the short execution protocol for future agents.
- If you change enforced AI behavior, update both when needed.
