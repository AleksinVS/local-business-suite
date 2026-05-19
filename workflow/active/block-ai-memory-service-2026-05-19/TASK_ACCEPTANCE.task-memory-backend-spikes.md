# Task Acceptance: task-memory-backend-spikes

Block: `block-ai-memory-service-2026-05-19`

Task: `task-memory-backend-spikes`

Decision: accepted

## Acceptance Review

The spike satisfies the declared task:

- LanceDB vs Qdrant was evaluated for local-first deployment, Django integration, filtering, hybrid/full-text search, operations, data placement, dependency footprint, migration, and testing strategy.
- Kuzu-first graph extraction vs Graphiti adapter was evaluated for local-first deployment, temporal/provenance support, RBAC feasibility, local LLM compatibility, Russian/business extraction risk, data placement, operational complexity, migration, and testing strategy.
- No production code, dependencies, or contracts were modified by the spike task.

## Accepted Backend Direction

- First vector backend: LanceDB.
- First graph backend: Kuzu with project-owned extractors.
- Qdrant remains a migration target.
- Graphiti remains a later adapter spike.

## Notes

The next implementation candidate is `task-memory-app-scaffold`, but backend dependency installation should wait until the indexing slice. The app scaffold can proceed with backend-neutral model/service boundaries.

