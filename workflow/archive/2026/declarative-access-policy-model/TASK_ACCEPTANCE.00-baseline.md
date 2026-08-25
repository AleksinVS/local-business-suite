# Task Acceptance: 00 baseline and golden matrix

- Status: Accepted
- Accepted by: primary agent
- Date: 2026-08-25

## Acceptance checks

- [x] All 26 current capabilities were inventoried by domain.
- [x] Current actor, implicit viewer, superuser, technical-group, ACL and
      whole-role boundaries were identified.
- [x] Pre-migration behavior is explicitly separated from target tests of later
      packages.
- [x] Twenty-eight representative golden scenarios passed through
      `make verify-fast`.
- [x] No executable behavior, test expectation, contract, template or runtime
      data changed.

## Remaining risk

Package 00 proves the current baseline, not the target ADR-0043 behavior. Each
intentional behavior change must replace only its corresponding golden
expectation and retain all unrelated boundaries.
