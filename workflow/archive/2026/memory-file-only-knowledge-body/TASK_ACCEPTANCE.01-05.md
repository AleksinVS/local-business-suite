# Task acceptance: 01-05

Дата: 2026-05-22.

Статус: принято исполнителем, ожидает пользовательской приемки.

## Проверка критериев

- `MemoryKnowledgeItem.text` удален.
- Текст знания для выдачи читается только из файла знания.
- Индекс не является источником выдаваемого текста.
- `MemorySearchDocument` не дублирует смысловые поля знания.
- Summary строятся из файлов знаний.
- Audit/eval используют document ids вместо chunk ids.
- `MemoryClaim` удален из MVP-схемы и не участвует в обычном пути `memory.remember`/`memory.search`.

## Подтвержденные команды

- `makemigrations --check --dry-run` - OK.
- `manage.py check` - OK.
- `validate_architecture_contracts` - OK.
- `manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests` - 106 tests OK.
- `memory_verify_knowledge_files --strict` - OK.
- `memory_file_backed_e2e` - OK.
- `memory_reindex --dry-run` - OK.
- `memory_eval --dry-run` - OK.
- `npm run test:e2e` - 1 Playwright test OK.
