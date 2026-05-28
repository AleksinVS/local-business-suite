# Task acceptance: universal source adapters memory analytics

Дата: 2026-05-28.

## Acceptance status

Accepted for owner review.

## Acceptance checks

- Единый envelope contract и adapter protocol реализованы.
- PII defaults реализованы: internal sources default `pii_off`, external default `pii_guarded`, PII audit не создается при `pii_off`.
- Secret scanning остается включенным независимо от PII profile.
- Memory projection и analytics projection строятся из одного envelope.
- `workorders` и `waiting_list` подключены через adapters.
- `adapter_check` выполняется перед выдачей `source_data`.
- Reconcile поддерживает upsert и tombstone для пропавших memory source objects.
- Unit/integration tests покрывают поиск, access denial, privacy defaults, analytics facts и `workorders.search`.

## Verified commands

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests apps.memory.tests apps.analytics.tests apps.workorders.tests apps.waiting_list.tests apps.ai.tests
python manage.py memory_file_content_search_e2e
python manage.py memory_reindex --corpus source_data --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code workorders --target all --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code waiting_list --target all --backend fulltext --dry-run
python manage.py analytics_recalculate_metrics --dry-run
```

## Follow-up

- После приемки владельцем перенести workflow в archive и удалить активную запись из backlog.
- Отдельно решить, нужен ли `waiting_list.search` wrapper или достаточно общего `memory.search`.
