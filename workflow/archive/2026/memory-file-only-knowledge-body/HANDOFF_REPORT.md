# Handoff report: memory-file-only-knowledge-body

Дата: 2026-05-22.

Статус: реализовано, ожидает приемки.

## Итог

Файл знания стал единственным источником текста знания. База `knowledge_meta` хранит метаданные, путь и хэши, а поисковая база хранит только технические записи и перестраиваемые поисковые токены.

## Выполненные срезы

| Срез | Статус | Результат |
|---|---|---|
| 01 remove knowledge text field | done | `MemoryKnowledgeItem.text` удален, миграция `0008` создана |
| 02 file-only reader/writer/indexing | done | запись, чтение, редактирование, удаление, summary и индексация работают через файлы знаний |
| 03 simplify search document/index | done | `MemorySearchDocument` больше не дублирует source/scope/sensitivity знания; индекс не хранит полный текст |
| 04 rename chunk fields | done | audit/eval используют `returned_document_ids` и `expected_document_ids`; `chunk_id` aliases удалены |
| 05 claim boundary/docs/tests | done | `MemoryClaim` удален из MVP-схемы; документация обновлена |

## Основные изменения

- `apps/memory/models.py`: удалены `MemoryKnowledgeItem.text`, `MemoryClaim`, смысловые дублирующие поля `MemorySearchDocument`, переименованы audit/eval document fields.
- `apps/memory/knowledge_files.py`: reader больше не делает fallback на базу; writer принимает текст процесса и пишет файл с проверкой хэшей.
- `apps/memory/chat_memory.py`: remember/edit/delete/index/summary читают и пишут текст через файлы знаний.
- `apps/memory/vector_backends.py`: SQLite backend хранит служебные токены и метаданные, но не хранит извлекаемый полный текст.
- `apps/memory/retrieval.py`: `memory.search` получает `document_id`, проверяет права и доверие, затем читает текст знания из файла.
- `apps/memory/migrations/0008_remove_memoryclaim_created_by_and_more.py`: новая миграция целевой схемы.
- Документация обновлена в ADR/architecture/guide/planning/backlog/README.

## Проверки

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests
./.venv/bin/python manage.py memory_verify_knowledge_files --strict
./.venv/bin/python manage.py memory_file_backed_e2e
./.venv/bin/python manage.py memory_reindex --dry-run
./.venv/bin/python manage.py memory_eval --dry-run
npm run test:e2e
```

Результат: все команды прошли успешно.

Примечание: для локальных команд управления миграция была явно применена к базе `knowledge_meta`:

```bash
./.venv/bin/python manage.py migrate --database=knowledge_meta --noinput
```

## Остаточные риски

- Графовый поиск не перерабатывался; это отдельный будущий блок.
- Production-векторный backend не добавлялся.
- `memory_claims_policy.json` оставлен как контракт будущего claim/belief слоя, но моделей `MemoryClaim`/`MemoryBelief` в MVP-схеме нет.
