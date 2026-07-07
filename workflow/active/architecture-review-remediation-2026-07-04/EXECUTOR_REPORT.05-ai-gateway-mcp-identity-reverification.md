# Executor report: 05-ai-gateway-mcp-identity-reverification

Дата: 2026-07-07
Исполнитель: Claude agent (executor)
Пакет: `workflow/active/architecture-review-remediation-2026-07-04/task-packets/05-ai-gateway-mcp-identity-reverification.json`
Поглощает: `architecture-review-remediation-2026-06-01/task-packets/03-ai-gateway-mcp-identity-and-prompt-logging.json`
Характер пакета: перепроверка (аудит). Продуктовый код НЕ менялся; добавлены только тесты, закрывающие пробелы покрытия.

## Итог одной строкой

Все четыре пункта чек-листа подтверждены как исправные (дефектов не найдено). По цепочке таймаутов найдено рассогласование на синхронном пути `/chat` — зафиксированы вердикт и рекомендация; значения по умолчанию не менялись (решение владельца, к тому же `config/settings.py` в scope параллельного пакета 04).

## Методологическая заметка (DevSecOps, кратко)

Два инварианта, которые проверяет этот пакет, — базовые для безопасного LLM-шлюза:

1. **Привязка service identity к живому пользователю.** Agent-runtime — это отдельный сервис, который ходит в Django-gateway под общим статическим токеном. Если бы gateway доверял полю `user_id` из запроса «на слово», то любой, кто добыл статический токен (или скомпрометированный узел runtime), мог бы выполнять инструменты от имени произвольного пользователя, в том числе уволенного/заблокированного. Поэтому gateway на каждый tool-вызов **перепроверяет** `user_id` по живой базе (`is_active=True`) и сверяет владельца сессии. Это принцип «не доверяй утверждённой личности, подтверди её у источника истины» (re-verification / confused-deputy protection).
2. **Отсутствие сырого prompt и полного actor-контекста в технических логах.** Технические логи (`docker compose logs`, файлы) обычно доступны шире, чем прикладная БД, дольше живут и уходят в системы агрегации. Prompt пользователя и полный actor-контекст — это персональные/чувствительные данные. Поэтому в логи пишутся только `prompt_sha256` + `prompt_length` (хэш для корреляции, длина для диагностики), а сырой текст остаётся в `AgentActionLog`/`ChatMessage` под прикладным контролем доступа. Разбор ошибки идёт по `request_id`, а не по тексту в логе.

## Чек-лист перепроверки — вердикты

### Пункт 1. Каждый tool-вызов через gateway привязан к проверенному `user_id` активного пользователя и сессии — ПОДТВЕРЖДЕНО

Точки:
- `apps/ai/views.py:181` `gateway_token_is_valid` — статический токен сверяется через `hmac.compare_digest` (защита от timing-атак); пустой ожидаемый токен → всегда `False`.
- `apps/ai/views.py:195` `reject_invalid_gateway_token` вызывается в `dispatch` у `AIToolExecuteView` (стр. 1188) и `AIToolConfirmView` (стр. 1234) — без валидного токена запрос не доходит до `post`.
- `apps/ai/views.py:201` `validate_gateway_actor` вызывается в `AIToolExecuteView.post` (стр. 1202) и `AIToolConfirmView.post` (стр. 1248). Логика:
  - actor обязан быть JSON-объектом (иначе 400);
  - `user_id` обязателен, приводится к `int`, должен быть `> 0` (иначе 403);
  - `User.objects.filter(pk=actor_user_id, is_active=True).first()` — **несуществующий или деактивированный** пользователь отклоняется (403 «Исполнитель не найден или отключен»);
  - если передан `username`, он должен совпадать с `actor.username` (иначе 403, warning в лог);
  - если передан `session_id` и такая сессия существует — проверяется, что `actor_user_id == session.user_id` (иначе 403, warning). Если сессии ещё нет, отказа нет: `get_or_create_session` в `tooling.py` создаст сессию для этого же пользователя, кросс-доступ невозможен.
- Путь подтверждения (`execute_pending_action`, `apps/ai/tooling.py:558-579`) дополнительно проверяет, что actor владеет pending-действием и что сессия совпадает.
- MCP-фасад (`services/agent_runtime/mcp_server.py`) не ходит в БД напрямую: каждый `@mcp.tool()` вызывает `gateway_client().execute_tool(...)`, то есть проходит те же проверки Django-gateway. MCP наружу не публикуется (non-goal соблюдён).

