# TC-P008 — PostgresExecutionStore transaction boundary

Scope: REAL ADAPTER CODE / FAKE CONNECTION / OFFLINE CONTRACT ONLY.

`tests/test_tc_p008_execution_store_transaction.py` executes the existing `PostgresExecutionStore` transaction path with an injected fake connector. It verifies that an exception from `SET LOCAL ROLE` exits the transaction context and closes the connection, and that unsafe PostgreSQL role identifiers are refused before execution.

This does **not** prove actual PostgreSQL rollback, concurrency, transactional idempotency, RLS enforcement or Cloudflare Queue redelivery. Those require an isolated driver-backed test with the real application schema, a restricted role and actual consumer/ACK sequence. The separate local PostgreSQL concurrency probe in TC-P008 uses synthetic SQL rather than the application adapter.

No production, billing, Dodo or credentials changed. All integration and activation gates remain blocked.
