# Retrospective: memory external systems connector MVP

## What Worked

- Reusing `MemorySnapshot` and `index_snapshot_text` kept the connector MVP aligned with existing safe corpus and chunk behavior.
- A standalone SQLite queue gives a separate queue backend without adding RabbitMQ/Redis before a pilot source exists.
- Normalized envelopes make tests and replay straightforward.

## Risks To Watch

- SQLite queue is an MVP backend. It should be load-tested with the pilot source before production scheduling.
- Raw quarantine can contain sensitive source payloads. Retention cleanup and access restrictions should be implemented before broad use.
- Manual scope mapping is acceptable for the first source, but can drift if source permissions are complex.

## Follow-up

- Build the first source-specific adapter only after the pilot system and questionnaire answers are confirmed.
- Add cleanup/retention enforcement before enabling raw quarantine for sensitive systems.
