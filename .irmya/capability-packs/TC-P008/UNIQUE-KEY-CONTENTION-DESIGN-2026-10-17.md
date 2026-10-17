# TC-P008 — Unique-key write contention, isolated nonprod design

Status: **DESIGN ONLY / NOT VERIFIED**. Updated: 2026-10-17.
No DDL, hosted SQL, Queue publish, or Cloudflare action is authorized by this document.

## Isolation decision

Do **not** repurpose `trendcite.cloud_queue_probe_invocation` or any customer/Queue ledger. Migration `0011_tc_p008_concurrency_probe.sql` grants INSERT/UPDATE to the nonprod runtime but its `invocation_id` primary key protects real probe history and does not provide an isolated write-contention experiment. A dedicated, disposable nonprod-only table is required. Temporary tables are unsuitable: separate PostgreSQL backends cannot contend on the same session-local temporary table.

Proposed table (for isolated disposable nonprod database/schema only; **do not execute**):

```sql
CREATE TABLE tc_p008_isolated.unique_write_probe (
  probe_key uuid PRIMARY KEY,
  probe_run uuid NOT NULL,
  contender text NOT NULL CHECK (contender IN ('holder', 'contender')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON tc_p008_isolated.unique_write_probe FROM PUBLIC, anon, authenticated;
-- Grant only narrowly scoped INSERT/SELECT/DELETE privileges to a disposable
-- probe role AFTER isolated nonprod ownership/privileges are reviewed.
```

This is a proposed contract, not an approved migration. Provisioning must be reversible and independently confirmed, with no grants to production.

## Required execution sequence (future gated test only)

1. Allocate a cryptographically random `probe_run` and `probe_key`, with a single-use expiry and a disposable isolated nonprod table. Confirm two independent backend PIDs and capture UTC server-clock timestamps.
2. Session A: `BEGIN`; `INSERT ... (probe_key, probe_run, contender='holder')`; keep transaction open behind an explicit synchronization barrier. Confirm that A holds the uncommitted unique key.
3. Session B: `BEGIN`; attempt **one** INSERT for the same `probe_key` with contender='contender' using `ON CONFLICT DO NOTHING RETURNING probe_key`. Record B's start timestamp and whether it is blocked waiting for A's commit. If permitted, a separate read-only observer verifies `pg_blocking_pids(B_pid)` and a relevant lock wait; no inference from elapsed time alone.
4. Release A to COMMIT. B completes and must return zero inserted rows; B COMMIT. Any unexpected result is FAIL, never PASS. Capture SQLSTATEs if present, but never credentials.
5. Independently SELECT exact `probe_run` and `probe_key`: durable row count **exactly 1**, winner 'holder'; assert the two backend PIDs are distinct. Check that both connections and transactions ended.
6. Targeted DELETE **only** by `probe_run` AND `probe_key`, verify row count **zero** independently, revoke/remove disposable grants, then remove the isolated table/schema only after confirming ownership and no other dependencies. Any cleanup failure is a blocking incident.

## Safety, boundedness and acceptance

- One probe identity; exactly two INSERT attempts; no retry loops; bounded query and transaction deadlines; strict terminal cleanup; separate read-only audit.
- Keep all customer tables, existing `trendcite` schema records, production resources and Queue traffic untouched.
- If the role cannot observe blocking PIDs, do not claim lock-wait proof. A final count of one alone proves deduplication, not contention. Record `NOT VERIFIED` if the required concurrent blocking evidence is absent.
- Abort if isolation, role grants, deadlines, unique-key ownership or cleanup cannot be demonstrated before execution. Do not create the table in shared runtime merely to satisfy this document.
- Prior hosted PASS of advisory-lock contention **does not** certify this unique-constraint write-contention claim.
- Separate claims of Worker platform termination and actual transport ACK loss remain `NOT VERIFIED` and must not be conflated with this test.
- Explicit authorized nonprod execution, cost assessment, restoration plan and independent readback are mandatory before any hosted run.

## Closure artifacts

Record sanitized probe ID, backend PIDs, UTC intervals, blocking source (if available), winner/loser result, exact final and post-cleanup counts, role isolation and Cloudflare/DARK readback in the acceptance matrix. No secrets or customer values are to be recorded.
