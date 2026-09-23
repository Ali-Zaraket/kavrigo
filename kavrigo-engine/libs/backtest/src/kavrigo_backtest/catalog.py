"""Frozen local Parquet catalog boundary for deterministic backtests.

Production catalog objects belong in immutable object storage. This local implementation keeps
the same trust boundary: run definitions carry only a relative object key and a byte hash, while
the service owns the catalog root and reads the exact bytes it verifies.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol, Self, runtime_checkable

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import Field, model_validator

from kavrigo_backtest.fixture import BacktestBar, InlineBarDataset, bar_dataset_hash
from kavrigo_domain import DomainModel, InstrumentId

__all__ = [
    "BAR_PARQUET_SCHEMA",
    "BarCatalog",
    "LocalParquetBarCatalog",
    "ParquetBarDatasetRef",
    "parquet_bytes_hash",
]

MAX_CATALOG_FILE_BYTES = 128 * 1024 * 1024

BAR_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("interval_seconds", pa.int64(), nullable=False),
        pa.field("open", pa.decimal128(38, 18), nullable=False),
        pa.field("high", pa.decimal128(38, 18), nullable=False),
        pa.field("low", pa.decimal128(38, 18), nullable=False),
        pa.field("close", pa.decimal128(38, 18), nullable=False),
        pa.field("volume", pa.decimal128(38, 18), nullable=False),
        pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


def parquet_bytes_hash(payload: bytes) -> str:
    """Hash the exact stored object, including Parquet metadata and encoding."""
    return "sha256:" + sha256(payload).hexdigest()


class ParquetBarDatasetRef(DomainModel):
    """Immutable reference resolved only inside a service-owned catalog root."""

    format: Literal["parquet-bars-v1"] = "parquet-bars-v1"
    object_key: Annotated[
        str,
        Field(
            min_length=9,
            max_length=256,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*\.parquet$",
        ),
    ]
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    row_count: Annotated[int, Field(strict=True, ge=12, le=5_000)]
    instrument_id: InstrumentId
    interval_seconds: Annotated[int, Field(strict=True, ge=60, le=86_400)]

    @model_validator(mode="after")
    def _safe_key(self) -> Self:
        key = PurePosixPath(self.object_key)
        if (
            "\\" in self.object_key
            or "//" in self.object_key
            or key.is_absolute()
            or any(part in {"", ".", ".."} for part in key.parts)
            or key.suffix != ".parquet"
        ):
            raise ValueError("catalog object key must be a relative .parquet path")
        return self


@runtime_checkable
class BarCatalog(Protocol):
    def load(self, reference: ParquetBarDatasetRef) -> tuple[BacktestBar, ...]: ...


class LocalParquetBarCatalog:
    """Read one verified object without allowing run input to select an arbitrary host path."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve(strict=True)
        if not self._root.is_dir():
            raise ValueError("catalog root must be a directory")

    def load(self, reference: ParquetBarDatasetRef) -> tuple[BacktestBar, ...]:
        candidate = (self._root / Path(*PurePosixPath(reference.object_key).parts)).resolve(
            strict=True
        )
        if self._root not in candidate.parents or not candidate.is_file():
            raise ValueError("catalog object resolves outside the configured root")
        # Verify and parse one in-memory byte string so a concurrent file replacement cannot
        # create a hash-check/read time-of-check-time-of-use gap.
        with candidate.open("rb") as stream:
            payload = stream.read(MAX_CATALOG_FILE_BYTES + 1)
        if len(payload) > MAX_CATALOG_FILE_BYTES:
            raise ValueError("catalog object exceeds the local read bound")
        if parquet_bytes_hash(payload) != reference.content_hash:
            raise ValueError("catalog object content hash mismatch")

        try:
            parquet = pq.ParquetFile(
                pa.BufferReader(payload),
                page_checksum_verification=True,
                thrift_string_size_limit=16 * 1024 * 1024,
                thrift_container_size_limit=100_000,
            )
            if parquet.metadata.num_rows != reference.row_count:
                raise ValueError("catalog object row count mismatch")
            if not parquet.schema_arrow.equals(BAR_PARQUET_SCHEMA, check_metadata=False):
                raise ValueError("catalog object schema mismatch")
            table = parquet.read(columns=BAR_PARQUET_SCHEMA.names, use_threads=False)
        except pa.ArrowException as error:
            raise ValueError("catalog object is not valid Parquet") from error
        values = table.to_pylist()
        for row in values:
            row["instrument_id"] = InstrumentId.parse(row["instrument_id"])
        rows = tuple(BacktestBar.model_validate(row) for row in values)
        if len(rows) != reference.row_count:
            raise ValueError("catalog object returned an incomplete row set")
        if any(
            bar.instrument_id != reference.instrument_id
            or bar.interval_seconds != reference.interval_seconds
            for bar in rows
        ):
            raise ValueError("catalog object metadata does not match its reference")

        # Reuse the canonical ordering and uniqueness checks applied to inline fixtures.
        validated = InlineBarDataset(bars=rows, content_hash=bar_dataset_hash(rows))
        return validated.bars
