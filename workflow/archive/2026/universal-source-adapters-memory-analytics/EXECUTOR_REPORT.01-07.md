# Executor report: universal source adapters memory analytics

Дата: 2026-05-28.

## Выполнено

- ADR-0018 переведен в `Accepted`.
- Добавлен общий `apps.core.source_adapters`: `SourceObjectEnvelope`, `SourceAdapter`, adapter registry, privacy profiles `pii_off`, `pii_guarded`, `pii_strict`.
- Добавлены policy fields в contract validation: `source_origin`, `privacy_profile`, `access_policy`.
- Добавлена memory projection из envelope: `MemorySourceObject`, `MemorySearchDocument`, FTS/vector indexing, secret gate, PII gate по privacy profile.
- Добавлен `adapter_check` перед выдачей `source_data`; при отсутствующем адаптере результат fail-closed.
- Добавлена analytics projection из envelope: `AnalyticsSource`, `AnalyticsContentObject`, `AnalyticsExtractionPacket`, `AnalyticsEvidenceRef`, `AnalyticsFact`.
- Добавлены адаптеры `workorders` и `waiting_list`.
- Добавлена команда `source_adapter_reconcile`.
- Добавлен AI wrapper `workorders.search`.
- Обновлены contracts для memory sources, analytics sources и AI tools.
- Обновлены пользовательские и архитектурные документы.

## Проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests apps.memory.tests apps.analytics.tests apps.workorders.tests apps.waiting_list.tests apps.ai.tests
python manage.py test apps.memory.tests.MemorySourceAdapterProjectionTests apps.ai.tests.AIViewsTests.test_workorders_search_tool_uses_memory_source_adapter_index
python manage.py memory_file_content_search_e2e
python manage.py memory_reindex --corpus source_data --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code workorders --target all --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code waiting_list --target all --backend fulltext --dry-run
python manage.py analytics_recalculate_metrics --dry-run
```

Результат: основной прогон 212 tests OK; точечный прогон после создания миграций 3 tests OK.

## Остаточные ограничения

- MVP использует snapshot/reconcile, не event bus/outbox.
- `waiting_list.search` как отдельный AI wrapper не добавлен; поиск доступен через `memory.search` с `source_codes=["waiting_list"]` на серверном уровне и через будущий wrapper при необходимости.
- Фрагментный поиск по разделам документа не входит в этот блок.
