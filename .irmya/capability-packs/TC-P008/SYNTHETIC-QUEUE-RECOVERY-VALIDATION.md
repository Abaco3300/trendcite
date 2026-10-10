# TC-P008 — Synthetic Queue/DLQ recovery validation

Scope: TEST ONLY / IN-MEMORY HARNESS / NOT PRODUCTION E2E.

The tests in `tests/test_tc_p008_synthetic_queue_recovery.py` demonstrate the intended properties of an isolated deterministic model: duplicate message replay after acknowledgment loss does not duplicate an effect; bounded retries quarantine poison messages; DLQ replay requires explicit approval; tenant-qualified keys remain distinct; successful and failed messages do not contaminate each other.

Important limitation: this harness is **not** the deployed Cloudflare Queue consumer, Postgres transactional ledger, or a multi-process crash test. A PASS here must not be promoted to production durability/idempotency evidence. Production Queue and DLQ have no bindings and remain inactive. Nothing here creates a live queue, charge, credential, or external cost.

Further acceptance evidence required before any production Queue integration:
- Real nonprod Queue message redelivery, poison-message handling and DLQ behavior with the actual adapter
- Transactional idempotency across process crashes and concurrent consumers
- Delivery ack after durable commit, with bounded retries and outage recovery
- Tenant-bound keys and authorization under actual Postgres RLS / service roles
- Queue retention and limits checked against provider configuration
- Read-only remote drift verification and explicit integration Human Gate

Dodo TEST/LIVE remain frozen; all real customer runtime and commercial activation are prohibited.
