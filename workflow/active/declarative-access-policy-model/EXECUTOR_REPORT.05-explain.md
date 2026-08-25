# Executor Report — Task 05: Explain and cleanup

## Result

Implemented the package-05 read-only access explanation and human-editor
handoff. Explanations now use enforcement inputs rather than dumping Django
auth tables. Inactive accounts retain assigned membership facts but have no
effective capabilities or superuser reserve.

## Changed files

- `apps/accounts/selectors.py`, `apps/accounts/tests.py` — removed direct
  Django-permission projection, separated technical and memory groups, added
  inactive effective-access guard, and exposed ACL/workflow as non-grant
  constraints.
- `apps/ai/services.py`, `apps/ai/tooling.py`, `apps/ai/tool_definitions.py`,
  `apps/ai/contracts.py` — added `access.users.explain` and
  `access.open_editor`, fresh `manage_roles`/superuser authorization, privacy-
  safe user listing, and a validator that rejects every access-domain write
  tool.
- `contracts/ai/tools.json` — added the two read-only tool definitions.
- `apps/settings_center/right_panel.py`, `apps/settings_center/apps.py`,
  `apps/settings_center/tests.py` — registered fixed user/role editor
  providers; arbitrary targets and view mode fail closed.
- `services/agent_runtime/tools.py` and its tests — exposed only bounded
  fields for the two new read tools.
- `apps/settings_center/access_workspace.py` and
  `templates/settings_center/user_form.html` — inactive/effective markers,
  separate memory-group presentation, and removal of the Django permissions
  section.
- `docs/architecture/POLICY_MODEL.md` and
  `docs/guides/SETTINGS_CENTER_OPERATIONS.md` — documented the source boundary,
  privacy payload, and editor handoff.

## Verification

- `python3 -m py_compile` for all changed Python modules — passed.
- `python3 -m json.tool contracts/ai/tools.json` — passed.
- `git diff --check` — passed.
- With `LOCAL_BUSINESS_AI_TOOLS_FILE` temporarily pointed at the Git contract:
  - selector/AI focused selection: `8 passed`;
  - runtime adapter focused selection: `3 passed`;
  - Settings Center provider selection: `2 passed`.

During primary-agent acceptance, the ignored runtime
`data/contracts/ai/tools.json` was migrated through the reviewed atomic
contract service. `SettingsChange #9` records the operation; no runtime file is
staged for Git. The normal AI verification profile then passed (`223 passed,
13 subtests`), as did access/provider/memory regressions (`58 passed, 8
subtests`).

## Residual risks

- The access fragment endpoint and browser drawer acceptance remain package 06
  scope; the provider currently points to the existing human editor routes.
- Workflow-wide full suite and browser e2e remain final-package checks.

## Correction stage

The critic corrections were applied within package scope:

- `access.users.list` is active-superuser-only again; its privacy-safe payload
  still separates roles, technical groups, and memory groups.
- Both new services use the fresh actor returned by the authority check.
- Settings Center providers reload a fresh active actor in both authorization
  checks, use a generic user title, and convert actor/target/role races to
  controlled denial/validation errors.
- Gateway integration tests prove successful and denied calls are audited and
  create no `PendingAction`; generic `ui.open_right_panel` rejects `edit`.
- Every `domain=access` tool must have `mode=read`; unknown, missing, and
  non-read modes fail closed.
- ACL/workflow descriptors carry `object_scoped` and narrowing effects without
  serializing object ACLs.

Correction verification: the actual gateway boundary tests
`AIViewsTests.test_access_explain_and_editor_are_read_only_audited_and_do_not_create_pending_actions`
and `AIViewsTests.test_generic_right_panel_rejects_edit_mode_at_gateway_boundary`
passed (`2 passed`, 73 deselected). They call the real `ai:tool_execute` endpoint,
assert successful and denied `AgentActionLog` records, assert no
`PendingAction`, and verify generic edit-mode rejection. The broader correction
selection also passed (`10 passed` boundary/semantic/provider tests and `7
passed` adapter/account/right-panel regressions), using the Git contract
override. Primary-agent runtime migration and final acceptance remain pending.
