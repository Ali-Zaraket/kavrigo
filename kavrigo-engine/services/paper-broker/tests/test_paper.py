from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from kavrigo_domain import OrderStatus, Position, Price, Quantity, content_hash
from kavrigo_paper import (
    LocalPaperBroker,
    LocalPaperVenue,
    PaperBook,
    PaperConfig,
    PaperDeliveryUnknown,
    PaperError,
    PaperInstrument,
    PaperLevel,
    replay,
)
from kavrigo_paper.account import entry_hash

from .conftest import BTC, ETH, WS, change, money


@pytest.fixture
def config():
    return PaperConfig(
        version="synthetic-ioc-v1",
        latency_ms=100,
        max_market_age_ms=2000,
        instruments=tuple(
            PaperInstrument(
                instrument_id=i,
                quantity_step="0.0001",
                price_tick="0.0001",
                minimum_notional_usd="1",
                network="crypto",
            )
            for i in (BTC, ETH)
        ),
    )


@pytest.fixture
def paper(build_session, clock, portfolio, config):
    risk = build_session()
    venue = LocalPaperVenue(
        environment="local",
        account_id="paper-account-one",
        initial_portfolio=portfolio,
        config=config,
        risk=risk,
        clock=clock,
    )
    return risk, venue, LocalPaperBroker(workspace_id=WS, venue=venue)


def book(clock, sequence=1, quantity="100", instrument=BTC, **updates):
    return PaperBook(
        instrument_id=instrument,
        sequence=sequence,
        event_time=clock(),
        received_at=clock(),
        bids=(PaperLevel(price="99.9", quantity=quantity),),
        asks=(PaperLevel(price="100.1", quantity=quantity),),
        **updates,
    )


def submit(paper, request, **kwargs):
    risk, _, broker = paper
    risk.evaluate(request)
    return broker.submit(order_intent_id=request.intent.order_intent_id, fencing_token=1, **kwargs)


def fill(paper, clock, **kwargs):
    clock.now += timedelta(milliseconds=100)
    observation = book(clock, **kwargs)
    paper[2].observe(observation)
    return observation


def test_buy_exact_accounting_and_replay(paper, make_request, clock):
    order = submit(paper, make_request())
    assert order.status is OrderStatus.SUBMITTED
    assert paper[2].state.portfolio.reserved_cash.amount == Decimal("100.1")
    fill(paper, clock)
    state = paper[2].state
    order = state.orders[0]
    assert order.status is OrderStatus.FILLED
    assert order.fills[0].price.value == Decimal("100.2001")
    assert order.filled_quantity.value == Decimal("0.9980")
    gross = order.fills[0].notional.amount
    fees = order.fees_paid.amount
    assert state.portfolio.cash.amount == Decimal(1000) - gross - fees
    assert state.cost_basis[BTC.value].amount == gross
    assert state.portfolio.realized_pnl_today.amount == -fees
    assert state.portfolio.unrealized_pnl.amount == Decimal("0.9980") * Decimal("99.9") - gross
    assert state.portfolio.reserved_cash.amount == 0
    assert (
        state.portfolio.equity.amount
        == state.portfolio.cash.amount + state.portfolio.gross_exposure.amount
    )
    assert replay(paper[1].export_replay(workspace_id=WS)) == state


def test_partial_ioc_cancels_remainder(paper, make_request, clock):
    submit(paper, make_request())
    fill(paper, clock, quantity="0.25")
    order = paper[2].state.orders[0]
    assert order.status is OrderStatus.CANCELLED
    assert order.reject_reason == "ioc_remainder_cancelled"
    assert order.filled_quantity.value == Decimal("0.25")
    assert paper[2].state.portfolio.reserved_cash.amount == 0
    # Canonical simulator resources are settled; the risk generation still retains its hold.
    assert (
        paper[0].handoff(workspace_id=WS, order_intent_id=order.order_intent_id, fencing_token=1)
        is None
    )


def test_multiple_levels_and_shared_depth(paper, make_request, clock):
    submit(paper, make_request(1, amount="50"))
    submit(paper, make_request(2, amount="50"))
    clock.now += timedelta(milliseconds=100)
    observation = change(
        book(clock),
        asks=(
            PaperLevel(price="100.1", quantity="0.3"),
            PaperLevel(price="100.2", quantity="0.3"),
        ),
    )
    paper[2].observe(observation)
    orders = paper[2].state.orders
    assert len(orders[0].fills) == 2
    assert sum(x.filled_quantity.value for x in orders) == Decimal("0.6")
    assert orders[1].status is OrderStatus.CANCELLED
    assert sum(x.fees_paid.amount for x in orders) == paper[2].state.fees_paid.amount
    assert replay(paper[1].export_replay(workspace_id=WS)) == paper[2].state


