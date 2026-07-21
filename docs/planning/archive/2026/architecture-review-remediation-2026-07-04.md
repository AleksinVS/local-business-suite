# Исправления по архитектурному ревью 2026-07-04

Статус: active plan.

Связанные материалы:

- ревью: `docs/guides/ARCHITECTURE_REVIEW_2026-07-04.md`;
- workflow-блок: `workflow/archive/2026/architecture-review-remediation-2026-07-04/`;
- ADR: `docs/adr/ADR-0031-runtime-contract-store-and-delivery.md` (Accepted 2026-07-05,
  с уточнениями реализации), `docs/adr/ADR-0032-retire-legacy-ai-ui-driver.md` (Accepted);
- поглощаемый блок: `workflow/archive/2026/architecture-review-remediation-2026-06-01/`
  (superseded, см. раздел «Связь с блоком 2026-06-01»).

## Цель

Закрыть дефекты и расхождения, найденные в ревью 2026-07-04, не меняя основной стек:
привести чтение/запись контрактов к согласованному и аудируемому пути, восстановить
production-контур (контракты agent-runtime, раздача медиа), изолировать IIS-артефакты,
сделать сборку воспроизводимой и погасить накопленное легаси.

Главная ценность: права доступа применяются одинаково во всех процессах; production
на Docker/Caddy работает целиком, а не за вычетом медиа и рабочих контрактов агента.

## Решения владельца, ограничивающие scope

1. `DEPLOY_PRIVATE.md` — легитимный указатель на приватные репозитории; переносится в
   `deployments/` и описывается в `PROJECT_STRUCTURE.yaml` (пакет 12).
2. `learning/` и `drafts/` в корне остаются как есть — вне scope.
3. `legacy`-драйвер AI UI выводится (ADR-0032, пакет 09).
4. CopilotKit-драйвер не трогать: решение о его судьбе отложено; он остаётся
   равноправным драйвером и эталоном совместимости.

## Фазы и задачи

Полные постановки — в task packets блока. Здесь сводка.

### Фаза 1 — авторизация и целостность контрактов (high)

1. **01-contract-read-write-consistency** — единый contract store с кэшем по ключу
   метаданных файла `(st_mtime_ns, st_size, st_ino)`, неизменяемым payload, снимком на
   время запроса и оптимистической проверкой при записи (ADR-0031 п.1-2, уточнения
   2026-07-05); перевод `RoleRulesUpdateView` на `apply_contract_payload`, упразднение
   `_refresh_inprocess_setting` и прямых мутаций `settings`.
   Поглощает задачу 02 блока 2026-06-01.
2. **02-agent-runtime-contract-delivery** — том `./data:ro` для agent-runtime в обоих
   compose-файлах, обязательное перечитывание контрактов агентом по ключу метаданных
   (гонка первого старта compose), лог фактического источника, предупреждение о fallback
   на дефолты (ADR-0031 п.3 шаг 1).

### Фаза 2 — production-контур (high)

3. **03-protected-media-serving** — выдача медиа через авторизованный view с проверкой
   доступа к объекту (заявке), удаление `static(MEDIA_URL, ...)`-маршрута,
   деплой-документация.

### Фаза 3 — изоляция dev/deploy-артефактов (medium)

4. **04-iis-debug-contour-isolation** — `PathInfoDebugMiddleware` и `debug_request`
   за единым env-флагом IIS-контура, лог в `data/logs/`, удаление файла
   `C:\inetpub\portal\debug_path.log` из корня. Поглощает часть задачи 04 блока 2026-06-01.
5. **05-ai-gateway-mcp-identity-reverification** — перепроверка и закрытие задачи 03
   блока 2026-06-01 (identity-привязка gateway/MCP; raw prompt в логах runtime по
   состоянию на 2026-07-04 не обнаружен — зафиксировать фактическое состояние).
6. **06-build-reproducibility-and-prod-compose** — сборка образов из `requirements.lock`,
   параметризация `env_file` в `docker-compose.prod.yml`, удаление мёртвых томов.

### Фаза 4 — структурные улучшения (medium/low)

7. **07-settings-bootstrap-extraction** — вынос создания каталогов и копирования
   контрактов из импорта `config/settings.py` в явный bootstrap (entrypoint/команда),
   валидация контрактов через Django system checks, унификация `env_bool`.
8. **08-contract-defaults-drift-strategy** — отчёт о дрейфе default↔runtime для всех
   контрактов в `validate_architecture_contracts` (ADR-0031 п.4).
