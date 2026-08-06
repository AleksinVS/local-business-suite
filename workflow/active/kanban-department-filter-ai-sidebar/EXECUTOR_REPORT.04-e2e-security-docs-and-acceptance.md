# Отчет исполнения пакета 04

## Результат

Сквозная связка канбана, URL-фильтра, PageContext и двух ИИ-драйверов реализована и
прошла техническую приемку. Старый Playwright-сценарий дерева заменен постоянным
`kanban_department_filter.spec.ts`.

## Матрица проверки

- доступные, недоступные, некорректные и повторяющиеся ID подразделений;
- нормализация предка с потомком и сохранение независимых ветвей;
- полный GET, HTMX, copied URL, reload и старый session key;
- повторяемые `department/status/assignee/device` без потери `q`;
- CSRF на PageContext, новой sidebar-сессии и native AG-UI proxy;
- native: open/collapse, клавиатура, поток после сворачивания, статус и фокус;
- CopilotKit: open/focus/collapse без пересоздания корня;
- мобильный диалог, фон, удержание/возврат фокуса и цели 44 px.

## Проверки и счетчики

- `make check` — успешно, статика синхронизирована;
- `make contracts` — 17 контрактов валидны;
- `make test-fast TEST_SCOPE=apps/workorders/tests.py` — 84 passed;
- `make test-fast TEST_SCOPE=apps/ai/tests` — 120 passed, 6 subtests passed;
- `make test-integration TEST_SCOPE=apps/workorders/tests.py` — 80 passed,
  4 deselected;
- Playwright native — 4 passed;
- Playwright CopilotKit lifecycle — 1 passed;
- `make test` — 571 passed, 77 subtests passed за 130.28 с;
- `npm run build:copilotkit`, `node --check`, `make gen-struct`, `git diff --check` —
  успешно.

Независимая проверка сначала обнаружила два дефекта фокуса/Escape. После исправлений и
добавления поточного e2e повторная проверка завершилась статусом PASS.

## Документационная свежесть

- обновлены ADR-0037, активный план, backlog, руководство `AI_SIDEBAR_CHAT.md`,
  workflow-отчеты, `.desc.json` и `PROJECT_STRUCTURE.yaml`;
- ADR-0023 ранее помечен как частично замененный новым UI-решением;
- README и AGENTS не требуют изменения по этому блоку: команды запуска, доменные границы
  и протокол исполнения не менялись; находящиеся там параллельные правки сохранены;
- deployment-документы не менялись: настройки, зависимости и схема развертывания прежние;
- отдельное изменение `POLICY_MODEL.md` не требуется: серверный selector-паттерн и роли
  не менялись.

## Остаточный риск

Полный CopilotKit runtime в локальной среде не запускался; проверены собранный React-клиент,
фокус, сворачивание и сохранение DOM-корня. Потоковый сценарий с управляемым ответом
выполнен на основном native-драйвере. Версии AG-UI/CopilotKit не обновлялись.
