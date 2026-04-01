# Vertical Slices

## Goal

Deliver business-visible increments that cut through multiple layers of the system while keeping each slice bounded and independently reviewable.

## Agent Roles

- `Architect (L1)` defines the slice boundaries, invariants, and acceptance surface.
- `Orchestrator` routes slices in dependency order and keeps state explicit.
- `Executor (L3)` implements one bounded slice end to end.
- `PM (L2)` performs block-level acceptance after the relevant slices are complete.

## General Plan

1. Define one user-visible block.
2. Split the block into thin vertical slices with explicit ownership boundaries.
3. Complete each slice with code, tests, and task-level self-acceptance by the executor.
4. Run block-level acceptance only after the block's required slices are done.

## General Principles

- One slice should expose one clear acceptance surface.
- Shared-layer work should be minimized and front-loaded only when necessary.
- Slice boundaries must reduce orchestration ambiguity.
- The executor should not need to invent missing architecture within a slice.

## Workflow

1. Architect selects vertical slicing and explains why it fits the block.
2. Architect defines slice order, allowed files, forbidden moves, and tests.
3. Orchestrator materializes task packets without paraphrasing.
4. Executors deliver slices one by one, recording implementation and task acceptance artifacts.
5. Orchestrator keeps state, retries safely, and performs artifact probes.
6. PM performs block acceptance after the block is complete.

## Use Cases

- Business feature with clear UI, service, and data touchpoints.
- Product delivery where stakeholders want visible progress after each implementation unit.
- Monolith or modular app where end-to-end feature completion is more valuable than layer-by-layer progress.

## Misuse Cases

- Shared infrastructure dominates the work.
- The same unstable contract must be rewritten in every slice.
- One slice cannot be validated without most other slices already being done.
