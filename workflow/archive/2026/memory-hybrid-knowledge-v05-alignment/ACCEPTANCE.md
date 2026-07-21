# Block Acceptance: memory-hybrid-knowledge-v05-alignment (ADR-0030)

Дата приемки: 2026-07-04.

## Решение

Блок принят. Все 8 task packets реализованы, каждый — отдельным коммитом с зелёными проверками на SQLite и PostgreSQL. Ядро памяти приведено к архитектуре hybrid-knowledge v0.5 (ADR-0030).

## Коммиты (ветка `feat/adr-0030-memory-alignment`)

| Packet | Commit |
|---|---|
| 01 канон + блокировка + reconciler | `4a5e20d`, `bae2ff7` |
| 02 прямая запись + схлопывание очередей | `8bcb8a9` |
| 03 git-ревью + кандидатство | `c17eef9` |
| 04 вынос `apps.filehub` + заморозка | `797cc4a` |
| 05 удаление graph-контура + рёбра | `fa4b02f` |
| 06 один профиль RRF | `4e16b68` |
| 07 заглушки data store | `65a3812` |
| 08 документация + e2e + DoD | (этот коммит) |

## Итоговые проверки (выполнены основным агентом на обоих бэкендах)

- `python manage.py check` — чисто (SQLite и PostgreSQL).
- `python manage.py makemigrations --check --dry-run` — «No changes detected».
- `python manage.py validate_architecture_contracts` — valid.
- `python manage.py test apps.memory.tests apps.ai.tests` — **180 tests, OK** на SQLite и PostgreSQL.
- `python manage.py memory_alignment_acceptance_e2e` — все 7 сценариев приемки пройдены на SQLite и PostgreSQL: manual edit→reconcile→search; remember→file+commit+index; sensitivity downgrade→pending; candidate→accept→org/; reconciler idempotent; edge vocabulary; data_store stub + DEBT-маркеры.
- `python -m pytest services/agent_runtime/tests/` — **55 passed** (tool-схема agent-runtime синхронизирована с сокращённым контрактом `memory.search`).

## Definition of Done

- Код и документация обновлены (`MEMORY_MVP_CURRENT_STATE.md`, `MEMORY_USER_GUIDE.md`, `MEMORY_DEPLOYMENT.md`, `AGENTS.md`, `README.md`).
- `.desc.json` и `PROJECT_STRUCTURE.yaml` актуальны.
- Backlog очищен от завершённого блока (удалён из `Next`); debt-записи этапов data store 5а/5б остаются в `Later`.
- Ретроспектива — `RETROSPECTIVE.md` (остаточные риски зафиксированы там).

## Остаточные риски (см. RETROSPECTIVE.md)

Windows-ветка блокировки протестирована только косвенно; `ingestion`-replay очереди не протестирован напрямую; стойкая dev-база `lbs-pg-verify` содержит устаревшие `MemoryKnowledgeItem`-строки (артефакт разработки, не дефект кода). Все — вне рантайм-корректности; полные тесты и e2e зелёные на обоих бэкендах.
