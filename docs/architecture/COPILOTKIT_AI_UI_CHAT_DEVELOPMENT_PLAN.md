# План разработки ИИ-чата в режиме CopilotKit UI

## Статус

Active planning.

Дата: 2026-06-10.

Целевой режим:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
```

## Связанные решения и документы

- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- `docs/architecture/AI_UI_PROTOCOL_FOUNDATION_PLAN.md`;
- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`;
- `docs/guides/AI_UI_PROTOCOL_OPERATIONS.md`;
- `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`;
- `workflow/active/copilotkit-ai-ui-chat-development/`.

Новый ADR не создается: архитектурные решения уже зафиксированы в ADR-0027 и ADR-0028. Этот документ описывает следующий проектный срез разработки продукта поверх принятой архитектуры.

## Методическая рамка

Режим UI-драйвера - это способ выбрать внешний слой общения с агентом без развилки серверной бизнес-логики. Django остается владельцем сессии, прав, истории, аудита и подтверждений. CopilotKit отвечает за пользовательский чат и клиентское состояние, Copilot Runtime проксирует AG-UI поток, а `services.agent_runtime` переводит внутренние события агента в версионируемый AG-UI формат.

## Цель

Довести CopilotKit-вариант ИИ-чата от рабочего пилота до production candidate, который можно включать через `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit` и сравнивать с самописным AG-UI-compatible вариантом без расхождения backend-контрактов.

## Текущая база

Уже реализовано:

- Django config endpoint для AI UI;
- подписанный actor/session payload;
- `CopilotKit` React island в левой AI-панели;
- отдельный `services/copilot_runtime`;
- AG-UI endpoint в `services.agent_runtime`;
- общий слой `apps/ai/ui_runtime/`;
- общий protocol layer `services/agent_runtime/protocols/`;
- e2e smoke для режима `copilotkit`.

Оставшийся разрыв: текущий срез проверяет жизнеспособность интеграции, но еще не задает полный продуктовый контракт ИИ-чата: новая беседа, история, контекст страницы, потоковые ошибки, tool trace, подтверждения действий, наблюдаемость и production-приемка.

## Целевое поведение

### Пользовательский сценарий

1. Пользователь входит в основной Django UI.
2. Левая AI-панель открывает CopilotKit-чат, если `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit`.
3. Чат получает только разрешенный контекст страницы через Django config и actor token.
4. Пользователь может начать новый чат, отправить сообщение и получить потоковый ответ.
5. Агент может предложить безопасную UI-команду, например открыть объект в правой панели.
6. Любое доменное write-действие проходит через существующие Django permissions, confirmation flow и audit.
7. При сбое Copilot Runtime, Agent Runtime или LLM пользователь видит понятную ошибку, а оператор видит request id/run id в логах.

### Обязательные UX-свойства

- Чат встроен в существующую левую панель, без отдельной landing-страницы.
- Состояние "новый чат" создает чистую беседу и не смешивает историю.
- Контекст страницы применяется автоматически, но не раскрывает raw DOM, секреты, полные UNC paths или лишние PII.
- Tool trace показывает действие компактно, без raw payload.
- UI-команды выполняются только через allow-list.
- Недоступные действия объясняются пользователю без раскрытия внутренних проверок.
- Fallback на `legacy` остается доступным через переменную окружения.

## Архитектурный контур

```text
Browser Django page
  -> templates/base.html
  -> static/dist/copilotkit/copilotkit-island.*
  -> /ai/ui/config/
  -> /copilotkit
  -> services/copilot_runtime
  -> services.agent_runtime /ag-ui
  -> LangGraph agent
  -> Django AI gateway
  -> domain apps, ChatSession, ChatMessage, AgentActionLog
```

Границы владения:

- Django UI runtime: выбор драйвера, actor/session, подпись, конфигурация клиента.
- CopilotKit driver: визуальный чат, отправка сообщений, чтение AG-UI state и UI-команд.
- Copilot Runtime: server-side proxy к AG-UI agent, без владения бизнес-данными.
- Agent Runtime protocols: AG-UI events, local protocol metadata, нормализация UI-команд.
- Django AI gateway: права, история, audit, выполнение доменных tools.

## Развиваемые подсистемы

| Срез | Основные файлы | Результат |
| --- | --- | --- |
| UX-контракт чата | `templates/base.html`, `static/src/copilotkit/`, e2e | Новый чат, отправка, потоковый ответ, ошибки, loading-state |
| История и сессии | `apps/ai/ui_runtime/`, `apps/ai/views.py`, Django chat models | Чистое разделение сессий, reload-safe поведение |
| AG-UI fidelity | `services/agent_runtime/protocols/agui/`, tests | Стабильные события, protocol metadata, корректный `RUN_ERROR` |
| UI-команды | `services/agent_runtime/protocols/common/ui_commands.py`, frontend bridge | Версионированные команды и allow-list |
| Безопасность | Django config view, actor token, logging | TTL, минимум данных, отсутствие секретов в browser state |
| Production | deployment docs, health checks, e2e | Повторяемый запуск и rollback |

