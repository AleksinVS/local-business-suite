# Workflow brief: external information system knowledge connectors

## Goal

Create the implementation path for collecting knowledge from external information systems through governed connectors, durable queueing, normalized staging artifacts and the existing memory ingestion pipeline.

## Business Value

The memory system can learn from operational systems without turning API dumps into unmanaged memory. Business owners decide what data is collected, how often it refreshes and how long staging artifacts are retained.

## Read Scope

- `apps/memory/`;
- `apps/ai/`;
- `contracts/ai/`;
- `contracts/schemas/`;
- `docs/adr/`;
- `docs/architecture/`;
- `docs/guides/`;
- `docs/planning/active/memory-external-systems-connector.md`;
- `workflow/active/memory-external-systems-connector/`.

## Write Scope For Future Implementation

Future implementation task packets may write:

- memory connector models, services, commands and tests under `apps/memory/`;
- AI/memory contracts under `contracts/ai/` and matching schemas;
- docs and deployment guides related to external connectors;
- generated structure files after `.desc.json` updates.

Runtime landing zone data must be written under `data/memory/external_api/` only during runtime or tests. Temporary experiments must stay in `.local/`.

## Non-goals

- No direct API-to-graph write path.
- No unbounded raw API response storage.
- No source credentials in repository contracts.
- No CDC infrastructure in MVP unless explicitly selected for a pilot source.
- No universal ACL inheritance in the first implementation stage.

## Acceptance

- Queue is present from the first implementation.
- Queue backend is separate from the primary Django database.
- Connector output is normalized envelopes with manifests and provenance.
- Raw API responses use explicit short-lived quarantine only.
- External permissions use manual scope mapping during source implementation.
- Retention and sensitivity are explicit per source.
- Existing memory privacy gates and safe corpus are reused.
- Pilot source can be synced, retried, reprocessed and audited.
