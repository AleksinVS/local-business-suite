# ADR-0002: Config-driven Policy And Workflow

## Status

Accepted

## Decision

Store role capabilities and workflow transitions in versioned JSON contracts instead of hardcoding them in Python branches.

## Consequences

- mutable rules become reviewable in git;
- validation becomes mandatory;
- future roles and states can be added without rewriting core policy flow.
