"""Pure deterministic checks and conservative integer sizing. No I/O or model invocation."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from kavrigo_domain import (
    Money,
    OrderSide,
    OrderType,
    PortfolioSnapshot,
    ProposedAction,
    Quantity,
    RiskDecision,
    RiskEvaluation,
    RiskReasonCode,
    RiskScope,
    TimeInForce,
    TradingMode,
    content_hash,
)
from kavrigo_domain.identifiers import InstrumentClass
from kavrigo_risk.contracts import RiskControls, RiskRecord, RiskRegistration, RiskRequest
from kavrigo_risk.fixed import BPS_DENOMINATOR, SCALE, ceil_div, decimal, product, units
from kavrigo_runtime.contracts import EvaluationRequest
from kavrigo_runtime.validation import eligible_evidence, snapshot_hash

R = RiskReasonCode
_SCOPES = list(RiskScope)


def age_ms(now: datetime, then: datetime) -> int:
    delta = now - then
    micros = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    return ceil_div(micros, 1000)


@dataclass(frozen=True)
class Reservation:
    intent_id: str
    instrument: str
    asset: str
    network: str
    buy_notional: int
    sell_quantity: int
    cash_debit: int
    cost: int


@dataclass
class Account:
    cash: int
    equity: int
    exposure: int
    asset_exposure: dict[str, int]
    network_exposure: dict[str, int]
    quantities: dict[str, int]
    open_assets: set[str]
    losses: int
    peak: int


def account_state(
    portfolio: PortfolioSnapshot, networks: dict[str, str], reservations: tuple[Reservation, ...]
) -> Account:
    exposure = 0
    assets: dict[str, int] = {}
    groups: dict[str, int] = {}
    quantities: dict[str, int] = {}
    for position in portfolio.positions:
        instrument, mark = position.instrument_id, position.mark_price
        if (
            instrument.instrument_class is not InstrumentClass.SPOT
            or instrument.quote != "USD"
            or mark is None
            or (mark.base, mark.quote) != (instrument.base, "USD")
            or position.quantity.value < 0
            or instrument.value not in networks
        ):
            raise ValueError("unknown position valuation")
        quantity = units(position.quantity.value)
        value = product(quantity, units(mark.value))
        exposure += value
        assets[instrument.base] = assets.get(instrument.base, 0) + value
        network = networks[instrument.value]
        groups[network] = groups.get(network, 0) + value
        quantities[instrument.value] = quantity
    cash, equity = units(portfolio.cash.amount), units(portfolio.equity.amount)
    if (
        portfolio.base_currency != "USD"
        or cash < 0
        or equity <= 0
        or equity != cash + exposure
        or units(portfolio.gross_exposure.amount) != exposure
        or units(portfolio.net_exposure.amount) != exposure
        or portfolio.open_order_count
        or portfolio.reserved_cash.amount != 0
    ):
        raise ValueError("unknown or inconsistent account state")
    open_assets = {asset for asset, value in assets.items() if value > 0}
    for item in reservations:
        cash -= item.cash_debit
        equity -= item.cost
        exposure += item.buy_notional
        assets[item.asset] = assets.get(item.asset, 0) + item.buy_notional
        groups[item.network] = groups.get(item.network, 0) + item.buy_notional
        quantities[item.instrument] = quantities.get(item.instrument, 0) - item.sell_quantity
        if item.buy_notional:
            open_assets.add(item.asset)
    return Account(
        cash=cash,
        equity=equity,
        exposure=exposure,
        asset_exposure=assets,
        network_exposure=groups,
        quantities=quantities,
        open_assets=open_assets,
        losses=max(0, -units(portfolio.realized_pnl_today.amount))
        + sum(item.cost for item in reservations),
        peak=units(portfolio.peak_equity.amount),
    )


def _context_reasons(
    request: RiskRequest,
    registration: RiskRegistration,
    portfolio: PortfolioSnapshot,
    controls: RiskControls,
    now: datetime,
) -> list[R]:
    intent, decision, allocation = request.intent, request.decision, request.allocation
    snapshot, execution, version = (
        request.snapshot,
        registration.execution,
        registration.agent_version,
    )
    reasons: list[R] = []
    if (
        intent.workspace_id != portfolio.workspace_id
        or intent.workspace_id != version.workspace_id
        or decision.workspace_id != intent.workspace_id
        or decision.agent_version_id != version.agent_version_id
        or intent.agent_version_id != version.agent_version_id
        or intent.decision_id != decision.decision_id
        or allocation.decision_id != decision.decision_id
        or allocation.instrument_id != intent.instrument_id
        or decision.instrument_id != intent.instrument_id
        or decision.snapshot_id != snapshot.snapshot_id
        or request.market.book.instrument_id != intent.instrument_id
        or snapshot.content_hash != snapshot_hash(snapshot)
        or decision.proposed_notional != allocation.requested_notional
        or intent.notional.currency != allocation.allocated_notional.currency
        or intent.notional.amount > allocation.allocated_notional.amount
        or not decision.proposed_action.requires_order
        or (intent.side is OrderSide.BUY) != (decision.proposed_action is ProposedAction.BUY)
        or not snapshot.as_of <= decision.decided_at <= intent.created_at <= now
        or snapshot.created_at > now
    ):
        reasons.append(R.CONTEXT_MISMATCH)
    if intent.is_expired_at(now):
        reasons.append(R.INTENT_EXPIRED)
    if intent.order_type is not OrderType.MARKET or intent.time_in_force is not TimeInForce.IOC:
        reasons.append(R.UNSUPPORTED_ORDER_TYPE)
    if (
        intent.mode not in {TradingMode.PAPER, TradingMode.BACKTEST}
        or intent.mode != portfolio.mode
        or intent.mode != version.spec.mode
    ):
        reasons.append(R.MODE_NOT_PERMITTED)
    if (
        intent.instrument_id not in version.spec.universe.instruments
        or intent.instrument_id not in snapshot.instruments
        or intent.instrument_id.quote != "USD"
    ):
        reasons.append(R.UNSUPPORTED_SYMBOL)
    if (
        not version.is_approved_for("local")
        or version.agent_version_id in controls.blocked_agent_versions
        or version.created_at > now
        or any(p.created_at > now for p in registration.policies)
    ):
        reasons.append(R.AGENT_VERSION_NOT_APPROVED)
    if controls.active_kills:
        reasons.append(R.KILL_SWITCH_ACTIVE)
    if not controls.account_known or not controls.as_of <= now < controls.valid_until:
        reasons.append(R.UNKNOWN_ACCOUNT_STATE)
    if now >= controls.lease_expires_at:
        reasons.append(R.EXECUTION_LEASE_EXPIRED)
    if not controls.connectivity_ok:
        reasons.append(R.EXCHANGE_CONNECTIVITY_DEGRADED)
    if not controls.event_calendar_known:
        reasons.append(R.SCHEDULED_EVENT_RISK)
    if (
        not portfolio.is_reconciled
        or portfolio.reconciled_at is None
        or not 0 <= age_ms(now, portfolio.reconciled_at) <= execution.max_reconciliation_age_ms
    ):
        reasons.append(R.RECONCILIATION_STALE)
    if not 0 <= age_ms(now, portfolio.as_of) <= execution.max_portfolio_age_ms:
        reasons.append(R.UNKNOWN_ACCOUNT_STATE)
    if any(p.opened_at is not None and p.opened_at > portfolio.as_of for p in portfolio.positions):
        reasons.append(R.UNKNOWN_ACCOUNT_STATE)
    market = request.market
    times = [market.observed_at, market.book.received_at]
    if market.book.venue_time is not None:
        times.append(market.book.venue_time)
    if market.book.received_at > market.observed_at or any(
        not 0 <= age_ms(now, stamp) <= execution.max_market_age_ms for stamp in times
    ):
        reasons.append(R.STALE_DATA)
    elapsed = age_ms(now, snapshot.as_of)
    if not 0 <= elapsed <= execution.max_snapshot_age_ms:
        reasons.append(R.STALE_DATA)
    quality = snapshot.quality
    if not quality.provider_health_ok or not quality.sequence_complete:
        reasons.append(R.STALE_DATA)
    if quality.freshness.stale_families:
        reasons.append(R.STALE_DATA)
    if quality.freshness.missing_families:
        reasons.append(R.MISSING_DATA_FAMILY)
    if intent.mode is TradingMode.BACKTEST and quality.contains_revised_data:
        reasons.append(R.CONTEXT_MISMATCH)
    for policy in registration.policies:
        if quality.score < policy.freshness.min_data_quality:
            reasons.append(R.DATA_QUALITY_BELOW_MINIMUM)
        for family in policy.freshness.required_families:
            age = quality.freshness.age_for(family)
            if age is None:
                reasons.append(R.MISSING_DATA_FAMILY)
        # Also enforce optional observed families for which a policy supplies a budget.
        for family, limit in policy.freshness.max_age_ms.items():
            age = quality.freshness.age_for(family)
            if age is not None and age + max(0, elapsed) > limit:
                reasons.append(R.STALE_DATA)
        if intent.side is OrderSide.BUY and any(
            event - timedelta(minutes=policy.event_risk.block_new_positions_before_macro_minutes)
            <= now
            <= event + timedelta(minutes=policy.event_risk.block_new_positions_after_macro_minutes)
            for event in controls.macro_events
        ):
            # Conservative V1: reject new risk throughout the configured event window.
            reasons.append(R.SCHEDULED_EVENT_RISK)
    refs = decision.evidence_refs + decision.contradicting_evidence_refs
    cycle = EvaluationRequest(
        workspace_id=intent.workspace_id,
        agent_version_id=intent.agent_version_id,
        idempotency_key=intent.idempotency_key,
        horizon_minutes=decision.prediction.horizon_minutes,
        snapshot=snapshot,
        portfolio=portfolio,
        evidence=request.evidence,
    )
    eligible = {
        item.evidence_id
        for item in eligible_evidence(cycle, version)
        if item.ingested_at <= snapshot.as_of
        and item.observed_at <= snapshot.as_of
        and (item.news_event is None or item.news_event.first_seen_at <= item.ingested_at)
        and (not item.instruments or intent.instrument_id in item.instruments)
        and (not item.assets or intent.instrument_id.base in item.assets)
    }
    if (
        set(snapshot.evidence_refs) != {item.evidence_id for item in request.evidence}
        or len(request.evidence) != len({item.evidence_id for item in request.evidence})
        or len(refs) != len(set(refs))
        or not set(refs) <= eligible
        or not decision.evidence_refs
        or len(refs) < version.spec.evidence.min_evidence_items
        or (
            version.spec.evidence.require_contradicting_evidence
            and not decision.contradicting_evidence_refs
        )
        or decision.prediction.horizon_minutes not in version.spec.analysis.horizons_minutes
    ):
        reasons.append(R.EVIDENCE_REQUIREMENTS_NOT_MET)
    return reasons


def evaluate(
    request: RiskRequest,
    registration: RiskRegistration,
    portfolio: PortfolioSnapshot,
    controls: RiskControls,
    networks: dict[str, str],
    reservations: tuple[Reservation, ...],
    now: datetime,
) -> tuple[RiskRecord, Reservation | None]:
    """Return a reproducible record and a reservation; only the session may hand it off."""
    reasons = _context_reasons(request, registration, portfolio, controls, now)
    intent, execution = request.intent, registration.execution
    instrument = intent.instrument_id
    amount = quantity = debit = cost = 0
    binding: RiskScope | None = None
    try:
        account = account_state(portfolio, networks, reservations)
    except ValueError:
        reasons.append(R.UNKNOWN_ACCOUNT_STATE)
        account = None
    reservation = None
    if not reasons and account is not None:
        try:
            requested = units(intent.notional.amount)
            increment = units(execution.notional_increment_usd)
            fee, slippage = units(execution.fee_bps), units(execution.slippage_bps)
            bid = units(request.market.book.bid_price.value)
            ask = units(request.market.book.ask_price.value)
            liquidity = units(request.market.liquidity_usd)
            spread_bps = ceil_div(20_000 * SCALE * (ask - bid), ask + bid)
            buying = intent.side is OrderSide.BUY
            displayed_quantity = units(
                request.market.book.ask_size.value if buying else request.market.book.bid_size.value
            )
            worst_price = (
                ceil_div(ask * (BPS_DENOMINATOR + slippage), BPS_DENOMINATOR)
                if buying
                else bid * (BPS_DENOMINATOR - slippage) // BPS_DENOMINATOR
            )
            if increment <= 0 or worst_price <= 0:
                raise ValueError("unusable precision or price")
            policies = sorted(
                registration.policies, key=lambda p: (_SCOPES.index(p.scope), p.risk_policy_id)
            )
            for policy in policies:
                limits = policy.limits
                if spread_bps > limits.max_spread_bps * SCALE:
                    reasons.append(R.SPREAD_TOO_WIDE)
                if liquidity < units(limits.min_liquidity_usd):
                    reasons.append(R.INSUFFICIENT_LIQUIDITY)
                edge = request.decision.prediction.expected_return_bps * (1 if buying else -1)
                if request.decision.proposed_action not in {
                    ProposedAction.REDUCE,
                    ProposedAction.CLOSE,
                } and (
                    edge * SCALE
                    <= fee + slippage + spread_bps + limits.min_edge_over_cost_bps * SCALE
                ):
                    reasons.append(R.EDGE_BELOW_COST_PLUS_MARGIN)
                if buying and account.losses * 100 * SCALE >= units(
                    limits.max_daily_loss_pct
                ) * units(portfolio.equity.amount):
                    reasons.append(R.DAILY_LOSS_LIMIT_REACHED)
                if (
                    buying
                    and (account.peak - account.equity) * 100 * SCALE
                    >= units(limits.max_drawdown_pct) * account.peak
                ):
                    reasons.append(R.DRAWDOWN_CIRCUIT_BREAKER)

            def violations(candidate: int) -> list[tuple[R, RiskScope]]:
                fee_cost = ceil_div(candidate * fee, BPS_DENOMINATOR)
                result: list[tuple[R, RiskScope]] = []
                if (candidate if buying else 0) + fee_cost > account.cash:
                    result.append((R.INSUFFICIENT_CASH, RiskScope.PORTFOLIO))
                if not buying and ceil_div(candidate * SCALE, worst_price) > account.quantities.get(
                    instrument.value, 0
                ):
                    result.append((R.MAX_POSITION_EXCEEDED, RiskScope.ASSET))
                if candidate * SCALE > displayed_quantity * (ask if buying else bid):
                    result.append((R.INSUFFICIENT_LIQUIDITY, RiskScope.ORDER))
                equity_after_cost = account.equity - fee_cost
                for policy in policies:
                    limits = policy.limits
                    if candidate > units(limits.max_order_notional_usd):
                        result.append((R.MAX_ORDER_EXCEEDED, policy.scope))
                    if not buying:
                        continue
                    if equity_after_cost <= 0:
                        result.append((R.INSUFFICIENT_CASH, policy.scope))
                    if (account.losses + fee_cost) * 100 * SCALE > units(
                        limits.max_daily_loss_pct
                    ) * units(portfolio.equity.amount):
                        result.append((R.DAILY_LOSS_LIMIT_REACHED, policy.scope))
                    if (account.peak - equity_after_cost) * 100 * SCALE > units(
                        limits.max_drawdown_pct
                    ) * account.peak:
                        result.append((R.DRAWDOWN_CIRCUIT_BREAKER, policy.scope))
                    for exposure, cap, reason in (
                        (
                            account.exposure + candidate,
                            limits.max_gross_exposure_pct,
                            R.MAX_GROSS_EXPOSURE_EXCEEDED,
                        ),
                        (
                            max(
                                value + (candidate if asset == instrument.base else 0)
                                for asset, value in {
                                    instrument.base: 0,
                                    **account.asset_exposure,
                                }.items()
                            ),
                            limits.max_single_asset_exposure_pct,
                            R.MAX_POSITION_EXCEEDED,
                        ),
                        (
                            max(
                                value + (candidate if group == networks[instrument.value] else 0)
                                for group, value in {
                                    networks[instrument.value]: 0,
                                    **account.network_exposure,
                                }.items()
                            ),
                            limits.max_network_exposure_pct,
                            R.NETWORK_CONCENTRATION_EXCEEDED,
                        ),
                    ):
                        if exposure * 100 * SCALE > units(cap) * equity_after_cost:
                            result.append((reason, policy.scope))
                    if len(account.open_assets | {instrument.base}) > limits.max_open_positions:
                        result.append((R.MAX_OPEN_POSITIONS_EXCEEDED, policy.scope))
                return result

            if not reasons:
                original_violations = violations(requested)
                low, high = 0, requested // increment
                # All sizing constraints are monotone in proposed size. Integer search avoids
                # rounded division accidentally approving a value just above a hard boundary.
                while low < high:
                    mid = (low + high + 1) // 2
                    if violations(mid * increment):
                        high = mid - 1
                    else:
                        low = mid
                amount = low * increment
                minimum = max(units(p.limits.min_order_notional_usd) for p in policies)
                quantity = (
                    (amount * SCALE // worst_price)
                    if buying
                    else ceil_div(amount * SCALE, worst_price)
                )
                if amount < minimum or amount <= 0 or quantity <= 0 or violations(amount):
                    amount = quantity = 0
                    reasons.extend(reason for reason, _ in original_violations)
                    reasons.append(R.BELOW_MINIMUM_ORDER_SIZE)
                else:
                    cost = ceil_div(amount * fee, BPS_DENOMINATOR)
                    debit = (amount if buying else 0) + cost
                    if amount < requested:
                        reasons.append(R.APPROVED_RESIZED)
                        reasons.extend(reason for reason, _ in original_violations)
                        next_step = violations(amount + increment)
                        binding = (
                            next_step[0][1]
                            if next_step and amount + increment <= requested
                            else RiskScope.ORDER
                        )
                    else:
                        reasons.append(R.APPROVED)
                    reservation = Reservation(
                        intent.order_intent_id,
                        instrument.value,
                        instrument.base,
                        networks[instrument.value],
                        amount if buying else 0,
                        0 if buying else quantity,
                        debit,
                        cost,
                    )
        except ValueError:
            reasons.append(R.UNSUPPORTED_PRECISION)
            amount = quantity = debit = cost = 0
            reservation = None
    fingerprints = {
        "request_hash": content_hash(request),
        "portfolio_hash": content_hash(portfolio),
        "registration_hash": content_hash(registration),
        "controls_hash": content_hash(controls),
        "reservations_hash": content_hash([vars(item) for item in reservations]),
    }
    identity = content_hash({**fingerprints, "evaluated_at": now, "evaluator_version": "v1"})
    decision = (
        RiskDecision.REJECTED
        if amount == 0
        else (
            RiskDecision.APPROVED_RESIZED
            if R.APPROVED_RESIZED in reasons
            else RiskDecision.APPROVED
        )
    )
    evaluation = RiskEvaluation(
        risk_evaluation_id="re_" + identity.removeprefix("sha256:")[:32],
        order_intent_id=intent.order_intent_id,
        decision_id=intent.decision_id,
        workspace_id=intent.workspace_id,
        evaluated_at=now,
        decision=decision,
        reason_codes=list(dict.fromkeys(reasons)),
        applied_policy_ids=[
            p.risk_policy_id
            for p in sorted(
                registration.policies, key=lambda p: (_SCOPES.index(p.scope), p.risk_policy_id)
            )
        ],
        binding_scope=binding,
        requested_notional=intent.notional,
        approved_notional=Money(amount=decimal(amount), currency=intent.notional.currency),
        evaluator_version="v1",
    )
    record = RiskRecord(
        evaluation=evaluation,
        account_id=controls.account_id,
        **fingerprints,
        expires_at=min(
            intent.expires_at,
            controls.valid_until,
            controls.lease_expires_at,
            now + timedelta(milliseconds=execution.max_approval_age_ms),
        ),
        max_quantity=Quantity(value=decimal(quantity), asset=instrument.base),
        max_cash_debit=Money(amount=decimal(debit), currency="USD"),
    )
    return record, reservation
