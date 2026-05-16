# Integrations

The platform treats integrations as explicit contracts between the internal business system and external environments.

## Integration Registry

All external systems must be registered in `config/integrations/registry.json`. Each entry should include:
- **Owner**: Person or department responsible for the external system.
- **Transport**: Protocol used (File, SQL, REST, SOAP, Queue).
- **Direction**: Inbound, Outbound, or Bi-directional.
- **Mode**: Batch, Near-real-time, or On-demand.
- **Status**: Active, Deprecated, or In-development.

## Preferred Bridge Strategy

For local-first enterprise landscapes, we follow a progressive integration path:

### 1. File Bridge (Stage 1)
- **Mechanism**: CSV, XLSX, XML, or JSON exchange via shared network folders (SMB/NFS).
- **Pros**: Minimal dependency on legacy APIs, easy to automate, robust to connection drops.
- **Cons**: Latency, requires strict format control.

### 2. Read-only SQL Bridge (Stage 2)
- **Mechanism**: ODBC/JDBC or direct DB connectors to legacy databases.
- **Pros**: Reliable data source without manual exports, ideal for analytical consolidation.
- **Cons**: Sensitive to external schema changes.
- **Constraint**: Only read into a staging or analytics raw layer; do not link transactional logic directly to external DB schemas.

### 3. API Bridge (Stage 3)
- **Mechanism**: REST/SOAP/HTTP services.
- **Pros**: Real-time interaction, cleaner separation than file exchange.
- **Cons**: High sensitivity to external system uptime, requires robust retry/idempotency handling.

### 4. Event/Queue Bridge (Stage 4)
- **Mechanism**: RabbitMQ, Kafka, or local brokers.
- **Pros**: Scalable, decoupled, supports complex event-driven workflows.
- **Cons**: Requires mature infrastructure and operational discipline.

## Operational Rules

1.  **Isolation**: External systems must not be coupled directly to core business screens or transaction paths until their contracts are stabilized.
2.  **Staging**: Always pull external data into a "raw" or "staging" layer (e.g., in the analytics store) before processing it into the domain model.
3.  **Audit**: Every integration operation (sync, export, import) must be logged with its result, timestamp, and any error details.
4.  **Fallback**: Systems should remain functional (even if with stale data) if an external integration is unavailable.
