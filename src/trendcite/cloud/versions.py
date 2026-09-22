"""Version identifiers for every deterministic Cloud algorithm.

The same discipline as :mod:`trendcite.versions`: every stored Cloud artefact names
the algorithm version that produced it, so a row written by an older build is never
silently reinterpreted by a newer one. This module imports nothing, not even the core
version block, so every other Cloud module may import it freely.

Core versions are *not* duplicated here. A stored signal carries the core
``signal_id``/``signal_eval`` versions it was produced with; Cloud only versions the
things Cloud itself decides.
"""

from __future__ import annotations

from typing import Final

#: How a Cloud-native entity id is derived from its logical identity.
CLOUD_ID_VERSION: Final = "cloud-id-v1"

#: How a RadarRun's idempotency key is derived (workspace, radar version, cutoff).
RUN_IDEMPOTENCY_VERSION: Final = "radar-run-idempotency-v1"

#: Historical deterministic matcher used by Cloud Foundation v1.
LEGACY_MATCHER_VERSION: Final = "watchlist-match-v1"

#: The canonical matcher. v2 adds the relevance engine: the include /
#: exclude rules are unchanged, but a satisfied include rule is no longer sufficient
#: on its own -- a match must also clear the relevance threshold. Stored artefacts
#: written by v1 keep saying v1, so an old decision stays readable as an old decision.
MATCHER_VERSION: Final = "watchlist-match-v2"

#: The deterministic relevance engine: components, weights, bands and the decision
#: threshold. Versioned separately from the matcher because the two can move apart:
#: a new component changes relevance without changing include/exclude semantics.
RELEVANCE_VERSION: Final = "relevance-v1"

#: The relational schema the migration ledger applies.
CLOUD_SCHEMA_VERSION: Final = "cloud-schema-v2"


def cloud_versions() -> dict[str, str]:
    """The version block a Cloud run records alongside the core engine versions."""
    return {
        "cloud_id": CLOUD_ID_VERSION,
        "run_idempotency": RUN_IDEMPOTENCY_VERSION,
        "matcher": MATCHER_VERSION,
        "relevance": RELEVANCE_VERSION,
        "cloud_schema": CLOUD_SCHEMA_VERSION,
    }
