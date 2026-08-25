# Executor report 02: AI/AD access mutation side paths

## Result

AI access mutation routes are removed. The AI catalog and dispatcher retain
read-only access tools (`access.get_role_rules`, `access.users.list` and
`access.groups.list`), while role/user access writes are no longer registered,
confirmed, or dispatched. The generic `PendingAction` flow remains unchanged
for non-access tools.

## Changed files

- `apps/ai/tooling.py` — removed dispatch and confirmation-preview branches for
  `access.update_role_permissions` and `access.users.update`.
- `apps/ai/services.py` — removed the role-definition and user-lifecycle
  preparation/apply services that could mutate access state; read-only access
  services remain.
- `apps/ai/tool_definitions.py` — removed both mutation tool definitions.
- `contracts/ai/tools.json` — removed both Git-default mutation definitions.
- `apps/ai/tests/test_views.py` — replaced mutation-success tests with
  registry/contract/dispatcher denial checks and persisted PendingAction
  fail-closed regression subtests for both removed IDs; unrelated PendingAction
  tests and non-access writes remain.
- `apps/ai/tests/test_semantic_validators.py` — added a canonical catalog
  assertion and a runtime-validator regression for the two forbidden IDs.
- `apps/ai/contracts.py` — rejects both retired access-mutation IDs at the
  runtime-contract boundary so a stale or manually prepared contract cannot
  advertise them again.
- `services/agent_runtime/tools.py` — removed both mutation wrappers from the
  active LangChain/external-agent adapter and its returned tool list.
- `services/agent_runtime/tests/test_normalization.py` — added adapter-level
  assertions that neither mutation ID is exposed or sent to the gateway while
  read-only access tools remain.
- `workflow/active/declarative-access-policy-model/EXECUTOR_REPORT.02-side-paths.md`
  — this report.

`apps/accounts/ldap_backend.py` and `apps/accounts/test_ldap_role_sync.py` did
not require a code change: the current AD role synchronizer already validates
mapped contract roles and then fails closed with an audit/error signal without
calling group membership writes. Existing focused tests cover disabled sync,
invalid/missing role mappings, valid mappings without an audited assignment
service, authentication success, and profile/privileged-state safeguards.

## Removed mutation routes

- `access.update_role_permissions`: removed from Python catalog, Git-default
  contract, confirmation preparation, dispatcher, and apply service.
- `access.users.update`: removed from Python catalog, Git-default contract,
  confirmation preparation, dispatcher, and lifecycle apply service. This
  closes AI writes to `is_active` and `department_id` as well as any attempted
  user access side fields.
- AD role assignment remains fail-closed; profile/identity authentication sync
  is preserved.

## Human handoff boundary

`ui.open_right_panel` remains a generic, read-only object opener. It is not
expanded here into an access-specific editor or prefill route, because its
server descriptor currently does not establish that handoff safely. A scoped
access explain/open/prefill handoff is deferred to packages 05/06; this package
keeps the existing read-only access tools and does not invent a URL or broaden
server policy.

## Checks

Passed:

```bash
python3 -m json.tool contracts/ai/tools.json
python3 -m py_compile apps/ai/tooling.py apps/ai/services.py apps/ai/tool_definitions.py apps/ai/tests/test_views.py apps/ai/tests/test_semantic_validators.py apps/accounts/ldap_backend.py
python3 -m py_compile services/agent_runtime/tools.py services/agent_runtime/tests/test_normalization.py
git diff --check
```

The Luna executor could not start pytest from its environment. The primary
agent then ran the repository verification environment:

```bash
make verify-fast \
  TEST_SCOPE="apps/ai/tests/test_views.py apps/ai/tests/test_semantic_validators.py apps/accounts/test_ldap_role_sync.py services/agent_runtime/tests/test_normalization.py"
```

Result: 142 passed, 6 subtests passed.

The primary agent migrated `data/contracts/ai/tools.json` through
`apply_contract_payload` as the active local superuser `abc`, with the actual
runtime base hash, the common contract lock, atomic replacement, and
`SettingsChange` audit ID 7. The resulting runtime catalog contains 24 tools
and neither forbidden ID. The ignored runtime file was not added to Git.

## Residual risks

- Existing database `PendingAction` rows bearing the removed tool codes are
  historical data; confirmation now fails closed because those tools are no
  longer in the catalog. Dedicated persisted-row tests cover both IDs.
- The legacy LDAP backup files are outside this task's write scope and were not
  modified; the active `ldap_backend.py` path is the fail-closed path covered
  above.
- Full integration/e2e suites were intentionally not run.
