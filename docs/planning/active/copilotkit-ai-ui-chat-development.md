# Разработка ИИ-чата в режиме CopilotKit UI

## Статус

Active planning.

Целевой режим:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
```

## Цель

Довести CopilotKit-вариант ИИ-чата до production candidate в основном Django UI: новый чат, потоковый ответ, безопасный контекст страницы, UI-команды, история, audit, ошибки, e2e и rollback.

## Связанные документы

- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`;
- `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`;
- `workflow/active/copilotkit-ai-ui-chat-development/`.

## Пользовательская ценность

Владелец проекта сможет тестировать полноценный CopilotKit-чат в основном интерфейсе и сравнивать его с будущим самописным AG-UI-compatible вариантом на одних backend-контрактах.

## Write scope

Ожидаемый реализационный scope:

- `apps/ai/ui_runtime/`;
- `apps/ai/views.py`;
- `apps/ai/urls.py`;
- `templates/base.html`;
- `static/src/copilotkit/`;
- `services/copilot_runtime/`;
- `services/agent_runtime/protocols/`;
- `services/agent_runtime/app.py`;
- `scripts/e2e/tests/`;
- `docs/guides/`;
- `docs/deployment/`.

Документационный scope текущего этапа:

- `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/planning/active/copilotkit-ai-ui-chat-development.md`;
- `workflow/active/copilotkit-ai-ui-chat-development/`;
- `.desc.json`;
- `PROJECT_STRUCTURE.yaml`;
- `docs/planning/backlog.md`.

## Non-goals

- Не удалять `legacy` sidebar.
- Не переносить историю или audit из Django в CopilotKit.
- Не включать Copilot Cloud persistence или hosted analytics.
- Не добавлять browser-side domain writes.
- Не менять доменные AI tools без отдельного scope.
- Не делать самописный UI в этом срезе.

## Этапы

### 1. UX-контракт

Статус: запланировано.

Результат:

- описаны состояния чата;
- новый чат отделен от текущей сессии;
- ошибки и loading-state покрыты e2e.

### 2. Сессии и история

Статус: запланировано.

Результат:

- Django остается владельцем `ChatSession` и `ChatMessage`;
- reload не создает неожиданный fork истории;
- actor token TTL обрабатывается предсказуемо.

### 3. AG-UI fidelity и protocol metadata

Статус: запланировано.

Результат:

- события соответствуют AG-UI-compatible контракту;
- local extensions namespaced;
- ошибки runtime идут как `RUN_ERROR`.

### 4. UI-команды

Статус: запланировано.

Результат:

- `ui.open_right_panel` нормализуется на сервере;
- frontend выполняет только allow-listed команды;
- отказ по правам понятен пользователю и виден в audit.

### 5. Security, deployment, observability

Статус: запланировано.

Результат:

- секреты не попадают в browser state;
- telemetry disabled by default;
- reverse proxy и rollback проверены.

### 6. Приемка

Статус: запланировано.

Результат:

- unit/integration/e2e checks выполнены;
- acceptance report создан;
- документация обновлена;
- backlog очищен после приемки владельцем.

## Acceptance criteria

- `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit` включает CopilotKit-чат в основном Django UI.
- Пользователь может начать новый чат и получить ответ.
- Контекст страницы передается через безопасный envelope.
- Команда открытия правого сайдбара работает только для разрешенного объекта.
- Ошибки runtime отображаются в UI и логируются с request id/run id.
- История и audit остаются в Django.
- `LOCAL_BUSINESS_AI_UI_DRIVER=legacy` остается рабочим rollback.
- E2E `--grep "CopilotKit"` проходит на локальном и целевом deployment.

## Проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```

## Риски

- Быстро меняющиеся версии CopilotKit/AG-UI.
- Расхождение CopilotKit и native UI по backend-контрактам.
- Утечки sensitive payload через state/tool trace.
- SSE timeout на reverse proxy.
- Смешение старой и новой истории чата.
