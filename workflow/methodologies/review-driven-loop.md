# Review-Driven Loop

## Goal

Use short implementation-review-correction cycles to converge on quality when requirements are incomplete, design choices are sensitive, or hidden constraints are likely.

## Agent Roles

- `Architect (L1)` sets the boundaries and review surface.
- `Executor (L3)` implements a bounded task.
- `Reviewer or PM (L2)` returns a concrete decision packet with gaps or acceptance.
- `Orchestrator` controls the loop and prevents silent drift.

## General Plan

1. Implement a bounded change.
2. Review it quickly and concretely.
3. Return only targeted rework, not a broad rewrite.
4. Repeat until the block is fit for acceptance.

## General Principles

- Reviews should be narrow, actionable, and test-backed when possible.
- Rework should be bounded, not open-ended.
- The loop exists to reduce ambiguity, not to replace architecture.

## Workflow

1. Architect defines the task and the review criteria.
2. Executor delivers code and local verification.
3. Reviewer returns `accepted` or `returned` with an explicit gap list.
4. Orchestrator routes the rework packet back to the executor.
5. PM performs final block acceptance when the loop closes.

## Use Cases

- UX or design-heavy tasks.
- Legacy code with hidden constraints.
- Work where the main risk is subtle regressions rather than missing scaffolding.

## Misuse Cases

- Stable, deterministic implementation that could be finished in one disciplined pass.
- Large architecture shifts that should be decided before coding starts.
- Teams that return vague narrative reviews instead of actionable corrections.
