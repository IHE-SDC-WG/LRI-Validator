from __future__ import annotations

import re
from dataclasses import dataclass

from .validator import CATALOG, Segment, _component, normalize_message, parse_segments


CONTENT = CATALOG["content"]
ECP_TEMPLATE_RE = re.compile(r"^\d{1,9}\.\d{9}$")
SITE_RE = re.compile(r"(?<![A-Z0-9])C(\d{2})(?:[.]?(\d))?(?![A-Z0-9])", re.IGNORECASE)
MORPHOLOGY_RE = re.compile(r"(?<!\d)(\d{4})(?:\s*/\s*([0-9]))?(?!\d)")
YEAR_RE = re.compile(r"^(?:19|20)\d{2}")


@dataclass(frozen=True, slots=True)
class Candidate:
    value: str
    line: int
    priority: int
    assumed_nos: bool = False


@dataclass(frozen=True, slots=True)
class GroupExtraction:
    index: int
    line_number: int
    site: str | None = None
    site_line: int | None = None
    site_assumed_nos: bool = False
    histology: str | None = None
    histology_line: int | None = None
    behavior: str | None = None
    behavior_line: int | None = None
    laterality: str | None = None
    laterality_line: int | None = None
    grade: str | None = None
    grade_line: int | None = None
    year: str | None = None
    year_line: int | None = None
    year_source: str | None = None
    template_key: str | None = None
    template_id: str | None = None
    template_line: int | None = None
    conflicts: tuple[tuple[str, int | None], ...] = ()

    def outbound_codes(self) -> dict[str, str]:
        values = {
            "site": self.site,
            "hist": self.histology,
            "behavior": self.behavior,
            "laterality": self.laterality,
            "grade": self.grade,
            "year": self.year,
        }
        return {key: value for key, value in values.items() if value is not None}

    def to_dict(self) -> dict[str, object]:
        def field(value: str | None, line: int | None, **extra: object) -> dict[str, object] | None:
            if value is None:
                return None
            return {"value": value, "line_number": line, **extra}

        template = None
        if self.template_key or self.template_id:
            template = {
                "key": self.template_key,
                "id": self.template_id,
                "line_number": self.template_line,
            }
        return {
            "group": self.index,
            "line_number": self.line_number,
            "site": field(self.site, self.site_line, assumed_nos=self.site_assumed_nos),
            "histology": field(self.histology, self.histology_line),
            "behavior": field(self.behavior, self.behavior_line),
            "laterality": field(self.laterality, self.laterality_line),
            "grade": field(self.grade, self.grade_line),
            "year": field(self.year, self.year_line, source=self.year_source),
            "template": template,
            "conflicting_fields": [name for name, _line in self.conflicts],
        }


@dataclass(frozen=True, slots=True)
class ContentExtraction:
    groups: tuple[GroupExtraction, ...]

    @property
    def has_registry_codes(self) -> bool:
        return any(group.site or group.histology for group in self.groups)

    def disclosure_params(self) -> list[dict[str, object]]:
        return [
            {"group": group.index, "line_number": group.line_number, "codes": group.outbound_codes()}
            for group in self.groups
            if group.outbound_codes()
        ]

    def to_dict(self) -> dict[str, object]:
        return {
            "groups": [group.to_dict() for group in self.groups],
            "disclosure_params": self.disclosure_params(),
        }


def decode_hl7(value: str) -> str:
    replacements = (
        ("\\.br\\", "\n"),
        ("\\F\\", "|"),
        ("\\S\\", "^"),
        ("\\T\\", "&"),
        ("\\R\\", "~"),
        ("\\E\\", "\\"),
    )
    for escaped, decoded in replacements:
        value = value.replace(escaped, decoded)
    return value


def normalize_site(value: str) -> tuple[str, bool] | None:
    matches = list(SITE_RE.finditer(value.upper()))
    specific = [match for match in matches if match.group(2)]
    selected = specific or matches
    values = {(f"C{match.group(1)}{match.group(2)}", False) if match.group(2) else (f"C{match.group(1)}9", True) for match in selected}
    if len(values) != 1:
        return None
    return next(iter(values))


def normalize_morphology(value: str) -> tuple[str, str | None] | None:
    matches = MORPHOLOGY_RE.findall(value)
    values = {(hist, behavior or None) for hist, behavior in matches}
    if len(values) != 1:
        return None
    return next(iter(values))


def normalize_behavior(value: str) -> str | None:
    morphology = normalize_morphology(value)
    if morphology and morphology[1] is not None:
        return morphology[1]
    match = re.search(r"(?:behavior|behaviour)\s*(?:code)?\s*[:=-]?\s*([0-9])\b", value, re.IGNORECASE)
    if match:
        return match.group(1)
    stripped = value.strip()
    return stripped if re.fullmatch(r"[0-9]", stripped) else None


