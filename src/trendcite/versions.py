"""Version identifiers for every deterministic algorithm TrendCite ships.

Every stored or emitted artefact names the algorithm version that produced it, so a
snapshot taken by an older build is never silently compared with a newer one. This
module deliberately imports nothing: every other module may import it.

Bump a version whenever the *output* of the corresponding algorithm changes for the
same input. Adding a new component, changing a weight, or changing a normalisation
constant all count.
"""

from __future__ import annotations

from typing import Final

#: How an observation's stable identity is derived (native id -> URL -> fingerprint).
OBSERVATION_IDENTITY_VERSION: Final = "observation-identity-v1"

#: How the ordered evidence set backing an evaluation is hashed.
EVIDENCE_SET_ALGORITHM: Final = "evidence-set-v1"

#: How a signal's stable id is derived from its canonical key.
SIGNAL_ID_VERSION: Final = "signal-id-v1"

#: The deterministic signal evaluation (components, weights, state machine).
SIGNAL_EVALUATION_VERSION: Final = "signal-eval-v1"

#: The public Content Opportunity score. Unchanged since v0.1.0; the public JSON
#: ``score`` object is frozen by this version.
CONTENT_OPPORTUNITY_SCORE_VERSION: Final = "content-opportunity-score-v1"

#: On-disk layout of the local history store.
HISTORY_FORMAT_VERSION: Final = "trendcite-history-v1"


def engine_versions() -> dict[str, str]:
    """The version block emitted with every report."""
    return {
        "observation_identity": OBSERVATION_IDENTITY_VERSION,
        "evidence_set": EVIDENCE_SET_ALGORITHM,
        "signal_id": SIGNAL_ID_VERSION,
        "signal_evaluation": SIGNAL_EVALUATION_VERSION,
        "content_opportunity_score": CONTENT_OPPORTUNITY_SCORE_VERSION,
        "history_format": HISTORY_FORMAT_VERSION,
    }
