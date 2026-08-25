# Task Acceptance — 03: Single role administration authority

## Verdict

PASS.

The primary agent accepts the critical role-authority package on the feature
branch. It has not yet received the final exact-SHA Sol review and has not been
merged or pushed.

## Accepted security properties

- A fresh active actor must have `manage_roles` from the same role-contract
  snapshot used by the operation; `is_staff` and legacy `$administration`
  metadata give no product authority.
- Non-superusers may change and assign only ordinary roles, never their own
  membership or a definition they hold.
- A role protected before or after the operation is active-superuser-only.
- Protected flags/scopes/targets use strict effective semantics; malformed or
  missing protected data fails closed.
- Active superusers retain self-assignment, protected-role administration,
  last-superuser guards, and the audited Django Admin reserve path.
- Creation starts with no grants, rejects reserved and colliding codes, cannot
  delete roles, and cannot capture a technical/AD/memory group during a race.
- Generic apply and rollback cannot change the role set or legacy
  `$administration` block.

## Evidence

- 387 affected-module tests and 90 subtests passed.
- Focused authority and migration selections passed after the primary review
  corrections.
- Architecture contracts and Django system checks passed.
- Runtime deployment migration completed as `SettingsChange` ID 8.

## Deferred work

Task 04 owns the explicit viewer migration. Task 06 owns the final unified UI,
responsive behavior, browser e2e, and owner visual acceptance.
