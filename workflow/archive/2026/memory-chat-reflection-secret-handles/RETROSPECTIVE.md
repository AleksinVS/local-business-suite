# Retrospective

## What worked

- Additive models avoided disruption to existing memory search and document ingestion.
- Keeping secret values out of the backend simplified the MVP: handles and metadata are enough for the agent-facing flow.
- Existing `MemorySnapshot`/`MemoryChunk` indexing could be reused for chat knowledge.

## Follow-up

- Add dedicated GUI for organization candidate audit.
- Replace staff/superuser shortcuts with granular contract-driven capabilities.
- Add real Vaultwarden URL conventions once deployment topology is chosen.
- Extend span-level secret handling from chat memory into document ingestion.
