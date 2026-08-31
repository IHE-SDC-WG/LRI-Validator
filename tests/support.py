from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "tests" / "fixtures" / "valid"
CONTENT_FIXTURES = ROOT / "tests" / "fixtures" / "content"
SEER_FIXTURES = ROOT / "tests" / "fixtures" / "seer"
CASES = json.loads((ROOT / "tests" / "fixtures" / "negative" / "cases.json").read_text())
CONTENT_CASES = json.loads((CONTENT_FIXTURES / "cases.json").read_text())


def apply_case(case: dict[str, object], *, base_dir: Path = VALID) -> str:
    value = (base_dir / case["base"]).read_text()
    for operation in case["operations"]:
        if operation["kind"] == "replace":
            assert operation["old"] in value
            value = value.replace(operation["old"], operation["new"], 1)
            continue
        lines = value.splitlines()
        matches = [index for index, line in enumerate(lines) if line.startswith(operation["segment"] + "|")]
        if operation["kind"] == "remove_segment":
            for index in reversed(matches):
                del lines[index]
            value = "\n".join(lines) + "\n"
            continue
        occurrence = int(operation.get("occurrence", 1))
        index = matches[occurrence - 1]
        parts = lines[index].split("|")
        field_number = int(operation["field"])
        part_index = field_number - 1 if operation["segment"] == "MSH" else field_number
        parts.extend([""] * max(0, part_index - len(parts) + 1))
        parts[part_index] = operation["value"]
        lines[index] = "|".join(parts)
        value = "\n".join(lines) + "\n"
    return value


def apply_content_case(name: str) -> str:
    case = next(case for case in CONTENT_CASES if case["name"] == name)
    return apply_case(case, base_dir=ROOT / "tests" / "fixtures")


def finding_key(report: dict[str, object]) -> list[tuple[str, str, str, int | None]]:
    return [(item["rule_id"], item["severity"], item["location"], item["line_number"]) for item in report["findings"]]


def seer_request_key(method: str, url: str, body: dict[str, object] | None) -> str:
    return json.dumps({"method": method, "url": url, "body": body}, sort_keys=True, separators=(",", ":"))


class FixtureTransport:
    def __init__(self) -> None:
        self.index = json.loads((SEER_FIXTURES / "index.json").read_text(encoding="utf-8"))
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def __call__(self, method: str, url: str, body: dict[str, object] | None) -> tuple[int, object]:
        self.calls.append((method, url, body))
        key = seer_request_key(method, url, body)
        if key not in self.index:
            raise AssertionError(f"Missing recorded SEER fixture for {key}")
        entry = self.index[key]
        data = json.loads((SEER_FIXTURES / entry["file"]).read_text(encoding="utf-8"))
        return int(entry["status"]), data
