# Block Brief: приведение памяти к hybrid-knowledge v0.5

## Зачем

Ядро памяти расходится с целевой архитектурой (`docs/architecture/hybrid-knowledge-architecture-v0.5.md`): канон инвертирован (база авторитетна, файл — копия; ручная правка файла ломает чтение), путь записи проходит через шесть сущностей и три воркера, граф построен как неработающий LLM-extraction контур, событийные таблицы дублируют git-историю, а 11 из 31 моделей относятся к чужому домену (автоупорядочивание файлов). Решение принято в `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md`.

## Что сделать

1. Файл знания — канон: frontmatter авторитетен, проекции пересобираемы, ручная правка — штатный путь (`needs-reconcile` вместо ошибки).
2. Прямая запись + pull-reconciler `memory_reconcile`; одна таблица-очередь с DLQ вместо четырех статусных таблиц.
3. Ревью и кандидатство — через git-примитив pending -> review -> merge; `log.md` и `index.md` генерируются из файлов.
4. File Source Auto Organization — вынести в `apps.filehub` и заморозить.
5. Graph-extraction контур удалить; взамен словарь типов рёбер + валидатор + детерминированный материализатор `relations:`.
6. Один профиль ранжирования (RRF); публичный выбор — только корпус.
7. Этапы data store 5а/5б НЕ реализуются: оставить заглушки в коде, DEBT-маркеры и debt-записи в backlog.
8. Документация, e2e acceptance, Definition of Done.

## Границы

- Не менять бизнес-права портала, AG-UI контур, secret handles, trust-гейты, PII-контур.
- Не реализовывать data store, graph runtime search, профили ADR-0016, external connector.
- Пользовательские данные не теряются: таблицы выводятся только после миграции содержимого; этап 1 работает с двойной сверкой и путем отката.
- Кроссплатформенная блокировка записи (Windows!) — до отключения очереди записи.

## Источники

- `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` — решение;
- `docs/architecture/hybrid-knowledge-architecture-v0.5.md` — целевой концепт (v0.6 внутри);
- `docs/planning/active/memory-hybrid-knowledge-v05-alignment.md` — проектный план;
- `docs/architecture/MEMORY_MVP_CURRENT_STATE.md` — текущая граница;
- `ARCHITECT_PLAN.json` и `task-packets/` — порядок исполнения.

## Результат приемки

Все восемь task packets имеют executor report и task acceptance; e2e acceptance-сценарии из проектного плана проходят; документация и debt-артефакты 5а/5б на месте; ретроспектива написана.