Вывод: actor привязан к проверенному активному пользователю и владельцу сессии; несуществующий/неактивный отклоняется. Дефектов нет.

Покрытие тестами: существующие `test_tool_gateway_rejects_invalid_token`, `test_tool_gateway_rejects_actor_mismatch_for_existing_session`, `test_tool_gateway_rejects_username_mismatch`, `test_tool_gateway_rejects_invalid_actor_user_id`, `test_pending_action_rejects_actor_mismatch`. **Добавлено** (пробелы, прямо названные в задаче): `test_tool_gateway_rejects_wrong_token` (непустой неверный токен), `test_tool_gateway_rejects_nonexistent_user_id`, `test_tool_gateway_rejects_inactive_user`.

### Пункт 2. Actor-токены подписаны и ограничены TTL — ПОДТВЕРЖДЕНО

- Выпуск/подпись (Django): `apps/ai/ui_runtime/actor.py`. `sign_actor_payload` = HMAC-SHA256 по каноничной сериализации (`signature_payload`, `sort_keys=True`), ключ — `LOCAL_BUSINESS_AI_GATEWAY_TOKEN`. `build_actor_payload` проставляет `issued_at` (unix-время) и `signature`.
- Проверка (agent-runtime): `services/agent_runtime/app.py:104` `_agui_signature_is_valid` — требует наличие токена, `signature` и `issued_at`; проверяет TTL (`abs(now - issued_at) > ttl` → отказ; default `LOCAL_BUSINESS_AI_UI_ACTOR_TOKEN_TTL_SECONDS=900`); пересчитывает HMAC и сверяет через `hmac.compare_digest`. Вызывается в `/ag-ui` (стр. 196); при провале — `RUN_ERROR code=invalid_actor_signature`, `run_agent` не запускается.
- Модель доверия (не менялась, non-goal соблюдён): подпись+TTL защищают **клиентский round-trip** (AG-UI/CopilotKit — actor-payload проходит через браузер). На серверных путях Django→runtime (`/chat`, `/chat/stream`) actor формируется на сервере из `request.user`, а исполнение инструментов повторно валидируется у gateway против живой БД (пункт 1) — defense-in-depth, подпись там не нужна.

Вывод: токены подписаны (HMAC-SHA256) и ограничены TTL (900s по умолчанию), проверка корректна. Дефектов нет.

Покрытие тестами: существующие `test_ag_ui_run_streams_standard_events` (валидная подпись), `test_ag_ui_run_rejects_missing_actor_signature`. **Добавлено**: `test_ag_ui_run_rejects_expired_actor_signature` (корректная подпись, но `issued_at` за пределами TTL → отказ) — закрывает ранее непокрытую ветку TTL.

### Пункт 3. Raw prompt и полный actor context НЕ попадают в технические логи agent-runtime и Django — ПОДТВЕРЖДЕНО

Grep по всем вызовам логгеров (команды и вывод ниже) показал: ни один вызов `logger.*`/`logging.*`/`print(` в `services/agent_runtime/` и `apps/ai/` не интерполирует сырой prompt, полный actor-контекст или payload.

Команды:
```
grep -rn -E "logger\.|logging\.(debug|info|warning|error|critical|exception)|print\(" services/agent_runtime/ --include=*.py | grep -v "/tests/"
grep -rn -E "logger\.|logging\.|print\(" services/agent_runtime/ --include=*.py | grep -v "/tests/" | grep -iE "prompt|actor_context|actor=|payload"   # → пусто
grep -rn -E "logger\.|logging\.(debug|info|warning|error|critical|exception)|print\(" apps/ai/ --include=*.py | grep -v "test"
grep -rn -E "logger\.|print\(" apps/ai/ --include=*.py | grep -v "test" | grep -iE "prompt|actor_context"   # → пусто
```