## Конфигурация

Минимальный локальный профиль:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL=http://127.0.0.1:3100/copilotkit
LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL=http://127.0.0.1:8090/ag-ui
LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION=1.0
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE=ag-ui@0.0.55
COPILOTKIT_RUNTIME_PORT=3100
COPILOTKIT_TELEMETRY_DISABLED=true
```

Для production:

- секреты задаются только в приватном deployment repo;
- `LOCAL_BUSINESS_COPILOTKIT_SERVICE_TOKEN` добавляется при включении service-to-service auth;
- reverse proxy публикует `/copilotkit`, но не публикует внутренние gateway endpoints;
- timeouts должны поддерживать долгие потоковые ответы.

## План реализации

### 1. UX-контракт CopilotKit-чата

Зафиксировать и реализовать минимальное ожидаемое поведение:

- новый чат;
- потоковый ответ;
- пустое состояние;
- состояние загрузки;
- понятная ошибка;
- компактный tool trace;
- открытие правой панели через UI-команду.

### 2. Сессии, история и reload

Проверить, что CopilotKit mode не создает разнобой с Django `ChatSession`:

- новая беседа не продолжает старую без явного выбора;
- reload страницы не теряет активную сессию неожиданно;
- история хранится в Django, а не в hosted сервисах;
- actor token TTL не ломает длинную сессию без понятной ошибки.

### 3. AG-UI события и расширения

Уточнить стабильный контракт событий:

- `RUN_STARTED`, `TEXT_MESSAGE_*`, `TOOL_CALL_*`, `STATE_DELTA`, `CUSTOM`, `RUN_FINISHED`, `RUN_ERROR`;
- `local_business.protocol` metadata;
- namespaced state path `/localBusiness/uiCommands`;
- совместимый старый путь `/localBusinessUiCommands` только как временный bridge.

### 4. UI-команды и правый сайдбар

Укрепить безопасный путь действий:

- единый нормализатор UI-команд;
- allow-list команд;
- отсутствие доменных write-действий в браузере;
- audit для команд, пришедших от агента;
- понятный отказ при отсутствии прав.

### 5. Безопасность и наблюдаемость

Проверить:

- в browser state нет session cookie, gateway token, raw actor context, raw PII, UNC paths;
- логи содержат request id/run id/conversation id, но не полный prompt;
- telemetry CopilotKit отключена по умолчанию;
- rollback на `LOCAL_BUSINESS_AI_UI_DRIVER=legacy` проверен.

### 6. Приемка production candidate

Перед включением:

- unit/integration tests по затронутому scope;
- e2e для режима `copilotkit`;
- ручная проверка нового чата в браузере;
- проверка reverse proxy `/copilotkit`;
- обновленные guides/deployment notes;
- acceptance report в workflow-блоке.

## Acceptance criteria

- При `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit` пользователь видит CopilotKit-чат в основном Django UI.
- Новый чат отвечает на первое сообщение в новой сессии.
- Контекст открытой страницы передается агенту через существующий безопасный envelope.
- `ui.open_right_panel` открывает правый сайдбар только для разрешенного объекта.
- Ошибка runtime/LLM маппится в понятное состояние UI и `RUN_ERROR`.
- История и audit остаются в Django.
- Browser state не содержит секретов и raw sensitive payload.
- Fallback `LOCAL_BUSINESS_AI_UI_DRIVER=legacy` работает без миграции данных.
- E2E покрывает основной сценарий CopilotKit-чата.

## Проверки

Базовые проверки разработки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
```

E2E для режима CopilotKit:

```bash
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
```

Документация и структура:

```bash
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```

## Риски

- CopilotKit и AG-UI могут менять протокол. Смягчение: фиксировать версии и держать mapper в `services.agent_runtime.protocols`.
- Две UI-ветки могут начать расходиться. Смягчение: общий слой `apps/ai/ui_runtime/` и `services/agent_runtime/protocols/` развивать до копирования в варианты.
- Tool trace может раскрыть лишние данные. Смягчение: server-side redaction и regression tests.
- Длинные SSE ответы могут ломаться на reverse proxy. Смягчение: отдельная deployment-проверка timeout.
- Hosted CopilotKit возможности могут случайно включить внешнее хранение. Смягчение: production default без hosted persistence/telemetry.

## Рекомендуемая последовательность веток

1. Влить общий protocol foundation в основную ветку после приемки.
2. От основной ветки создать две параллельные ветки:
   - `feature/copilotkit-ai-ui-chat`;
   - `feature/native-ag-ui-chat`.
3. Общие изменения в `apps/ai/ui_runtime/` и `services/agent_runtime/protocols/` вносить в отдельную короткую ветку и быстро вливать в обе UI-ветки.
4. В UI-ветках держать только driver-specific код и tests.
