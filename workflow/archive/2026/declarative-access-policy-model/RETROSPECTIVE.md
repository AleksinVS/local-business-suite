# Retrospective — lean role administration

## What improved

- The proposed generic authorization platform was rejected before it became a
  second policy system. Existing domain policies remain the source of truth.
- Delegated administration is understandable: one authority, ordinary roles,
  and a short protected-role boundary.
- Direct Save reduced visible ceremony while retaining concurrency, validation,
  audit and server-side authorization.
- Independent Luna criticism found UI integration and modal-accessibility gaps;
  primary visual review found stacking and alignment issues missed by tests.
- Independent exact-SHA review found two integration guarantees that unit-level
  acceptance had not frozen: exact migration impact and atomic role activation
  across the file/DB boundary. Both now have explicit regression tests.
- The explicit viewer migration separates safe code rollout from owner decisions
  about real users and boards.

## Difficulties

- Legacy access work spanned contracts, account services, Settings Center, AI,
  AD, Board ACLs, memory projections and browser state; golden tests were needed
  before simplification.
- A shared access/memory lock caused apparent infinite saves and had to be split
  without introducing a revoke race.
- The final full suite exposed that a 90-second isolated migration budget was too
  small on a loaded development host; the production behavior itself was sound.
- A prepared migration being inert is useful: it lets the signed, exact access
  delta be reviewed before the cutover changes real users or Board ACLs.

## Follow-up boundaries

- Run the real roleless-user report, approve every user and Board decision, then
  apply the `viewer` cutover as a separate runtime operation.
- Role deletion, moving definitions to the database, memory technical-group
  consolidation, and waiting-list status simplification remain separate work
  requiring measured need and their own acceptance.
- Do not reintroduce a compiler, generic `authorize` API, evaluator registry, or
  user-facing confirmation ritual without a demonstrated product requirement.
