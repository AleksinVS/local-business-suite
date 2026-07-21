# Executor report: memory audit review UI

## Status

Implemented; owner review pending.

## Implemented

- Added `MemoryReviewAction` immutable action log.
- Added assignment/resolution fields to `MemoryIngestionIssue`.
- Added index-health issue kinds for failed/stale/missing FTS/vector/deleted-source cases.
- Kept persistent `ReviewCase` out of MVP.
- Added read-only `ReviewQueueItem` projection in selectors.
- Added server-side review permissions and group capability mapping:
  - `memory_admin`;
  - `memory_auditor`;
  - `memory_index_operator`;
  - `memory_observer`.
- Added safe serializer for review text and metadata.
- Added review services for issue transitions, comments, assignment, reindex enqueue and delete stale index.
- Added `/memory/review/` UI:
  - dashboard;
  - issue queue;
  - issue detail;
  - index health list;
  - search document detail;
  - review action audit log.
- Added navigation link for authorized users.
- Added tests for access control, `ReviewQueueItem`, issue review, index actions and safe log output.
- Updated memory operator/user guides and project structure metadata.

## Files touched

- `apps/memory/models.py`;
- `apps/memory/migrations/0010_memoryreviewaction_memoryingestionissue_assigned_to_and_more.py`;
- `apps/memory/admin.py`;
- `apps/memory/policies.py`;
- `apps/memory/review_safety.py`;
- `apps/memory/review_selectors.py`;
- `apps/memory/review_services.py`;
- `apps/memory/views.py`;
- `apps/memory/urls.py`;
- `config/urls.py`;
- `apps/core/context_processors.py`;
- `templates/base.html`;
- `templates/memory/review/`;
- `static/src/css/app.css`;
- `apps/memory/tests.py`;
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`;
- `docs/guides/MEMORY_USER_GUIDE.md`.

## Runtime notes

- Local migration `memory.0010` was applied with `.venv/bin/python manage.py migrate`.
- The UI is available at `/memory/review/` for users with memory review capability.
- The UI does not expose full extracted text, raw secret values, raw PII or raw query.
