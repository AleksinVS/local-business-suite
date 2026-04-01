# Vertical Slices Selection Criteria

## Choose Vertical Slices When

- the block can be broken into user-visible increments;
- each increment has a mostly local acceptance surface;
- dependencies between increments are real but manageable;
- early partial delivery has product value;
- the team wants progress to be legible to non-architects.

## Avoid Vertical Slices When

- shared platform work dominates the block;
- architecture is still too unstable to freeze slice boundaries;
- each slice would repeatedly modify the same fragile files;
- the real risk sits in contracts or infrastructure, not in feature assembly;
- acceptance requires near-total completion before any slice is meaningful.

## Strong Signals

- There is a clear "this slice works" statement.
- File ownership can be bounded per slice.
- Tests can be mapped per slice without inventing new architecture.

## Warning Signals

- "We'll clean up shared code later" appears in every slice.
- Multiple slices need the same foundational abstraction but plan to duplicate it temporarily.
- The orchestrator would need to reinterpret requirements to route work.
