from __future__ import annotations

import json

import pytest

from lri_validator import UnsupportedInputError, validate_message
from tests.support import CASES, NEGATIVE, VALID, apply_case


EXPECTED_STYLES = {
    "breast-synoptic-summary.hl7": "synoptic summary",
    "unstructured-narrative.hl7": "unstructured narrative",
    "structured-narrative.hl7": "structured narrative",
    "synoptic-summary.hl7": "synoptic summary",
    "synoptic-segmented.hl7": "synoptic segmented",
    "cap-ecp.hl7": "CAP eCP",
}

INVALID_EXAMPLES = {
    "invalid-ecp-link.hl7": "ECP-003",
    "invalid-message-type.hl7": "LRI-15",
    "invalid-missing-specimen.hl7": "STRUCTURE-001",
}


@pytest.mark.parametrize("name,style", EXPECTED_STYLES.items())
def test_valid_synthetic_styles(name: str, style: str) -> None:
    report = validate_message((VALID / name).read_text())
    assert report.valid
    assert report.detected_report_style == style
    assert report.counts["error"] == 0


@pytest.mark.parametrize("name,rule_id", INVALID_EXAMPLES.items())
def test_invalid_synthetic_examples(name: str, rule_id: str) -> None:
    report = validate_message((NEGATIVE / name).read_text())
    assert not report.valid
    assert rule_id in {finding.rule_id for finding in report.findings}


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_negative_catalog(case: dict[str, object]) -> None:
    report = validate_message(apply_case(case))
    actual = {finding.rule_id for finding in report.findings}
    assert set(case["expected"]).issubset(actual)
    if any(finding.severity == "error" and finding.rule_id in case["expected"] for finding in report.findings):
        assert not report.valid
    for prefix in case.get("absent_locations", ()):
        assert not [finding for finding in report.findings if finding.location.startswith(prefix)]


def _case_findings(name: str) -> dict[tuple[str, str], str]:
    report = validate_message(apply_case(next(case for case in CASES if case["name"] == name)))
    return {(finding.rule_id, finding.location): finding.message for finding in report.findings}


@pytest.mark.parametrize("name,rule_id,location,fragments", [
    ("cnn-caret-separators", "LRI-NAACCR-02", "OBR-32.1.11", ["is empty", "&-separated inside OBR-32.1", "^ starts the next OBR-32 component"]),
    ("cnn-caret-separators", "LRI-NAACCR-01", "OBR-32.1.10", ["CNN.10 (assigning authority universal ID) is empty."]),
    ("cnn-type-in-namespace", "LRI-NAACCR-02", "OBR-32.1.11", ["CNN.9 is valued but CNN.10 and CNN.11 are empty", "type belongs in CNN.11 and the ID in CNN.10"]),
    ("invalid-cnn-type", "LRI-NAACCR-02", "OBR-32.1.11", ["CNN.11 (assigning authority universal ID type) holds an unsupported value; it must be NPI, MD, or ISO."]),
    ("invalid-cnn-npi", "LRI-NAACCR-01", "OBR-32.1.10", ["CNN.10 is not a valid NPI as CNN.11 NPI requires."]),
    ("hd-namespace-only", "COMPONENT-R", "ORC-12.9.2", ["ORC-12.9 has no universal ID or type; HD_04 needs namespace&ID&type, e.g. LOCAL&1234567893&NPI."]),
    ("hd-namespace-only", "COMPONENT-R", "OBR-16.9.3", ["OBR-16.9 has no universal ID or type"]),
    ("hd-unsupported-type", "HD04-001", "ORC-12.9.3", ["ORC-12.9.3 is not CLIA, NPI, MD, or ISO."]),
    ("xcn-missing-family-name", "COMPONENT-R", "OBX-16.2", ["OBX-16.2 (family name) is empty; XCN_03 requires it."]),
    ("xcn-degree-sent", "COMPONENT-X", "OBX-16.7", ["OBX-16.7 (degree) is valued; XCN_03 excludes it."]),
    ("msh3-namespace-only", "COMPONENT-R", "MSH-3.2", ["MSH-3 has no universal ID or type; HD_04 needs namespace^ID^type, e.g. LOCAL^2.16.840.1.113883.19.5^ISO."]),
    ("xon-authority-namespace-only", "COMPONENT-R", "ORC-21.6.3", ["ORC-21.6 has no universal ID or type"]),
    ("msh21-not-oid", "LRI-2", "MSH-21.3", ["not an ISO OID"]),
    ("msh21-not-iso", "LRI-3", "MSH-21.4", ["is not ISO"]),
])
def test_identifier_messages(name: str, rule_id: str, location: str, fragments: list[str]) -> None:
    message = _case_findings(name)[(rule_id, location)]
    for fragment in fragments:
        assert fragment in message


def test_identifier_findings_omit_raw_values() -> None:
    report_json = json.dumps(validate_message(apply_case(next(case for case in CASES if case["name"] == "identifier-privacy"))).to_dict())
    assert "SECRET" not in report_json


def test_cnn_hint_is_not_repeated() -> None:
    findings = _case_findings("cnn-type-in-namespace")
    assert "CNN.9" not in findings[("LRI-NAACCR-01", "OBR-32.1.10")]


def test_msh21_errors_no_longer_use_ei03_rule() -> None:
    for name in ("msh21-not-oid", "msh21-not-iso"):
        assert not any(rule_id == "LRI-NAACCR-05" for rule_id, _ in _case_findings(name))


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
