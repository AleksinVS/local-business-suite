# Agent Development Methodologies

This directory captures workflow patterns for multi-agent delivery that are not tied to one repository.

## Available Methodologies

- `Vertical slices`
- `Spec -> scaffold -> harden`
- `Review-driven loop`
- `Contract-first / schema-first`
- `TDD`

## When To Use What

`Vertical slices` are effective when the team needs visible business progress early and the feature can be split into mostly independent user-facing increments.

`Spec -> scaffold -> harden` is effective when the team needs a fast working baseline first and can improve rigor in later passes without losing architectural control.

`Review-driven loop` is effective when requirements are not fully stable, design quality matters, or a short review-feedback cycle is safer than a large one-pass implementation.

`Contract-first / schema-first` is effective when multiple agents or services must integrate against one stable contract and the cost of mismatch is high.

`TDD` is effective when behavior is well understood, regressions are costly, and the fastest path to confidence is to let tests define the implementation boundary.

## Cross-Cutting Use Cases

- Prefer `Vertical slices` for product features with clear UI, workflow, and storage boundaries.
- Prefer `Spec -> scaffold -> harden` for new modules, migrations from ad hoc code to structured code, and platform additions that need a quick but safe foothold.
- Prefer `Review-driven loop` for UX-heavy work, ambiguous requirements, or legacy code with hidden constraints.
- Prefer `Contract-first / schema-first` for APIs, AI tool contracts, event flows, and multi-team boundaries.
- Prefer `TDD` for bug fixes, deterministic domain logic, and risky refactors where executable proofs matter more than narrative plans.

## Misuse Patterns

- `Vertical slices` are a poor default when every slice must repeatedly touch the same fragile shared layer.
- `Spec -> scaffold -> harden` is a poor fit when the scaffold itself can create irreversible damage, such as public API drift or unsafe schema rollout.
- `Review-driven loop` is a poor fit when the review surface is too expensive to repeat and the requirements are already stable.
- `Contract-first / schema-first` is overkill when the task is local, short-lived, and has no integration boundary.
- `TDD` is a weak default when the main uncertainty is exploratory design rather than behavior.
