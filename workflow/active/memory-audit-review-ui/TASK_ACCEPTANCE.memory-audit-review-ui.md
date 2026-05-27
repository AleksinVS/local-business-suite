# Task acceptance: memory audit review UI

## Result

Accepted for owner review.

## Acceptance checks

- `MemoryIngestionIssue` remains the primary review queue.
- Persistent `ReviewCase` was not added.
- `ReviewQueueItem` is selector-level only and has no Django table.
- `MemoryReviewAction` records issue and index actions.
- Secret-like and PII-like values are sanitized in review text and metadata.
- Unauthorized user gets 403 for `/memory/review/`.
- `memory_admin` can open issue/index UI, resolve issue, enqueue reindex and delete stale index.
- Reindex UI creates `MemoryIndexJob`; delete stale uses backend delete service.

## Verification

```text
.venv/bin/python manage.py check
OK

.venv/bin/python manage.py makemigrations --check --dry-run
No changes detected

.venv/bin/python manage.py validate_architecture_contracts
Architecture contracts are valid.

.venv/bin/python manage.py test apps.memory.tests
Ran 49 tests: OK

.venv/bin/python manage.py test apps.settings_center.tests apps.ai.tests
Ran 63 tests: OK

.venv/bin/python manage.py memory_file_content_search_e2e
Memory file content search e2e succeeded; documents=6

.venv/bin/python manage.py migrate
Applied memory.0010: OK
```

## Residual risk

- UI enqueue creates `MemoryIndexJob`; actual asynchronous execution still depends on the existing worker/management-command operational model.
- FTS/vector presence diagnostics use `MemorySearchDocument.metadata.index_versions` and status metadata, not a deep backend consistency scan on every page load.
- Source-content preview remains intentionally out of scope.
