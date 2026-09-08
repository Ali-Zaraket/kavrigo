"""Deterministic candidate scoring over existing step 6 features (§6.2)."""

from datetime import timedelta
from decimal import Decimal, localcontext

from kavrigo_domain import AgentVersion, MarketSnapshot
from kavrigo_domain.numeric import DECIMAL_CONTEXT
from kavrigo_runtime.contracts import Candidate, NetworkContext, ScannerPolicy


def scan(
    snapshot: MarketSnapshot, version: AgentVersion, policy: ScannerPolicy
) -> tuple[Candidate, ...]:
    allowed = {item.value for item in version.spec.universe.instruments}
    candidates: list[Candidate] = []
    with localcontext(DECIMAL_CONTEXT):
        for features in snapshot.features:
            if features.instrument_id.value not in allowed:
                continue
            hits = tuple(
                sorted(
                    name
                    for name, threshold in policy.absolute_thresholds.items()
                    if name in features.values and abs(features.values[name]) >= threshold
                )
            )
            if version.spec.analysis.market_scanner and not hits:
                continue
            score = max(
                (
                    abs(features.values[name])
                    / (abs(features.values[name]) + policy.absolute_thresholds[name])
                    for name in hits
                ),
                default=Decimal(0),
            )
            candidates.append(
                Candidate(
                    instrument_id=features.instrument_id,
                    interest_score=score,
                    reasons=hits or ("scanner_disabled",),
                    expires_at=snapshot.as_of + timedelta(milliseconds=policy.candidate_ttl_ms),
                )
            )
    return tuple(
        sorted(candidates, key=lambda c: (-c.interest_score, c.instrument_id.value))[
            : policy.max_candidates
        ]
    )


class FrozenNetworkContexts:
    """Read-only adapter over already frozen state; no shared 'latest' reads mid-cycle."""

    def __init__(self, contexts: tuple[NetworkContext, ...] = ()) -> None:
        self._records = tuple(item.model_dump_json() for item in contexts)

    def frozen_contexts(self) -> tuple[NetworkContext, ...]:
        return tuple(NetworkContext.model_validate_json(item) for item in self._records)
