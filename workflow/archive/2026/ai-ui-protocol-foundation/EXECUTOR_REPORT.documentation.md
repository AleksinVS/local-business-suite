# Executor report: documentation

## Scope

Создан документационный срез для общей версионируемой основы AI UI протоколов.

## Изменения

- Добавлен ADR-0028.
- Добавлен архитектурный план.
- Добавлен активный planning-файл.
- Создан workflow-блок с task packets.
- Обновлены `.desc.json` и карта проекта.

## Реализация

Runtime-код в этом срезе не изменялся. Документы описывают следующий этап работ:

- общий Django-side AI UI runtime;
- `services.agent_runtime.protocols`;
- рефакторинг CopilotKit-драйвера;
- самописный AG-UI-compatible UI;
- e2e/security/deployment matrix.

## Проверки

Ожидаемые проверки для документационного среза:

```bash
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```

## Остаточные риски

- ADR имеет статус `Proposed` и требует подтверждения владельцем перед реализацией.
- AG-UI/CopilotKit версии нужно проверять при начале реализации.
- Native UI scope нужно удерживать как AG-UI-compatible клиент, чтобы не создать второй backend-протокол без необходимости.
