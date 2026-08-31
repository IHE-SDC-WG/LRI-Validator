from __future__ import annotations

import json

import pytest

from lri_validator.content import decode_hl7, extract_content, normalize_site
from tests.support import CONTENT_FIXTURES, VALID


@pytest.mark.parametrize(
    "name,expected",
    [
        ("breast-ecp.hl7", ("C504", "8500", "3", "2", "2", "breast")),
        ("prostate-segmented.hl7", ("C619", "8140", "3", None, "3", "prostate")),
        ("heme-narrative.hl7", ("C421", "9732", "3", None, None, None)),
    ],
)
def test_extracts_codes_across_report_styles(name: str, expected: tuple[str | None, ...]) -> None:
    group = extract_content((CONTENT_FIXTURES / name).read_text()).groups[0]
    assert (group.site, group.histology, group.behavior, group.laterality, group.grade, group.template_key) == expected
    assert group.year == "2026"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("breast-synoptic-summary.hl7", ("C504", "8500", "3")),
        ("cap-ecp.hl7", ("C504", "8500", "3")),
        ("structured-narrative.hl7", ("C504", "8500", "3")),
        ("synoptic-segmented.hl7", ("C619", "8140", "3")),
        ("synoptic-summary.hl7", ("C504", "8500", "3")),
        ("unstructured-narrative.hl7", ("C421", "9732", "3")),
    ],
)
def test_every_bundled_example_has_seer_inputs(name: str, expected: tuple[str, str, str]) -> None:
    group = extract_content((VALID / name).read_text()).groups[0]
    assert (group.site, group.histology, group.behavior) == expected


def test_unstructured_narrative_uses_structured_specimen_site() -> None:
    value = (VALID / "unstructured-narrative.hl7").read_text()
    assert "Primary Site" not in value
    group = extract_content(value).groups[0]
    assert group.site == "C421"
    assert group.site_line == 7


def test_icdo_site_can_come_from_specimen_type() -> None:
    lines = (VALID / "unstructured-narrative.hl7").read_text().splitlines()
    specimen_index = next(index for index, line in enumerate(lines) if line.startswith("SPM|"))
    fields = lines[specimen_index].split("|")
    fields[4] = "C42.1^Bone marrow specimen^ICD-O-3"
    fields[8] = ""
    lines[specimen_index] = "|".join(fields)
    group = extract_content("\n".join(lines) + "\n").groups[0]
    assert group.site == "C421"
    assert group.site_line == 7


def test_decodes_supported_hl7_escapes() -> None:
    assert decode_hl7("one\\.br\\two\\F\\three\\S\\four\\T\\five\\R\\six\\E\\seven") == "one\ntwo|three^four&five~six\\seven"


def test_site_normalization_and_nos_flag() -> None:
    assert normalize_site("C50.4") == ("C504", False)
    assert normalize_site("C504") == ("C504", False)
    assert normalize_site("C50") == ("C509", True)
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("C50.4", "C50")
    group = extract_content(value).groups[0]
    assert group.site == "C509"
    assert group.site_assumed_nos is True


def test_conflicting_candidates_are_skipped() -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace(
        "Histologic Type: Invasive carcinoma",
        "Primary Site: Prostate (C61.9)\\.br\\Histologic Type: Invasive carcinoma",
    )
    group = extract_content(value).groups[0]
    assert group.site is None
    assert ("site", 9) in group.conflicts


def test_spm_year_precedes_obr_year() -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("202608270900-0400", "202508270900-0400", 1)
    group = extract_content(value).groups[0]
    assert group.year == "2026"
    assert group.year_line == 10
    assert group.year_source == "SPM-17"


def test_two_order_groups_remain_separate() -> None:
    extraction = extract_content((CONTENT_FIXTURES / "two-group-mph.hl7").read_text())
    assert [(group.site, group.laterality) for group in extraction.groups] == [("C504", "2"), ("C501", "1")]


def test_extraction_summary_omits_arbitrary_message_text() -> None:
    value = (CONTENT_FIXTURES / "poison.hl7").read_text()
    summary = json.dumps(extract_content(value).to_dict())
    assert "ZZPOISONZZ" not in summary
    assert "C504" in summary
