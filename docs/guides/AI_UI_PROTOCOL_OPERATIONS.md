# Операционный guide: AI UI protocol foundation

## Статус

Accepted for pilot. Первый срез реализован для трех драйверов: `legacy`, `copilotkit`, `native`.

## Назначение

Документ описывает, как включать и проверять общий AI UI слой. Основной целевой вариант - самописный UI в режиме `native`. CopilotKit остается отдельным равноправным драйвером и референсом AG-UI совместимости. Оба варианта используют один backend-контур.

## Драйверы

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
LOCAL_BUSINESS_AI_UI_DRIVER=native
```

Поведение:

- `legacy` - текущий HTMX sidebar;
- `copilotkit` - React island + Copilot Runtime `/copilotkit`;
- `native` - самописный sidebar + Django proxy `/ai/ui/ag-ui/run/`.

Старый флаг `LOCAL_BUSINESS_COPILOTKIT_ENABLED=true` сохраняет совместимость и включает CopilotKit, если `LOCAL_BUSINESS_AI_UI_DRIVER` не задан явно.

## Проверка версии AG-UI

При изменениях серверной части AI UI обязательно проверить актуальность AG-UI профиля:

```bash
node -e "const p=require('./package.json'); console.log(p.dependencies['@ag-ui/client'])"
rg -n "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE|ag-ui@" config docs package.json package-lock.json
```

Если изменение затрагивает `/ag-ui`, `services.agent_runtime.protocols`, `apps.ai.ui_runtime`, AI tools, Django AI gateway или deployment-профили, дополнительно сверить официальные release notes/docs AG-UI/CopilotKit. Результат по умолчанию - предупреждение в отчете: текущая версия актуальна или есть новая версия, но обновление не выполнялось.

Запрещено без согласования:

- менять `@ag-ui/client`;
- менять версии `@copilotkit/*`;
- менять `LOCAL_BUSINESS_AI_UI_AGUI_PROFILE`;
- менять wire contract событий только потому, что вышла новая версия.

После согласованного обновления версии обязательны unit/integration/e2e проверки по `legacy`, `copilotkit`, `native` и обновление ADR/guides/deployment.

## Protocol contract

AG-UI stream должен содержать:

- `RUN_STARTED`;
- `CUSTOM name="local_business.protocol"`;
- `TEXT_MESSAGE_*`;
- `TOOL_CALL_*`, если были tools;
- `STATE_DELTA path="/localBusiness/uiCommands"`, если есть UI-команды;
- `RUN_FINISHED` или `RUN_ERROR`.

Переходная совместимость:

- `/localBusinessUiCommands` пока дублируется для CopilotKit island;
- новый основной путь: `/localBusiness/uiCommands`.

## Проверка режимов

Legacy:

```bash
LOCAL_BUSINESS_AI_UI_DRIVER=legacy .venv/bin/python manage.py runserver 127.0.0.1:8001
```

CopilotKit:

```bash
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit .venv/bin/python manage.py runserver 127.0.0.1:8001
uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090
npm run copilot-runtime:start
```

Native:

```bash
LOCAL_BUSINESS_AI_UI_DRIVER=native .venv/bin/python manage.py runserver 127.0.0.1:8001
uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090
```

## Smoke checks

```bash
curl -fsS http://127.0.0.1:8001/health/
curl -fsS http://127.0.0.1:8090/health
```

Для CopilotKit дополнительно:

```bash
curl -fsS http://127.0.0.1:3100/health
```

## Обязательные проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
E2E_AI_UI_DRIVER=legacy npm run test:e2e -- --project=chromium --grep "context-aware sidebar"
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
```

## Rollback

Быстрый rollback:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
```

Для CopilotKit дополнительно можно остановить `copilot_runtime` и снять `/copilotkit` с reverse proxy.

## Безопасность

- Браузер не получает `LOCAL_BUSINESS_AI_GATEWAY_TOKEN`.
- Native UI не отправляет actor payload напрямую в agent runtime; Django proxy пересоздает подпись.
- Frontend выполняет только allow-listed UI-команды.
- Write tools остаются backend-only и проходят policies, confirmation и audit.
