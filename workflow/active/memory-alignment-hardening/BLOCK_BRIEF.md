# Block Brief: доводка памяти после ревью целевой архитектуры

## Зачем

Блок `memory-hybrid-knowledge-v05-alignment` (ADR-0030) исполнен и принят 2026-07-04. Ревью целевой архитектуры 2026-07-06 нашло пробелы, не покрытые исполнением, а ретроспектива блока зафиксировала остаточные риски. Без доводки: git-autocrlf на Windows ломает content-hash дисциплину; возможна петля `needs-reconcile`; конкурентные запуски reconciler не исключены; словарь рёбер существует без производителя рёбер; критерии возврата отложенных контуров (профили, граф) нефальсифицируемы без golden set.

## Что сделать

Три пакета (`task-packets/`): (01) LF-нормализация канона + защита reconciler от петли и конкурентных запусков; (02) golden set `memory_eval` + матрица восстановления; (03) инструкция эмиссии `relations:` для семантического прохода + чистка dead-config профилей + фикс фильтра review-UI.

## Границы

- Архитектура ADR-0030 не меняется; это доводка реализации.
- Data store (5а/5б), graph runtime search, профили ранжирования, фрагментный поиск — не в этом блоке.
- Массовая перезапись существующих файлов знаний запрещена.
- Каждый пакет проверяется на SQLite и PostgreSQL.

## Источники

- `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` — раздел «Требуемые действия», «Дополнение 2026-07-06»;
- `workflow/archive/2026/memory-hybrid-knowledge-v05-alignment/RETROSPECTIVE.md` — остаточные риски;
- `docs/planning/active/memory-alignment-hardening.md` — план;
- `docs/architecture/MEMORY_MVP_CURRENT_STATE.md` — текущая граница.

## Результат приемки

Все пакеты имеют executor report и task acceptance; Definition of Done из плана выполнен; ретроспектива написана.
