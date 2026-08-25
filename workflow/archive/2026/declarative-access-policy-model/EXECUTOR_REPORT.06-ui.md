# Executor Report 06 — UI and E2E acceptance

## Result

Implemented the approved Access Workspace UI completion on the existing shared
branch. The canonical `AccessWorkspaceView` remains the only workspace write
adapter; existing account, role, board, and memory services are still used for
mutations. Standalone user/role routes remain reserve new-tab paths.

## Changed files

- `apps/settings_center/access_workspace.py` — protected/ordinary role read-model
  markers and explicit create-role state.
- `apps/settings_center/right_panel.py` — server-owned handoff to workspace
  HTMX fragment URLs for user and role editors.
- `apps/settings_center/views.py` — global drawer target, ordinary-role creation
  dispatch, fragment rendering, and out-of-band Roles refresh.
- `apps/settings_center/tests.py` — focused provider, global-fragment, role
  protection, and create-overlay coverage.
- `templates/settings_center/partials/access_workspace/role_create_editor.html`
  — in-workspace ordinary-role creation form.
- `templates/settings_center/partials/access_workspace/global_inspector.html`
  — fragment-only global right-panel host, including role membership editing.
- `templates/settings_center/partials/access_workspace/inspector_host.html` —
  workspace create state and protected-role denial explanation.
- `templates/settings_center/partials/access_workspace/table_panel.html` —
  Create role action and non-color ordinary/protected labels.
- `templates/settings_center/role_catalog.html` and
  `templates/settings_center/role_definition_form.html` — reserve-path role
  clarity.
- `static/src/js/access_workspace.js` — bounded HTMX defaults.
- `static/src/js/role_capability_editor.js` — shared authenticated-page access
  editor initializer, user-bundle tabs, and generic access-form dirty tracking.
- `static/src/js/right_panel.js` — access editor target aliases, 15-second fetch
  timeout, busy-state cleanup, retryable draft-preserving errors, and bounded
  fragment requests.
- `static/src/css/app.css` — drawer, role-kind, denial, and responsive styles.
- `templates/base.html`, `templates/settings_center/access_workspace.html`, and
  `templates/settings_center/role_definition_form.html` — shared script loading
  and removal of duplicate page-level role-editor loads.
- `scripts/e2e/tests/access_administration.spec.ts` — global editor, ordinary
  role, dirty-close, and narrow viewport acceptance scenarios.
- `docs/guides/ACCESS_MANAGEMENT_USER_GUIDE.md`,
  `docs/guides/SETTINGS_CENTER_OPERATIONS.md`,
  `docs/deployment/SETTINGS_CENTER_DEPLOYMENT.md` — operational behavior and
  deployment notes.

## Design choices

- The existing workspace remains the canonical editor and service boundary.
- `access.open_editor` resolves trusted user/role identity server-side and loads
  a fragment; callers cannot provide arbitrary URLs or HTML.
- Role creation starts as an ordinary blank role. Protected creation remains
  visibly superuser-only and is enforced by the existing service.
- Protected roles have explicit text labels and nearby denial reasons, not color
  alone. Site sections remain projections and are not role grants.
- The global drawer uses the existing Kanban-style overlay. A small client-side
  alias rewrite lets shared legacy partials save back into the global target
  without duplicating the form or mutation service.

## Checks

- `./.venv/bin/python manage.py check` — passed.
- Focused Django tests (6 tests: provider, global fragment, role protection,
  create overlay) — passed.
- Focused Django tests (3 existing HTMX/panel/save tests) — passed.
- Pytest direct invocation was attempted but the repository plugin import was
  unavailable (`config.pytest_plugin`); Django's test runner was used instead.
- Browser E2E was not run by this executor; the main agent owns acceptance.

## Residual risks

- Full browser behavior at 320px, focus restoration, and transport failure
  scenarios still require the main agent's Playwright acceptance run.
- Shared user/role partials retain their historical local HTMX target in the
  server response; `right_panel.js` rewrites that trusted alias before HTMX
  processing when mounted in the global drawer.
- The architect-modified task packet was preserved and not rewritten.

## Critic correction pass

Applied the Luna xhigh critic corrections. The shared editor initializer now
loads on every authenticated page before `right_panel.js`; fragment swaps
reinitialize user tabs and dirty tracking. The workspace delegates those
behaviors to the shared initializer. Protected role definition, description,
and user editors now show the explicit denial to delegated managers while the
existing service authorization remains unchanged. Global role-create validation
and service errors preserve the global retry target, and a sandboxed POST test
proves the OOB Roles refresh and newly selected editor without changing runtime
repository data. The global drawer now has modal semantics, focus trapping,
inert background, opener restoration, dirty replacement/close confirmation, and
full-viewport behavior at 320px. Failed requests restore disabled controls and
busy state while retaining the dirty form.

Correction checks attempted:

- Django focused correction set (6 tests: global retry target, sandboxed role
  creation/OOB refresh, delegated protected-role denial, and access-editor panel
  coverage) — passed.
- Django focused regression set (3 HTMX/panel/save tests) — passed.
- `manage.py check`, JavaScript syntax checks for the three changed scripts, and
  `git diff --check` — passed.
- Playwright remains intentionally deferred to the main agent's acceptance run.

## Primary-agent acceptance addendum

The deferred browser matrix was completed after the correction pass: all 22
smoke scenarios passed. The primary agent additionally corrected the shared
initializer name collision, the local create-role fragment state, static asset
cache versions, the 320 px drawer stacking order, and protected-role checkbox
alignment. A focused rerun of the two visually affected browser scenarios also
passed. The remaining browser risks above are therefore closed for this package;
the authoritative result is recorded in `TASK_ACCEPTANCE.06-ui.md`.
