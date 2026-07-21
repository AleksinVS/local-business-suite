# Active plan: сбор знаний из внешних информационных систем

Статус: MVP queue/landing-zone slice implemented; first source-specific adapter is pending pilot selection.

Дата: 2026-05-20.

## Цель

Спроектировать и реализовать контур подключения внешних информационных систем к памяти: API-коннекторы, durable queue, normalized landing zone, retention, handoff в существующий memory ingestion и начальный сбор сведений о типах сущностей графа знаний.

## Бизнес-ценность

ИИ-бот получает знания не только из документов и чата, но и из рабочих систем организации. Это должно происходить управляемо: с понятным владельцем данных, графиком обновления, правами доступа, безопасным хранением выгрузок и проверяемыми ссылками на источник.

## Архитектурные источники

- `docs/adr/ADR-0006-external-system-knowledge-connectors.md`;
- `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md`;
- `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

## Scope

- business/source questionnaire in simple language;
- graph entity/type questionnaire for initial schema discovery;
- external source connector architecture;
- separate queue backend from the first implementation stage;
- normalized landing zone under runtime `data/`;
- optional short-lived raw API response quarantine;
- manual source-system permission mapping to portal `scope_tokens`;
- retention model by storage layer;
- source contract and queue model design;
- handoff from normalized envelopes to existing memory ingestion;
- issue/dead-letter queue and admin visibility;
- pilot connector strategy.

## Non-goals

- No immediate implementation in `apps/` without a separate task packet.
- No direct graph writes from an external API.
- No unbounded raw API dump storage.
- No production CDC setup unless selected as a separate source-specific decision.
- No universal external ACL inheritance in MVP.

## Proposed Execution Order

1. Approve pilot external system and fill both questionnaires.
2. Create source contract schema and model migrations.
3. Add standalone external connector queue backend.
4. Add landing zone manifest/envelope writer.
5. Add generic connector runner and worker command.
6. Add handoff from envelope to existing memory ingestion.
7. Add issue/dead-letter admin visibility and tests.
8. Add first pilot connector or mock connector.
9. Run smoke/eval and adjust retention/schedule.

## Acceptance Criteria

- Business users can fill questionnaires without technical translation.
- Every connector has a declared data owner, schedule, retention and access scope.
- Queue exists from the first implementation stage and supports retries/dead-letter.
- Queue backend is separate from the primary Django database.
- Connector output is normalized envelopes, not unmanaged raw dumps.
- Raw API responses are stored only in short-lived quarantine when source config explicitly enables it.
- Existing memory privacy gates and safe corpus are reused.
- Deleted/changed external records are handled through hashes/cursors/tombstones.
- Tests cover idempotency, retry, retention metadata, secret blocking and handoff.

## Verification Commands For Implementation

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py makemigrations --check --dry-run
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_eval --dry-run
```
