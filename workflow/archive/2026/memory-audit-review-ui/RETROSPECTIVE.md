# Retrospective: memory audit review UI

## What worked

- `MemoryIngestionIssue` was enough as the main queue; no persistent `ReviewCase` was needed.
- `ReviewQueueItem` gave the UI a stable list contract without duplicating lifecycle state.
- Existing Django templates and session auth were sufficient for the first operator UI.

## Watch next

- If multiple domains need the same assignment/SLA/escalation lifecycle, revisit persistent `MemoryReviewCase` with a new ADR update.
- Add deeper backend index consistency checks only if `metadata.index_versions` proves insufficient in operations.
- Consider a separate safe document preview only after deciding storage and redaction rules for extracted text.
