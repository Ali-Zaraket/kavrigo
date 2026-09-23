"""Frozen Parquet catalog objects are bounded, hash-verified and schema-exact."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from kavrigo_backtest import (
    BAR_PARQUET_SCHEMA,
    LocalParquetBarCatalog,
    ParquetBarDatasetRef,
    parquet_bytes_hash,
)
from kavrigo_domain import InstrumentId

AT = datetime(2026, 1, 1, tzinfo=UTC)
BTC = InstrumentId.parse("BTC-USDT.BINANCE")


def _rows(count: int = 12) -> list[dict[str, object]]:
    return [
        {
            "instrument_id": BTC.value,
            "interval_seconds": 900,
            "open": Decimal(100 + index),
            "high": Decimal(101 + index),
            "low": Decimal(99 + index),
            "close": Decimal("100.5") + index,
            "volume": Decimal("10.000000"),
            "event_time": AT + timedelta(minutes=15 * index),
            "ingested_at": AT + timedelta(minutes=15 * index, seconds=1),
        }
        for index in range(count)
    ]


def _write(path: Path, *, schema: pa.Schema = BAR_PARQUET_SCHEMA) -> bytes:
    pq.write_table(pa.Table.from_pylist(_rows(), schema=schema), path)
    return path.read_bytes()


def _reference(payload: bytes, **updates: object) -> ParquetBarDatasetRef:
    values: dict[str, object] = {
        "object_key": "fixtures/btc.parquet",
        "content_hash": parquet_bytes_hash(payload),
        "row_count": 12,
        "instrument_id": BTC,
        "interval_seconds": 900,
    }
    values.update(updates)
    return ParquetBarDatasetRef(**values)  # type: ignore[arg-type]


def test_catalog_loads_the_exact_hash_verified_object(tmp_path: Path) -> None:
    target = tmp_path / "fixtures" / "btc.parquet"
    target.parent.mkdir()
    reference = _reference(_write(target))

    bars = LocalParquetBarCatalog(tmp_path).load(reference)

    assert len(bars) == 12
    assert bars[0].instrument_id == BTC
    assert bars[-1].ingested_at == AT + timedelta(minutes=165, seconds=1)


def test_catalog_rejects_bytes_changed_after_the_reference_was_frozen(tmp_path: Path) -> None:
    target = tmp_path / "fixtures" / "btc.parquet"
    target.parent.mkdir()
    reference = _reference(_write(target))
    target.write_bytes(target.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="content hash mismatch"):
        LocalParquetBarCatalog(tmp_path).load(reference)


def test_catalog_rejects_a_noncanonical_schema(tmp_path: Path) -> None:
    target = tmp_path / "fixtures" / "btc.parquet"
    target.parent.mkdir()
    fields = [
        pa.field("volume", pa.float64(), nullable=False) if field.name == "volume" else field
        for field in BAR_PARQUET_SCHEMA
    ]
    rows = _rows()
    for row in rows:
        row["volume"] = 10.0
    schema = pa.schema(fields)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), target)
    reference = _reference(target.read_bytes())

    with pytest.raises(ValueError, match="schema mismatch"):
        LocalParquetBarCatalog(tmp_path).load(reference)


def test_catalog_rejects_manifest_row_count_drift(tmp_path: Path) -> None:
    target = tmp_path / "fixtures" / "btc.parquet"
    target.parent.mkdir()
    reference = _reference(_write(target), row_count=13)

    with pytest.raises(ValueError, match="row count mismatch"):
        LocalParquetBarCatalog(tmp_path).load(reference)


@pytest.mark.parametrize(
    "key",
    [
        "../btc.parquet",
        "/outside/catalog.parquet",
        "fixtures/btc.csv",
        "fixtures//btc.parquet",
        "a\\b.parquet",
    ],
)
def test_catalog_reference_cannot_select_an_arbitrary_host_path(key: str) -> None:
    with pytest.raises(ValidationError):
        _reference(b"fixture", object_key=key)
