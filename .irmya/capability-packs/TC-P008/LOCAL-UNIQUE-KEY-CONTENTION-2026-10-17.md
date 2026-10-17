# TC-P008 — Isolated local PostgreSQL unique-key contention

Status: **PASS LOCAL / HOSTED NOT VERIFIED**. Date: 2026-10-17.

A new disposable PostgreSQL 17 Alpine Docker container was launched on a loopback-only random port, with a dedicated database named `tc_p008_local`. The test runner `scripts/tc_p008_local_unique_write.py` used two independent psycopg connections and synchronized transactions against one UUID primary key. A separate observer used PostgreSQL `pg_blocking_pids`; this is actual unique-index contention rather than advisory-lock or timing-only evidence.

Sanitized first-run observations: holder PID 70, contender PID 71, blocked PID 71, blocking PID 70, holder committed, contender INSERT ON CONFLICT DO NOTHING returned 0, independent durable row count 1, winner holder, and targeted cleanup count 0. Python evidence-contract validation returned PASS local and explicitly hosted NOT_VERIFIED.

After the successful local run, the runner's connection guard was strengthened to parse the DSN and require loopback host and exact disposable database name. Destructive CASCADE cleanup was removed in favor of explicitly dropping only the known disposable table and schema. Those final hardening edits must pass the ordinary local quality gates; no second real database run is asserted by this note. The disposable Docker container was stopped and removed.

**Boundaries:** no Cloudflare calls, hosted database SQL, production schema, customer data, Queue traffic, platform termination or ACK manipulation. The accepted hosted unique-key proof remains NOT VERIFIED. Worker termination and transport ACK loss remain NOT VERIFIED. Production DARK; commercialization HOLD.
