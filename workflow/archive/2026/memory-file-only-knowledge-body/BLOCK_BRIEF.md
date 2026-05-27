# Block brief: текст знания только в файле знания

Дата: 2026-05-22.

## Цель

Сделать файл знания единственным источником текста знания.

После блока:

```text
data/knowledge_repo/**/*.md = текст знания
MemoryKnowledgeItem = метаданные знания
MemorySearchDocument = техническая карточка поиска
поисковый индекс = перестраиваемая производная структура
```

## Причина

Сейчас `MemoryKnowledgeItem.text` дублирует файл знания. Это создает два источника истины и противоречит целевой архитектуре ADR-0011/ADR-0013.

## Входит

- Удалить `MemoryKnowledgeItem.text`.
- Перевести writer на запись файла до metadata.
- Удалить fallback чтения текста из базы.
- Перевести index worker и summary builder на чтение файлов.
- Упростить `MemorySearchDocument`.
- Убрать полный извлекаемый текст из индекса.
- Переименовать `chunk`-поля аудита и eval в `document`.
- Изолировать или удалить `MemoryClaim` из активного MVP-пути.

## Не входит

- Новая стратегия графового поиска.
- Production-векторный backend.
- Внешний API памяти.
- Новое хранилище секретов.
- Совместимая миграция production-данных.

## Важные правила

- Внедрения еще не было, поэтому данные переносить не нужно.
- Нельзя оставлять скрытый fallback на текст из базы.
- Индекс не должен быть источником текста для выдачи.
- Summary читают файлы знаний.
- Документация обновляется вместе с кодом.

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
