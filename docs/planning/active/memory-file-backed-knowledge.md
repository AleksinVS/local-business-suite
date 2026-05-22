# Active plan: файловые знания, раздельные базы и единый поиск

Статус: первый MVP-срез миграции реализован, активен до приемки.

Дата: 2026-05-22.

## Цель

Привести систему памяти к целевой архитектуре:

- знания хранятся в файлах и версионируются через Git;
- данные остаются в источниках;
- временные raw/safe слои удаляются после обработки;
- метаданные и индексы вынесены отдельно;
- поиск знаний и файлового хранилища идет через единый сервис;
- чаты и управляющие модели аналитики вынесены в отдельные базы.

## Контекст

Связанные документы:

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0010-memory-mvp-simplification.md`;
- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/adr/ADR-0013-file-only-knowledge-body.md`;
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`.

Workflow:

- `workflow/active/memory-file-backed-knowledge/`.
- `workflow/active/memory-file-only-knowledge-body/` - следующий исполнительный блок для удаления текста знания из базы и индекса.

## Объем работ

Входит:

- формат файла знания;
- runtime Git-репозиторий `data/knowledge_repo/`;
- writer service с очередью, lock, временными файлами и атомарной заменой;
- reader service с проверкой прав;
- metadata database для знаний;
- единый search/index service с корпусами `knowledge` и `source_data`;
- режимы поиска без тяжелого планирования локальной моделью;
- degraded mode для `indexing_pending`;
- перенос чатов в `data/db/chat.sqlite3`;
- перенос управляющих моделей аналитики в `data/db/analytics_control.sqlite3`;
- отдельный процесс ночной рефлексии;
- migration/export существующих `MemoryKnowledgeItem` в файлы.

Не входит:

- выбор окончательного production backend для векторного индекса;
- внешний публичный API памяти;
- перенос секретов в новое хранилище;
- полная замена всех legacy-имен моделей за один этап;
- изменение бизнес-моделей портала, не связанных с памятью.

## Порядок реализации

1. Создать формат файла знания и схему проверки.
2. Добавить writer service и очередь записи.
3. Добавить reader service.
4. Настроить runtime Git-репозиторий знаний.
5. Перевести `memory.remember` на запись файла через очередь.
6. Создать metadata mirror для знаний.
7. Экспортировать существующие `MemoryKnowledgeItem` в файлы.
8. Построить единый search/index service.
9. Добавить `corpus_type` и режимы поиска.
10. Реализовать fallback в source_data.
11. Разнести базы чатов, знаний и аналитики.
12. Разделить writer worker, index worker и reflection worker.
13. Обновить документацию, тесты и e2e-сценарии.

## Критерии приемки

- Новое знание записывается в файл под `data/knowledge_repo/`.
- Запись выполняется через очередь и writer service.
- Git фиксирует изменение знания.
- Metadata database содержит запись о знании и путь к файлу.
- Reader service возвращает знание только после проверки прав.
- Поиск по умолчанию ищет в корпусе `knowledge`.
- Поиск по файлам включается явно или как fallback при пустом результате по знаниям.
- Результаты знаний содержат ссылки на исходные данные.
- Временные raw/safe файлы удаляются после успешной обработки.
- Персональное знание становится корпоративным только через кандидата и аудит.
- Чаты физически хранятся в `data/db/chat.sqlite3`.
- Управляющие модели аналитики хранятся в `data/db/analytics_control.sqlite3`.
- Графовый индекс не создает новые типы сущностей без кандидатства.
- Крупный блок закрыт unit-тестами и e2e-тестами.

## Проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests
python manage.py memory_eval --dry-run
npm run test:e2e
```

Для миграции баз дополнительно нужны smoke-проверки:

```bash
python manage.py migrate --plan
python manage.py showmigrations
```

## Реализованный срез

Выполнено 2026-05-22:

- добавлены раздельные базы `chat`, `knowledge_meta`, `analytics_control` и маршрутизатор баз;
- добавлен файловый Git-репозиторий знаний `data/knowledge_repo/`;
- `memory.remember` обрабатывается через очередь и `knowledge_writer_worker`;
- writer пишет файл знания атомарно, создает Git commit и обновляет metadata;
- поиск возвращает файловые знания как `result_type=knowledge`;
- добавлены команды миграции legacy-чата, legacy-аналитики и legacy-знаний;
- ночная рефлексия вынесена в `knowledge_reflection_worker`;
- добавлена команда `memory_file_backed_e2e`.

Команды первичной миграции:

```bash
python manage.py migrate --database=default
python manage.py migrate --database=chat
python manage.py migrate --database=knowledge_meta
python manage.py migrate --database=analytics_control
python manage.py migrate_legacy_chat_db --dry-run
python manage.py migrate_legacy_chat_db
python manage.py migrate_legacy_analytics_control_db --dry-run
python manage.py migrate_legacy_analytics_control_db
python manage.py memory_migrate_legacy_knowledge --dry-run
python manage.py memory_migrate_legacy_knowledge
python manage.py memory_verify_knowledge_files --strict
```

Остается для следующих срезов:

- отдельное аналитическое хранилище DuckDB;
- удаление `MemorySnapshot` и `MemoryChunk` из активного пути через `docs/planning/active/memory-snapshot-chunk-removal.md`;
- детальная стратегия графового поиска.
