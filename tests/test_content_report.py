from __future__ import annotations

import json

import pytest

from lri_validator import validate_content
from lri_validator.seer import MemoryCache
from tests.support import CONTENT_FIXTURES, FixtureTransport, VALID, apply_content_case


@pytest.mark.parametrize("path", sorted(VALID.glob("*.hl7")), ids=lambda path: path.name)
def test_every_bundled_example_completes_seer_fixture_check(path) -> None:
    report = validate_content(
        path.read_text(),
        transport=FixtureTransport(),
        cache=MemoryCache(),
        syntax_valid=True,
    )
    assert report.status == "complete"
    assert report.valid is True
    assert report.queries


def test_content_report_contract_and_poison_boundary() -> None:
    report = validate_content(
        (CONTENT_FIXTURES / "poison.hl7").read_text(),
        transport=FixtureTransport(),
        cache=MemoryCache(),
        syntax_valid=True,
    )
    data = report.to_dict()
    assert set(data) == {
        "schema_version", "content_ruleset_version", "profile", "based_on", "status", "valid",
        "counts", "findings", "extraction", "queries", "coverage_notices", "attribution",
    }
    serialized = json.dumps(data)
    assert "ZZPOISONZZ" not in serialized
    assert "C504" in serialized
    assert "Surveillance, Epidemiology, and End Results" in data["attribution"]


def test_missing_key_is_partial_not_pass(monkeypatch) -> None:
    monkeypatch.setattr("lri_validator.content_rules.load_api_key", lambda: (None, None))
    report = validate_content((VALID / "breast-synoptic-summary.hl7").read_text(), syntax_valid=True)
    assert report.status == "partial"
    assert report.valid is True
    assert any(finding.rule_id == "CONTENT-API-01" for finding in report.findings)
    assert report.queries == ()


def test_no_extractable_codes_is_not_applicable(monkeypatch) -> None:
    monkeypatch.setattr("lri_validator.content_rules.load_api_key", lambda: (None, None))
    report = validate_content(apply_content_case("no-extractable-site"), syntax_valid=True)
    assert report.status == "not-applicable"
    assert report.valid is True
    assert not any(finding.rule_id == "CONTENT-API-01" for finding in report.findings)
