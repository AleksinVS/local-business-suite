# Task Acceptance: Settings Center GUI

Статус: implemented; owner review pending.

## Acceptance Checklist

- [x] `apps.settings_center` добавлен и зарегистрирован.
- [x] Descriptor registry загружает descriptors из core/accounts/AI/memory.
- [x] Runtime contract editor валидирует, показывает diff, пишет атомарно и создает audit.
- [x] Settings dashboard и основные формы работают на Django templates + HTMX.
- [x] Пользователи управляются локально, AD identity link реализован явно.
- [x] Vaultwarden-style secret handles используются вместо raw secret values.
- [x] Memory ACL inheritance реализован с fail-closed политикой.
- [x] Contextual mini-chat получает `setting_id` и masked descriptor context.
- [x] `.env` settings работают через status/proposal workflow.
- [x] Документация, `.desc.json` и `PROJECT_STRUCTURE.yaml` обновлены.

## Verification

Фактические результаты:

```bash
.venv/bin/python manage.py check
# passed

.venv/bin/python manage.py validate_architecture_contracts
# passed

.venv/bin/python manage.py makemigrations --check --dry-run
# passed, no changes detected

.venv/bin/python manage.py test apps.settings_center.tests apps.accounts.tests apps.memory.tests apps.ai.tests
# passed, 105 tests

.venv/bin/python manage.py memory_eval --dry-run
# passed, 4 checks
```

```bash
make gen-struct
# passed, PROJECT_STRUCTURE.yaml regenerated
```

```bash
git diff --check -- . ':(exclude)BACKLOG.md'
# passed
```

Full `git diff --check` is blocked by pre-existing trailing whitespace in root `BACKLOG.md`, outside this workflow's write scope.

## Residual Risks

- Contextual mini-chat currently uses safe descriptor-aware local response logic; routing to an external LLM/runtime can be hardened in a follow-up without changing the descriptor context contract.
- ACL inheritance MVP consumes normalized ACL metadata/overrides and fails closed; native Windows ACL collector adapter remains follow-up deployment work.
