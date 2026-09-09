from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event

import pytest

from kavrigo_domain import OrderStatus
from kavrigo_paper import LocalPaperVenue, PaperError, PaperLevel, replay
from kavrigo_paper import account as account_module
from kavrigo_paper.ledger import Ledger

from .conftest import BTC, ETH, WS, change, money
from .test_paper import book, fill, submit
from .test_paper import config as config
from .test_paper import paper as paper


def test_control_change_serializes_with_fill(paper, make_request, clock, controls, monkeypatch):
    submit(paper, make_request())
    entered, release, updating = Event(), Event(), Event()
    original = Ledger._fill_level

    def paused_fill(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    def change_controls():
        updating.set()
        paper[0].update_controls(change(controls, version=2, fencing_token=2))

    monkeypatch.setattr(Ledger, "_fill_level", paused_fill)
    clock.now += timedelta(milliseconds=100)
    with ThreadPoolExecutor(max_workers=2) as pool:
        matching = pool.submit(paper[1].observe, workspace_id=WS, book=book(clock))
        try:
            assert entered.wait(5)
            update = pool.submit(change_controls)
            assert updating.wait(5)
            with pytest.raises(TimeoutError):
                update.result(timeout=0.1)
        finally:
            release.set()
        matching.result(timeout=5)
        update.result(timeout=5)
    paper[2].reconcile()
    order = paper[2].state.orders[0]
    assert order.status is OrderStatus.FILLED
    assert not paper[0].execution_allowed(
        workspace_id=WS, order_intent_id=order.order_intent_id, fencing_token=1
    )


def test_advancing_clock_records_submit_after_risk_issuance(
    build_session, portfolio, config, clock, make_request
):
    request = make_request()

    def advancing_clock():
        clock.now += timedelta(microseconds=1)
        return clock.now

    risk = build_session(clock=advancing_clock)
    venue = LocalPaperVenue(
        environment="local",
        account_id="paper-account-one",
        initial_portfolio=portfolio,
        config=config,
        risk=risk,
        clock=advancing_clock,
    )
    risk.evaluate(request)
    order = venue.submit(
        workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=1
    )
    entry = venue.export_replay(workspace_id=WS).entries[0]
    assert order.status is OrderStatus.SUBMITTED
    assert entry.command.at > entry.command.permit.approval.approved_at


def test_replay_binds_configuration_header(paper, make_request):
    submit(paper, make_request())
    bundle = paper[1].export_replay(workspace_id=WS)
    with pytest.raises(PaperError, match="journal_integrity_error"):
        replay(change(bundle, config=change(bundle.config, latency_ms=0)))


def test_full_journal_rejects_fill_atomically_and_keeps_recovery(
    paper, make_request, clock, monkeypatch
):
    order = submit(paper, make_request())
    before = paper[1].export_replay(workspace_id=WS)
    monkeypatch.setattr(
        account_module, "MAX_ARTIFACT_BYTES", len(before.model_dump_json().encode("utf-8")) + 50
    )
    clock.now += timedelta(milliseconds=100)
    with pytest.raises(PaperError, match="journal_size_exhausted"):
        paper[2].observe(book(clock))
    assert paper[1].export_replay(workspace_id=WS) == before
    paper[2].reconcile()
    assert paper[2].state.orders == (order,)
    assert paper[2].state.portfolio.cash.amount == 1000


def test_diagnostic_failure_after_fill_recovers_without_second_fill(
    paper, make_request, clock, monkeypatch
):
    submit(paper, make_request())

    def failed_hook(*args):
        raise RuntimeError("diagnostic hook failed")

    monkeypatch.setattr(paper[1]._telemetry, "committed", failed_hook)
    clock.now += timedelta(milliseconds=100)
    observation = book(clock)
    with pytest.raises(RuntimeError, match="diagnostic hook failed"):
        paper[2].observe(observation)
    assert not paper[2].state.portfolio.is_reconciled
    assert len(paper[2].reconcile().discovered_fill_ids) == 1
    before = paper[2].state
    paper[2].observe(observation)
    assert paper[2].state == before


@pytest.mark.parametrize("failure", ["future", "increment"])
def test_invalid_book_never_mutates_ledger(paper, make_request, clock, failure):
    submit(paper, make_request())
    before = paper[1].export_replay(workspace_id=WS)
    observation = book(clock)
    if failure == "future":
        observation = change(observation, received_at=clock() + timedelta(seconds=1))
    else:
        observation = change(observation, asks=(PaperLevel(price="100.10001", quantity="1"),))
    with pytest.raises(PaperError, match="invalid_market"):
        paper[2].observe(observation)
    assert paper[1].export_replay(workspace_id=WS) == before


def test_other_asset_update_does_not_freshen_held_mark(paper, make_request, clock):
    submit(paper, make_request())
    fill(paper, clock)
    previous = paper[2].state.mark_times[BTC.value]
    clock.now += timedelta(seconds=3)
    paper[2].observe(book(clock, instrument=ETH))
    assert paper[2].state.mark_times[BTC.value] == previous
    assert not paper[2].state.portfolio.is_reconciled
    paper[2].observe(book(clock, sequence=2))
    assert paper[2].state.portfolio.is_reconciled


def test_invalid_initial_pnl_is_not_silently_rewritten(build_session, portfolio, config, clock):
    with pytest.raises(PaperError, match="inconsistent_initial_unrealized_pnl"):
        LocalPaperVenue(
            environment="local",
            account_id="paper-account-one",
            initial_portfolio=change(portfolio, unrealized_pnl=money(1)),
            config=config,
            risk=build_session(),
            clock=clock,
        )


def test_simulator_minimum_rejects_without_fill(
    build_session, portfolio, config, clock, make_request
):
    config = change(
        config,
        instruments=tuple(change(item, minimum_notional_usd="200") for item in config.instruments),
    )
    risk = build_session()
    venue = LocalPaperVenue(
        environment="local",
        account_id="paper-account-one",
        initial_portfolio=portfolio,
        config=config,
        risk=risk,
        clock=clock,
    )
    request = make_request()
    risk.evaluate(request)
    order = venue.submit(
        workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=1
    )
    assert order.status is OrderStatus.REJECTED
    clock.now += timedelta(milliseconds=100)
    venue.observe(workspace_id=WS, book=book(clock))
    _, state = venue.read(workspace_id=WS)
    assert not state.orders[0].fills
    assert state.portfolio.cash.amount == 1000


def test_unissued_approval_is_not_executable(paper, make_request):
    request = make_request()
    assert paper[0].evaluate(request).evaluation.is_approved
    assert not paper[0].execution_allowed(
        workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=1
    )
