from __future__ import annotations

import json
import subprocess
import sys

from tests.support import CASES, ROOT, VALID, apply_case


def run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "lri_validator.cli", *args], cwd=ROOT, input=stdin,
        text=True, capture_output=True, check=False,
    )


def test_cli_exit_zero_and_json() -> None:
    result = run_cli(str(VALID / "cap-ecp.hl7"), "--format", "json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["valid"] is True


def test_cli_exit_one_for_validation_errors(tmp_path) -> None:
    path = tmp_path / "invalid.hl7"
    path.write_text(apply_case(next(case for case in CASES if case["name"] == "wrong-version")))
    result = run_cli(str(path))
    assert result.returncode == 1
    assert "LRI-16" in result.stdout


def test_cli_exit_two_for_unsupported_input(tmp_path) -> None:
    path = tmp_path / "batch.hl7"
    path.write_text("BHS|^~\\&|batch\rMSH|^~\\&|message\r")
    result = run_cli(str(path))
    assert result.returncode == 2
    assert "not supported" in result.stderr


def test_cli_reads_stdin() -> None:
    result = run_cli("-", stdin=(VALID / "unstructured-narrative.hl7").read_text())
    assert result.returncode == 0
    assert "PASS" in result.stdout
