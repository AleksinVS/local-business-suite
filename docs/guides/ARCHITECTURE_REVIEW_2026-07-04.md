# Архитектурное ревью проекта

Дата: 2026-07-04.

Статус: review saved, remediation planned.

Предыдущее ревью: `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md`. Его remediation-блок
`workflow/archive/2026/architecture-review-remediation-2026-06-01/` не был исполнен (нет executor reports);
незакрытые задачи из него поглощаются новым блоком
`workflow/active/architecture-review-remediation-2026-07-04/` (см. раздел «Связь с ревью 2026-06-01»).

## Краткий вывод

Архитектурная дисциплина проекта (ADR, контракты, валидаторы, планирование) на высоком уровне.
Основные проблемы сосредоточены в рантайм-слое и противоречат заявленным принципам:

- изменения контрактов «на горячую» применяются только в одном из нескольких gunicorn-воркеров;
- agent-runtime в Docker вообще не видит рабочие контракты из `data/contracts/`;
- медиа-файлы не раздаются в production через контур Docker/Caddy и раздаются без проверки прав в dev;
- отладочный IIS-middleware с жёстким Windows-путём работает во всех средах.

Методологическое пояснение (класс проблемы): Django загружает настройки один раз при старте процесса.
Схема «записали файл + обновили `settings` в памяти» работает только в процессе, который обработал
запрос; остальные воркеры и отдельные сервисы продолжают жить со старой копией. Изменяемую
конфигурацию нужно либо читать из хранилища при обращении (с дешёвым кэшем по mtime), либо явно
доставлять во все процессы.

## Проверки, выполненные в ходе ревью

Ревью проводилось чтением кода и конфигурации без изменений прикладного кода, поэтому
тестовые прогоны не запускались. Проверенные точки зафиксированы ссылками на файлы и строки ниже.

## Находки

### 1. Ошибки (реальные дефекты)

#### 1.1. Горячее обновление контрактов работает только в одном процессе

- `apps/settings_center/contract_services.py:121` (`_refresh_inprocess_setting`) и
  `apps/core/views.py:138` после записи файла обновляют `settings.LOCAL_BUSINESS_ROLE_RULES`
  только в памяти текущего процесса.
- Production запускается с `--workers 3` (`docker/entrypoint.prod.sh`).
- Итог: после изменения прав ролей через UI два воркера из трёх продолжают применять старые
  права доступа до перезапуска. `role_rules` управляет авторизацией
  (`apps/workorders/policies.py:16` читает их из `settings`).

Рекомендация: единый `ContractStore`/`PolicyStore`, читающий файл по требованию с кэшем по
`stat().st_mtime`; убрать прямые чтения `settings.LOCAL_BUSINESS_*_RULES`. Решение: ADR-0031.

#### 1.2. Два пути записи одного контракта, один — без валидации и аудита

- `RoleRulesUpdateView.post` (`apps/core/views.py:110-141`) пишет `role_rules.json` напрямую:
  без `validate_role_rules_payload`, без записи `SettingsChange`, через поверхностный `.copy()`
  (вложенные словари мутируются в объекте настроек ещё до записи).
- AI-инструмент (`apps/ai/services.py:664`) ходит через `settings_center.apply_contract_payload`
  с валидацией и аудитом; его docstring утверждает «тот же путь записи, что и UI» — это неверно.
- Через UI можно сохранить контракт, который на следующем старте уронит процесс
  (`ImproperlyConfigured` в `config/settings.py`).

Рекомендация: перевести форму `apps/core` на `apply_contract_payload` или удалить её в пользу
Settings Center. Совпадает с незакрытой задачей 02 блока 2026-06-01.

#### 1.3. Agent-runtime не видит рабочие контракты в Docker

- `services/agent_runtime/config.py` резолвит контракты через `data/contracts/...`,
  но ни `docker-compose.yml`, ни `docker-compose.prod.yml` не монтируют `./data`
  в контейнер `agent-runtime` (том смонтирован только в `web`).
- Runtime молча откатывается на дефолты `contracts/`, запечённые в образ. Правки
  `tools.json`/`task_types.json`/`models.json` через Settings Center до агента не доходят;
  любое изменение дефолтов требует пересборки образа.
- Противоречит принципу «`data/contracts/` — рантайм-источник истины».

Рекомендация: минимально — смонтировать `./data:/app/data:ro` в agent-runtime; целевой
вариант — отдавать контракты рантайму через Django gateway. Решение: ADR-0031.