9. **09-legacy-ai-ui-driver-removal** — вывод `legacy`-драйвера по ADR-0032.
10. **10-sqlite-legacy-cleanup** — удаление no-op `LocalBusinessDatabaseRouter`,
    `LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES`, `LOCAL_BUSINESS_DB_SPLIT_ENABLED`
    (пост-ADR-0029; проект в dev-стадии, данные не мигрируются).
11. **11-core-structure-hygiene** — разнос доменных валидаторов из
    `apps/core/json_utils.py` по приложениям, разбиение монолитных `tests.py`
    на пакеты `tests/`.
12. **12-planning-docs-hygiene** — архивация завершённых/superseded workflow-блоков,
    синхронизация backlog, битая ссылка в `ARCHITECTURE.md`, перенос
    `DEPLOY_PRIVATE.md` в `deployments/` с обновлением `.desc.json` и
    `PROJECT_STRUCTURE.yaml`.

## Порядок исполнения

Фазы 1-2 — до остальных (авторизация и сломанный production важнее гигиены).
Внутри фазы 4 порядок свободный; пакет 08 зависит от пакета 01 (общий contract store),
пакет 12 выполняется последним (фиксирует итоговое состояние документации).

## Write scope (предполагаемый, уточняется в пакетах)

- `apps/core/` (contract store, views, middleware, json_utils, tests);
- `apps/settings_center/contract_services.py` и tests;
- `apps/ai/` (services, views, ui_runtime, шаблоны/статика legacy, tests);
- `apps/workorders/` (policies, media view, tests);
- `services/agent_runtime/config.py`, `app.py`;
- `config/settings.py`, `config/urls.py`;
- `docker-compose.yml`, `docker-compose.prod.yml`, `Dockerfile`,
  `docker/entrypoint.prod.sh`, `Makefile`;
- `contracts/` — только при добавлении версии схемы (пакет 08, по согласованию);
- документация: `README.md`, `docs/architecture/`, `docs/deployment/`, `docs/guides/`,
  `docs/adr/`, `docs/planning/`, `.desc.json`, `PROJECT_STRUCTURE.yaml`;
- `workflow/archive/2026/architecture-review-remediation-2026-07-04/` и архивация старых блоков.

## Non-goals

- Не менять бизнес-модель заявок, памяти, аналитики.
- Не трогать CopilotKit-драйвер и `services/copilot_runtime` (кроме документации).
- Не переносить контракты в базу данных.
- Не реализовывать шаг 2 доставки контрактов через gateway (ADR-0031 п.3) — отдельная
  будущая задача.
- Не трогать `learning/`, `drafts/`, личный корневой `BACKLOG.md`.
- Не проводить миграции данных (dev-стадия, production-данных нет).

## Definition of Ready — выполнено

- Цель и ценность: см. выше.
- Затрагиваемые модули и write scope: см. выше и task packets.
- Non-goals: см. выше.
- Acceptance checks: в каждом task packet + сводные проверки блока.
- ADR: ADR-0031 (Accepted 2026-07-05, с уточнениями реализации), ADR-0032 (Accepted).
  Блокирующих решений не осталось — фаза 1 готова к исполнению.

## Сводные проверки блока

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test
git diff --check
```

Для фазы 1-2 дополнительно обязателен e2e-сценарий: изменение прав роли через Settings
Center при нескольких воркерах (или его честная эмуляция в тестах через отдельные
экземпляры store) и HTTP-проверка выдачи медиа авторизованным/неавторизованным
пользователем. Независимая проверка субагентом обязательна для пакетов 01-03
(права доступа, security) по `docs/guides/TESTING_POLICY.md`.

## Связь с блоком 2026-06-01

Блок `architecture-review-remediation-2026-06-01` не исполнялся (нет executor reports).
Разбор его задач:

- 01 (миграции раздельных баз) — неактуальна после ADR-0029, закрыта без работ;
- 02 (путь записи role_rules) — поглощена пакетом 01;
- 03 (identity gateway/MCP, prompt в логах) — поглощена пакетом 05;
- 04 (debug log, ссылки, структура) — поглощена пакетами 04 и 12.

Старый блок помечен `SUPERSEDED.md` и архивируется пакетом 12 вместе с его планом
`docs/planning/archive/2026/architecture-review-remediation-2026-06-01.md`.

## Definition of Done блока

- Все пакеты либо приняты (executor report + acceptance), либо явно перенесены
  с причиной в backlog;
- README, PROJECT_STRUCTURE.yaml, ADR-0031/0032, deployment-документация обновлены;
- сводные проверки блока зелёные; для фазы 1-2 есть e2e-подтверждение;
- backlog очищен, блок перенесён в `workflow/archive/2026/`;
- ревью-документ 2026-07-04 получает статус «remediation complete».