Разбор по местам:
- `services/agent_runtime/app.py`: `_safe_chat_log_context` и inline `log_context` для `/ag-ui` содержат `prompt_sha256`, `prompt_length`, `history_count` и обезличенные поля actor (`actor_user_id`, `actor_channel`, `actor_is_superuser`, `actor_roles_count`, `page_context_present`) — **без сырого prompt и без полного actor**. Error-логи (`logger.error`) пишут только `request_id`/`conversation_id`/`error_type` (`exc.__class__.__name__`), не текст исключения.
- `services/agent_runtime/graph.py`: `logger.error("Tool %s failed: %s", tool_name, exc)` (стр. 242/369) — имя инструмента и объект исключения; prompt/actor не логируются. `_invoke_chat_model_with_deadline` и `faulthandler`-dump сырой prompt не пишут. Остаточное замечание (не дефект): текст `exc` от инструмента теоретически может содержать доменные данные из аргументов инструмента, но не chat-prompt и не actor-контекст.
- `apps/ai/views.py`: warning-логи (стр. 222/236/766/961/1095) содержат идентификаторы (`request_id`, `action_id`, `session`, `user_id`, при mismatch — `supplied_username`) и `error_type`; сырой prompt и текст исключения не пишутся.
- `apps/ai/services.py` (генерация заголовка): prompt не логируется.

Вывод: дефектов нет. Покрытие: существующий unit-тест `TestRuntimeSafeLogging.test_safe_chat_log_context_excludes_raw_prompt_and_actor_details` + зафиксированная grep-проверка выше.

### Пункт 4. Audit-путь ошибок хранит только `prompt_sha256`/`prompt_length` — ПОДТВЕРЖДЕНО

- `apps/ai/views.py:104` `record_chat_runtime_error` пишет в `AgentActionLog.request_payload` только `prompt_sha256` (sha256 от prompt) и `prompt_length`, плюс корреляцию (`conversation_id`, `request_id`, `origin_channel`, `model_id`, `session_external_id`) — **сырой prompt не пишется**. В `error_message` кладётся `str(exc)[:4000]` (текст исключения для операторского разбора, не prompt).
- Успешный tool-путь (`apps/ai/tooling.py:_build_audit_request_payload`) сохраняет только аргументы инструмента (`safe_payload`) + trace-контекст, причём для `memory.remember`/`memory.update_personal`/`ai.skills.create_or_update` чувствительные поля редактируются/усекаются. Chat-prompt в `AgentActionLog` не пишется (в gateway-вызовах `actor_context.user_prompt` отсутствует, `user_message=None`).
- Безопасный разбор по `request_id` (описан в `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md`, стр. 43-51, 120-126) остаётся рабочим: сообщение об ошибке несёт `request_id` → оператор находит `AgentActionLog` по `request_payload.request_id` → через связанные `session`/`message` при наличии прав смотрит `ChatMessage.content`. В логах — только идентификаторы, хэш и длина prompt, модель, код ошибки.

Вывод: дефектов нет.

## Цепочка таймаутов — вердикт и рекомендация

### Факты

- Agent-runtime (`services/agent_runtime/graph.py`): `LLM_DEADLINE_SECONDS=300` (стр. 31); `future.result(timeout=LLM_DEADLINE_SECONDS)` (стр. 100); `init_chat_model(..., timeout=300)` (стр. 212/339); идле-дедлайн стрима `AGENT_DEADLINE_SECONDS=300` (стр. 44). То есть один LLM-вызов рантайм разрешает до ~300с.
- Django-клиент к рантайму (`apps/ai/runtime_client.py`):
  - синхронный `/chat` → `httpx.post(..., timeout=self.timeout)`, где `self.timeout = LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT` default **90с** (`config/settings.py:553`). Это единый httpx-таймаут (connect/read/write/pool = 90).
  - `/chat/stream` и `ag_ui_stream` → `httpx.Timeout(connect=30, read=600, write=30, pool=30)` — **read=600с**.
- Gunicorn (`config/settings.py:595`): `GUNICORN_TIMEOUT` default **600**; prod-валидация (стр. 650-651): `min_stream_timeout = LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT + 30` (= 120 при 90), `GUNICORN_TIMEOUT >= min_stream_timeout` → 600 ≥ 120 (проходит).

### Кто кого обрубает первым

