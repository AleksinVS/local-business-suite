# Spec -> Scaffold -> Harden

## Goal

Reach a safe and reviewable implementation in three intentional passes: define the shape, build the minimum working structure, then tighten correctness and maintainability.

## Agent Roles

- `Architect (L1)` defines the target shape and guardrails.
- `Executor A` creates the scaffold.
- `Executor B` hardens behavior, tests, and edge cases.
- `PM (L2)` accepts the full block only after hardening.

## General Plan

1. Freeze the required shape and boundaries.
2. Build the smallest viable implementation skeleton.
3. Tighten tests, validation, contracts, and documentation.

## General Principles

- The scaffold is intentionally incomplete but structurally correct.
- Hardening is not cleanup theater; it is where correctness is proven.
- The scaffold must not introduce public drift that later passes cannot safely repair.

## Workflow

1. Architect chooses the method when a stable shape is known but full rigor would slow initial progress too much.
2. The first implementation pass creates files, routes, models, placeholders, and thin happy-path behavior.
3. The hardening pass fills gaps, adds tests, tightens validation, and removes provisional shortcuts.
4. PM accepts only the hardened result, not the scaffold.

## Use Cases

- New module inside an existing codebase.
- Migration from proof-of-concept code to production-ready structure.
- Feature delivery where architecture is known but full correctness requires a second pass.

## Misuse Cases

- External contracts are already public and cannot tolerate a provisional scaffold.
- The scaffold would create unsafe data or irreversible side effects.
- The team has no discipline to schedule or enforce the hardening pass.
