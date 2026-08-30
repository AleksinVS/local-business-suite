# Исполнение блока упрощения настроек

Этот документ определяет порядок работы исполнителей и проверяющих. Он не даёт
разрешения на production cutover.

## 1. Старт пакета

Перед каждым пакетом исполнитель:

1. читает ADR-0048, проектную архитектуру, активный план и свой task packet;
2. проверяет зависимости пакета и решения владельца;
3. фиксирует `git status --short` в executor report;
4. перечисляет уже существующие незакоммиченные файлы и не изменяет их без
   write scope;
5. выполняет read-only baseline checks;
6. подтверждает, что временные выводы пойдут в `.local/`;
7. не начинает cutover, если ADR/gate не выполнен.

Если затронутые строки уже изменены владельцем или другим активным блоком,
исполнитель останавливает пересекающийся write и сообщает точный конфликт.
Запрещены `git stash`, `git restore`, `git reset`, `git clean` и переключение
ветки без прямого запроса владельца.

## 2. Состояния task packet

- `planned` — пакет описан, стартовый gate не выполнен;
- `ready` — gate выполнен, scope подтверждён;
- `in_progress` — исполнитель начал write;
- `implemented` — код и локальные проверки готовы;
- `accepted` — независимая проверка и основной агент приняли результат;
- `blocked_external` — требуется решение владельца, production доступ или
  внешняя инфраструктура.

Статус `accepted` ставится только после `TASK_ACCEPTANCE.<task-id>.md`.

## 3. Общая реализационная дисциплина

- Generic storage mechanics находятся в Settings Center/shared configuration
  layer; доменная семантика остаётся в domain apps.
- Новый документ сначала получает спецификацию, validator и tests, затем reader,
  затем writer, и только потом cutover.
- Один task packet не добавляет второй неучтённый registry.
- Reader не возвращает изменяемую ссылку на кэшированный payload.
- DB transaction короткая; внешние вызовы и reindex не выполняются под row lock.
- Writer сначала получает transaction-level advisory locks для сортированного
  набора document ids, затем row locks; это обязательно и для отсутствующего
  override. Ключ стабильно выводится из SHA-256, не через Python `hash()`.
- Cache/notification выполняется только через `transaction.on_commit()`.
- Security writer не заменяется generic CRUD.
- Rollback создаёт новую ревизию и audit event.
- Schema mismatch не чинится рекурсивным merge.
- Секретоподобные ключи проверяются и маскируются до audit/report.

## 4. Проверки перед и после изменения

Перед пакетом:

```bash
git status --short
make verify-fast TEST_SCOPE=<baseline-scope>
```

После содержательного изменения:

```bash
make verify-fast TEST_SCOPE=<affected-tests>
git diff --check
```

При первом содержательном падении:

1. сохранить длинный вывод в `.local/`;
2. определить первую причину;
3. исправить или сузить гипотезу;
4. использовать `make test-failed`;
5. не повторять одну и ту же команду более двух раз без новой гипотезы.

Профили и полный прогон задаются task packet. Пакет 08 выполняет единственный
финальный `make verify-full`.

## 5. Executor report

После реализации создаётся
`EXECUTOR_REPORT.<task-id>.md` со следующими разделами:

```text
# <task id/title>
## Исходное состояние Git
## Реализованные изменения
## Изменённые файлы
## Миграция данных
## Выполненные проверки
## Результаты и длительность
## Первое содержательное падение и исправление
## Security/privacy/recovery оценка
## Отклонения от packet
## Остаточные риски
## Готовность к независимой проверке
```

Длинные логи не копируются в Markdown: report содержит путь внутри `.local/` и
краткий итог.

## 6. Независимая проверка

Проверяющий не меняет код, Git и runtime data. Он получает read scope, матрицу и
критерии, а не команду «запустить один тест».

| Пакет | Основная независимая матрица |
|---|---|
| 01 | полнота inventory, отсутствие доменной семантики в generic registry |
| 02 | конкурентные insert/update, row locks, rollback, audit atomicity |
| 03 | классификация drift, идемпотентность, секреты, backup/rollback |
| 04 | два документа/один UX, multi-worker, цвета и fallback |
| 05 | роли, roleless, default role, privilege ceiling, workflow transitions |
| 06 | gateway allowlist/auth, ETag, schema mismatch, last-known-good |
| 07 | memory commands, FileHub jobs, privacy/trust snapshot, static classification |
| 08 | полный cross-domain e2e, recovery, legacy-reference scan |

Существенное отклонение основной агент воспроизводит. Результат оформляется как
`TASK_ACCEPTANCE.<task-id>.md` с решением `accepted`, `changes_requested` или
`blocked_external`.

## 7. Cutover protocol

Для каждого документа/среза:

1. определить владельца и freeze window;
2. сделать backup legacy-файла и PostgreSQL;
3. выполнить migration `--plan`;
4. проверить audit evidence и schema version;
5. остановить write UI/commands для среза;
6. повторить final `--plan`;
7. выполнить `--apply`;
8. переключить reader/writer;
9. выполнить unit/integration/e2e smoke;
10. проверить health и hashes во всех потребителях;
11. открыть write;
12. зафиксировать observation window и rollback deadline.

Если runtime drift неоднозначен, `--apply` отказывается продолжать. Решение
владельца фиксируется в executor report и audit context.

Постоянная file+DB dual-write запрещена. Допустим только короткий read-only
comparison в рамках dry-run/verification.

## 8. Rollback protocol

Rollback разрешён автоматически только когда:

- legacy backup проверен;
- после cutover нет новых несовместимых DB revisions;
- schema versions совместимы;
- ожидаемые hashes совпадают;
- возврат не потеряет audit или изменения пользователя.

Если новые ревизии появились, сначала выполняется управляемый export текущей DB
версии в совместимый legacy payload и validation. Простое переключение на старый
файл запрещено.

## 9. Завершение блока

Пакет 08:

- собирает все executor/acceptance reports;
- подтверждает отсутствие незавершённых migrations и ambiguous drift;
- выполняет recovery drill и финальные e2e;
- обновляет ADR status/последствия только после решения владельца;
- обновляет README, operations/deployment, `.desc.json`, PROJECT_STRUCTURE;
- создаёт `RETROSPECTIVE.md`;
- после пользовательской приёмки переносит planning/workflow в архив и удаляет
  задачу из backlog.

До этого workflow остаётся в `workflow/active/`.