def test_latency_never_fills_from_pre_submission_market(paper, make_request, clock):
    submit(paper, make_request())
    paper[2].observe(book(clock))
    assert paper[2].state.orders[0].status is OrderStatus.SUBMITTED
    clock.now += timedelta(milliseconds=100)
    late = change(book(clock, 2), event_time=clock() - timedelta(milliseconds=150))
    with pytest.raises(PaperError, match="out_of_order_market"):
        paper[2].observe(late)
    paper[2].reconcile()
    paper[2].observe(book(clock, 2))
    assert paper[2].state.orders[0].status is OrderStatus.FILLED


def test_duplicate_command_and_market_no_second_fill(paper, make_request, clock):
    request = make_request()
    first = submit(paper, request)
    second = paper[2].submit(order_intent_id=request.intent.order_intent_id, fencing_token=1)
    assert first == second
    observation = fill(paper, clock)
    before = paper[2].state
    paper[2].observe(observation)
    assert paper[2].state == before
    assert len(paper[1].export_replay(workspace_id=WS).entries) == 2


def test_concurrent_duplicate_submissions(paper, make_request):
    request = make_request()
    paper[0].evaluate(request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        orders = list(
            pool.map(
                lambda _: paper[1].submit(
                    workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=1
                ),
                range(24),
            )
        )
    assert all(order == orders[0] for order in orders)
    assert len(paper[1].export_replay(workspace_id=WS).entries) == 1


def test_lost_submit_ack_then_unknown_fill_reconciles(paper, make_request, clock):
    request = make_request()
    with pytest.raises(PaperDeliveryUnknown):
        submit(paper, request, acknowledge=False)
    assert not paper[2].state.portfolio.is_reconciled
    with pytest.raises(PaperError, match="reconciliation_required"):
        paper[2].submit(order_intent_id=request.intent.order_intent_id, fencing_token=1)
    clock.now += timedelta(milliseconds=100)
    paper[1].observe(workspace_id=WS, book=book(clock))
    result = paper[2].reconcile()
    assert len(result.discovered_fill_ids) == 1
    assert paper[2].state.orders[0].status is OrderStatus.FILLED
    assert paper[2].state.portfolio.is_reconciled
    retry = paper[2].submit(order_intent_id=request.intent.order_intent_id, fencing_token=1)
    assert retry == paper[2].state.orders[0]
    assert len(paper[1].export_replay(workspace_id=WS).entries) == 2


def test_lost_fill_ack_unknown_projection_and_recreated_broker(paper, make_request, clock):
    submit(paper, make_request())
    clock.now += timedelta(milliseconds=100)
    with pytest.raises(PaperDeliveryUnknown):
        paper[2].observe(book(clock), acknowledge=False)
    assert paper[2].state.orders[0].status is OrderStatus.UNKNOWN
    assert not paper[2].state.portfolio.is_reconciled
    recovered = LocalPaperBroker(workspace_id=WS, venue=paper[1])
    recovered.reconcile()
    assert recovered.state.orders[0].status is OrderStatus.FILLED
    assert recovered.state == replay(paper[1].export_replay(workspace_id=WS))
    assert len(paper[2].reconcile().discovered_fill_ids) == 1


@pytest.mark.parametrize("failure", ["stale", "expired", "kill", "fence", "lease", "revoked"])
def test_risk_recheck_before_fill(paper, make_request, clock, controls, failure):
    submit(paper, make_request())
    clock.now += timedelta(milliseconds=100)
    if failure == "stale":
        clock.now += timedelta(seconds=3)
    elif failure == "expired":
        clock.now += timedelta(seconds=11)
    else:
        updates = {"version": 2, "as_of": clock()}
        if failure == "kill":
            updates["active_kills"] = ("global",)
        elif failure == "fence":
            updates["fencing_token"] = 2
        elif failure == "lease":
            updates["lease_expires_at"] = clock() + timedelta(milliseconds=1)
        else:
            updates["blocked_agent_versions"] = (make_request().intent.agent_version_id,)
        paper[0].update_controls(change(controls, **updates))
        clock.now += timedelta(milliseconds=2)
    paper[2].observe(book(clock))
    state = paper[2].state
    assert state.orders[0].status in (OrderStatus.EXPIRED, OrderStatus.CANCELLED)
    assert not state.orders[0].fills
    assert state.portfolio.cash.amount == 1000


def test_rejected_intent_cannot_create_order(paper, make_request):
    request = make_request()
    request = change(
        request,
        decision=change(request.decision, proposed_action="no_trade", proposed_notional=money(0)),
    )
    assert submit(paper, request) is None
    assert paper[2].state.orders == ()


def test_conflicting_market_key_is_atomic(paper, make_request, clock):
    submit(paper, make_request())
    observation = fill(paper, clock)
    before = paper[1].export_replay(workspace_id=WS)
    with pytest.raises(PaperError, match="market_idempotency_conflict"):
        paper[2].observe(change(observation, asks=(PaperLevel(price="110", quantity="1"),)))
    assert paper[1].export_replay(workspace_id=WS) == before
    paper[2].reconcile()


def test_gap_requires_explicit_full_resync(paper, make_request, clock):
    submit(paper, make_request())
    paper[2].observe(book(clock, 1))
    clock.now += timedelta(milliseconds=100)
    paper[2].observe(book(clock, 3))
    assert not paper[2].state.portfolio.is_reconciled
    assert not paper[2].state.orders[0].fills
    paper[2].observe(book(clock, 4))
    assert not paper[2].state.portfolio.is_reconciled
    paper[2].observe(book(clock, 5, resync=True))
    assert paper[2].state.portfolio.is_reconciled
    assert paper[2].state.orders[0].status is OrderStatus.CANCELLED


def test_cancel_and_minimum_rejection(paper, make_request, clock):
    order = submit(paper, make_request())
    cancelled = paper[2].cancel(order.client_order_id)
    assert cancelled.status is OrderStatus.CANCELLED
    assert paper[2].cancel(order.client_order_id) == cancelled
    fill(paper, clock)
    assert not paper[2].state.orders[0].fills


def test_batch_seal_prevents_reseed_or_new_submission(paper, make_request, clock):
    submit(paper, make_request())
    fill(paper, clock)
    request = make_request(2)
    paper[0].evaluate(request)
    with pytest.raises(PaperError, match="batch_sealed"):
        paper[2].submit(order_intent_id=request.intent.order_intent_id, fencing_token=1)


def test_tenant_boundary(paper, clock):
    wrong = "ws_" + "f" * 32
    for operation in (
        lambda: paper[1].read(workspace_id=wrong),
        lambda: paper[1].export_replay(workspace_id=wrong),
        lambda: paper[1].observe(workspace_id=wrong, book=book(clock)),
        lambda: LocalPaperBroker(workspace_id=wrong, venue=paper[1]),
    ):
        with pytest.raises(PaperError, match="workspace_mismatch"):
            operation()


def test_replay_detects_tampering(paper, make_request, clock):
    submit(paper, make_request())
    fill(paper, clock)
    bundle = paper[1].export_replay(workspace_id=WS)
    altered = change(bundle.entries[-1], state_hash="sha256:" + "f" * 64)
    with pytest.raises(PaperError, match="journal_integrity_error"):
        replay(change(bundle, entries=(*bundle.entries[:-1], altered)))
    altered = change(altered, entry_hash=entry_hash(altered))
    with pytest.raises(PaperError, match="journal_state_mismatch"):
        replay(change(bundle, entries=(*bundle.entries[:-1], altered)))
    with pytest.raises(PaperError, match="journal_integrity_error"):
        replay(change(bundle, entries=tuple(reversed(bundle.entries))))


def test_low_decimal_context_does_not_change_replay(paper, make_request, clock):
    submit(paper, make_request())
    fill(paper, clock)
    bundle = paper[1].export_replay(workspace_id=WS)
    expected = replay(bundle)
    with localcontext() as context:
        context.prec = 2
        assert replay(bundle) == expected


def test_returned_state_and_journal_are_detached(paper, make_request, clock):
    submit(paper, make_request())
    fill(paper, clock)
    original = paper[2].state
    altered = paper[2].state
    altered.orders[0].fills.clear()
    altered.cost_basis.clear()
    assert paper[2].state == original


def test_local_only(paper, portfolio, config, clock):
    with pytest.raises(PaperError, match="local_only"):
        LocalPaperVenue(
            environment="production",
            account_id="x",
            initial_portfolio=portfolio,
            config=config,
            risk=paper[0],
            clock=clock,
        )


def test_fee_and_realized_pnl_on_complete_sale(
    build_session, portfolio, registration, controls, clock, config, make_request
):
    position = Position(
        instrument_id=BTC,
        quantity=Quantity(value="2", asset="BTC"),
        average_entry_price=Price(value="80", base="BTC", quote="USD"),
        mark_price=Price(value="100", base="BTC", quote="USD"),
        realized_pnl=money(0),
        unrealized_pnl=money(40),
        network="crypto",
    )
    initial = change(
        portfolio,
        cash=money(800),
        positions=[position],
        gross_exposure=money(200),
        net_exposure=money(200),
        unrealized_pnl=money(40),
    )
    registration = change(registration, execution=change(registration.execution, slippage_bps="0"))
    risk = build_session(portfolio=initial, registrations=(registration,))
    venue = LocalPaperVenue(
        environment="local",
        account_id=controls.account_id,
        initial_portfolio=initial,
        config=config,
        risk=risk,
        clock=clock,
    )
    broker = LocalPaperBroker(workspace_id=WS, venue=venue)
    request = make_request(amount="200", action="close")
    request = change(
        request,
        market=change(
            request.market,
            book=change(request.market.book, bid_price=Price(value="100", base="BTC", quote="USD")),
        ),
    )
    submit((risk, venue, broker), request)
    clock.now += timedelta(milliseconds=100)
    broker.observe(change(book(clock), bids=(PaperLevel(price="100", quantity="2"),)))
    state = broker.state
    assert state.orders[0].status is OrderStatus.FILLED
    assert state.cost_basis[BTC.value].amount == 0
    assert state.portfolio.positions == []
    assert state.portfolio.cash.amount == Decimal("999.8")
    assert state.portfolio.realized_pnl_today.amount == Decimal("39.8")
    assert state.portfolio.unrealized_pnl.amount == 0


def test_capacity_preserves_dedupe(build_session, portfolio, controls, config, clock, make_request):
    risk = build_session()
    venue = LocalPaperVenue(
        environment="local",
        account_id=controls.account_id,
        initial_portfolio=portfolio,
        config=config,
        risk=risk,
        clock=clock,
        capacity=1,
    )
    first, second = make_request(), make_request(2)
    risk.evaluate(first)
    risk.evaluate(second)
    order = venue.submit(
        workspace_id=WS, order_intent_id=first.intent.order_intent_id, fencing_token=1
    )
    with pytest.raises(PaperError, match="capacity"):
        venue.submit(
            workspace_id=WS, order_intent_id=second.intent.order_intent_id, fencing_token=1
        )
    assert (
        venue.submit(workspace_id=WS, order_intent_id=first.intent.order_intent_id, fencing_token=1)
        == order
    )
    assert (
        risk.handoff(
            workspace_id=WS, order_intent_id=second.intent.order_intent_id, fencing_token=1
        )
        is not None
    )


def test_telemetry_excludes_financial_values(paper, make_request, clock):
    with capture_logs() as logs:
        submit(paper, make_request())
        fill(paper, clock)
        paper[2].reconcile()
    paper_logs = [entry for entry in logs if entry["event"].startswith("paper_")]
    assert paper_logs
    assert all(
        set(entry) <= {"event", "log_level", "kind", "fill_count", "discovered_fill_count"}
        for entry in paper_logs
    )


@pytest.mark.property
@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(cents=st.integers(100, 25000), depth_units=st.integers(1, 100000))
def test_approved_bounds_and_accounting_property(
    build_session, portfolio, controls, config, clock, make_request, cents, depth_units
):
    clock.now = portfolio.as_of
    risk = build_session()
    venue = LocalPaperVenue(
        environment="local",
        account_id=controls.account_id,
        initial_portfolio=portfolio,
        config=config,
        risk=risk,
        clock=clock,
    )
    broker = LocalPaperBroker(workspace_id=WS, venue=venue)
    request = make_request(amount=str(Decimal(cents) / 100))
    record = risk.evaluate(request)
    order = broker.submit(order_intent_id=request.intent.order_intent_id, fencing_token=1)
    if order is None:
        assert not record.evaluation.is_approved
        return
    clock.now += timedelta(milliseconds=100)
    broker.observe(book(clock, quantity=str(Decimal(depth_units) / 10000)))
    state, order = broker.state, broker.state.orders[0]
    gross = sum((item.notional.amount for item in order.fills), Decimal(0))
    assert gross <= record.evaluation.approved_notional.amount
    assert order.filled_quantity.value <= record.max_quantity.value
    assert gross + order.fees_paid.amount <= record.max_cash_debit.amount
    assert state.portfolio.cash.amount == portfolio.cash.amount - gross - order.fees_paid.amount
    assert state.portfolio.cash.amount >= 0
    assert (
        state.portfolio.equity.amount
        == state.portfolio.cash.amount + state.portfolio.gross_exposure.amount
    )
    assert content_hash(replay(venue.export_replay(workspace_id=WS))) == content_hash(state)
