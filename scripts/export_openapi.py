"""Export/check the web contract without a running database or provider credentials."""

import argparse
import json
from pathlib import Path

from kavrigo_api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = (
        Path(__file__).resolve().parents[1] / "kavrigo-platform/apps/web/contracts/openapi.json"
    )
    schema = create_app().openapi()
    if args.check:
        if json.loads(target.read_text(encoding="utf-8")) != schema:
            raise SystemExit("OpenAPI snapshot differs; run scripts/export_openapi.py")
    else:
        target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
