# AGENTS.md

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
| Architecture decisions | `docs/adr/` | ADR records (`ADR-NNNN-*.md`) |
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
| VOB3 (IIS submodule) | `VOB3/` | IIS-specific configs |
| Runtime logs | — | Never committed; gitignored (`*.log`, `server_log.txt`) |
| Temp/session artifacts | `.tmp/`, `.playwright-mcp/` | Gitignored; auto-generated, never track |

**Rules:**
- Do not create markdown files in root unless they are `README.md`, `AGENTS.md`, or `PROJECT_MAP.md`.
- **Architectural Decisions:** Any significant change to the system design, choice of tools, or core logic MUST be documented as an ADR in `docs/adr/`.
- Bugfix reports, completed task docs, and one-off plans go to `archive/`.
- Reference docs (architecture, models, deployment) go to `docs/`.
- Logs are gitignored. Never commit `*.log` or `server_log.txt`.
- Never commit `.playwright-mcp/` or `.tmp/` contents.

## IIS Deployment Specifics

When working with IIS deployment (Windows Server), be aware of:

1. **Python Version**: Must use Python 3.11.9 (3.13+ is incompatible with wfastcgi 3.0.0)
2. **PATH_INFO Fix**: Project includes `apps/core/middleware.PathInfoDebugMiddleware` to fix IIS FastCGI PATH_INFO issues
3. **Secret Storage**: Use `.env` file, not `web.config` (see `docs/SECURE_SECRETS.md` → now in `archive/`)
4. **Authentication**: Windows Authentication SSO with LDAP fallback (see `docs/deployment/IIS_SSO.md`)
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
