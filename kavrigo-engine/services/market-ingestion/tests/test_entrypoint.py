"""Sampling is explicit, local, time bounded, and disabled by default."""

import pytest

from kavrigo_market_ingestion import __main__ as entrypoint


async def test_default_mode_only_inspects_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAVRIGO_INGESTION_SAMPLE_SECONDS", raising=False)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    await entrypoint._run()


@pytest.mark.parametrize(
    ("environment", "duration"),
    [("production", "1"), ("local", "0"), ("local", "61"), ("local", "NaN")],
)
async def test_sample_refuses_unsafe_configuration(
    monkeypatch: pytest.MonkeyPatch, environment: str, duration: str
) -> None:
    monkeypatch.setenv("KAVRIGO_ENV", environment)
    monkeypatch.setenv("KAVRIGO_INGESTION_SAMPLE_SECONDS", duration)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    with pytest.raises(SystemExit, match=r"local mode|1\.\.60"):
        await entrypoint._run()


async def test_live_execution_flag_is_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    with pytest.raises(SystemExit, match="refused"):
        await entrypoint._run()
