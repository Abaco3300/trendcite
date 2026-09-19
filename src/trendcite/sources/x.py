"""Optional X/Twitter adapter interface.

TrendCite does not scrape X and does not work around its access controls. This
adapter only reserves the interface that a future implementation using the official,
authenticated X API would plug into. In this MVP it always reports itself as
unavailable, and no TrendCite feature depends on it.
"""

from __future__ import annotations

import os
from datetime import datetime

from ..models import EvidenceItem
from .base import SourceAdapter, SourceUnavailable


class XAdapter(SourceAdapter):
    name = "x"
    description = "X/Twitter (optional interface only; official API required; not implemented)"

    def collect(self, now: datetime) -> list[EvidenceItem]:
        if not os.environ.get("X_BEARER_TOKEN"):
            raise SourceUnavailable("X adapter not configured (optional; official API only)")
        raise SourceUnavailable(
            "X adapter is an interface only in this MVP; there is no scraping fallback by design"
        )
