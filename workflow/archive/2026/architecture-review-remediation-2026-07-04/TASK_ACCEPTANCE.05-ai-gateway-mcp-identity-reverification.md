# Приёмка: 05-ai-gateway-mcp-identity-reverification

Дата: 2026-07-07.
Роли: исполнитель-аудитор — субагент (Opus); независимая проверка — не требуется
(`independent_verification: false`, риск medium); code-review и приёмка —
агент-оркестратор.

## Вердикт

**Принят.** Аудит подтвердил корректность identity-контура; продуктовый код не
менялся, добавлены только тесты. Одна находка (рассогласование таймаутов) вынесена
в backlog как решение владельца — не блокирует приёмку.

## Вердикты аудита по чек-листу

1. **Привязка tool-вызова к проверенному активному user_id/сессии — ПОДТВЕРЖДЕНО.**
   `gateway_token_is_valid` (`hmac.compare_digest`), `validate_gateway_actor`
   (`apps/ai/views.py:201`, вызовы 1202/1248): требует `user_id>0`, проверяет
   `User.objects.filter(pk=..., is_active=True)` (отклоняет несуществующего/
   неактивного), сверяет username и владельца сессии. MCP-фасад — только через
   gateway. Дефектов нет.
2. **Actor-токены подписаны и с TTL — ПОДТВЕРЖДЕНО.** Выпуск: `apps/ai/ui_runtime/actor.py`
   (HMAC-SHA256 по каноничному payload, ключ — gateway-токен, `issued_at`);
   проверка: `services/agent_runtime/app.py:104` `_agui_signature_is_valid`
   (TTL default 900s + `hmac.compare_digest`). Дефектов нет.
3. **Raw prompt / полный actor context не в техлогах — ПОДТВЕРЖДЕНО grep-ом** по
   `logger.*`/`print(` в `services/agent_runtime/` и `apps/ai/`: логируются
   `prompt_sha256`+`prompt_length` и обезличенные поля.
4. **Audit ошибок хранит только `prompt_sha256`/`prompt_length` — ПОДТВЕРЖДЕНО**
   (`record_chat_runtime_error`, `views.py:104`); безопасный разбор по `request_id`
   рабочий.

## Acceptance-проверки

- `.venv/bin/python manage.py test apps.ai.tests` → **Ran 101 tests, OK**
  (добавлены `test_tool_gateway_rejects_wrong_token`, `..._nonexistent_user_id`,
  `..._inactive_user` — все проверяют 403 + отсутствие записи `AgentActionLog`).
- `.venv/bin/python -m pytest services/agent_runtime/tests -q` → **68 passed**
  (добавлен `test_ag_ui_run_rejects_expired_actor_signature` — ранее непокрытая
  ветка TTL).
- `.venv/bin/python manage.py check` → без ошибок.

## Находка: рассогласование цепочки таймаутов (в backlog, решение владельца)

На **синхронном** `/chat`: Django-клиент к agent-runtime ждёт
`LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT=90s`, а agent-runtime разрешает один
LLM-вызов до `LLM_DEADLINE_SECONDS=300s` (`services/agent_runtime/graph.py:31,100`).
Django обрубает первым: пользователь получает таймаут, пока рантайм ещё работает;
для write-инструментов побочный эффект может записаться уже после ответа об
ошибке (риск дублей). Стриминговые пути (`read=600s`) с 300s согласованы.

Правку значений исполнитель НЕ вносил — обоснованно: (а) `config/settings.py`
был в scope параллельного пакета 04 (координация), (б) это компромисс с
capacity-последствиями (поднятие sync-таймаута до >330s блокирует gunicorn-воркер
на всё это время; при 3 воркерах prefork несколько долгих чатов насыщают пул).

Рекомендация (варианты для владельца): (1) поднять
`LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT` > 330 и дать gunicorn запас над стримовым
read=600; (2) снизить `LLM_DEADLINE_SECONDS` под sync-таймаут; (3) вести весь
чат через стриминг. Занесено в `docs/planning/backlog.md`.

## Мелкое замечание (вне scope, в рекомендацию)

`graph.py`: `logger.error("Tool %s failed: %s", tool_name, exc)` может вынести в
лог текст доменного исключения инструмента (не prompt/actor). Низкий риск,
кандидат на сужение лога.