#### 1.4. Медиа-файлы не раздаются в production (контур Linux/Caddy) и не защищены

- Единственный маршрут — `config/urls.py:35` через `django.conf.urls.static.static()`,
  который возвращает пустой список при `DEBUG=0`. Whitenoise обслуживает только статику,
  Caddy проксирует всё на `web:8000`.
- Итог: вложения заявок (`data/media/workorders/`) в Docker-развёртывании отдают 404.
- Даже в dev медиа раздаётся без проверки прав: файлы по заявкам доступны любому, кто знает URL.

Рекомендация: защищённая выдача через view (`login_required` + проверка доступа к заявке +
`FileResponse`), без прямой раздачи каталога.

#### 1.5. Отладочный IIS-middleware работает во всех средах и пишет по жёсткому Windows-пути

- `apps/core/middleware.py:9` — `self.log_file = "C:\\inetpub\\portal\\debug_path.log"`.
  На Linux это создало файл-мусор `C:\inetpub\portal\debug_path.log` в корне проекта
  (нарушение правила «чистого корня»).
- Middleware включён безусловно (`config/settings.py:113`): эвристика переписывания
  `PATH_INFO` применяется и вне IIS; в dev-режиме на каждый запрос идёт открытие/дозапись
  файла с молчаливым проглатыванием исключений.

Рекомендация: включать по env-флагу только в IIS-развёртывании (deployment silo, правило 2
AGENTS.md), лог — в `data/logs/`; файл `C:\inetpub...` удалить из корня.

### 2. Противоречия с собственными правилами и документацией

- **`workflow/active` расходится с backlog.** В backlog «Active» — 13 направлений,
  в `workflow/active/` — 20 блоков. Блоки `architecture-review-remediation-2026-06-01`,
  `design-patterns-hardening-2026-06-01`, `memory-audit-review-ui`,
  `memory-hybrid-ranking-profiles`, `settings-center-gui`,
  `testing-policy-and-independent-verification`, `universal-right-drawer-ai-navigation`
  отсутствуют в активном backlog: либо backlog устарел, либо блоки должны уехать в
  `workflow/archive/<год>/`.
- **`docker-compose.prod.yml` привязан к конкретному хосту:** `env_file:
  deployments/test-host/.env` жёстко зашит в «общий» production-компоуз. Объявлены тома
  `db`, `media`, `static`, `logs`, которые никем не используются — мёртвая конфигурация.
- **Битая ссылка:** `docs/architecture/ARCHITECTURE.md:20` ссылается на
  `../../ai/chat_agent/ARCHITECTURE.md` — такого пути нет.
- **`requirements.lock` никем не используется.** Dockerfile и `make install` ставят
  `requirements.txt`; лок-файл не подключён ни к одной сборке — транзитивные зависимости
  в образе не зафиксированы.
- **Хостовые артефакты в корне:** каталог `VOB3/` (инструкции AD/IIS, `web.config.template`)
  относится к deployment silo. `DEPLOY_PRIVATE.md` — по решению владельца легитимен как
  указатель на приватные репозитории, но переносится в `deployments/` и описывается в
  `PROJECT_STRUCTURE.yaml`.

### 3. Неоптимальные решения

- **`config/settings.py` как исполняемый bootstrap (761 строка).** При импорте: создание
  ~20 каталогов, копирование контрактов (`get_contract_path`, `config/settings.py:401`),
  загрузка и валидация ~30 JSON-файлов. Любая команда `manage.py` платит эту цену; запись
  на диск при импорте конфигурации — побочный эффект в неожиданном месте. Лучше: settings
  только вычисляет пути; создание каталогов и копирование — в явной команде bootstrap;
  валидация — через Django system checks.
- **Копирование контрактов «один раз при первом старте» без стратегии обновления.**
  После копирования дефолт из git больше не влияет на рантайм-копию; дрейф проверяется
  только для AI tools (`validate_ai_tools_drift`). Нужен отчёт о дрейфе default↔runtime
  для всех контрактов и/или версия схемы в контракте.
- **`apps/core/json_utils.py` — модуль-«бог» (2131 строка, 48 функций).** Ядро знает
  валидацию контрактов всех доменов. Разрешение конфликта правил 3 и 5 AGENTS.md:
  в core — универсальное (`load_json_file`, `atomic_write_json`), доменные валидаторы —
  в `apps/<домен>/contracts.py` с декларативной регистрацией.
