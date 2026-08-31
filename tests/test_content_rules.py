from __future__ import annotations

import copy

from lri_validator import validate_content
from lri_validator.seer import MemoryCache
from tests.support import CONTENT_FIXTURES, FixtureTransport, VALID, apply_content_case


def rule_ids(report) -> set[str]:
    return {finding.rule_id for finding in report.findings}


def check(value: str, transport=None):
    return validate_content(
        value,
        transport=transport or FixtureTransport(),
        cache=MemoryCache(),
        syntax_valid=True,
    )


def test_breast_content_passes_complete_online_checks() -> None:
    report = check((VALID / "breast-synoptic-summary.hl7").read_text())
    assert report.status == "complete"
    assert report.valid
    assert report.counts == {"error": 0, "warning": 0, "information": 1}
    assert rule_ids(report) == {"CONTENT-RECODE-01"}


def test_invalid_site_histology_combination_is_an_error() -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("C50.4", "C99.9").replace("8500/3", "1234/3")
    report = check(value)
    assert "CONTENT-COMBO-01" in rule_ids(report)
    assert not report.valid


def test_schema_and_dictionary_field_domains() -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("8500/3", "8500/8")
    report = check(value)
    assert "CONTENT-FIELD-01" in rule_ids(report)
    assert "CONTENT-COMBO-01" not in rule_ids(report)

    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("Laterality: Left", "Laterality: 8").replace(
        "7771000^Left^SCT", "8^8^NAACCR"
    )
    assert "CONTENT-DICT-01" in rule_ids(check(value))

    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("Histologic Grade: G2", "Histologic Grade: 8")
    report = check(value)
    assert "CONTENT-FIELD-03" in rule_ids(report)
    assert "CONTENT-DICT-01" not in rule_ids(report)


def test_missing_non_default_schema_input_is_reported() -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("8500/3", "8500")
    report = check(value)
    assert "CONTENT-FIELD-02" in rule_ids(report)
    assert report.status == "complete"


def test_template_site_schema_and_recode_mismatches() -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("Breast Invasive Resection", "Prostate Resection")
    rules = rule_ids(check(value))
    assert {"CONTENT-SITE-01", "CONTENT-COMBO-03", "CONTENT-RECODE-02"} <= rules


def test_multiple_schema_result_is_partial() -> None:
    value = (CONTENT_FIXTURES / "prostate-segmented.hl7").read_text()
    value = value.replace("Prostate Resection", "Lung Resection").replace("C61.9", "C34.9")
    value = value.replace("202608270900-0400", "", 1).replace("202608270900-0400", "", 1)
    report = check(value)
    assert "CONTENT-COMBO-02" in rule_ids(report)
    assert report.status == "partial"


def test_hematopoietic_exact_match_unknown_code_and_year() -> None:
    value = (CONTENT_FIXTURES / "heme-narrative.hl7").read_text()
    report = check(value)
    assert "CONTENT-HEME-01" not in rule_ids(report)
    assert report.status == "complete"

    unknown = value.replace("9732/3", "9999/3")
    assert {"CONTENT-COMBO-01", "CONTENT-HEME-01"} <= rule_ids(check(unknown))

    class FutureValidityTransport(FixtureTransport):
        def __call__(self, method, url, body):
            status, data = super().__call__(method, url, body)
            if "/disease/latest/id/" in url:
                data = copy.deepcopy(data)
                data["valid"] = {"start": 2030}
            return status, data

    assert "CONTENT-HEME-02" in rule_ids(check(value, FutureValidityTransport()))
    assert "CONTENT-HEME-02" in rule_ids(check(apply_content_case("heme-year-invalid")))


def test_multiple_primary_pair_is_checked() -> None:
    report = check((CONTENT_FIXTURES / "two-group-mph.hl7").read_text())
    mph = [finding for finding in report.findings if finding.rule_id == "CONTENT-MPH-01"]
    assert len(mph) == 1
    assert "MULTIPLE_PRIMARIES" in mph[0].message


def test_api_failures_resolve_to_partial_report() -> None:
    report = check((VALID / "breast-synoptic-summary.hl7").read_text(), lambda _method, _url, _body: (401, {}))
    assert report.status == "partial"
    assert report.valid is True
    assert [finding.rule_id for finding in report.findings].count("CONTENT-API-01") == 1


def test_ambiguity_stays_local_and_is_not_sent() -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace(
        "Histologic Type: Invasive carcinoma",
        "Primary Site: Prostate (C61.9)\\.br\\Histologic Type: Invasive carcinoma",
    )
    transport = FixtureTransport()
    report = check(value, transport)
    assert "CONTENT-EXTRACT-01" in rule_ids(report)
    assert all(not (body and "site" in body) for _method, _url, body in transport.calls)
