# Skill Support Changes For Multiple Methodologies

## Purpose

These changes are needed so workflow skills can support more than one delivery method without assuming vertical slices by default.

## Required Changes

- Architect skill must explicitly choose a delivery method per block from:
  - `Vertical slices`
  - `Spec -> scaffold -> harden`
  - `Review-driven loop`
  - `Contract-first / schema-first`
  - `TDD`
- Architect plan contract should store:
  - `development_method`
  - `method_selection_rationale`
  - `acceptance_model`
- Orchestrator skill must route execution according to the selected method instead of assuming slice-by-slice PM acceptance.
- Executor skill must own `task_acceptance` and write a dedicated task acceptance artifact or section using a fixed template.
- PM skill must own `block_acceptance`, not per-task acceptance, unless Architect explicitly documents an exception.
- Shared artifact contracts should define immutable per-task artifacts and canonical latest artifacts.
- Orchestrator scripts should support:
  - prompt generation by mode;
  - post-run artifact probing;
  - worker heartbeat and idle detection;
  - workflow health summary generation;
  - block retrospective generation.

## Terminology Changes

- Non-standard terms must be avoided when a common term exists.
- If a non-standard term is still used, the first mention must explain it in parentheses.
- Terms like `provider-aware retry policy` should be written in plain language on first use, for example:
  - `provider-aware retry policy (retry rules that react differently to capacity limits, tool hangs, active subprocesses, and already-written artifacts)`

## Acceptance Model Changes

- `task_acceptance` is performed by the executor as local verification and self-review.
- `block_acceptance` is performed by PM after the whole block is implemented.
- PM review during planning remains allowed as `plan_review`, which is distinct from `block_acceptance`.
