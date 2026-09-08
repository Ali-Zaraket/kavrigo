"""One structured proposal per candidate, with evidence references checked locally."""

from kavrigo_domain import (
    AgentDecision,
    AgentVersion,
    DecisionProposal,
    DecisionState,
    EvidenceItem,
    ModelCallRecord,
    ModelProfile,
    Prediction,
    ProposedAction,
    SignalScores,
)
from kavrigo_domain.base import UtcDatetime
from kavrigo_domain.prompts import DEFAULT_PROMPT_TEMPLATE
from kavrigo_domain.snapshot import MarketRegime
from kavrigo_model_gateway import PromptDefinition
from kavrigo_runtime.contracts import AnalysisInput


def analysis_prompt(profile: ModelProfile = ModelProfile.REASON_BALANCED) -> PromptDefinition:
    if profile not in {ModelProfile.REASON_BALANCED, ModelProfile.REASON_DEEP}:
        raise ValueError("asset analysis requires a reasoning profile")
    return PromptDefinition(
        key="asset-analysis-v2-" + profile.value,
        profile=profile,
        system_text=DEFAULT_PROMPT_TEMPLATE,
        input_type=AnalysisInput,
        output_type=DecisionProposal,
    )


def proposal_reason(
    proposal: DecisionProposal, facts: AnalysisInput, version: AgentVersion
) -> str | None:
    all_refs = proposal.evidence_refs + proposal.contradicting_evidence_refs
    known = {item.evidence_id: item for item in facts.evidence}
    if any(ref not in known for ref in all_refs) or len(all_refs) != len(set(all_refs)):
        return "unsupported_evidence_reference"
    if proposal.prediction.horizon_minutes != facts.horizon_minutes:
        return "horizon_mismatch"
    if proposal.proposed_action.requires_order:
        if (
            len(set(all_refs)) < version.spec.evidence.min_evidence_items
            or not proposal.evidence_refs
        ):
            return "insufficient_supported_evidence"
        # The model must search this frozen corpus for contradictions. A source's hint flag is
        # not an exhaustive classification: refusing before analysis when it is absent would
        # prevent newly extracted news from ever being inspected for counter-evidence.
        if (
            version.spec.evidence.require_contradicting_evidence
            and not proposal.contradicting_evidence_refs
        ):
            return "missing_contradicting_evidence"
        assert proposal.proposed_notional is not None
        if proposal.proposed_notional.currency != facts.instrument.quote:
            return "proposal_currency_mismatch"
        if proposal.estimated_cost_bps is None or proposal.estimated_cost_bps < 0:
            return "unknown_estimated_cost"
    return None


def abstain(horizon: int, reason: str) -> DecisionProposal:
    return DecisionProposal(
        market_regime=MarketRegime.UNKNOWN,
        state=DecisionState.UNKNOWN,
        signals=SignalScores(),
        prediction=Prediction(
            expected_return_bps=0, confidence=0, uncertainty=1, horizon_minutes=horizon
        ),
        proposed_action=ProposedAction.NO_TRADE,
        reason_codes=[reason],
    )


def bind(
    proposal: DecisionProposal,
    *,
    version: AgentVersion,
    snapshot_id: str,
    facts: AnalysisInput,
    decision_id: str,
    decided_at: UtcDatetime,
    calls: tuple[ModelCallRecord, ...] = (),
) -> AgentDecision:
    # Model output is never allowed to supply identity or provenance. All fields are validated
    # together here, and this result is still a proposal with no risk or execution capability.
    return AgentDecision.model_validate(
        {
            **proposal.model_dump(mode="python"),
            "decision_id": decision_id,
            "workspace_id": version.workspace_id,
            "agent_version_id": version.agent_version_id,
            "snapshot_id": snapshot_id,
            "instrument_id": facts.instrument,
            "decided_at": decided_at,
            "model_calls": calls,
        }
    )


def relevant_evidence(
    evidence: tuple[EvidenceItem, ...], instrument: str, asset: str
) -> tuple[EvidenceItem, ...]:
    return tuple(
        item
        for item in evidence
        if (
            (not item.instruments and not item.assets)
            or any(i.value == instrument for i in item.instruments)
            or asset in item.assets
        )
    )
