# TC-P008 — Supabase isolation alternatives and cost decision

Date: 2026-10-17. Evidence classification: **PROVIDER READ / NO PROVISIONING**.

## Confirmed provider facts

Supabase organization `ISTRIADE Development`, ID `evkjeujsnuekwdzfgfnw`, is on the `free` plan (connected provider response). Supabase `get_cost` returned:

| Alternative | Provider response | Meaning |
| --- | --- | --- |
| Preview branch | USD **0.01344 per hour** | Compute baseline; additional usage categories may apply, and Supabase docs state branches are not covered by Spend Cap |
| New project | USD **0 per month** | Current provider quote in this organization; it is not confirmation that a free-project slot can be provisioned or that every usage category is always free |
| Dedicated local PostgreSQL 17 | No new Supabase charge | Already exercised as PASS LOCAL; cannot count as hosted proof |
| Existing shared ISTRIADE PLATFORM Postgres schema | No new project quote | **Rejected**: no authorized disposable boundary/role; risks shared runtime |

Supabase project listing showed `ISTRIADE PLATFORM` as the only active healthy project in this connected organization, with four inactive projects. Supabase documentation says Free accounts are entitled to two active free projects, but limits may also depend on owners/admins and other organizations; **do not assume** that one additional free project is currently provisionable merely from this inventory. Verify availability and full resource/billing conditions at time of any proposed provisioning.

Provider references:
- `https://supabase.com/docs/guides/platform/billing-faq`: quota of two active Free projects, paused projects not counted, dedicated instance per project.
- `https://supabase.com/docs/guides/platform/manage-your-usage/branching`: branches independently meter compute, disk, egress and storage; default Micro starts at USD 0.01344/hour; no Spend Cap for branches.

## Technical assessment

**Preferred candidate, subject to explicit provisioning authorization:** a brand-new dedicated, strictly nonprod free project with **no customer data copied**, separate credentials/roles, random isolated keys, two direct PostgreSQL sessions and a read-only observer. An independent project better separates failure domains from the canonical ISTRIADE PLATFORM than creating another schema in the same shared database. The quoted project fee is zero, but the availability and entire cost envelope must still be confirmed before creation.

**Secondary alternative:** a short-lived preview branch **without copying production customer data**, with a clear expiration, cleanup and authorized spending cap in time, since the nominal hourly fee is nonzero and additional usage is possible. If the provider only supports or defaults to copying existing data, block branch creation until that risk is understood.

**Rejected:** giving broad CREATE, monitoring or schema-owner grants to the existing `trendcite_nonprod_runtime` role, repurposing `trendcite.cloud_queue_probe_invocation`, or testing against the shared `postgres` database. None establish the bounded disposable environment required by TC-P008.

## Required gate before provider writes

1. Explicit human authority for a specific zero-cost project (after eligibility is reconfirmed), or explicit acceptance of the actual branch costs/limits; this cost lookup **does not** itself authorize creation.
2. New, independent identity and database with no customer dataset, routes, Queue subscriptions or production bindings; verify intended region and whether project/branch can be deleted immediately.
3. Least-privilege probe owner, insert/observe role and bounded cleanup, including an actual permissions check for `pg_blocking_pids` or a safe alternate observer.
4. One attempt per contender; two distinct backends; observed unique-index block; holder commit; contender 0 inserts; final count one; targeted cleanup count zero; hard transaction and query deadlines.
5. Independent inventory and billing readbacks after teardown; no external activation or commercial switches.

## Decision

`HOSTED_SETUP = NOT_AUTHORIZED`
`HOSTED_UNIQUE_KEY_CONTENTION = NOT_VERIFIED`
`HOSTED_ISOLATION_GATE = BLOCKED_PENDING_ELIGIBILITY_AND_HUMAN_COST_GATE`
`PRODUCTION = DARK`
`COMMERCIALIZATION = HOLD`

No Supabase project, branch, role, DDL or paid hosted test was created under this review.
