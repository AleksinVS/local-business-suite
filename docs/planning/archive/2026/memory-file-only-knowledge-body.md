# Active plan: текст знания только в файле знания

Статус: реализовано, ожидает приемки и архивации workflow.

Дата: 2026-05-22.

## Цель

Убрать последний крупный разрыв файловой памяти: текст знания не должен храниться в базе или извлекаться из индекса. Единственный источник текста знания - файл в `data/knowledge_repo/`.

## Контекст

Связанные документы:

- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/adr/ADR-0013-file-only-knowledge-body.md`;
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`;
- `docs/architecture/MEMORY_FILE_ONLY_KNOWLEDGE_BODY_PLAN.md`;
- `workflow/archive/2026/memory-file-only-knowledge-body/`.

## Согласованные решения

- Нет внедрения и тестовой эксплуатации, поэтому не нужна миграция существующих данных.
- `MemoryKnowledgeItem.text` нужно удалить.
- Текст знания хранится только в файле знания.
- Текст для выдачи всегда читается из файла знания.
- Индекс является перестраиваемой производной структурой и не хранит извлекаемый полный текст.
- Дублирование между `MemoryKnowledgeItem` и `MemorySearchDocument` нужно убрать.
- Старые `chunk`-поля можно переименовывать без совместимости со старыми данными.
- Графовый поиск не входит в этот блок.
- Summary собираются из файлов знаний.
- `MemoryClaim` не входит в активный MVP-путь и не должен хранить копию текста знания.

## Реализовано

На 2026-05-22 выполнено:

- `MemoryKnowledgeItem.text` удален из модели и миграцией `memory.0008`;
- текст знания записывается и читается только из `data/knowledge_repo/**/*.md`;
- отсутствие файла или несовпадение хэша считается ошибкой целостности;
- `MemorySearchDocument` упрощен до технической поисковой карточки без дублирования прав, источника и чувствительности знания;
- SQLite-поиск хранит служебные токены и метаданные, но не хранит извлекаемый полный текст знания;
- аудит и eval используют `returned_document_ids` и `expected_document_ids`;
- `MemoryClaim` удален из MVP-схемы, будущий слой утверждений остается отдельным этапом;
- summary строятся из файлов знаний.

## Что такое MemoryClaim

`MemoryClaim` - будущая карточка отдельного проверяемого утверждения.

Он нужен не для простого "запомни", а для ситуации, когда разные источники противоречат друг другу и систему нужно научить проверять, принимать, отклонять или заменять отдельные утверждения.

Для MVP `MemoryClaim` не нужен в рабочем пути:

- обычный `memory.remember` его не создает;
- обычный `memory.search` его не возвращает;
- он не должен хранить полный текст знания;
- его можно удалить из MVP-схемы или оставить только как выключенную заготовку без текстового тела.

## Объем работ

Входит:

- удалить поле `MemoryKnowledgeItem.text`;
- переписать writer service так, чтобы текст записывался в файл до metadata-записи;
- переписать reader service без fallback на базу;
- переписать index worker на чтение файлов знаний;
- переписать summary builder на чтение файлов знаний;
- убрать смысловое дублирование из `MemorySearchDocument`;
- убрать извлекаемый полный текст из полнотекстового индекса;
- переименовать `returned_chunk_ids` и `expected_chunk_ids`;
- удалить compatibility aliases `chunk_id` после перевода кода и тестов;
- изолировать или удалить `MemoryClaim` из MVP active path;
- обновить документацию, тесты и e2e.

Не входит:

- новая стратегия графового поиска;
- production-векторный backend;
- внешний API памяти;
- изменение secret backend;
- перенос production-данных.

## Порядок реализации

1. Удалить `MemoryKnowledgeItem.text` из модели, миграций текущего среза, admin и тестов.
2. Ввести helper записи файла из текста процесса без сохранения текста в модели.
3. Перевести создание, редактирование и удаление знания на file-first workflow.
4. Удалить fallback чтения текста из базы.
5. Перевести индексацию и summary на чтение файлов.
6. Упростить `MemorySearchDocument` до технической поисковой карточки.
7. Перестроить полнотекстовый индекс так, чтобы он не хранил извлекаемый body.
8. Переименовать audit/eval поля с `chunk` на `document`.
9. Изолировать или удалить `MemoryClaim` из MVP active path.
10. Обновить документацию, `.desc.json`, `PROJECT_STRUCTURE.yaml`.

## Критерии приемки

- В `MemoryKnowledgeItem` нет поля `text`.
- В базе `knowledge_meta` нет колонки с полным текстом знания.
- Файл знания является обязательным для чтения.
- Отсутствующий файл или несовпадение хэша дает ошибку проверки, а не fallback.
- `memory.search` читает текст из файла знания.
- `knowledge_index_worker` читает текст из файла знания.
- Summary строятся из файлов.
- `MemorySearchDocument` не дублирует смысловые поля знания как источник истины.
- Полнотекстовый индекс не возвращает полный текст как источник выдачи.
- Audit использует `returned_document_ids`.
- Eval использует `expected_document_ids`.
- `chunk_id` compatibility aliases удалены.
- `MemoryClaim` не хранит полный текст знания и не участвует в обычном MVP-пути.
- Unit и e2e проверки проходят.

## Проверки

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests
./.venv/bin/python manage.py memory_verify_knowledge_files --strict
./.venv/bin/python manage.py memory_file_backed_e2e
./.venv/bin/python manage.py memory_eval --dry-run
npm run test:e2e
git diff --check -- . ':(exclude)BACKLOG.md'
```
