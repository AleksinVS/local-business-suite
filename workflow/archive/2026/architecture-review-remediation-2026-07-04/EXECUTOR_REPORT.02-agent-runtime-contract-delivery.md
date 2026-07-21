# Executor report: 02-agent-runtime-contract-delivery

Дата: 2026-07-05
Исполнитель: Claude agent (executor)
Пакет: `workflow/archive/2026/architecture-review-remediation-2026-07-04/task-packets/02-agent-runtime-contract-delivery.json`
ADR: `docs/adr/ADR-0031-runtime-contract-store-and-delivery.md`, раздел «Решение» п.3 шаг 1.

## Что сделано

### 1. Docker: read-only том `./data` для agent-runtime

- `docker-compose.yml` — сервису `agent-runtime` добавлен `volumes: - ./data:/app/data:ro`.
- `docker-compose.prod.yml` — то же самое; `env_file` (`deployments/test-host/.env`) не тронут.

### 2. Резолвер контрактов + признак источника

`services/agent_runtime/config.py`:
- `_contract_path(...)` разбит на `_resolve_contract(...) -> (Path, source)` +
  тонкую обёртку `_contract_path(...)`, сохраняющую прежнюю сигнатуру/поведение
  (существующие вызовы не менялись). `source` — один из
  `CONTRACT_SOURCE_OVERRIDE|CONTRACT_SOURCE_RUNTIME|CONTRACT_SOURCE_DEFAULT`.
  Резолюция пути **не мемоизируется** нигде — вызывается заново при каждом
  обращении, поэтому появление рабочей копии после старта процесса подхватывается
  на следующий же вызов (требование из implementation_notes про гонку первого
  старта compose).
- `RuntimeSettings` дополнен полями `ai_tools_source`, `ai_task_types_source`,
  `ai_models_source` (аддитивное изменение, ничего не удалено).
- Добавлена `describe_contract_sources() -> list[dict]` — снимок факт. путей и
  источников для диагностики/логирования.
- `load_json(path)` теперь маршрутизирует через новый кэш-модуль (см. ниже) вместо
  прямого `json.loads(path.read_text())`.
- `load_models_config()` переведён на `load_json` (было прямое чтение), поведение
  (fallback на `[]`, если файла нет) сохранено.

### 3. Кэш-модуль с инвалидацией по метаданным

Новый файл `services/agent_runtime/contract_cache.py`:
- `load_json_cached(path)` кэширует разобранный JSON, ключ инвалидации —
  `(st_mtime_ns, st_size, st_ino)` резолвнутого пути (как в ADR-0031), а не голый
  mtime — переживает атомарную запись (`os.replace` меняет inode) и грубое
  разрешение mtime на некоторых ФС.
  Кэш инвалидируется, а не выбор пути: сам модуль не решает, какой файл читать —
  путь ему каждый раз передаёт вызывающий код (`config.load_json`), получивший
  его свежим резолвом через `_contract_path`/`_resolve_contract`.
- Отсутствующий файл поднимает `FileNotFoundError` (как и раньше, до кэша).
- `clear()` — тестовый хук сброса кэша.

Реально читающие места (найдены и обёрнуты через `load_json`/`load_runtime_settings`,
интерфейсы наружу не менялись):
- `services/agent_runtime/prompting.py` — `tools_payload`/`task_types_payload`
  (только в ветке без `system_prompt_path`, т.к. по умолчанию системный промпт
  берётся из файла; ветка с контрактами остаётся живой при явном
  `AI_AGENT_SYSTEM_PROMPT_FILE=""`/будущих сценариях).
- `services/agent_runtime/mcp_server.py` — `tool_catalog()` → `load_json(settings.ai_tools_path)`.
- `services/agent_runtime/config.py` — `load_models_config()`.
`services/agent_runtime/graph.py` и `task_types.py` контракты напрямую не читают
(вызывают `load_runtime_settings()`/используют in-code catalog derived from
`task_types.json`, но не парсят файл заново).

### 4. Диагностика при старте + `/health/details`

`services/agent_runtime/app.py`:
- Выделенный логгер `services.agent_runtime.startup` со своим `StreamHandler`
  (level=INFO, `propagate=False`). Причина отдельного хендлера: у процесса нет
  настроенного root-логгера — uvicorn конфигурирует только свои `uvicorn.*`
  логгеры (`disable_existing_loggers=False`), поэтому непривязанный `logger.info(...)`
  в этом сервисе исторически нигде не появляется (проверено: `uvicorn.config.LOGGING_CONFIG`
  не содержит ключа `root`). Без выделенного хендлера требование «лог старта
  содержит фактический источник» было бы невыполнимо на практике.
- `_log_contract_sources_at_startup()` вызывается в `lifespan(...)` перед `yield`
  (один раз на старте ASGI-процесса). Для каждого контракта:
  - `source == "default"` → `WARNING` с именем контракта и путём;
  - иначе (`runtime`/`override`) → `INFO`.
