# TCP-P001 — Public Onboarding, CLI & Agent Interface

Status: OPEN
Authorization: inherited from authorized TrendCite Public outcome

## Outcome
Reduce time-to-first-value for human CLI users and make TrendCite Public reliably consumable by agents and automation without adding hosted dependencies or hidden telemetry.

## In scope
- current CLI audit
- help/errors/examples
- deterministic non-interactive behavior
- stable machine-readable output where justified
- tests
- Agent Skill/docs alignment
- package-facing documentation directly required by the above

## Out of scope
- TrendCite Pro hosted runtime
- authentication
- customer workspaces
- billing/entitlements
- persistent SaaS infrastructure
- hidden telemetry
- production activation of Pro

## Acceptance
- existing human workflow remains compatible
- machine/agent path is documented and deterministic
- no unsolicited interactive text contaminates machine output
- tests cover new behavior
- canonical preflight passes when execution environment permits
- remote CI PASS at logical checkpoint
- P0 = 0
- P1 = 0
- Professional QA PASS
