"""TC-P008 hosted proof readiness record, 2026-10-19.

Evidence:
- PR #121 contains an unconditional execution gate.
- Offline tests cover cancellation failures and no-delete on active backends.
- pg_cancel_backend cancels a running query; it is NOT a guaranteed session
  termination mechanism. PostgreSQL pg_stat_activity readback is essential.
- A zero-count readback is a point-in-time observation, not evidence that all
  connections were forcibly terminated or that the database target was
  authenticated.
- Current tests use injected connections; no real hosted SQL was executed.

Release gate (all required):
1. Verify the connection factory restricts the exact isolated sandbox host,
   role and TLS endpoint before any connection is made.
2. Implement and test a bounded recovery policy for cancellation refusals,
   stale backends, observer failure, cleanup connection failure, and timeouts.
3. Prove scoped DELETE only when backend absence is observed independently.
4. Audit zero probe rows using a second independent connection and verify that
   the run IDs match. Preserve every incident and fail closed.
5. Run a specifically approved isolated hosted test with time-bounded access,
   independent reviewer and complete evidence.
6. Only then consider removing the unconditional execution gate.

Unchanged boundaries:
PRODUCTION=DARK
COMMERCIALIZATION=HOLD
HOSTED_CERTIFICATION=NOT_VERIFIED
PR_121=DRAFT
