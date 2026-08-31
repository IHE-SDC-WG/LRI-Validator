from __future__ import annotations

import json
import os
import subprocess
import sys

from lri_validator import cli
from lri_validator.content_rules import validate_content as real_validate_content
from lri_validator.seer import MemoryCache
from tests.support import FixtureTransport, ROOT, VALID


def run_cli(*args: str, home: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("SEER_API_KEY", None)
    env["HOME"] = home
    return subprocess.run(
        [sys.executable, "-m", "lri_validator.cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_content_flag_adds_envelope_and_missing_key_is_partial(tmp_path) -> None:
    result = run_cli(str(VALID / "breast-synoptic-summary.hl7"), "--content", "--format", "json", home=str(tmp_path))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert set(payload) == {"schema_version", "syntax", "content"}
    assert payload["syntax"]["valid"] is True
    assert payload["content"]["status"] == "partial"
    assert any(finding["rule_id"] == "CONTENT-API-01" for finding in payload["content"]["findings"])


def test_content_is_skipped_after_syntax_errors(tmp_path) -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("|2.5.1|", "|2.3|")
    path = tmp_path / "invalid.hl7"
    path.write_text(value, encoding="utf-8")
    result = run_cli(str(path), "--content", "--format", "json", home=str(tmp_path))
    assert result.returncode == 1
    assert json.loads(result.stdout)["content"] is None


def test_default_json_contract_is_unchanged(tmp_path) -> None:
    result = run_cli(str(VALID / "breast-synoptic-summary.hl7"), "--format", "json", home=str(tmp_path))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "syntax" not in payload and "content" not in payload
    assert set(payload) == {
        "schema_version", "ruleset_version", "profile", "detected_report_style",
        "valid", "counts", "findings", "coverage_notices",
    }


def test_content_errors_set_exit_one(monkeypatch, tmp_path, capsys) -> None:
    value = (VALID / "breast-synoptic-summary.hl7").read_text().replace("C50.4", "C99.9").replace("8500/3", "1234/3")
    path = tmp_path / "invalid-content.hl7"
    path.write_text(value, encoding="utf-8")

    def fixture_content(text, **options):
        return real_validate_content(text, transport=FixtureTransport(), cache=MemoryCache(), syntax_valid=options["syntax_valid"])

    monkeypatch.setattr(cli, "validate_content", fixture_content)
    monkeypatch.setattr(cli, "load_api_key", lambda: (None, None))
    assert cli.main([str(path), "--content", "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["content"]["valid"] is False
