from __future__ import annotations

import json
import subprocess

import pytest

from lri_validator import validate_content
from lri_validator.seer import MemoryCache
from tests.support import CONTENT_CASES, CONTENT_FIXTURES, FixtureTransport, ROOT, VALID, apply_content_case, finding_key


CASES = [
    *sorted(VALID.glob("*.hl7")),
    CONTENT_FIXTURES / "prostate-segmented.hl7",
    CONTENT_FIXTURES / "heme-narrative.hl7",
    CONTENT_FIXTURES / "two-group-mph.hl7",
    CONTENT_FIXTURES / "poison.hl7",
]


def javascript_content(value: str) -> dict[str, object]:
    result = subprocess.run(
        ["node", "tests/js_content_validate.cjs"],
        cwd=ROOT,
        input=json.dumps({"text": value}),
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(result.stdout)
    assert response["ok"], response.get("error") + "\n" + response.get("stack", "")
    return response["report"]


def assert_parity(value: str) -> None:
    python_report = validate_content(
        value,
        transport=FixtureTransport(),
        cache=MemoryCache(),
        syntax_valid=True,
    ).to_dict()
    javascript_report = javascript_content(value)
    assert javascript_report["status"] == python_report["status"]
    assert javascript_report["valid"] == python_report["valid"]
    assert javascript_report["counts"] == python_report["counts"]
    assert javascript_report["extraction"] == python_report["extraction"]
    assert finding_key(javascript_report) == finding_key(python_report)
    assert [
        (query["method"], query["url"], query["body"], query["cached"], query["status"])
        for query in javascript_report["queries"]
    ] == [
        (query["method"], query["url"], query["body"], query["cached"], query["status"])
        for query in python_report["queries"]
    ]


@pytest.mark.parametrize("path", CASES, ids=lambda path: path.name)
def test_python_javascript_content_parity(path) -> None:
    assert_parity(path.read_text())


NEGATIVE_CASES = [(case["name"], apply_content_case(case["name"])) for case in CONTENT_CASES]


@pytest.mark.parametrize("_name,value", NEGATIVE_CASES, ids=[name for name, _value in NEGATIVE_CASES])
def test_negative_content_parity(_name: str, value: str) -> None:
    assert_parity(value)
