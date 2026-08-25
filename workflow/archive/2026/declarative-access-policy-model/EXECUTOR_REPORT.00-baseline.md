# Executor Report: 00 baseline and golden matrix

## Result

PASS. The current pre-migration authorization behavior is already covered by a
minimal cross-domain golden set; no production code, contracts, templates,
runtime data, or test assertions were changed.

## Inventory

The Git-default role catalog contains 26 capabilities:

- workorders: `view_scope`, `create_workorder`, `edit_scope`, `comment_scope`,
  `upload_attachment_scope`, `confirm_closure_scope`, `rate_scope`,
  `transition_scope`, `transition_targets`, `manage_board_columns`,
  `manage_assignments`;
- inventory/organization: `manage_inventory`, `view_analytics`,
  `manage_departments`;
- access/settings/AI: `manage_roles`, `manage_settings`, `manage_ai_skills`;
- memory: `memory_organization_write`, `memory_organization_review`;
- waiting list: `create_waiting_list`, `waiting_list_view_scope`,
  `waiting_list_edit_scope`, `waiting_list_edit_statuses`,
  `waiting_list_transition_scope`, `waiting_list_transition_from_statuses`,
  `waiting_list_transition_targets`.

Enforcement remains split by domain:

- role definitions and membership: `apps.accounts` services/policies;
- workorder scopes, board ACL and workflow: `apps.workorders`;
- waiting-list whole-role scope/status/target evaluation: `apps.waiting_list`;
- technical memory groups plus source/object ACL: `apps.memory`;
- runtime contract CAS/lock/audit: `apps.settings_center`;
- AI and AD are separate clients and do not define authorization semantics.

## Frozen current decisions

- roleless active users currently receive `default_board_viewer` read-only
  access; package 04 intentionally changes this only after migration;
- `manager` assignment is currently limited by `$administration`, while `admin`
  edits definitions; package 03 intentionally replaces this split;
- non-superuser self-assignment and privileged flag changes are denied;
- active superuser self-assignment remains allowed through its guarded path;
- board ACL cannot be bypassed by a direct selector argument;
- waiting-list scope and status fields cannot be combined across different
  roles;
- `is_staff` and direct Django permissions do not grant product or memory
  authority;
- technical memory groups remain distinct from contract roles;
- LDAP role mutation remains fail-closed;
- AI access writes still exist in this baseline and are removed only in package
  02.

## Verification

Command:

```text
make verify-fast TEST_SCOPE="apps/accounts/tests.py apps/workorders/tests.py apps/waiting_list/tests.py apps/settings_center/tests.py apps/memory/tests/test_review_boundaries.py apps/ai/tests/test_views.py apps/accounts/test_ldap_role_sync.py" TEST_FLAGS="-k 'non_superuser_cannot_self_assign or superuser_self_assignment_requires_dedicated or only_superuser_can_change_technical or effective_access_explains or user_without_role_gets_only or default_viewer_can_open or selector_board_argument or role_assignment_allowlist_rejects or manager_cannot_edit_without or waiting_policy_does_not_union or delegated_editor_critical or manage_settings_is_role or staff_and_django_permission or contract_roles_and_technical or admin_role_update_tool or access_users_update_rejects_group or ldap_authentication_succeeds'"
```

Result: PASS, 18 selected scenarios across seven test modules. Django system
check and `git diff --check` also passed.

An additional fail-closed set also passed (`5 passed, 245 deselected`): complete
superuser catalog projection, inactive-superuser denial, malformed/unknown
capability rejection, inactive memory-operator denial, and role-editor denial
when the contract is unavailable.

The independent Sol review requested five more existing pre-migration
boundaries. They passed (`5 passed, 358 deselected, 6 subtests passed`): private
board denial for the implicit viewer, service-level manager assignment
allowlist, the current admin/editor split, and the two current AI
department/disable writes that package 02 intentionally removes.

The existing tests were sufficient; adding duplicate test bodies would not
increase confidence and would make the later intentional migration harder to
read.
