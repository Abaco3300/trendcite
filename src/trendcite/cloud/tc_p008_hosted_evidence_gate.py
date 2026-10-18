"""TC-P008 hosted certification gate: pure evidence checks, never an execution claim."""

from collections.abc import Mapping

from trendcite.cloud.tc_p008_cleanup_evidence import verify_probe_cleanup
from trendcite.cloud.tc_p008_unique_write_contention import validate_unique_write_contention


def assess_hosted_probe(
    contention: Mapping[str, object],
    cleanup: Mapping[str, object],
    *,
    hosted_run_attested: bool = False,
) -> dict[str, str]:
    """Fail closed unless run attestation and both evidence contracts pass."""
    if hosted_run_attested is not True:
        raise RuntimeError("hosted execution attestation missing")
    if cleanup.get("probe_key") != contention.get("probe_key"):
        raise RuntimeError("probe key mismatch")
    if cleanup.get("probe_run") != contention.get("probe_run"):
        raise RuntimeError("probe run mismatch")
    validate_unique_write_contention(contention)
    verify_probe_cleanup(cleanup)
    return {"evidence_contract": "PASS", "hosted_result": "REQUIRES_INDEPENDENT_REVIEW"}
