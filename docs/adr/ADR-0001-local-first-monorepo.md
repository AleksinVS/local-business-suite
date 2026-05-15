# ADR-0001: Local-first Django Monorepo

## Status

Accepted

## Decision

Use a single Django monorepo with modular apps for local deployment.

## Consequences

- deployment stays simple;
- shared auth and dictionaries are easier to manage;
- module boundaries must be documented to avoid accidental coupling.