- **Синхронный `/chat`: РАССОГЛАСОВАНИЕ.** Клиент сдаётся через 90с, а рантайм разрешает один LLM-вызов до 300с. При долгом LLM Django обрубает первым: httpx-таймаут → `AgentRuntimeError` → пользователь видит ошибку «превышено время ожидания», **пока рантайм ещё работает** (до 300с). Последствия: (а) впустую потраченный compute рантайма и LLM-провайдера; (б) для write-инструментов побочный эффект (создание/переход заявки и т.п.) может записаться в БД **после** того, как пользователь уже получил таймаут, что провоцирует ретрай и потенциальные дубликаты действий. Этот путь используется как non-AJAX fallback в `AIChatMessageCreateView` (основной путь — стриминг).
- **Стриминг `/chat/stream` и AG-UI прокси: согласовано.** read=600с > 300с дедлайна рантайма, Django переживает рантайм. Здесь первым срабатывает дедлайн рантайма (300с), что корректно транслируется в один SSE `agent_runtime_error`.
- **Пограничное замечание по gunicorn.** Prod-валидация привязана к синхронному `LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT` (90), а не к стриминговому read=600. При этом `GUNICORN_TIMEOUT` (600) ровно равен стриминговому read (600) — worker-таймаут gunicorn без запаса относительно самого долгого стрима.

### Вердикт

Да, это дефект согласованности цепочки таймаутов — конкретно на синхронном пути `/chat` (клиентский дедлайн 90с существенно меньше собственного LLM-дедлайна рантайма 300с). Стриминговые пути согласованы.

### Рекомендация (значения по умолчанию НЕ менялись — решение владельца; к тому же `config/settings.py` в scope пакета 04)

Выбрать один из вариантов, осознанно:
1. Поднять `LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT` выше `300 + overhead` (~330-360с), чтобы синхронный клиент переживал LLM-дедлайн рантайма. Тогда prod-валидация потребует `GUNICORN_TIMEOUT >= ~360-390`; текущий default 600 это покрывает.
2. Либо снизить `LLM_DEADLINE_SECONDS` (graph.py) под клиентский бюджет 90с (например ~60с), если 90с — это намеренный продуктовый SLA. Учесть, что это затронет и стриминговый путь.
3. Либо признать синхронный `/chat` best-effort/устаревшим (он уже только fallback) и вести все ответы через стриминг.
4. Дополнительно: дать gunicorn запас относительно стримингового read=600 (GUNICORN_TIMEOUT > 600) либо снизить стриминговый `read`.

Почему не правил здесь: пакет прямо разрешает не менять дефолты (owner decision), а правка `LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT`/`GUNICORN_TIMEOUT` затрагивает `config/settings.py`, который редактирует параллельный пакет 04 (координационное ограничение — не трогать). Правка `LLM_DEADLINE_SECONDS` изменила бы поведение и стримингового пути, что тоже архитектурное решение владельца.

Как читать такое рассогласование (методически): выстройте таймауты по слоям от внешнего к внутреннему и проверьте монотонность «внешний ≥ внутренний + overhead». Клиент (Django→runtime) должен ждать дольше, чем максимально возможная работа сервера (LLM-дедлайн + tool round-trips), иначе клиент «сдаётся» на живой запрос: тратится ресурс и возможны побочные эффекты после ответа об ошибке. Здесь слой «клиент 90с» оказался короче слоя «LLM 300с» — классический перевёрнутый порядок таймаутов.

## Изменения кода

Продуктовый код НЕ менялся (аудит подтвердил исправность). Изменены только тестовые файлы (в пределах write_scope):

- `apps/ai/tests.py` — добавлены в `AIViewsTests`:
  - `test_tool_gateway_rejects_wrong_token`
  - `test_tool_gateway_rejects_nonexistent_user_id`
  - `test_tool_gateway_rejects_inactive_user`
- `services/agent_runtime/tests/test_normalization.py` — добавлен в `TestAGUIRuntimeEndpoint`:
  - `test_ag_ui_run_rejects_expired_actor_signature`

`config/settings.py`, `apps/core/*`, `.env.example`, `docs/deployment/*` не трогались. `make gen-struct` не запускался.

## Проверки (acceptance)

- `.venv/bin/python manage.py test apps.ai.tests` → `Ran 101 tests ... OK`.
- `.venv/bin/python -m pytest services/agent_runtime/tests -q` → `68 passed`.
- `.venv/bin/python manage.py check` → `System check identified no issues (0 silenced)`.

## Остаточные риски

- Рассогласование таймаутов на синхронном `/chat` остаётся до решения владельца (см. рекомендацию). Риск средний-низкий: основной трафик идёт через стриминг, где цепочка согласована.
- Мелкое замечание по логам: `logger.error("Tool %s failed: %s", tool_name, exc)` в graph.py может вынести в лог текст доменного исключения инструмента (не prompt, не actor). При желании можно логировать `exc.__class__.__name__` вместо `exc` — вне scope этого пакета, отдельным решением.
