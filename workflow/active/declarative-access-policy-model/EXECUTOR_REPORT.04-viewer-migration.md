# Executor report: 04 explicit viewer migration

## Result

Implemented the owner-approved explicit `viewer` migration boundary. The
runtime role contract remains unchanged in this workspace; only the Git
default now contains the exact read-only viewer definition. Runtime phase is
still determined solely by the presence of `viewer` in the runtime contract.
The correction and acceptance passes add a distinct `VIEWER_ROLE`/phase
predicate, signed private operation and phase snapshots, deterministic domain
audits, deferred existing-role choices, monotonic phase transitions, and
resumable prepare/cutover/rollback recovery.

## Files changed

- `contracts/role_rules.json`: frozen least-privilege `viewer` definition,
  complete capability catalog, `protected=false`, no write capability.
- `apps/settings_center/access_migration_services.py`: read-only report,
  immutable report hashing, signed manifest validation, locked/transactional
  prepare, private 0700/0600 artifacts, audited cutover and exact rollback
  orchestration; no migration model or feature flag.
- `apps/settings_center/contract_services.py`: private locked contract
  primitives using backup, expected hashes, atomic replacement and
  `SettingsChange` audit for cutover/rollback.
- `apps/accounts/access_contracts.py`: freezes `viewer` against ordinary role
  definition writers; its `protected=false` value remains descriptive, not an
  authorization bypass.
- `apps/accounts/services.py`, `apps/workorders/services.py`: migration-only
  role/ACL adapters with deterministic audit fingerprints; settings-center
  migration code performs no direct M2M mutation.
- `apps/accounts/management/commands/report_roleless_users.py`:
  read-only report command.
- `apps/accounts/management/commands/apply_roleless_user_manifest.py`:
  owner-approved inert preparation command.
- `apps/accounts/management/commands/cutover_explicit_viewer.py` and
  `rollback_explicit_viewer.py`: audited phase transitions.
- `apps/accounts/management/commands/access_management_e2e.py`: optional
  `--viewer-migration` prepare/cutover/rollback scenario.
- `apps/accounts/selectors.py`, `apps/workorders/policies.py`,
  `apps/settings_center/access_workspace.py`: fallback and UI/read-model
  behavior now depend on runtime viewer presence.
- `apps/settings_center/tests.py`, `apps/workorders/tests.py`: report and
  runtime-phase coverage.
- `docs/guides/SETTINGS_CENTER_OPERATIONS.md`,
  `docs/deployment/SETTINGS_CENTER_DEPLOYMENT.md`: operator procedure and
  runtime-artifact rules.

## Checks

- `git status --short` recorded before edits; no branch, commit, push, stash,
  reset, restore, or cleanup operation performed.
- `python3 -m compileall` / `.venv/bin/python -m py_compile`: migration and
  command modules compile. (The pre-existing workorders test file contains
  trailing class-body expressions; it still compiles after the new test.)
- `.venv/bin/python manage.py check --deploy`: passed with six existing
  deployment-security warnings.
- `.venv/bin/python manage.py validate_architecture_contracts`: passed; it
  reports the expected Git-default/runtime `viewer` candidate drift.
- Read-only shell report: `report_roleless_users(output_path=False)` returned
  compatibility phase and did not change users, groups, boards, ACLs, or the
  runtime contract.
- Focused envelope/path checks: signed envelope round-trip, immutable report
  hash stability after choice edits, and rejection of an artifact path outside
  `data/access-migrations` passed.
- Focused migration and phase tests passed: `5 passed`. They cover an inert
  existing-role choice, signed phase tamper rejection, a private operation
  path, recovery after prepare DB commit, recovery after partial cutover DB
  commit, recovery after contract replacement, partial rollback cleanup,
  monotonic artifacts, profile/permission/inactive-member drift, unique audit
  replay and runtime phase parity.
- Full Settings Center suite passed: `122 passed, 1 deselected, 59 subtests`.
- Accounts assignment and Workorders role/view/capability suites passed:
  `137 passed, 16 subtests`.
- `python manage.py validate_architecture_contracts` passed and reported the
  expected Git-default/runtime candidate `viewer` drift.
- Independent Sol high recovery review found and drove fixes for audit replay
  order, phase integrity, interrupted file-write reconciliation and monotonic
  recovery artifacts; final verdict is recorded in task acceptance.

## Runtime operations not performed

No owner manifest was applied, no viewer group/membership/ACL was staged, and
no runtime contract cutover or rollback was executed against `data/`. The
focused shell checks used `output_path=False`; no report artifact was created.
Reports, backups and manifests remain operator-owned runtime artifacts under
`data/access-migrations/` and are not committed.

## Residual risks

- Production acceptance must run the optional migration e2e command in an
  isolated test database and then the owner-approved real manifest workflow.
- Runtime contract drift is intentionally reported as a candidate and must be
  reconciled by the owner before cutover.
- Applying the real manifest remains an explicit owner operation. Code-level
  acceptance used isolated runtime-contract files and did not alter `data/`.
