# Task Acceptance: 04 explicit viewer migration

- Status: Accepted after final Sol high gate
- Accepted by: primary agent
- Date: 2026-08-25

## Acceptance checks

- [x] The Git default contains one explicit least-privilege `viewer` role; the
      runtime copy was not changed automatically.
- [x] Compatibility fallback is disabled only by a valid runtime `viewer`
      definition.
- [x] Every roleless active user and every customer-open board requires an
      explicit owner choice; no role or ACL is inferred.
- [x] Existing-role choices remain inert during prepare and are applied only at
      cutover.
- [x] Prepare, cutover and rollback require a freshly loaded active
      superuser and reuse one signed reason-bound operation.
- [x] All persisted phases are signed, private, monotonic and protected from
      cross-operation overwrite.
- [x] User-role and board-ACL changes use domain adapters with deterministic,
      fully validated audit records.
- [x] Interrupted prepare, DB cutover, contract replacement and partial
      rollback are idempotently resumed only from exact audited states.
- [x] Drift in users, roles, technical groups, departments, boards, ACLs,
      viewer profile, Django permissions, inactive membership or contracts
      fails closed.
- [x] Focused and broader regression suites passed; architecture-contract
      validation reports only the expected unapplied `viewer` candidate.
- [x] Operations and deployment instructions describe private artifacts,
      exact repeated reason and retry procedure.

## Runtime operation

The owner-approved production manifest was intentionally not generated or
applied. `data/contracts/role_rules.json`, users, groups and board ACLs remain
unchanged by acceptance. Runtime cutover is a separate operator action after
reviewing the roleless-user report.

## Remaining risk

The optional management-command e2e performs a real temporary cutover and
rollback. It must be run in an isolated acceptance database/runtime directory,
not against production data. The final workflow-wide browser e2e remains part
of package 06.
