"""PYTHONPATH=kavrigo-research python -m kavrigo_evals --code-revision <sha> --output <path>."""

import argparse
import asyncio
from pathlib import Path

from kavrigo_evals.contracts import GoldenDataset
from kavrigo_evals.runner import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path(__file__).parents[1] / "datasets/golden-v1.json"
    )
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--dirty", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = GoldenDataset.model_validate_json(args.dataset.read_text(encoding="utf-8"))
    report = asyncio.run(evaluate(dataset, args.code_revision, dirty=args.dirty))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    passed = sum(result.passed for result in report.results)
    print(f"Synthetic boundary evals: {passed}/{len(report.results)} passed; {report.dataset_hash}")
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
