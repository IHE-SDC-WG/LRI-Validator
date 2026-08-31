from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


Severity = Literal["error", "warning", "information"]
ContentStatus = Literal["complete", "partial", "not-applicable"]


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    rule_id: str
    location: str
    line_number: int | None
    message: str
    expected_behavior: str
    source_section: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    schema_version: str
    ruleset_version: str
    profile: str
    detected_report_style: str
    valid: bool
    counts: dict[str, int]
    findings: tuple[Finding, ...]
    coverage_notices: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["findings"] = [finding.to_dict() for finding in self.findings]
        data["coverage_notices"] = list(self.coverage_notices)
        return data


@dataclass(frozen=True, slots=True)
class ContentReport:
    schema_version: str
    content_ruleset_version: str
    profile: str
    based_on: dict[str, object]
    status: ContentStatus
    valid: bool
    counts: dict[str, int]
    findings: tuple[Finding, ...]
    extraction: dict[str, object]
    queries: tuple[dict[str, object], ...]
    coverage_notices: tuple[str, ...]
    attribution: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["findings"] = [finding.to_dict() for finding in self.findings]
        data["queries"] = [dict(query) for query in self.queries]
        data["coverage_notices"] = list(self.coverage_notices)
        return data