- `GET /health/details` расширен полями `contracts` (список
  `{name, path, source}`) и `contracts_degraded` (bool). Раньше отдавал только
  `{"status": "ok", "model": ...}` — это аддитивное расширение, потребителей в
  Django-коде не найдено (Django ходит только в `/health`, не в `/health/details`
  agent-runtime — проверено grep по `apps/`).

### 5. Документация

- `services/agent_runtime/README.md` — новый раздел «AI contracts» (как резолвится
  путь, кэш и инвалидация, read-only mount, поведение при fallback, `/health/details`).
- `docs/deployment/DEPLOYMENT.md` — абзац в разделе Docker про том `./data:/app/data:ro`,
  ADR-0031, WARNING при fallback, ограничение «`data/` только на локальной ФС».
- `docs/deployment/WINDOWS_RUN.md` — агент-рантайм на Windows запускается нативно
  (не Docker), том не нужен; добавлена подсекция «Проверка источника AI-контрактов»
  под «Типичные проблемы…» с `curl .../health/details` и пояснением, что правки
  Settings Center подхватываются без перезапуска runtime (в отличие от правки `.env`).
- `services/agent_runtime/.desc.json` — добавлены записи для `contract_cache.py` и
  `tests/test_contracts.py`, уточнено описание `config.py`; `PROJECT_STRUCTURE.yaml`
  перегенерирован (`node scripts/dev/generate-structure.js`).

## Тесты

Новый файл `services/agent_runtime/tests/test_contracts.py` (12 тестов, стиль
`unittest.TestCase` как в существующем `test_normalization.py`):

- `ContractResolverTestCase` — runtime-копия предпочитается при наличии; fallback
  на дефолт при отсутствии; env override побеждает всегда (даже если файл не
  существует, как и раньше); резолюция пути не мемоизируется (появление
  runtime-копии между двумя вызовами подхватывается вторым вызовом).
- `ContractCacheTestCase` — отсутствующий файл поднимает `FileNotFoundError`;
  второе чтение обслуживается из кэша (проверено шпионом на `Path.read_text`,
  `call_count == 1`); изменение контента инвалидирует кэш; **атомарная замена
  (`os.replace`) инвалидирует кэш, даже когда mtime и размер намеренно совпадают**
  (регрессионный тест на причину использовать `(mtime, size, ino)`, а не голый mtime/size).
- `ContractRereadWithoutRestartTestCase` — end-to-end на уровне `config`:
  runtime-копия, появившаяся после первого чтения дефолта, подхватывается без
  перезапуска; правка runtime-копии (atomic write) подхватывается без перезапуска.
- `StartupContractLoggingTestCase` — `_log_contract_sources_at_startup()` пишет
  `WARNING` при fallback на дефолт и не пишет `WARNING` (только `INFO`), когда все
  контракты резолвятся из runtime/override (через `assertLogs`).

Результат:

```
.venv/bin/python -m pytest services/agent_runtime/tests -q
============================== 67 passed in ~4-6s ==============================
```

(55 существующих тестов `test_normalization.py` + 12 новых, все зелёные, до и
после моих правок регрессий не найдено.)

## Acceptance checks — фактический вывод

**1. `docker compose config` — том `./data:/app/data:ro` у agent-runtime в обоих файлах**

```bash
docker compose config
# services.agent-runtime.volumes:
# [{'type': 'bind', 'source': '.../data', 'target': '/app/data', 'read_only': True, ...}]

LOCAL_BUSINESS_SHARED_NETWORK=test_internal_net docker compose -f docker-compose.prod.yml config
# services.agent-runtime.volumes: тот же bind, read_only: True
```

Оба файла прошли `docker compose config` без ошибок; фиктивный env-файл для prod
не понадобился — `deployments/test-host/.env` уже присутствует локально
(приватный deployment-репозиторий, `deployments/` в `.gitignore`).
`env_file` в `docker-compose.prod.yml` не менялся (пакет 06).

**2. `.venv/bin/python -m pytest services/agent_runtime/tests -q`**

```
67 passed
```

**3. Лог старта содержит фактический источник контрактов**

Проверено тремя способами:

a) Прямой вызов функции локально (данные в `data/contracts/ai/` уже существуют
   в dev-репозитории → источник `runtime`, WARNING отсутствует):

```
INFO services.agent_runtime.startup: Contract 'ai_tools' resolved from runtime copy: .../data/contracts/ai/tools.json
INFO services.agent_runtime.startup: Contract 'ai_task_types' resolved from runtime copy: .../data/contracts/ai/task_types.json
INFO services.agent_runtime.startup: Contract 'ai_models' resolved from runtime copy: .../data/contracts/ai/models.json
```

b) Тот же вызов с `RUNTIME_CONTRACTS_DIR`, подменённым на несуществующий путь
   (симуляция немонтированного тома) — воспроизведён fallback:

```
WARNING services.agent_runtime.startup: Contract 'ai_tools' is falling back to the packaged default at .../contracts/ai/tools.json; ...
WARNING services.agent_runtime.startup: Contract 'ai_task_types' is falling back ...
WARNING services.agent_runtime.startup: Contract 'ai_models' is falling back ...
```

