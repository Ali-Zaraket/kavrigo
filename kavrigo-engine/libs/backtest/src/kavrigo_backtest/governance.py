"""Frozen deterministic-risk inputs for the bounded reference backtest.

The model does not choose these values. They are immutable run configuration supplied by the
trusted control plane and included in the backtest configuration hash.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_domain import (
    AgentVersion,
    DataFamily,
    DataPack,
    DomainModel,
    ExactDecimal,
    InstrumentClass,
    RiskExecutionPolicy,
    RiskPolicy,
    RiskScope,
    TradingMode,
    UtcDatetime,
    content_hash,
)
from kavrigo_domain.identifiers import AgentVersionId

__all__ = ["ReferenceRiskReplay"]


class ReferenceRiskReplay(DomainModel):
    """Policies and supervisor facts replayed at every reference-strategy order signal."""

    kind: Literal["reference-risk-replay-v1"] = "reference-risk-replay-v1"
    agent_version: AgentVersion
    policies: Annotated[tuple[RiskPolicy, ...], Field(min_length=3, max_length=16)]
    execution: RiskExecutionPolicy
    networks: dict[str, Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]]
    account_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
    expected_edge_bps: Annotated[ExactDecimal, Field(gt=0, le=10_000)]
    account_known: bool = True
    connectivity_ok: bool = True
    event_calendar_known: bool = True
    active_kills: Annotated[
        tuple[Literal["global", "workspace", "account", "agent", "asset", "risk_class"], ...],
        Field(max_length=6),
    ] = ()
    blocked_agent_versions: Annotated[tuple[AgentVersionId, ...], Field(max_length=128)] = ()
    macro_events: Annotated[tuple[UtcDatetime, ...], Field(max_length=128)] = ()

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        version = self.agent_version
        if version.spec.mode is not TradingMode.BACKTEST:
            raise ValueError("risk replay requires a backtest agent version")
        if any(
            instrument.quote != "USD"
            or instrument.venue != "SIM"
            or instrument.instrument_class is not InstrumentClass.SPOT
            for instrument in version.spec.universe.instruments
        ):
            raise ValueError("reference risk replay requires synthetic USD spot on SIM")
        if version.spec_hash != content_hash(version.spec):
            raise ValueError("risk replay agent spec hash mismatch")
        if not version.is_approved_for("local"):
            raise ValueError("risk replay agent version must be approved for local execution")
        if DataPack.PRICE_TECHNICAL not in version.spec.data_packs:
            raise ValueError("reference risk replay requires the price technical data pack")
        if self.execution.execution_policy_id != version.spec.execution_policy_ref:
            raise ValueError("risk replay execution policy reference mismatch")
        ids = [policy.risk_policy_id for policy in self.policies]
        if len(ids) != len(set(ids)):
            raise ValueError("risk replay contains duplicate policies")
        scopes = {policy.scope for policy in self.policies}
        if not {RiskScope.GLOBAL, RiskScope.WORKSPACE, RiskScope.AGENT} <= scopes:
            raise ValueError("risk replay requires global, workspace and agent policies")
        if not any(
            policy.scope is RiskScope.AGENT
            and policy.risk_policy_id == version.spec.risk_policy_ref
            for policy in self.policies
        ):
            raise ValueError("risk replay agent policy reference mismatch")
        for policy in self.policies:
            expected_workspace = None if policy.scope is RiskScope.GLOBAL else version.workspace_id
            if policy.workspace_id != expected_workspace:
                raise ValueError("risk replay policy workspace mismatch")
            expected_hash = content_hash(policy.model_dump(mode="python", exclude={"content_hash"}))
            if policy.content_hash != expected_hash:
                raise ValueError("risk replay policy hash mismatch")
            if set(policy.freshness.required_families) != {DataFamily.CANDLES}:
                raise ValueError("bar-based risk replay may require candle freshness only")
        if any(
            instrument.value not in self.networks
            for instrument in version.spec.universe.instruments
        ):
            raise ValueError("risk replay requires a network for every instrument")
        if len(self.active_kills) != len(set(self.active_kills)):
            raise ValueError("risk replay controls contain duplicate kill scopes")
        if self.expected_edge_bps <= Decimal(0):
            raise ValueError("risk replay expected edge must be positive")
        return self

    @property
    def replay_hash(self) -> str:
        return content_hash(self)
