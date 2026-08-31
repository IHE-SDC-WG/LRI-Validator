from __future__ import annotations

import json

import pytest

from lri_validator import UnsupportedInputError, validate_message
from tests.support import CASES, VALID, apply_case


EXPECTED_STYLES = {
    "breast-synoptic-summary.hl7": "synoptic summary",
    "unstructured-narrative.hl7": "unstructured narrative",
    "structured-narrative.hl7": "structured narrative",
    "synoptic-summary.hl7": "synoptic summary",
    "synoptic-segmented.hl7": "synoptic segmented",
    "cap-ecp.hl7": "CAP eCP",
}


@pytest.mark.parametrize("name,style", EXPECTED_STYLES.items())
def test_valid_synthetic_styles(name: str, style: str) -> None:
    report = validate_message((VALID / name).read_text())
    assert report.valid
    assert report.detected_report_style == style
    assert report.counts["error"] == 0


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_negative_catalog(case: dict[str, object]) -> None:
    report = validate_message(apply_case(case))
    actual = {finding.rule_id for finding in report.findings}
    assert set(case["expected"]).issubset(actual)
    if any(finding.severity == "error" and finding.rule_id in case["expected"] for finding in report.findings):
        assert not report.valid


@pytest.mark.parametrize("value", [
    "FHS|^~\\&|batch\rBHS|^~\\&|batch\rMSH|^~\\&|one\r",
    "MSH|^~\\&|one\rMSH|^~\\&|two\r",
    "\x0bMSH|^~\\&|one\r",
    "",
])
def test_unsupported_input(value: str) -> None:
    with pytest.raises(UnsupportedInputError):
        validate_message(value)


def test_complete_mllp_and_line_endings_are_accepted() -> None:
    value = (VALID / "unstructured-narrative.hl7").read_text().replace("\n", "\r")
    assert validate_message("\x0b" + value + "\x1c\r").valid


def test_report_contract_omits_raw_message_values() -> None:
    value = apply_case(next(case for case in CASES if case["name"] == "invalid-cnn-npi"))
    report_json = json.dumps(validate_message(value).to_dict())
    assert "1234567890" not in report_json
    assert "Bone marrow core biopsy" not in report_json
    assert set(validate_message(value).to_dict()) == {
        "schema_version", "ruleset_version", "profile", "detected_report_style",
        "valid", "counts", "findings", "coverage_notices",
    }
