# Contract-First / Schema-First

## Goal

Stabilize the external or internal contract before implementation so multiple agents can work in parallel without semantic drift.

## Agent Roles

- `Architect (L1)` defines the contract and acceptance rules.
- `Executor(s)` implement producers, consumers, or UI against the frozen contract.
- `PM (L2)` validates contract compliance at block acceptance.

## General Plan

1. Define the contract first.
2. Freeze or version it.
3. Implement code against it.
4. Validate conformance and edge cases.

## General Principles

- The contract is the coordination surface.
- Implementation is secondary to compatibility.
- Contract changes require explicit review, not silent drift.

## Workflow

1. Architect publishes schema, API shape, event format, or state machine.
2. Orchestrator routes workers against that contract.
3. Executors implement bounded responsibilities.
4. PM checks conformance, negative cases, and compatibility.

## Use Cases

- API design.
- AI tool contracts.
- Cross-service events.
- Shared UI data contracts across multiple screens or clients.

## Misuse Cases

- One-off local features with no integration boundary.
- Exploratory product work where the contract is expected to change rapidly.
- Cases where the schema adds more overhead than the implementation itself.