- **Монолитные `tests.py`** (`apps/memory/tests.py` — 2738 строк, `apps/ai/tests.py` — 2655):
  разложить в пакеты `tests/`.
- **Легаси после ADR-0029:** no-op `LocalBusinessDatabaseRouter` (`apps/core/db_routers.py`),
  `LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES`, константа `LOCAL_BUSINESS_DB_SPLIT_ENABLED = False`.
  Назначить срок удаления.
- **`debug_request` (`apps/core/debug_views.py`)** выводит переменные окружения
  staff-пользователю; инструмент диагностики IIS должен включаться тем же флагом,
  что и IIS-middleware.
- **Три драйвера AI-чата одновременно** (`legacy`, `copilotkit`, `native`) плюс Node-сервис
  `copilot_runtime` и Node-стадия сборки в основном Dockerfile. Решение владельца:
  `legacy` выводится (ADR-0032); судьба CopilotKit-драйвера не решена и остаётся вне scope.
- **Дублирование разбора env-переменных в settings:** есть `env_bool()`
  (`config/settings.py:226`), но часть флагов парсится вручную (строки 200-202, 556-558,
  601, 614-616, 626-630).
- **13 «активных» направлений в backlog** — большой объём параллельного незавершённого;
  рекомендуется ограничить WIP.

### 4. Что сделано хорошо

Культура ADR со статусами и связями; guard-rails production-конфигурации (запрет DEBUG,
дефолтных секретов, SQLite в production, проверка таймаута gunicorn против таймаута
стриминга); `hmac.compare_digest` для токена шлюза; TLS-настройки LDAP с проверкой
сертификата по умолчанию; атомарная запись контрактов; аудит изменений в Settings Center;
e2e-команды приёмки как первоклассные артефакты.

## Решения владельца по итогам обсуждения (2026-07-04)

1. `DEPLOY_PRIVATE.md` легитимен как указатель на приватные репозитории; переносится в
   `deployments/` и описывается в `PROJECT_STRUCTURE.yaml`.
2. Каталоги `learning/` и `drafts/` в корне остаются как есть (вне scope remediation).
3. `legacy`-драйвер AI-чата выводится из кода (ADR-0032).
4. По CopilotKit-драйверу решение не принято: он сохраняется как равноправный драйвер
   и эталон совместимости; его вывод или сохранение — отдельное будущее решение.

## Связь с ревью 2026-06-01

Статус задач старого блока `architecture-review-remediation-2026-06-01`:

| Задача 2026-06-01 | Состояние на 2026-07-04 | Куда уходит |
| --- | --- | --- |
| 01 миграции раздельных runtime-баз | Неактуальна: ADR-0029 свёл базы к единому `default` | Закрывается без работ |
| 02 единый путь записи role_rules | Не выполнена, дефект подтверждён (`apps/core/views.py:110-141`) | Пакет 01 нового блока |
| 03 identity checks AI gateway/MCP и prompt в логах | Частично: raw prompt в логах runtime не найден; identity-контур требует перепроверки | Пакет 05 нового блока |
| 04 debug log в корне и битые ссылки | Не выполнена: `C:\inetpub...` в корне, битая ссылка в `ARCHITECTURE.md` | Пакеты 04 и 12 нового блока |

Старый блок помечается как superseded и архивируется в рамках пакета 12.

## Приоритеты remediation

1. **Сейчас:** находки 1.1 + 1.2 (единый путь чтения/записи контрактов) — это авторизация.
2. **Сейчас:** находки 1.3 (контракты для agent-runtime) и 1.4 (раздача media с проверкой
   прав) — сломанная функциональность production-контура.
3. **Следом:** находка 1.5 + IIS-артефакты в deployment silo; подключить `requirements.lock`.
4. **Плановое:** bootstrap из settings, разнос `json_utils.py`, дрейф контрактов,
   SQLite-легаси, вывод `legacy`-драйвера, гигиена планирования и структуры.

## Связанные материалы

- План: `docs/planning/active/architecture-review-remediation-2026-07-04.md`.
- Workflow-блок: `workflow/active/architecture-review-remediation-2026-07-04/`.
- ADR: `docs/adr/ADR-0031-runtime-contract-store-and-delivery.md`,
  `docs/adr/ADR-0032-retire-legacy-ai-ui-driver.md`.
