# Final executor report — lean role administration

## Result

All packages 00–07 are implemented on `feature/lean-access-control`. The product
model now uses one role contract, one delegated `manage_roles` authority,
ordinary/protected roles, direct service-backed Save, fresh authorization,
atomic contract writes, domain audit, and the active-superuser reserve path.
AI and AD no longer mutate access. Django Admin remains the break-glass route.

The access workspace retains six projections and one navigation level. User and
role editors save inside a Kanban-style right drawer without document reload;
the left field editor preserves sidebar width and restores the complete AI chat.
Role creation, capability grouping, protected-role explanations, dirty-draft
protection, timeout recovery, and 320 px modal behavior are covered by browser
tests and primary-agent visual inspection.

## Verification

- Settings Center fast suite: 132 passed, 62 subtests passed, 1 slow test
  deselected.
- Contracts profile: 49 passed, 54 deselected.
- AI profile: 223 passed, 13 subtests passed.
- Memory profile: 156 passed, 65 subtests passed.
- UI profile: 300 server tests and 23 subtests passed; 22 Chromium smoke tests
  passed.
- Final `make verify-full`: 899 passed and 172 subtests passed in 324.91 s.
- `validate_architecture_contracts`: valid.
- `makemigrations --check --dry-run`: no changes.
- collected static sources: synchronized.

The first full run exposed only a 90-second test timeout while an isolated
SQLite schema was actively migrating. The same scenario reproduced twice; its
test-only limit was raised to 180 seconds. The focused two-process writer test
then passed in 76.54 seconds, and the complete full run passed.

## Runtime boundary

The Git default contains the frozen least-privilege `viewer` role. The local
runtime still reports it as an unapplied candidate by design. No user, group,
Board ACL, or runtime contract was changed automatically. A real cutover remains
an operator action requiring an owner-approved complete private manifest.

## Documentation

ADR-0043, policy/architecture documentation, access and Settings Center guides,
deployment instructions, README, planning, workflow reports, and test policy
references were checked and updated in the packages that changed them. AGENTS.md
does not require a change. Structure is regenerated after archiving this block.