def normalize_laterality(value: str) -> str | None:
    stripped = value.strip()
    if re.fullmatch(r"[0-9]", stripped):
        return stripped
    lowered = re.sub(r"\s+", " ", stripped.lower())
    for word, code in CONTENT["laterality_words"].items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return code
    return None


def normalize_grade(value: str) -> str | None:
    stripped = value.strip()
    if re.fullmatch(r"[1-9A-DHLM]", stripped, re.IGNORECASE):
        return stripped.upper()
    match = re.search(r"\b(?:grade\s*)?(?:G\s*)?([1-4])\b", stripped, re.IGNORECASE)
    return match.group(1) if match else None


def _label_field(label: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    for field, labels in CONTENT["labels"].items():
        if any(normalized == candidate or normalized.endswith(" " + candidate) for candidate in labels):
            return field
    return None


def _append(candidates: dict[str, list[Candidate]], field: str, value: str | None, line: int, priority: int) -> None:
    if value is not None:
        candidates[field].append(Candidate(value, line, priority))


def _append_site(candidates: dict[str, list[Candidate]], value: tuple[str, bool] | None, line: int, priority: int) -> None:
    if value is not None:
        candidates["site"].append(Candidate(value[0], line, priority, assumed_nos=value[1]))


def _coded_candidates(observation: Segment, candidates: dict[str, list[Candidate]]) -> None:
    label = decode_hl7(_component(observation.field(3), 2))
    field_name = _label_field(label)
    value = decode_hl7(observation.field(5))
    triplets = [
        (_component(value, 1), _component(value, 2), _component(value, 3)),
        (_component(value, 4), _component(value, 5), _component(value, 6)),
    ]
    aliases = {alias.upper() for alias in CONTENT["icdo_system_aliases"]}
    for identifier, display, system in triplets:
        if not identifier and not display:
            continue
        combined = " ".join(part for part in (identifier, display) if part)
        if field_name == "site":
            site = normalize_site(combined)
            _append_site(candidates, site, observation.line, 1)
        elif field_name == "histology":
            morphology = normalize_morphology(combined)
            if morphology:
                _append(candidates, "histology", morphology[0], observation.line, 1)
                _append(candidates, "behavior", morphology[1], observation.line, 1)
        elif field_name == "behavior":
            _append(candidates, "behavior", normalize_behavior(combined), observation.line, 1)
        elif field_name == "laterality":
            code = CONTENT["laterality_snomed"].get(identifier) or normalize_laterality(combined)
            _append(candidates, "laterality", code, observation.line, 1)
        elif field_name == "grade":
            _append(candidates, "grade", normalize_grade(combined), observation.line, 1)
        if system.upper() in aliases:
            site = normalize_site(identifier)
            morphology = normalize_morphology(identifier)
            _append_site(candidates, site, observation.line, 1)
            if morphology:
                _append(candidates, "histology", morphology[0], observation.line, 1)
                _append(candidates, "behavior", morphology[1], observation.line, 1)


def _specimen_site_candidates(specimen: Segment, candidates: dict[str, list[Candidate]]) -> None:
    aliases = {alias.upper() for alias in CONTENT["icdo_system_aliases"]}
    for field_number in (4, 8):
        for repetition in specimen.field(field_number).split("~") if specimen.field(field_number) else ():
            triplets = (
                (_component(repetition, 1), _component(repetition, 2), _component(repetition, 3)),
                (_component(repetition, 4), _component(repetition, 5), _component(repetition, 6)),
            )
            for identifier, display, system in triplets:
                if not identifier and not display:
                    continue
                combined = " ".join(part for part in (identifier, decode_hl7(display)) if part)
                if field_number == 8 or system.upper() in aliases:
                    _append_site(candidates, normalize_site(combined), specimen.line, 3)


def _labeled_candidates(text: str, line: int, candidates: dict[str, list[Candidate]]) -> None:
    decoded = decode_hl7(text)
    label_patterns = {
        field: "|".join(re.escape(label) for label in labels)
        for field, labels in CONTENT["labels"].items()
    }
    for field_name, pattern in label_patterns.items():
        for match in re.finditer(rf"(?:^|[\n;])\s*(?:{pattern})\s*[:=-]\s*([^\n;]+)", decoded, re.IGNORECASE):
            value = match.group(1)
            if field_name == "site":
                site = normalize_site(value)
                _append_site(candidates, site, line, 2)
            elif field_name == "histology":
                morphology = normalize_morphology(value)
                if morphology:
                    _append(candidates, "histology", morphology[0], line, 2)
                    _append(candidates, "behavior", morphology[1], line, 2)
            elif field_name == "behavior":
                _append(candidates, "behavior", normalize_behavior(value), line, 2)
            elif field_name == "laterality":
                _append(candidates, "laterality", normalize_laterality(value), line, 2)
            elif field_name == "grade":
                _append(candidates, "grade", normalize_grade(value), line, 2)
    morphology_matches = MORPHOLOGY_RE.findall(decoded)
    if len(morphology_matches) == 1 and int(morphology_matches[0][0]) >= int(CONTENT["heme_histology_min"]):
        _append(candidates, "histology", morphology_matches[0][0], line, 4)
        _append(candidates, "behavior", morphology_matches[0][1] or None, line, 4)


def _select(candidates: list[Candidate]) -> tuple[str | None, int | None, bool]:
    if not candidates:
        return None, None, False
    values = {candidate.value for candidate in candidates}
    if len(values) != 1:
        return None, min(candidate.line for candidate in candidates), True
    chosen = min(candidates, key=lambda candidate: (candidate.priority, candidate.line))
    return chosen.value, chosen.line, False


def _template(observations: list[Segment]) -> tuple[str | None, str | None, int | None]:
    metadata = next((item for item in observations if _component(item.field(3), 1) == "60572-5"), None)
    if metadata is None:
        return None, None, None
    value = decode_hl7(metadata.field(5))
    identifier = _component(value, 1)
    template_id = identifier if ECP_TEMPLATE_RE.fullmatch(identifier) else None
    lowered = value.lower()
    for template in CONTENT["templates"]:
        if any(pattern in lowered for pattern in template["patterns"]):
            return template["key"], template_id, metadata.line
    return None, template_id, metadata.line


def _group_extraction(index: int, segments: list[Segment]) -> GroupExtraction:
    candidates: dict[str, list[Candidate]] = {
        "site": [], "histology": [], "behavior": [], "laterality": [], "grade": []
    }
    observations = [segment for segment in segments if segment.name == "OBX"]
    specimens = [segment for segment in segments if segment.name == "SPM"]
    obr = next((segment for segment in segments if segment.name == "OBR"), None)
    for observation in observations:
        _coded_candidates(observation, candidates)
        label = decode_hl7(_component(observation.field(3), 2))
        value = decode_hl7(observation.field(5))
        if label:
            _labeled_candidates(label + ": " + value, observation.line, candidates)
        _labeled_candidates(value, observation.line, candidates)
    for specimen in specimens:
        _specimen_site_candidates(specimen, candidates)
        for repetition in specimen.field(9).split("~") if specimen.field(9) else ():
            identifier = _component(repetition, 1)
            display = decode_hl7(_component(repetition, 2))
            code = CONTENT["laterality_snomed"].get(identifier) or normalize_laterality(display)
            _append(candidates, "laterality", code, specimen.line, 3)
    selected = {field: _select(values) for field, values in candidates.items()}
    year = None
    year_line = None
    year_source = None
    for specimen in specimens:
        match = YEAR_RE.match(_component(specimen.field(17), 1))
        if match:
            year, year_line, year_source = match.group(0), specimen.line, "SPM-17"
            break
    if year is None and obr is not None:
        match = YEAR_RE.match(obr.field(7))
        if match:
            year, year_line, year_source = match.group(0), obr.line, "OBR-7"
    template_key, template_id, template_line = _template(observations)
    conflicts = tuple((field, value[1]) for field, value in selected.items() if value[2])
    site = selected["site"][0]
    selected_site_candidate = min(
        (candidate for candidate in candidates["site"] if candidate.value == site),
        key=lambda candidate: (candidate.priority, candidate.line),
        default=None,
    )
    return GroupExtraction(
        index=index,
        line_number=segments[0].line,
        site=site,
        site_line=selected["site"][1],
        site_assumed_nos=bool(selected_site_candidate and selected_site_candidate.assumed_nos),
        histology=selected["histology"][0],
        histology_line=selected["histology"][1],
        behavior=selected["behavior"][0],
        behavior_line=selected["behavior"][1],
        laterality=selected["laterality"][0],
        laterality_line=selected["laterality"][1],
        grade=selected["grade"][0],
        grade_line=selected["grade"][1],
        year=year,
        year_line=year_line,
        year_source=year_source,
        template_key=template_key,
        template_id=template_id,
        template_line=template_line,
        conflicts=conflicts,
    )


def extract_content(text: str) -> ContentExtraction:
    segments = parse_segments(normalize_message(text))
    starts = [index for index, segment in enumerate(segments) if segment.name == "ORC"]
    groups = []
    for group_index, start in enumerate(starts, 1):
        end = starts[group_index] if group_index < len(starts) else len(segments)
        groups.append(_group_extraction(group_index, segments[start:end]))
    return ContentExtraction(tuple(groups))
