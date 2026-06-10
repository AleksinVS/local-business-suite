# Операционный guide: CopilotKit и AG-UI

## Статус

Accepted for pilot. Первый рабочий срез реализован за AI UI driver: Django config endpoint, React-остров, CopilotKit Runtime service и AG-UI endpoint.

Связанные документы:

- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- `docs/guides/AI_UI_PROTOCOL_OPERATIONS.md`;
- `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`;
- `workflow/active/copilotkit-ag-ui-integration/`.

## Назначение

Этот guide нужен администратору и разработчику, чтобы безопасно включать, проверять и отключать CopilotKit UI поверх существующего Django AI-чата.

## Базовое правило

CopilotKit - это UI и runtime-прокси. Он не становится владельцем данных, прав или истории. При сомнении проверять Django:

- `ChatSession`;
- `ChatMessage`;
- `AgentActionLog`;
- Django AI gateway;
- доменные policies.

## Режимы

### Disabled

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
```

Поведение:

- React island не монтируется;
- `/copilotkit` может быть недоступен;
- текущий AI sidebar работает как раньше.

### Pilot

```text
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
COPILOTKIT_TELEMETRY_DISABLED=true
```

Поведение:

- CopilotKit island виден только разрешенным пользователям или staff-группе;
- история и audit сохраняются в Django;
- e2e и smoke checks обязательны перед показом пользователям.

### Production candidate

Допускается только после приемки:

- security checklist закрыт;
- e2e проходит на целевом deployment;
- rollback проверен;
- документация deployment обновлена под конкретный хост.

## Локальная проверка после реализации

Запустить Django:

```bash
python manage.py runserver
```

Запустить agent runtime:

```bash
uvicorn services.agent_runtime.app:app --host 0.0.0.0 --port 8090 --reload
```

Запустить Copilot Runtime:

```bash
npm run copilot-runtime:start
```

Проверить health:

```bash
curl -fsS http://127.0.0.1:8090/health
curl -fsS http://127.0.0.1:3100/health
curl -fsS -X POST http://127.0.0.1:3100/copilotkit \
  -H 'content-type: application/json' \
  --data '{"method":"info"}'
curl -fsS 'http://127.0.0.1:3100/copilotkit/threads?agentId=local_business'
```

Проверить Django:

```bash
python manage.py check
python manage.py validate_architecture_contracts
npm run build:copilotkit
```

Старый флаг `LOCAL_BUSINESS_COPILOTKIT_ENABLED=true` поддерживается для совместимости, если `LOCAL_BUSINESS_AI_UI_DRIVER` не задан явно.

Для локальной проверки без reverse proxy можно временно поставить:

```text
LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL=http://127.0.0.1:3100/copilotkit
```

## Управление сессией

Основной config endpoint для CopilotKit-режима:

```text
GET /ai/chat/copilotkit/config/
```

Основной пользовательский вход:

```text
GET /ai/chat/
```

В режиме `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit` этот вход перенаправляет на:

```text
GET /ai/chat/copilotkit/
```

Старый полноэкранный Django chat detail не используется как основной AI-chat entrypoint в CopilotKit-режиме.

Новый чистый sidebar thread создается через:

```text
POST /ai/ui/session/new/
```

Поведение:

- предыдущая активная sidebar-сессия пользователя архивируется;
- новая сессия получает новый `thread_id`;
- выбранный `model_id` переносится из предыдущей sidebar-сессии;
- история остается в Django, CopilotKit не становится хранилищем диалога.

## Smoke-сценарии

### Новый чат

1. Открыть страницу с CopilotKit panel.
2. Нажать кнопку нового чата.
3. Проверить, что `POST /ai/ui/session/new/` вернул новый `thread_id`.
4. Отправить первое сообщение.
5. Проверить, что новая беседа не содержит сообщения предыдущей sidebar-сессии.

### Текстовый ответ

1. Открыть страницу с CopilotKit panel.
2. Задать нейтральный вопрос без доменного действия.
3. Проверить, что ответ идет потоково.
4. Проверить, что в Django появилась запись assistant message.

### Открытие объекта справа

1. Открыть страницу заявок.
2. В CopilotKit panel попросить открыть видимую заявку.
3. Проверить, что tool activity не раскрывает лишние payload.
4. Проверить, что правый сайдбар открылся через существующий endpoint.
5. Проверить `AgentActionLog` по `request_id`.

### Запрещенный write

1. Войти пользователем без права изменения заявки.
2. Попросить изменить статус заявки.
3. Проверить, что write не выполнен.
4. Проверить понятное сообщение пользователю.
5. Проверить audit denied/failed event.

## Наблюдаемость

Минимальные точки:

- request id в Django view;
- run id в AG-UI event stream;
- `conversation_id` и `request_id` в `AgentActionLog`;
- health `agent_runtime`;
- health `copilot_runtime`;
- browser console только без секретов и raw prompts.

Логи не должны содержать:

- полный prompt;
- actor context целиком;
- session cookie;
- gateway token;
- raw PII;
- UNC path;
- full tool result.

## Разбор частых проблем

### CopilotKit panel не появилась

Проверить:

- `LOCAL_BUSINESS_COPILOTKIT_ENABLED`;
- `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit`;
- выполнен ли `npm run build:copilotkit` или собран Docker-образ web;
- template feature flag;
- browser console на ошибку загрузки JS;
- права пользователя на экспериментальный UI.

### Поток начинается и сразу завершается

Проверить:

- health agent runtime;
- формат AG-UI events;
- что stream содержит `RUN_STARTED`;
- что текстовые события имеют `messageId`;
- что ошибка маппится в `RUN_ERROR`, а не raw exception.

### Tool activity видна, но действие не выполнено

Проверить:

- Django AI gateway token;
- ownership `ChatSession`;
- permissions пользователя;
- confirmation state;
- `AgentActionLog`;
- что frontend tool не пытается выполнить доменную запись напрямую.

### В CopilotKit state появились лишние данные

Немедленно:

1. выключить feature flag;
2. сохранить request ids в incident note;
3. проверить AG-UI mapper и frontend context bridge;
4. убедиться, что данные не ушли во внешний сервис;
5. не включать повторно без regression test.

## Rollback

Быстрый rollback:

```text
LOCAL_BUSINESS_COPILOTKIT_ENABLED=false
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
```

Если добавлен отдельный service:

1. снять route `/copilotkit` с reverse proxy;
2. остановить `copilot_runtime`;
3. оставить `agent_runtime` и Django без изменений;
4. проверить текущий AI sidebar через `/ai/`.

## Обязательные проверки перед приемкой

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
npm run test:e2e -- --project=chromium
git diff --check
```
