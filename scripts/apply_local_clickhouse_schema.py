"""Apply the local ClickHouse schema to a loopback test service only."""

from __future__ import annotations

import argparse
import pathlib
import urllib.error
import urllib.parse
import urllib.request


SCHEMA = (
    pathlib.Path(__file__).resolve().parents[1]
    / "kavrigo-infra/local/clickhouse/init/001_schema.sql"
)


def statements(sql: str) -> list[str]:
    """Split this repository's schema after removing its line comments."""
    uncommented = "\n".join(line.partition("--")[0] for line in sql.splitlines())
    return [statement.strip() for statement in uncommented.split(";") if statement.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8123")
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("The local schema bootstrap requires a loopback HTTP origin")

    sql_statements = statements(SCHEMA.read_text(encoding="utf-8"))
    for index, statement in enumerate(sql_statements, start=1):
        request = urllib.request.Request(  # noqa: S310 - URL was restricted to loopback HTTP
            args.url,
            data=statement.encode("utf-8"),
            headers={
                "X-ClickHouse-User": "kavrigo",
                "X-ClickHouse-Key": "kavrigo_local_dev",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(2_000).decode("utf-8", errors="replace")
            raise RuntimeError(f"ClickHouse schema statement {index} failed: {detail}") from exc
    print(f"Applied {len(sql_statements)} local ClickHouse schema statements")


if __name__ == "__main__":
    main()
