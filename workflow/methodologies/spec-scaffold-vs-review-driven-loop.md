# Spec -> Scaffold -> Harden vs Review-Driven Loop

## Core Difference

`Spec -> scaffold -> harden` is a staged build strategy. It assumes the target shape is mostly known, and the team benefits from building a structured baseline first and tightening it afterward.

`Review-driven loop` is an iterative correction strategy. It assumes the main uncertainty is not the initial structure but the quality of each implementation decision under real review.

## What Each Method Optimizes

`Spec -> scaffold -> harden` optimizes for fast structured progress with a planned second pass for rigor.

`Review-driven loop` optimizes for safe convergence when the first pass is likely to be incomplete, visually off, or constrained by unknowns.

## Typical Sequence

`Spec -> scaffold -> harden`

1. Freeze the intended shape.
2. Build the scaffold.
3. Harden validation, tests, edge cases, and docs.

`Review-driven loop`

1. Implement a bounded task.
2. Review it.
3. Return targeted corrections.
4. Repeat until accepted.

## Best Use Cases

Use `Spec -> scaffold -> harden` when the architecture is known but the full production finish would slow the first pass too much.

Use `Review-driven loop` when hidden constraints, UX sensitivity, or legacy behavior make early review more valuable than a staged scaffold.

## Main Failure Mode

The failure mode of `Spec -> scaffold -> harden` is never reaching the harden phase.

The failure mode of `Review-driven loop` is endless low-quality iteration caused by vague reviews or unstable boundaries.
