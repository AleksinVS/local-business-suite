# Integrations

The platform treats integrations as explicit contracts.

Registry:

- all known external systems should be described in `config/integrations/registry.json`;
- every entry should declare owner, transport, direction, update mode and payloads.

Preferred bridge order:

1. file bridge;
2. read-only SQL bridge;
3. API bridge;
4. queue or event bridge.

Operational rule:

- external systems should not be coupled directly into core business screens before their contract is stabilized.
