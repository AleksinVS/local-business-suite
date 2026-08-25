# Final acceptance — lean role administration

Status: implementation and primary-agent acceptance complete; the first
exact-SHA Sol high review was rejected, its S2 findings were corrected, and a
second exact-SHA review is required before merge.

## Accepted behavior

- One `manage_roles` product authority administers ordinary roles.
- Only an active superuser can create, edit, assign, or self-assign protected
  roles; Django Admin remains an explicit reserve path.
- Role metadata catalog changes use only the deployment command with exact
  Git/runtime hashes; ordinary runtime writers cannot change it.
- AI and AD cannot mutate roles, account activation, department, memory groups,
  or access-related profile fields.
- Direct Save keeps fresh actor/target authorization, CAS, validation, atomic
  writes and audit without a user-facing preview/confirmation protocol.
- No role means no implicit product role after the separately approved viewer
  cutover; technical group authority remains confined to its domain.
- Explain projections match enforcement and do not present unused Django
  permissions as effective product access.
- The one-window access UI, global drawer handoff, ordinary role creation,
  grouped capabilities, error recovery, keyboard behavior, 320 px layout, and
  reserve Django Admin route passed browser acceptance.
- The signed viewer migration artifact contains exact Board access before,
  after, added and removed sets only after every user and Board choice is
  explicit.
- A concurrent same-name Group collision cannot leave an active role
  definition: an empty owned Group is reserved before contract activation;
  unrelated groups fail before any contract write.

## Runtime migration decision

The user approved the architecture and delegated final UI inspection to the
primary agent. No production/runtime user manifest was supplied, so applying
the explicit `viewer` cutover is correctly excluded from this code merge. The
existing compatibility phase remains active and is reported as expected drift.

## Gate

The corrected state passed its targeted regression suites and the final
`make verify-full`: 901 tests and 172 subtests. This acceptance becomes final
only if independent Sol high review reports no unresolved S1/S2 findings for
the exact clean feature SHA and no tracked file changes after that review.

After the final full run, the Luna xhigh correction review reported PASS for
S1/S2 and two S3 cleanup items. The superuser explain source and stale active
workflow descriptions were corrected; their focused regression set passed
5 tests and architecture validation passed again.

The subsequent exact-SHA Sol review also passed S1/S2 and identified a residual
hard-stop interval between contract activation and Group materialization. The
final ordering now reserves the inert Group first; a dedicated test proves that
a stop before contract write grants nothing and that an identical retry safely
completes the role.

After this ordering refinement, the complete role-administration class passed
11 tests and 17 subtests; the combined Settings Center and accounts regression
passed 185 tests and 72 subtests. The earlier feature-wide full run remains
green at 901 tests and 172 subtests.
