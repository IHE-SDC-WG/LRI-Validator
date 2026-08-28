from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "tests" / "fixtures" / "valid"
CASES = json.loads((ROOT / "tests" / "fixtures" / "negative" / "cases.json").read_text())


def apply_case(case: dict[str, object]) -> str:
    value = (VALID / case["base"]).read_text()
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


def finding_key(report: dict[str, object]) -> list[tuple[str, str, str, int | None]]:
    return [(item["rule_id"], item["severity"], item["location"], item["line_number"]) for item in report["findings"]]
