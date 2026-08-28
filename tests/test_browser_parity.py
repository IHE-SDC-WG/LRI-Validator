from __future__ import annotations

import json
import subprocess

import pytest

from lri_validator import validate_message
from tests.support import CASES, ROOT, VALID, apply_case, finding_key


def javascript_validate(value: str) -> dict[str, object]:
    result = subprocess.run(
        ["node", "tests/js_validate.cjs"], cwd=ROOT, input=json.dumps({"text": value}),
        text=True, capture_output=True, check=True,
    )
    response = json.loads(result.stdout)
    assert response["ok"], response.get("error")
    return response["report"]


@pytest.mark.parametrize("path", sorted(VALID.glob("*.hl7")), ids=lambda path: path.name)
def test_valid_fixture_parity(path) -> None:
    value = path.read_text()
    python_report = validate_message(value).to_dict()
    javascript_report = javascript_validate(value)
    assert javascript_report["valid"] == python_report["valid"]
    assert javascript_report["detected_report_style"] == python_report["detected_report_style"]
    assert finding_key(javascript_report) == finding_key(python_report)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_negative_fixture_parity(case: dict[str, object]) -> None:
    value = apply_case(case)
    python_report = validate_message(value).to_dict()
    javascript_report = javascript_validate(value)
    assert javascript_report["valid"] == python_report["valid"]
    assert finding_key(javascript_report) == finding_key(python_report)


def test_unsupported_input_parity() -> None:
    result = subprocess.run(
        ["node", "tests/js_validate.cjs"], cwd=ROOT,
        input=json.dumps({"text": "BHS|^~\\&|batch\rMSH|^~\\&|message\r"}),
        text=True, capture_output=True, check=True,
    )
    assert json.loads(result.stdout)["ok"] is False
