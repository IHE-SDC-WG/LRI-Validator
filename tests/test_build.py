from __future__ import annotations

import hashlib
import subprocess

from tests.support import ROOT


def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_html_build_is_deterministic_and_self_contained() -> None:
    output = ROOT / "dist" / "naaccr-lri-validator.html"
    before = digest(output)
    subprocess.run(["python", "scripts/build_html.py"], cwd=ROOT, check=True, capture_output=True, text=True)
    assert digest(output) == before
    text = output.read_text()
    assert "/*__DATA__*/" not in text
    assert "/*__VALIDATOR__*/" not in text
    assert "/*__CONTENT__*/" not in text
    assert "/*__APP__*/" not in text
    assert "http://" not in text
    assert text.count("https://") == text.count("https://api.seer.cancer.gov/") >= 1
    assert text.count("fetch(") == 1 and "XMLHttpRequest" not in text
    assert "localStorage" not in text and "sessionStorage" not in text
    assert "Content-Security-Policy" not in text
    assert "window.onerror" in text
    assert "window.atob" not in text
    assert "JSON.parse" not in text
    assert 'type="application/json"' not in text
    assert "api.seer.cancer.gov" in text


def test_javascript_syntax() -> None:
    subprocess.run(["node", "--check", "web/validator.js"], cwd=ROOT, check=True)
    subprocess.run(["node", "--check", "web/content.js"], cwd=ROOT, check=True)
    subprocess.run(["node", "--check", "web/app.js"], cwd=ROOT, check=True)


def test_built_page_controls_start_and_respond() -> None:
    subprocess.run(["node", "tests/page_boot.cjs"], cwd=ROOT, check=True)
