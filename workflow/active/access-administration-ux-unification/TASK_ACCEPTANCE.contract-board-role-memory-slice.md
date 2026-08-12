# Приёмка: contract, Board, role impact и memory groups

Статус: принято.

## Принятые критерии

- два отдельных процесса с общей БД и рабочим контрактом дают один `APPLIED` и
  один stale conflict;
- fault/reconciliation/rollback не оставляют неизвестную версию доступной для
  следующей записи;
- определение роли меняет только active superuser, одна роль за операцию;
- superuser self-assignment сохранён через рискованный signed preview/apply;
- Board и memory technical groups имеют отдельные owner-сервисы и аудит;
- резервный Django Admin вызывает те же role/Board сервисы;
- конкурентное подтверждение AI вызывает dispatch ровно один раз, а неопределённый
  итог не маркируется ложным успехом;
- операторское наблюдение AI не закрывает неопределённый статус до реализации
  fencing, а устаревший user-update отклоняется по подписанному состоянию;
- профиль и AD-связь откатываются, если их аудит не записался;
- lifecycle и аудит пользователя применяются под общим lock и одной транзакцией;
- исходные profile/AD principal не попадают в аудит, используются HMAC-отпечатки;
- сквозной HTTP-сценарий подтверждает фактическое изменение области роли.

## Выполненные целевые проверки

- точечные AD mode и AI audit tests: 3 passed;
- широкий затронутый набор: 520 passed, 9 deselected, 80 subtests;
- profile `contracts`: 48 passed, 51 deselected;
- profile `ai`: 205 passed, 8 subtests;
- profile `memory`: 92 passed, 59 subtests;
- profile `ui`: 268 passed, 16 subtests и 3 Playwright smoke/e2e;
- profile `deployment`: 29 passed, 58 deselected, 8 subtests;
- standalone `access_administration_e2e` на отдельной чистой SQLite-базе: OK,
  тестовые данные удалены; helper контекста дополнительно покрыт 2 тестами;
- регрессия медленных seed-команд после исправления: 4 passed;
- финальный `make verify-full`: 682 passed, 104 subtests на чистой базе с
  реальными миграциями; `check`, `check_staticfiles`, `makemigrations --check`
  и валидация 17 архитектурных контрактов прошли;
- независимый статический security-review: замечаний P0/P1/P2 нет;
- Luna-критик проверил корректирующий bootstrap-срез; замечания по ADR,
  `backlog` и единственности аудита устранены и покрыты 2 подтестами.

## Остаточный риск

AD role sync остаётся fail-closed даже при включённом mapping до появления
поддерживаемого system actor. Пакеты 04/05 и проверка владельцем остаются активными;
workflow-блок не архивируется.