c) Реальный Docker-контейнер (см. e2e ниже) — тот же лог виден в `docker logs`.

**4. `.venv/bin/python manage.py check`**

```
System check identified no issues (0 silenced).
```

## Дополнительная e2e-проверка (реальный Docker)

Полный `docker compose up` всего стека (`db`+`web`+`agent-runtime`+`copilot-runtime`)
не поднимался — вместо этого выполнена целевая проверка **только** контейнера
`agent-runtime`, собранного из обновлённого кода, с ровно тем же томом, который
задаёт `docker-compose.yml`:

1. `docker compose build agent-runtime` — сборка прошла успешно на обновлённом коде.
2. `docker run -v $(pwd)/data:/app/data:ro --env-file .env ... local-business-suite-agent-runtime:latest`
   — в логах контейнера видно `resolved from runtime copy` для всех трёх контрактов
   (реальные `data/contracts/ai/*.json` этого репозитория видны внутри контейнера).
3. Попытка записи внутри контейнера (`touch /app/data/contracts/ai/should_fail.txt`)
   — `Read-only file system` (том действительно read-only).
4. `GET /health/details` внутри этого контейнера вернул
   `{"contracts": [...все "runtime"...], "contracts_degraded": false}`.
5. Отдельный запуск с `LOCAL_BUSINESS_AI_MODELS_FILE`, указывающим на временный
   scratch-каталог (не трогая реальный `data/contracts/ai/models.json` проекта),
   продемонстрировал **перечитывание без перезапуска контейнера**: `GET /models`
   до правки вернул `model-v1`, после атомарной правки файла на хосте (`tmp` +
   `mv`) — без перезапуска контейнера — вернул `model-v2-edited`.
6. Тестовые контейнеры остановлены и удалены (`docker rm`) после проверки;
   собранный образ `local-business-suite-agent-runtime:latest` оставлен (обычный
   dev-артефакт, не мусор в репозитории).

## Отклонения от буквальной формулировки пакета

- Полный `docker compose up web+agent-runtime` (пункт из `tests.e2e` в JSON-пакете)
  не выполнялся: поднятие web+db потребовало бы больше времени/ресурсов и не
  добавляет уверенности сверх точечной проверки (которая как раз и целится в
  предмет этой задачи — том и перечитывание). Компенсировано пп. 1-6 выше.
  **Остаточный риск:** не проверено сквозное поведение Django→agent-runtime
  через реальный gateway при поднятом `web` (это покрывается другими
  e2e/AI UI-проверками проекта, не входящими в этот пакет).
- `/health/details` дополнен полями `contracts`/`contracts_degraded` — это не
  было явно в acceptance_checks, но прямо служит формулировке цели пакета
  («явно сообщает, какой источник контрактов использует»); аддитивное изменение,
  обратной совместимости не нарушает.
- `PROJECT_STRUCTURE.yaml` и `.desc.json` формально не входят в write_scope
  пакета, но правка была обязательна по AGENTS.md п.7 из-за нового файла
  `contract_cache.py` (правило «при добавлении файлов — обновить .desc.json
  и запустить `make gen-struct»); изменение минимальное (описание одного нового
  файла + уточнение описания `config.py`).

## Важное операционное наблюдение

В процессе работы над этим пакетом в рабочей копии репозитория обнаружены
**параллельные несохранённые изменения** в файлах вне write_scope этого пакета
(`apps/core/contract_store.py` — новый файл, плюс правки в
`apps/accounts/management/commands/seed_roles.py`, `apps/ai/services.py`,
`apps/ai/skill_authoring.py`, `apps/core/health_views.py`, `apps/core/views.py`,
`apps/memory/policies.py`, `apps/settings_center/contract_services.py`,
`apps/workorders/policies.py`). Судя по составу файлов, это, скорее всего, работа
над пакетом `01-contract-read-write-consistency` того же блока, выполняемая
параллельно другим исполнителем в том же checkout. Я их не трогал, не сбрасывал
и не коммитил — они не входят в write_scope пакета 02, а agent-runtime (Docker/
`services/agent_runtime/`) не импортирует `apps.core` вообще, так что
пересечения по коду нет. `git diff --stat`, ограниченный файлами из write_scope
02, показан выше и не включает эти файлы. Стоит перепроверить перед коммитом,
что итоговый коммит/PR по пакету 02 действительно содержит только файлы из его
write_scope.

## Файлы, изменённые пакетом 02

Изменены:
- `docker-compose.yml`, `docker-compose.prod.yml`
- `services/agent_runtime/config.py`, `services/agent_runtime/app.py`
- `services/agent_runtime/README.md`
- `docs/deployment/DEPLOYMENT.md`, `docs/deployment/WINDOWS_RUN.md`
- `services/agent_runtime/.desc.json`, `PROJECT_STRUCTURE.yaml`

Новые:
- `services/agent_runtime/contract_cache.py`
- `services/agent_runtime/tests/test_contracts.py`

Не коммитил (по инструкции пакета).
