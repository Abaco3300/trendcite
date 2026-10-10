# TC-P008 — Local PostgreSQL durability checkpoint

Status: PASS / SYNTHETIC POSTGRES 17 / NON-AUTHORITATIVE

Command (opt-in; requires local Docker image postgres:17):
`python scripts/tc_p008_postgres_durability_probe.py`

The probe provisions a disposable container with no published ports and no external network, creates a synthetic PostgreSQL table with tenant/job composite primary key, and runs 24 concurrent psql processes executing the same conflict-safe INSERT. Exactly one inserts a durable effect; retry after a synthetic lost ACK is idempotent. A different synthetic tenant with the same job ID is independently inserted. The container is removed in a finally block.

Observed result:
- concurrent_attempts=24
- single_tenant_a_effect=true
- duplicate_ack_loss_safe=true
- tenant_b_independent=true
- cloudflare_consumer_e2e=NOT_VERIFIED
- production_integration_ready=false

The test does NOT exercise the TrendCite PostgresExecutionStore, genuine Cloudflare Queue, transaction consumer ACK, network outages, security roles/RLS, replay policy, poison-message DLQ, or a process crash during commit. Those remain nonprod integration acceptance gaps. Dodo remains frozen; no live customer or resource activation.

This checkpoint cannot be treated as authorization to create Hyperdrive, bind queues, or deploy real runtime.
