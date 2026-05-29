# Workflow Brief: interface-russification

Статус: active implementation.

Дата: 2026-05-29.

## Цель

Сделать интерфейс портала русскоязычным во всех видимых пользователю элементах и зафиксировать путь к будущей архитектуре локализации.

## Архитектурные источники

- `docs/adr/ADR-0022-interface-russification-and-localization-roadmap.md`
- `docs/planning/active/interface-russification-and-localization.md`
- `docs/guides/INTERFACE_RUSSIFICATION.md`

## Read scope

- `templates/`
- `static/src/js/`
- `apps/*/models.py`
- `apps/*/forms.py`
- `apps/*/views.py`
- `apps/core/settings_descriptors.py`
- `apps/ai/tool_definitions.py`
- `contracts/ai/tools.json`
- `scripts/e2e/tests/`
- `docs/adr/`
- `docs/planning/active/`
- `docs/guides/`

## Write scope

- `templates/`
- `static/src/js/`
- `apps/*/models.py`, только человекочитаемые labels/verbose/help text
- `apps/*/forms.py`, только labels/placeholders/messages
- `apps/*/views.py`, только пользовательские сообщения
- `apps/core/settings_descriptors.py`
- `apps/ai/tool_definitions.py`
- `contracts/ai/tools.json`, если registry синхронизируется
- `docs/adr/ADR-0022-interface-russification-and-localization-roadmap.md`
- `docs/planning/active/interface-russification-and-localization.md`
- `docs/guides/INTERFACE_RUSSIFICATION.md`
- `workflow/active/interface-russification/`
- `.desc.json`
- `PROJECT_STRUCTURE.yaml`

## Non-goals

- Не внедрять полноценный многоязычный runtime.
- Не добавлять выбор языка пользователя.
- Не переводить машинные идентификаторы и коды контрактов.
- Не менять бизнес-логику.
- Не переводить данные, уже введенные пользователями.

## Acceptance

- Основные страницы портала не содержат видимых английских UI-подписей, кроме разрешенных технических терминов.
- Ревью памяти, ИИ-центр и центр настроек переведены в первую очередь.
- Человекочитаемые labels статусов и действий переведены на русский.
- Документация объясняет, что текущий этап - русская базовая версия, а не полноценная локализация.
- Проверки Django и e2e по основным сценариям проходят.

## Verification

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.core.tests apps.ai.tests apps.memory.tests apps.settings_center.tests apps.workorders.tests apps.waiting_list.tests apps.inventory.tests
npm run test:e2e -- --project=chromium --grep "sidebar"
make gen-struct
git diff --check
```
