import json
from pathlib import Path

import pytest
from kavrigo_evals.contracts import GoldenDataset
from kavrigo_evals.runner import evaluate, run_case
from pydantic import ValidationError

DATASET = GoldenDataset.model_validate_json(
    (Path(__file__).parents[1] / "datasets/golden-v1.json").read_text()
)


@pytest.mark.parametrize("case", DATASET.cases, ids=lambda case: case.case_id)
async def test_golden_boundaries(case):
    result = await run_case(case)
    assert result.passed, result.model_dump()


async def test_report_reproducible_and_failure_is_not_hidden():
    first = await evaluate(DATASET, "0" * 40)
    second = await evaluate(DATASET, "0" * 40)
    assert first == second
    assert first.passed
    assert {r.category for r in first.results} == {"extraction", "injection", "decision"}
    wrong = DATASET.model_dump(mode="json")
    wrong["cases"][0]["expected_calls"] = 0
    failed = await evaluate(GoldenDataset.model_validate(wrong), "0" * 40)
    assert failed.dataset_hash != first.dataset_hash
    assert not failed.passed
    assert failed.results[0].checks["model_calls"] is False
    serialized = first.model_dump_json()
    assert "synthetic-secret-sentinel" not in serialized
    assert "model_reply" not in serialized


def test_dataset_refuses_duplicate_ids_and_extra_contract_fields():
    data = json.loads(DATASET.model_dump_json())
    data["cases"].append(data["cases"][0])
    with pytest.raises(ValidationError, match="unique"):
        GoldenDataset.model_validate(data)
    with pytest.raises(ValidationError):
        GoldenDataset.model_validate({**data, "execute": True})
