# Исправления по архитектурному ревью 2026-07-04

## Цель

Закрыть находки ревью `docs/guides/ARCHITECTURE_REVIEW_2026-07-04.md`: согласованное и
аудируемое чтение/запись контрактов во всех процессах, рабочий production-контур
(контракты agent-runtime, защищённая раздача медиа), изоляция IIS/dev-артефактов,
воспроизводимая сборка, вывод легаси (`legacy`-драйвер AI UI, остатки SQLite-разделения),
гигиена структуры и планирования.

## Бизнес-ценность

Права ролей применяются одинаково во всех воркерах сразу после изменения; вложения заявок
доступны в production и только тем, кому положено; правки AI-контрактов реально доходят до
агента; сборка воспроизводима; матрица AI UI сокращается, документация и планирование
соответствуют фактическому состоянию.

## Границы (scope)

12 task packets, сгруппированных в 4 фазы. Полный write scope — в
`docs/planning/active/architecture-review-remediation-2026-07-04.md` и в самих пакетах.

## Non-goals

- Не менять бизнес-модели заявок, памяти, аналитики.
- Не трогать CopilotKit-драйвер и `services/copilot_runtime` (решение по нему отложено).
- Не переносить контракты в БД; не реализовывать доставку контрактов через gateway
  (шаг 2 ADR-0031) — отдельная будущая задача.
- Не трогать `learning/`, `drafts/`, личный корневой `BACKLOG.md`.
- Не проводить миграции данных (dev-стадия).

## Решения владельца

1. `DEPLOY_PRIVATE.md` переносится в `deployments/` и описывается в PROJECT_STRUCTURE.yaml.
2. `legacy`-драйвер AI UI выводится (ADR-0032); CopilotKit — без решения, не трогать.

## ADR

- `docs/adr/ADR-0031-runtime-contract-store-and-delivery.md` — Accepted 2026-07-05
  с уточнениями реализации (ключ инвалидации по метаданным файла, неизменяемый payload,
  fail-fast/fail-safe семантика ошибок, снимок на запрос, оптимистическая проверка записи,
  обязательное перечитывание в agent-runtime); реализуется пакетами 01/02/08.
- `docs/adr/ADR-0032-retire-legacy-ai-ui-driver.md` — Accepted; реализуется пакетом 09.

## Связь с блоком 2026-06-01

Блок `workflow/active/architecture-review-remediation-2026-06-01/` не исполнялся и
помечен superseded. Его задача 01 неактуальна (ADR-0029), задачи 02/03/04 поглощены
пакетами 01, 05, 04+12 текущего блока. Архивация старого блока — пакет 12.

## Acceptance

Блок принят, когда:

- изменение прав роли через Settings Center применяется во всех воркерах без перезапуска
  (подтверждено тестом с независимыми экземплярами store или multi-worker e2e);
- запись `role_rules` возможна только через service layer с валидацией и audit;
- agent-runtime в Docker читает рабочие контракты из `data/contracts/` (read-only) и
  логирует фактический источник;
- `/media/...` в production отдаётся авторизованным view с проверкой прав, анонимному
  пользователю — отказ;
- IIS-middleware и `debug_request` включаются только явным env-флагом, лог пишется в
  `data/logs/`, файла `C:\inetpub...` в корне нет;
- образы собираются из `requirements.lock`; `docker-compose.prod.yml` не привязан к
  `test-host` и не содержит мёртвых томов;
- bootstrap-побочные эффекты вынесены из импорта settings; валидация контрактов доступна
  как system checks;
- `validate_architecture_contracts` показывает дрейф default↔runtime по всем контрактам;
- `legacy`-драйвер удалён, матрица AI UI — `copilotkit/native`;
- SQLite-легаси (router, legacy-константы) удалено;
- доменные валидаторы вынесены из `apps/core/json_utils.py`, монолитные `tests.py` разбиты;
- завершённые/superseded блоки в архиве, backlog синхронизирован, `DEPLOY_PRIVATE.md`
  в `deployments/`, битые ссылки исправлены, `PROJECT_STRUCTURE.yaml` перегенерирован;
- сводные проверки блока зелёные; независимая проверка выполнена для пакетов 01-03.

## Сводные проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test
git diff --check
```
