# Executor Report: Production Cutover на PostgreSQL

Дата: 2026-08-18. Хост: stc-web (Windows 10 Pro, IIS/DefaultAppPool, C:\inetpub\portal).
Основание: runbook `docs/deployment/POSTGRESQL_MIGRATION.md`, план `.local/postgresql-migration/CUTOVER_PLAN.md`.

## Выполнено

1. PostgreSQL 17.11 установлен на хосте (служба `postgresql-x64-17`, автозапуск, только 127.0.0.1).
   БД `local_business_suite`, роль `local_business_app`, расширения `unaccent`, `pg_trgm`.
2. Dry-run на копии runtime-данных пройден дважды (до и после расширения полей):
   export → validate → import --replace → validate --strict — 74 таблицы, 0 ошибок ограничений.
3. Cutover в freeze window (~20 минут):
   - остановлены DefaultAppPool, Portal Agent Runtime (и дубль-процесс рантайма);
   - бэкап `data/` (tar + консистентный sqlite-снимок) и `.env` в `.local/backups/postgresql-migration/`;
   - целевая БД пересоздана, `migrate` — 0 неприменённых миграций;
   - экспорт живого SQLite (все 4 алиасаlegacy-путей на `data/db/local_business.sqlite3` — см. П1 плана);
   - импорт `--replace`, strict-валидация: 74/74 таблицы, constraint_error пуст;
   - `memory_reindex`, `source_adapter_reconcile`, `memory_eval --dry-run` (passed=6, failed=0);
   - `.env` переведён на production: DJANGO_ENV=production, DEBUG=0, новые SECRET_KEY/
     AI_GATEWAY_TOKEN/AUDIT_FINGERPRINT_KEY (v2), GUNICORN_TIMEOUT=660, DATABASE_URL,
     fulltext=postgresql, queue=database;
   - пересобран staticfiles-манифест (без него DEBUG=0 роняет страницы на htmx-теге);
   - старт пула и рантайма.
4. Регулярный бэкап: `scripts/windows/backup_postgresql.ps1` + Scheduled Task
   `\Portal\Portal PostgreSQL Backup` (ежедневно 02:37, pg_dump -Fc + zip контрактов, ротация 7 дней).

### Security correction после merge-review

Первоначальная задача была создана от `SYSTEM` и писала в изменяемый
`data\backups`. Независимое ревью признало этот вариант небезопасным из-за
возможной подмены каталога NTFS junction. До следующего запуска задачу нужно
отключить и пересоздать под отдельной backup identity с каталогом
`C:\ProgramData\LocalBusinessSuite\backup`, закрытым ACL и параметрами identity
из `docs/deployment/POSTGRESQL_MIGRATION.md`. Обновлённый скрипт fail-closed
проверяет principal, ACL и reparse points и не удаляет посторонние файлы. Это
обязательное внешнее действие deployment; commit сам не меняет Scheduled Task.

## Смоук-проверки после cutover (все пройдены)

- `/health/` — 200 (внимание: с завершающим слэшем; `/health` без слэша — 404);
- страницы `/`, `/waiting-list/`, `/workorders/`, `/inventory/`, `/accounts/login/` — 200;
- users=29, waiting_list=19, devices=3119, chat messages=136, AgentActionLog=36;
- длинные значения inventory (493/134 симв.) на месте;
- права листа ожидания у shevchuk.elv: просмотр/создание/редактирование чужих записей — True,
  переходы из waiting = {cancelled, scheduled} (по карте workflow);
- `manage.py check` — 0 проблем; drift `validate_architecture_contracts` — тот же, что до cutover
  (trust_policy/status_colors, существовал ранее).

## Инциденты cutover и решения

- `ValueError: Missing staticfiles manifest entry for 'django_htmx/htmx.min.js'` при DEBUG=0 —
  лечится `collectstatic` (файлы лежат в `static/django_htmx` благодаря deploy-скрипту).
- Два процесса agent runtime (venv + системный python) на порту 8090 — остановлены при freeze.

## Rollback window

**Закрыто 2026-08-18**: владелец подтвердил приемку («все штатно») после записи пользователей
в PostgreSQL. Простой возврат к SQLite невозможен — только delta-reconciliation.
SQLite-файлы в `data/db` не удалены и остаются архивом дорезервного состояния
(прежний `.env` — `.local/backups/postgresql-migration/.env-cutover`).

## Открытые пункты

- Пересоздать backup Scheduled Task по security correction выше; до этого
  старая SYSTEM-задача должна быть отключена.
- Решение о закрытии SQLite runtime в `main` (вынос в fork по ADR-0029) — за владельцем;
  архивные файлы в `data/db` пока хранятся.
- Секреты: `.local/backups/postgresql-migration/generated_secrets.txt` и `cutover_django_secrets.txt`.
