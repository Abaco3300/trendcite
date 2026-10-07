"""Supplemental linked-content records for TrendCite Cloud.

These records are intentionally outside EvidenceItem and all scoring inputs.
They provide bounded context and provenance after canonical scoring has finished.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ...vecturl import LinkedContentEvidence
from .. import ids
from ._base import require_aware


@dataclass(frozen=True)
class LinkedContentEnrichment:
    signal_id: str
    evidence: LinkedContentEvidence

    @classmethod
    def from_evidence(
        cls,
        signal_id: str,
        evidence: LinkedContentEvidence,
    ) -> LinkedContentEnrichment:
        return cls(signal_id=signal_id, evidence=evidence)


@dataclass(frozen=True)
class RunLinkedContentEvidence:
    linked_content_id: str
    workspace_id: str
    run_id: str
    signal_id: str
    bundle_id: str
    source_url: str
    text_fragments: tuple[str, ...]
    provenance: tuple[dict[str, Any], ...]
    quality_overall: float | None
    quality_completeness: float | None
    quality_provenance_coverage: float | None
    fulfilled_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    actual_cost_micro_usd: int | None
    captured_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        run_id: str,
        enrichment: LinkedContentEnrichment,
        captured_at: datetime,
    ) -> RunLinkedContentEvidence:
        evidence = enrichment.evidence
        provenance = tuple(
            {
                "provenance_id": item.provenance_id,
                "origin_type": item.origin_type,
                "method": item.method,
                "provider": item.provider,
                "provider_product": item.provider_product,
                "model": item.model,
                "source_ref": item.source_ref,
                "created_at": item.created_at,
            }
            for item in evidence.provenance
        )
        return cls(
            linked_content_id=ids.cloud_id(
                "linked-content",
                run_id,
                enrichment.signal_id,
                evidence.source_url,
            ),
            workspace_id=workspace_id,
            run_id=run_id,
            signal_id=enrichment.signal_id,
            bundle_id=evidence.bundle_id,
            source_url=evidence.source_url,
            text_fragments=evidence.text_fragments,
            provenance=provenance,
            quality_overall=evidence.quality_overall,
            quality_completeness=evidence.quality_completeness,
            quality_provenance_coverage=evidence.quality_provenance_coverage,
            fulfilled_capabilities=evidence.fulfilled_capabilities,
            missing_capabilities=evidence.missing_capabilities,
            actual_cost_micro_usd=evidence.actual_cost_micro_usd,
            captured_at=require_aware(captured_at, "captured_at"),
        )
