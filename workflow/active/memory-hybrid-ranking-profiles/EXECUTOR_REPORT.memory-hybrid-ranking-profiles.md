# Executor Report: memory hybrid ranking profiles

## Scope

Реализованы профили гибридного ранжирования для `memory.search`, source semantic search через существующий API, правила reindex/delete для source-файлов, а также подсказки и обертки ИИ-бота.

## Changes

- Добавлен параметр `ranking_profile` в Django gateway, tool contract и agent runtime wrapper.
- В `apps.memory.retrieval` добавлены профили `precise`, `balanced`, `semantic_heavy`, `source_content`, `source_semantic`, `graph_future`.
- Итоговый score строится через RRF по рангу канала; raw BM25/vector score сохраняется только для диагностики.
- Source semantic search включен для `source_data` через LanceDB без нового внешнего API.
- Source-файлы индексируются документом целиком; фрагментный индекс оставлен как следующий этап.
- Secret-bearing документы блокируются, старые FTS/vector записи удаляются, создается blocker issue.
- PII не блокирует и не обезличивает локальные FTS/LanceDB индексы, но создает audit issue `pii_audit`; issue metadata не хранит необезличенную PII.
- Reindex учитывает `content_hash`, ACL fingerprint, sensitivity, trust/authority и версии fulltext/vector/embedding.
- При удалении/исчезновении source-файла FTS/vector записи удаляются, `MemorySearchDocument` переводится в `deleted`.
- Подсказки agent runtime закрепляют выбор `search_mode` + `ranking_profile` по намерению пользователя.

## Verification

- `./.venv/bin/python -m py_compile ...`
- `./.venv/bin/python -m json.tool ...`
- `./.venv/bin/python manage.py validate_architecture_contracts`
- `./.venv/bin/python manage.py check`
- `./.venv/bin/python manage.py test apps.memory.tests`
- `./.venv/bin/python manage.py test apps.ai.tests`
- `./.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization.TestPromptMemorySection services.agent_runtime.tests.test_normalization.TestRuntimeMemoryTool`
- `./.venv/bin/python manage.py memory_file_content_search_e2e`
- Runtime wrapper e2e через `services.agent_runtime.tools.build_tools` и Django gateway: `ranking_profile=source_semantic`, `vector_requested=True`, первый результат `source_data`.

## Runtime State

- Применена миграция `memory.0009_alter_memoryingestionissue_issue_kind`.
- Django оставлен работать на `0.0.0.0:8000`.
- Agent runtime оставлен работать на `0.0.0.0:8090`.

## Notes

В рабочем дереве были другие незавершенные изменения по памяти и документации. Они не откатывались.
