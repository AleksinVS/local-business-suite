# TDD

## Goal

Use executable expectations to define behavior first and let implementation follow the tests.

## Agent Roles

- `Architect (L1)` sets scope and behavior boundaries when needed.
- `Executor A` writes or sharpens tests first.
- `Executor B` implements until tests pass, or the same executor does both in sequence.
- `PM (L2)` validates final behavior and regression coverage at block level.

## General Plan

1. Define expected behavior in tests.
2. Implement the minimum code to satisfy those tests.
3. Refactor while preserving green status.

## General Principles

- Tests should define behavior, not private implementation trivia.
- Red-green-refactor is only useful if the tests are meaningful and bounded.
- TDD does not remove the need for architecture; it sharpens behavior within it.

## Workflow

1. Write failing tests that express the required behavior.
2. Implement the smallest valid solution.
3. Refactor for clarity and maintainability.
4. Expand coverage for regressions and negative cases.
5. PM accepts the block when behavior and coverage are sufficient.

## Use Cases

- Bug fixes with clear reproduction.
- Domain logic with deterministic rules.
- Refactors where regression confidence is the main risk.

## Misuse Cases

- Early-stage exploratory UX.
- Tasks where the architecture is still undecided.
- Test suites that are expensive, flaky, or disconnected from real behavior.
