# Task Acceptance — 05: Explain and cleanup

## Status

Accepted by the primary agent after Luna xhigh criticism and correction.
Date: 2026-08-25.

## Acceptance evidence

- [x] Direct Django permissions are absent from the product explanation model
      and user form.
- [x] Contract roles, superuser reserve, technical groups, memory groups, ACL,
      and workflow constraints remain distinguishable.
- [x] Inactive users have no effective capabilities or effective superuser
      reserve while membership facts remain visible.
- [x] AI explanation/listing payloads omit email, AD identity, raw Django
      permissions, and complete ACLs.
- [x] `access.users.explain` and `access.open_editor` are read-only and do not
      use `PendingAction`.
- [x] Editor handoff accepts only an existing user or contract role and uses
      server-owned local descriptors.
- [x] The AI contract validator rejects access-domain write tools.
- [x] Focused selector, AI, runtime-adapter, and provider tests pass with the
      Git contract selected for local verification.
- [x] Gateway integration tests prove successful/denied audits without
      `PendingAction`, and generic right-panel edit mode fails closed.
- [x] The validator rejects access tools with missing, unknown, or non-read
      modes; ACL/workflow descriptors identify object-scoped narrowing effects.

## Primary-agent checks

- [x] `data/contracts/ai/tools.json` was migrated through the reviewed atomic
      runtime-contract service by active superuser `#39`; `SettingsChange #9`
      records the applied before/after hashes. The ignored runtime copy is not
      staged or committed.
- [x] AI verification profile passed: `223 passed, 13 subtests`.
- [x] Access assignment, provider, and memory-boundary regressions passed:
      `58 passed, 8 subtests`.
- [x] Architecture contracts validate; `ai.contract.tools` now matches the Git
      default.
- [x] `@ag-ui/client` and `agui_profile` remain pinned to `0.0.55`; package 05
      changes neither dependencies nor the wire contract.

## Remaining package boundary

The provider returns a safe descriptor for the existing human editors. The
fragment endpoint, actual drawer rendering, narrow-screen behavior, and browser
acceptance remain package 06 scope and are not claimed by this acceptance.
