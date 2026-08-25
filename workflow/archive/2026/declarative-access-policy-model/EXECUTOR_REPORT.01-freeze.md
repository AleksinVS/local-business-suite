# Executor Report — Task 01: Frozen capability metadata

## Result

Implemented the permanent transport invariant for `role_rules.$capabilities` and a
separate deployment-only migration command. No runtime contract, Git default,
model, migration, schema, commit, or push was changed by this task.

## Files changed

- `apps/settings_center/contract_services.py`
- `apps/settings_center/management/commands/migrate_role_capabilities.py`
- `apps/settings_center/tests.py`
- `docs/guides/SETTINGS_CENTER_OPERATIONS.md`
- `workflow/active/declarative-access-policy-model/EXECUTOR_REPORT.01-freeze.md`

The permitted `apps/accounts/access_contracts.py` and `apps/accounts/tests.py`
write scopes did not require changes.

## Security and consistency design

- Every ordinary `role_rules` write, including raw apply, rollback, and the
  constrained single-role writer, now reloads the real runtime contract under the
  common access-control lock and unconditionally requires both:
  `hash(runtime.$capabilities) == hash(current Git-default.$capabilities)` and
  `candidate.$capabilities == runtime.$capabilities`.
- The Git default is read only from the immutable repository path
  `BASE_DIR/contracts/role_rules.json`; the mutable runtime/environment override
  cannot become the comparison baseline. Missing, malformed, unknown, or drifted
  catalogs fail closed.
- The bypass is a separate service used only by
  `migrate_role_capabilities`. It freshly reloads and requires an active
  superuser before and after lock acquisition, and requires caller-supplied
  hashes of the current runtime catalog, target Git catalog, and full current
  runtime contract.
- The reviewed full candidate must have a catalog exactly equal to the current
  Git default. The role set, service blocks other than `$capabilities`, role
  presentation metadata, unchanged capability values, and unrelated grants must
  remain byte-for-byte equivalent as normalized JSON. Only changed catalog
  entries and the corresponding per-role keys may differ.
- No-op and hash mismatch paths fail before backup, audit creation, or runtime
  replacement. A successful migration uses the existing pending-audit,
  atomic-write, post-write-hash, and reconciliation protocol under the same lock.
- A verified pre-write backup is created under `data/contracts/backups`. Audit
  context records the operator, reason, expected catalog hashes, operation kind,
  and backup filename. Command output contains only the audit identifier, short
  contract hashes, and backup filename; it does not print payloads or grants.
- Ordinary Settings Center and historical rollback paths cannot invoke the
  deployment bypass.

## Tests added

`FrozenRoleCapabilityCatalogTests` covers:

1. already-drifted runtime catalog rejection on otherwise valid ordinary apply;
2. candidate catalog mutation rejection on the generic raw service path;
3. historical rollback metadata rejection;
4. constrained role Save rejection while Git/runtime catalogs drift;
5. wrong runtime-catalog, Git-catalog, and full-runtime hashes, plus no-op, with
   no runtime write, audit row, or backup;
6. rejection of unrelated existing grant, role-set, `$administration`, and role
   presentation-metadata changes;
7. direct delta-validator coverage for a newly added capability with explicit
   per-role values and rejection of unrelated role metadata;
8. successful management-command migration, verified backup and APPLIED audit,
   safe output, and a subsequent successful ordinary role-definition write.

One pre-existing delegated-writer assertion was updated to expect the new frozen
catalog error at the transport boundary.

## Verification performed

- `python3 -m py_compile apps/settings_center/contract_services.py apps/settings_center/management/commands/migrate_role_capabilities.py apps/settings_center/tests.py`
  — passed.
- `make verify-fast TEST_SCOPE=apps/settings_center/tests.py TEST_FLAGS='-k FrozenRoleCapabilityCatalogTests'`
  — 8 passed, 97 deselected, 7 subtests passed.
- `make verify-fast TEST_SCOPE=apps/settings_center/tests.py TEST_FLAGS='-k SettingsCenterContractTests'`
  — 9 passed, 96 deselected, 15 subtests passed.
- `make verify-fast TEST_SCOPE=apps/settings_center/tests.py`
  — 104 passed, 1 deselected, 42 subtests passed.
- `make verify-fast TEST_SCOPE=apps/accounts/tests.py TEST_FLAGS="-k 'role_definition or role_assignment or self_assign or technical_flags'"`
  — 6 passed, 45 deselected.
- `git diff --check` — passed.

## Residual risk and shared-tree note

A combined accounts/AI selection was attempted while task 02 was being changed
concurrently. It failed in
`AIViewsTests.test_admin_role_update_tool_uses_settings_center_audit` because the
concurrent AI catalog no longer exposed `access.update_role_permissions`. This is
outside task 01 write scope and is not reproduced by the complete Settings Center
suite or the targeted accounts suite above. The primary agent is independently
reviewing and testing that parallel package.

No full test suite was run. Final acceptance, cross-package verification, and any
acceptance-report status remain the primary agent's responsibility.
