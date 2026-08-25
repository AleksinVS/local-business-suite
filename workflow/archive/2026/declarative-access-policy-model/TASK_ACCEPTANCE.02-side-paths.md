# Task Acceptance — 02: AI/AD access mutation side paths

## Verdict

PASS.

The package removes AI access writes across the Django gateway, Python and JSON
catalogs, service layer, confirmation preparation, and the external agent
adapter. AD identity/profile behavior remains available, while AD role mutation
remains fail-closed.

## Independent review cycle

The first Luna xhigh review returned FAIL because the external agent adapter and
runtime tool catalog still exposed the retired identifiers. The Luna correction
removed the adapter wrappers, added persisted `PendingAction` tests, and left
the runtime operation to the primary agent. The primary agent additionally made
the runtime validator reject reintroduction of either identifier and migrated
the ignored runtime contract through the canonical service.

The second Luna xhigh review returned PASS with no unresolved S1/S2 findings.

## Primary-agent verification

```text
make verify-fast \
  TEST_SCOPE="apps/ai/tests/test_views.py apps/ai/tests/test_semantic_validators.py apps/accounts/test_ldap_role_sync.py services/agent_runtime/tests/test_normalization.py"
```

Result: 142 passed, 6 subtests passed.

Runtime verification: 24 tool definitions; neither
`access.update_role_permissions` nor `access.users.update` is present.
`SettingsChange` audit ID 7 records the atomic runtime migration.

## Accepted boundaries

- Historical pending rows for a removed tool fail closed, reach `FAILED`, do
  not dispatch, and do not mutate a user or role.
- Non-access `PendingAction` semantics are unchanged.
- No AI path can write roles, groups, department, activation, username,
  privileged flags, or AD identity.
- Existing read-only access inspection remains available.
- Access-specific effective-access explanation and safe opening of the human
  editor are explicitly transferred to task 05. Task 02 acceptance no longer
  depends on inventing an unsafe generic URL handoff.

## Residual scope

Task 05 must add the scoped read-only explanation/editor handoff and migrate the
runtime tool contract again if it adds a tool. Final AI and UI profile checks
remain part of block acceptance.
