# TC-P008 — Remaining acceptance gates after hosted concurrence

Updated: 2026-10-17. Scope: nonprod; production DARK. This is an execution decision record, **not** new hosted evidence.

## Certified baseline — do not repeat

The acceptance matrix `NONPROD-QUEUE-ACCEPTANCE-MATRIX-2026-10-13.md` records real hosted Queue delivery/retry/DLQ, physical-message redelivery after application exception, overlapping Queue consumers, identical-logical-message deduplication, independent PostgreSQL backend overlap and transaction-scoped advisory-lock contention. Last hosted SQL diagnostic: 2026-10-17, one authorized nonprod HTTP 200, Ray `a4c02f4e0f889aa6-MIA`. Temporary bindings were removed and independently verified absent.

## Remaining distinct claims and their proof requirements

| Claim | What would qualify as direct proof | Current decision |
| --- | --- | --- |
| Same-key unique-constraint write contention on PostgreSQL | Two concurrently open, distinct hosted PostgreSQL transactions target the **same disposable unique key**; capture both server-side transaction timelines, exact winner/loser outcomes, durable final row count = 1, and targeted cleanup of only the disposable records. Transaction advisory-lock success is insufficient. | NOT VERIFIED; design isolated schema/namespace and strictly bounded, auditable cleanup **before** considering an authorized nonprod run |
| Platform-enforced Worker death after a durable commit | Provider-level evidence of actual Worker termination after durable commit, followed by the broker's actual recovery outcome and unique logical persistence. A caught exception, synthetic `RuntimeError`, HTTP timeout, or canceled client request is insufficient. | NOT VERIFIED; no destructive test authorized; require an isolated nonprod Worker/Queue, provider-recognized termination evidence and rollback plan |
| Broker-to-Worker lost ACK at transport level | Direct broker/provider evidence of a missing transport acknowledgment for an actually delivered message, subsequent physical redelivery and exactly one durable logical effect. Application-level exception is insufficient. | NOT VERIFIED; do not simulate network interference or intentionally suppress ACK on the shared runtime |
| Production activation | Separate production human gate HG-H and commercial/security prerequisites | BLOCKED; outside TC-P008 certification |

## Execution order and safety gates

1. **Read-only design stage:** inventory the existing SQL uniqueness constraint, Queue retry contract, PostgreSQL role, diagnostic allowlist and available isolated nonprod resources. This stage does not write to hosted infrastructure.
2. **Unique-key test design:** follow `UNIQUE-KEY-CONTENTION-DESIGN-2026-10-17.md` for an independently provisioned disposable nonprod schema/table, two distinct backend sessions, one attempt per contender, observed blocking, bounded timeouts, durable final count and targeted cleanup. A new isolated table would require separately authorized provisioning; no live test until cost/risk, rollback and authorization are satisfied.
3. **Worker termination and lost ACK:** treat as separate provider fault domains. Do not infer either from already certified application-exception redelivery. Keep these NOT VERIFIED absent direct independent provider evidence.
4. **Certification closure:** refresh matrix and deployment state only with observed evidence, retain specific UNKNOWN/NOT VERIFIED labels, and recheck absence of transient bindings and DARK production state.

## Hard stops

- Do not repeat any of the existing PASS HOSTED probes as a substitute for missing evidence.
- Do not modify production routes, Queue bindings, commercial switches, credentials or customer data.
- Do not execute paid hosted synthetic loads, crash injection or transport interference in this design stage.
- Do not upgrade an acceptance classification on tests, simulations, SQL plans or CI alone.
