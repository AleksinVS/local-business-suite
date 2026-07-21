# Task Acceptance: documentation

Дата: 2026-05-29.

## Acceptance

- Проектная политика тестирования создана в `docs/guides/TESTING_POLICY.md`.
- В `AGENTS.md` добавлено операционное правило независимой проверки.
- В `README.md` добавлена навигационная ссылка.
- Исполнительный workflow-блок содержит brief, plan, task packet, executor report, acceptance и retrospective.
- `.desc.json` обновлены для новых узлов структуры.

## Verification

- `make gen-struct` — OK.
- `.venv/bin/python manage.py check` — OK.
- `.venv/bin/python manage.py validate_architecture_contracts` — OK.
- `git diff --check` — OK.

## Решение

Документационная задача принята на уровне локальных проверок. Workflow остается в `active` до приемки владельцем.
