from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from importlib import resources

from .model import Finding, ValidationReport


class UnsupportedInputError(ValueError):
    """Raised when the input boundary is valid data but outside v1 scope."""


@dataclass(frozen=True, slots=True)
class Segment:
    name: str
    parts: tuple[str, ...]
    line: int

    def field(self, number: int) -> str:
        if self.name == "MSH":
            if number == 1:
                return "|"
            index = number - 1
        else:
            index = number
        return self.parts[index] if index < len(self.parts) else ""


def _catalog() -> dict[str, object]:
    return json.loads(resources.files(__package__).joinpath("catalog.json").read_text())


CATALOG = _catalog()
CONSTANTS = CATALOG["constants"]
RULES = CATALOG["rules"]
OID_RE = re.compile(r"^(?:(?:0|1)\.(?:0|[1-9]|[1-3][0-9])|2\.(?:0|[1-9]\d*))(?:\.(?:0|[1-9]\d*))*$")
MD_RE = re.compile(r"^[A-Za-z]{2,4}[_-].+$")
DT_RE = re.compile(r"^(?:0000|\d{4}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\.\d{1,4})?)?)?)?)?)?)(?:[+-]\d{4})?$")
ECP_RE = re.compile(r"^(\d{1,9}\.\d{9})(?:__([1-9]\d*))?$")


REQUIRED_FIELDS = {
    "MSH": (1, 2, 4, 7, 9, 10, 11, 12, 15, 16, 21),
    "PID": (1, 3, 5, 8),
    "PV1": (1, 2),
    "ORC": (1, 3, 12, 21),
    "OBR": (1, 3, 4, 7, 16, 21, 22, 25, 32),
    "OBX": (1, 2, 3, 5, 11),
    "SPM": (1, 2, 4, 17, 18),
    "NTE": (1, 3),
}

RE_FIELDS = {
    "MSH": (3, 5, 6, 13, 14, 17, 19),
    "PID": (7, 10, 11, 13, 14, 15, 16, 17, 18, 22, 30, 31, 32, 39),
    "PV1": (7, 8, 9, 17),
    "ORC": (2, 4, 22, 23, 24, 28),
    "OBR": (2, 10, 11, 13, 17, 29, 31, 44, 47, 49, 50),
    "OBX": (7, 8, 14, 16, 17, 19),
    "SPM": (3, 5, 7, 8, 9, 11, 21, 24, 30, 31),
    "NTE": (2, 4),
}

MAX_REPEATS = {
    ("PID", 3): 8, ("PID", 5): 8, ("PID", 11): 4, ("PID", 13): 8,
    ("PID", 14): 4, ("PID", 15): 1, ("PID", 16): 1, ("PID", 17): 1,
    ("PID", 18): 1, ("PID", 29): 1, ("PID", 30): 1, ("PID", 31): 1,
    ("PID", 32): 3, ("PID", 39): 5, ("PV1", 7): 2, ("PV1", 8): 2,
    ("PV1", 9): 2, ("PV1", 17): 2, ("ORC", 21): 1, ("ORC", 22): 4,
    ("ORC", 23): 4, ("ORC", 24): 4, ("ORC", 28): 1, ("OBR", 10): 4,
    ("OBR", 16): 4, ("OBR", 17): 4, ("OBR", 21): 1, ("OBR", 28): 999,
    ("OBR", 29): 1, ("OBR", 31): 20, ("OBR", 32): 1, ("OBR", 44): 1,
    ("OBR", 50): 1, ("OBX", 5): 1, ("OBX", 14): 1, ("OBX", 15): 1,
    ("OBX", 16): 5, ("OBX", 17): 6, ("OBX", 19): 1, ("SPM", 2): 1,
    ("SPM", 4): 1, ("SPM", 7): 1, ("SPM", 8): 1, ("SPM", 11): 1,
    ("SPM", 17): 1, ("SPM", 18): 1, ("SPM", 24): 5, ("SPM", 30): 1,
    ("SPM", 31): 1, ("NTE", 2): 1, ("NTE", 3): 1, ("NTE", 4): 1,
}


def normalize_message(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    value = text.lstrip("\ufeff").strip(" \t\r\n")
    if value.startswith("\x0b"):
        value = value[1:]
        if value.endswith("\x1c\r"):
            value = value[:-2]
        elif value.endswith("\x1c"):
            value = value[:-1]
        else:
            raise UnsupportedInputError("MLLP start framing was found without a valid end frame.")
    elif "\x0b" in value or "\x1c" in value:
        raise UnsupportedInputError("Partial or embedded MLLP framing is not supported.")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in value.split("\n") if line.strip()]
    if not lines:
        raise UnsupportedInputError("No HL7 message was provided.")
    if lines[0][:3] in {"FHS", "BHS"}:
        raise UnsupportedInputError("FHS/BHS batch wrappers are not supported; provide one ORU_R01 message.")
    if sum(1 for line in lines if line.startswith("MSH")) != 1:
        raise UnsupportedInputError("Exactly one HL7 message is supported per validation.")
    return "\r".join(lines) + "\r"


def _segments(normalized: str) -> list[Segment]:
    result: list[Segment] = []
    for line, raw in enumerate(normalized.rstrip("\r").split("\r"), 1):
        name = raw[:3]
        result.append(Segment(name, tuple(raw.split("|")), line))
    return result


def _components(value: str, separator: str = "^") -> list[str]:
    return value.split(separator)


def _component(value: str, number: int, separator: str = "^") -> str:
    parts = _components(value, separator)
    return parts[number - 1] if number <= len(parts) else ""


def _is_npi(value: str) -> bool:
    if not re.fullmatch(r"\d{10}", value):
        return False
    digits = [int(char) for char in "80840" + value[:9]]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        doubled = digit * 2 if index % 2 == 0 else digit
        total += doubled // 10 + doubled % 10
    return (10 - total % 10) % 10 == int(value[-1])


def _parse_date(value: str) -> datetime | None:
    value = _component(value, 1)
    if not value or value == "0000" or not DT_RE.fullmatch(value):
        return None
    core = re.sub(r"[+-]\d{4}$", "", value).split(".")[0]
    if len(core) < 8:
        return None
    padded = (core + "000000")[:14]
    try:
        return datetime.strptime(padded, "%Y%m%d%H%M%S")
    except ValueError:
        return None


class Evaluator:
    def __init__(self, segments: list[Segment]) -> None:
        self.segments = segments
        self.findings: list[Finding] = []
        self.styles: list[str] = []

    def add(self, rule_id: str, location: str, line: int | None, message: str) -> None:
        rule = RULES[rule_id]
        self.findings.append(Finding(
            severity=rule["severity"], rule_id=rule_id, location=location,
            line_number=line, message=message, expected_behavior=rule["expected"],
            source_section=rule["section"],
        ))

    def one(self, name: str) -> Segment | None:
        return next((segment for segment in self.segments if segment.name == name), None)

    def all(self, name: str) -> list[Segment]:
        return [segment for segment in self.segments if segment.name == name]

    def run(self) -> None:
        self.base_parse()
        self.message_identity()
        self.structure()
        self.fields()
        self.profile()
        self.set_ids()
        self.identifiers()
        self.order_groups()

    def base_parse(self) -> None:
        malformed = next((s for s in self.segments if not re.fullmatch(r"[A-Z0-9]{3}", s.name)), None)
        if malformed:
            self.add("ER7-001", malformed.name or "message", malformed.line, "A segment identifier is not three uppercase letters or digits.")
            return
        try:
            from hl7apy.consts import VALIDATION_LEVEL
            from hl7apy.parser import parse_message
            raw = "\r".join("|".join(segment.parts) for segment in self.segments) + "\r"
            parse_message(raw, find_groups=False, validation_level=VALIDATION_LEVEL.TOLERANT)
        except Exception:
            self.add("ER7-001", "message", None, "HL7apy could not parse the ER7 message.")

    def message_identity(self) -> None:
        msh = self.one("MSH")
        if not msh:
            self.add("STRUCTURE-001", "MSH", None, "MSH is missing.")
            return
        if msh.parts[0] != "MSH" or msh.field(1) != "|":
            self.add("LRI-13", "MSH-1", msh.line, "The field separator is not |.")
        if msh.field(2) not in {"^~\\&", "^~\\&#"}:
            self.add("LRI-14", "MSH-2", msh.line, "The encoding characters do not match the allowed constants.")
        if _components(msh.field(9))[:3] != ["ORU", "R01", "ORU_R01"]:
            self.add("LRI-15", "MSH-9", msh.line, "The message identity is not ORU^R01^ORU_R01.")
        if _component(msh.field(12), 1) != "2.5.1":
            self.add("LRI-16", "MSH-12.1", msh.line, "The version is not 2.5.1.")

    def structure(self) -> None:
        if self.segments and self.segments[0].name != "MSH":
            self.add("STRUCTURE-001", self.segments[0].name, self.segments[0].line, "MSH must be the first segment.")
        for name, minimum, maximum in (("MSH", 1, 1), ("PID", 1, 1), ("PV1", 1, 1), ("ORC", 1, 999), ("OBR", 1, 999), ("OBX", 1, 999), ("SPM", 1, 999)):
            count = len(self.all(name))
            if count < minimum or count > maximum:
                self.add("STRUCTURE-001", name, None, f"Expected {minimum}..{maximum if maximum < 999 else '*'} {name} segments; found {count}.")
        for dsc in self.all("DSC"):
            self.add("DSC-001", "DSC", dsc.line, "DSC is prohibited by the profile.")
        rank = {"MSH": 0, "SFT": 1, "PID": 2, "PD1": 3, "NTE": 99, "NK1": 4, "PV1": 5, "PV2": 6, "ORC": 7, "OBR": 8, "TQ1": 9, "TQ2": 10, "OBX": 11, "PRT": 12, "SPM": 13}
        last = -1
        in_orders = False
        for segment in self.segments:
            if segment.name == "NTE":
                continue
            if segment.name == "ORC":
                in_orders = True
                last = rank["ORC"]
                continue
            current = rank.get(segment.name)
            if current is None or segment.name == "DSC":
                continue
            if in_orders and segment.name in {"OBX", "PRT", "SPM"}:
                pass
            elif in_orders and segment.name == "OBR":
                last = current
            elif current < last:
                self.add("STRUCTURE-001", segment.name, segment.line, f"{segment.name} is out of profile order.")
            else:
                last = current

    def fields(self) -> None:
        for segment in self.segments:
            for number in REQUIRED_FIELDS.get(segment.name, ()):
                if not segment.field(number):
                    self.add("FIELD-R", f"{segment.name}-{number}", segment.line, f"Required field {segment.name}-{number} is empty.")
            for number in RE_FIELDS.get(segment.name, ()):
                if not segment.field(number):
                    self.add("FIELD-RE", f"{segment.name}-{number}", segment.line, f"Expected-when-known field {segment.name}-{number} is empty.")
            for (name, number), maximum in MAX_REPEATS.items():
                if segment.name == name and segment.field(number):
                    repeats = len(segment.field(number).split("~"))
                    if repeats > maximum:
                        self.add("CARDINALITY-001", f"{name}-{number}", segment.line, f"Found {repeats} repetitions; maximum is {maximum}.")
        for pid in self.all("PID"):
            if pid.field(30) == "Y" and not pid.field(29):
                self.add("FIELD-R", "PID-29", pid.line, "PID-29 is required when PID-30 is Y.")

    def profile(self) -> None:
        msh = self.one("MSH")
        if not msh:
            return
        identifiers = []
        for repetition in msh.field(21).split("~"):
            identifier = _component(repetition, 3)
            identifiers.append(identifier)
            if identifier and (not OID_RE.fullmatch(identifier) or _component(repetition, 4) != "ISO"):
                self.add("LRI-NAACCR-05", "MSH-21", msh.line, "A profile identifier is not an ISO OID EI value.")
        oids = CONSTANTS["profile_oids"]
        if oids["naaccr"] not in identifiers:
            self.add("LRI-NAACCR-PROFILE", "MSH-21", msh.line, "The NAACCR component OID is missing.")
        if oids["conflicting_table_ng_fru"] in identifiers:
            self.add("LRI-11", "MSH-21", msh.line, "The draft table's .25 OID does not satisfy literal conformance statement LRI-11.")
            self.add("DRAFT-CONFLICT-01", "MSH-21", msh.line, "The message uses the draft table's conflicting .25 NG-FRU OID.")
        elif not (oids["legacy_ng_fru"] in identifiers or {oids["common"], oids["ng"], oids["fru"]}.issubset(identifiers)):
            self.add("LRI-11", "MSH-21", msh.line, "Neither the legacy NG-FRU OID nor all three NG-FRU component OIDs are present.")

    def set_ids(self) -> None:
        for name in ("OBR",):
            for expected, segment in enumerate(self.all(name), 1):
                if segment.field(1) != str(expected):
                    self.add("LRI-34", f"{name}-1", segment.line, f"Expected set ID {expected}; found {segment.field(1)!r}.")
        for name in ("PID", "PV1"):
            for segment in self.all(name):
                if segment.field(1) != "1":
                    self.add("SETID-001", f"{name}-1", segment.line, f"{name}-1 must be 1.")

    def _typed_identifier(self, uid: str, kind: str, location: str, line: int, prefix: str) -> None:
        if kind == "NPI" and not _is_npi(uid):
            self.add(f"{prefix}-03" if prefix.endswith("NAACCR") else "LRI-NAACCR-06", location, line, "The universal identifier is not a valid NPI.")
        elif kind == "MD" and not MD_RE.fullmatch(uid):
            self.add(f"{prefix}-04" if prefix.endswith("NAACCR") else "LRI-NAACCR-07", location, line, "The universal identifier lacks the required state/province prefix.")
        elif kind == "ISO" and not OID_RE.fullmatch(uid):
            self.add(f"{prefix}-05" if prefix.endswith("NAACCR") else "LRI-NAACCR-08", location, line, "The universal identifier is not an ISO OID.")

    def identifiers(self) -> None:
        for name, fields in {"ORC": (2, 3, 4), "OBR": (2, 3)}.items():
            for segment in self.all(name):
                for number in fields:
                    value = segment.field(number)
                    if value:
                        self._typed_identifier(_component(value, 3), _component(value, 4), f"{name}-{number}", segment.line, "LRI-NAACCR")
        for name, fields in {"PV1": (7, 8, 9, 17), "ORC": (12,), "OBR": (16, 28), "OBX": (16, 25)}.items():
            for segment in self.all(name):
                for number in fields:
                    for repetition in segment.field(number).split("~") if segment.field(number) else ():
                        authority = _component(repetition, 9)
                        if authority:
                            self._typed_identifier(_component(authority, 2, "&"), _component(authority, 3, "&"), f"{name}-{number}.9", segment.line, "HD")
        for obr in self.all("OBR"):
            cnn = _component(obr.field(32), 1)
            if cnn:
                uid, kind = _component(cnn, 10, "&"), _component(cnn, 11, "&")
                if not uid:
                    self.add("LRI-NAACCR-01", "OBR-32.1.10", obr.line, "CNN.10 is empty.")
                if kind not in {"NPI", "MD", "ISO"}:
                    self.add("LRI-NAACCR-02", "OBR-32.1.11", obr.line, "CNN.11 has an unsupported identifier type.")
                elif uid:
                    mapping = {"NPI": "LRI-NAACCR-03", "MD": "LRI-NAACCR-04", "ISO": "LRI-NAACCR-05"}
                    valid = _is_npi(uid) if kind == "NPI" else MD_RE.fullmatch(uid) if kind == "MD" else OID_RE.fullmatch(uid)
                    if not valid:
                        self.add(mapping[kind], "OBR-32.1.10", obr.line, "CNN.10 is invalid for the declared identifier type.")

    def order_groups(self) -> None:
        starts = [index for index, segment in enumerate(self.segments) if segment.name == "ORC"]
        filler_ids: set[str] = set()
        for group_number, start in enumerate(starts, 1):
            end = starts[group_number] if group_number < len(starts) else len(self.segments)
            group = self.segments[start:end]
            orc = group[0]
            obrs = [segment for segment in group if segment.name == "OBR"]
            if len(obrs) != 1:
                self.add("STRUCTURE-001", "ORDER_OBSERVATION", orc.line, f"Order group must contain one OBR; found {len(obrs)}.")
                continue
            obr = obrs[0]
            obx = [segment for segment in group if segment.name == "OBX"]
            spm = [segment for segment in group if segment.name == "SPM"]
            if obr.field(25) != "X" and not obx:
                self.add("STRUCTURE-001", "OBX", obr.line, "A non-cancelled order group needs at least one OBX.")
            if not spm:
                self.add("STRUCTURE-001", "SPM", obr.line, "The NAACCR order group needs specimen information.")
            first_spm = min((s.line for s in spm), default=10**9)
            if any(item.line > first_spm for item in obx):
                self.add("STRUCTURE-001", "OBX/SPM", first_spm, "Result OBXs must precede the SPM group in this profile structure.")
            for expected, segment in enumerate(obx, 1):
                if segment.field(1) != str(expected):
                    self.add("SETID-001", "OBX-1", segment.line, f"Expected OBX set ID {expected}; found {segment.field(1)!r}.")
            for expected, segment in enumerate(spm, 1):
                if segment.field(1) != str(expected):
                    self.add("SETID-001", "SPM-1", segment.line, f"Expected SPM set ID {expected}; found {segment.field(1)!r}.")
            for rule, field_a, field_b in (("LRI-23", 2, 2), ("LRI-24", 3, 3), ("LRI-25", 12, 16)):
                left, right = orc.field(field_a), obr.field(field_b)
                if left and left != right:
                    self.add(rule, f"ORC-{field_a}/OBR-{field_b}", obr.line, "The paired ORC and OBR values differ.")
            if orc.field(3) in filler_ids:
                self.add("LRI-28", "ORC-3", orc.line, "The filler order number repeats in this message.")
            filler_ids.add(orc.field(3))
            self.dates(obr, obx, spm)
            self.status(obr, obx)
            self.style(obr, obx)
            self.spm_terminology(spm)

    def dates(self, obr: Segment, obx: list[Segment], spm: list[Segment]) -> None:
        dated = [(obr, number) for number in (7, 8, 22)]
        dated += [(item, number) for item in obx for number in (14, 19)]
        dated += [(item, number) for item in spm for number in (17, 18)]
        for segment, number in dated:
            value = segment.field(number)
            if value:
                for component in value.split("^"):
                    if component and (not DT_RE.fullmatch(component) or (component not in {"0000"} and len(re.sub(r"[+-]\d{4}$", "", component).split(".")[0]) >= 8 and _parse_date(component) is None)):
                        self.add("DATE-001", f"{segment.name}-{number}", segment.line, "The field contains an invalid date/time.")
        obr7, obr8, obr22 = map(_parse_date, (obr.field(7), obr.field(8), obr.field(22)))
        if obr7 and obr8 and obr8 < obr7:
            self.add("LRI-33", "OBR-8", obr.line, "OBR-8 precedes OBR-7.")
        if obr7 and obr22 and obr22 < obr7:
            self.add("DATE-001", "OBR-22", obr.line, "The report status date precedes specimen collection.")
        for specimen in spm:
            start = _parse_date(_component(specimen.field(17), 1))
            finish = _parse_date(_component(specimen.field(17), 2)) or start
            received = _parse_date(specimen.field(18))
            if start and obr7 and start != obr7:
                self.add("DATE-001", "SPM-17.1/OBR-7", specimen.line, "SPM-17.1 does not equal OBR-7.")
            if start and received and received < start:
                self.add("DATE-001", "SPM-18", specimen.line, "Specimen receipt precedes collection.")
            for observation in obx:
                observed = _parse_date(observation.field(14))
                if observed and start and finish and not start <= observed <= finish:
                    self.add("DATE-001", "OBX-14", observation.line, "Observation date is outside SPM-17.")

    def status(self, obr: Segment, obx: list[Segment]) -> None:
        statuses = [item.field(11) for item in obx if item.field(11)]
        if not statuses:
            return
        if all(value in {"N", "X", "D"} for value in statuses): expected = "X"
        elif any(value in {"C", "A", "B", "W"} for value in statuses): expected = "M" if any(value in {"I", "P"} for value in statuses) else "C"
        elif "P" in statuses: expected = "P"
        elif "I" in statuses: expected = "A" if "F" in statuses else "I"
        else: expected = "F"
        if obr.field(25) != expected:
            self.add("STATUS-001", "OBR-25", obr.line, f"OBX-11 values imply {expected}; found {obr.field(25)!r}.")

    def style(self, obr: Segment, obx: list[Segment]) -> None:
        if not obx:
            return
        first = obx[0]
        first_code, declaration = _component(first.field(3), 1), first.field(5)
        if first_code == "60573-3":
            if declaration in CONSTANTS["document_styles"]:
                style = CONSTANTS["document_styles"][declaration]
            elif declaration.endswith(" Synoptic Summary") and not declaration.startswith("CAP "):
                style = "synoptic summary"
            elif declaration.endswith(" Synoptic Segmented") and not declaration.startswith("CAP "):
                style = "synoptic segmented"
            else:
                style = "unknown synoptic"
                self.add("STYLE-001", "OBX-5", first.line, "The first OBX has an unrecognized report style declaration.")
        else:
            codes = {_component(item.field(3), 1) for item in obx}
            style = "structured narrative" if len(obx) > 1 and codes.issubset(set(CONSTANTS["narrative_obx3_loincs"])) else "unstructured narrative"
        self.styles.append(style)
        code = _component(obr.field(4), 1)
        if code in CONSTANTS["deprecated_loincs"]:
            self.add("DEPRECATED-001", "OBR-4", obr.line, f"LOINC {code} is deprecated in the draft.")
        elif code not in CONSTANTS["obr4_loincs"]:
            self.add("OBR4-001", "OBR-4", obr.line, f"LOINC {code!r} is not one of the report codes completely enumerated in Table 7.13.")
        if style in {"synoptic summary", "synoptic segmented", "CAP eCP"} and code not in CONSTANTS["synoptic_obr4_loincs"]:
            self.add("STYLE-001", "OBR-4", obr.line, "A synoptic style is paired with a non-synoptic OBR-4 code.")
        if style in {"synoptic summary", "synoptic segmented", "CAP eCP"}:
            self.metadata(obx, style)
        if style == "unstructured narrative" and len(obx) != 1:
            self.add("NARRATIVE-001", "OBX", first.line, "Unstructured narrative must use one complete content OBX.")
        if style == "structured narrative":
            for item in obx:
                if _component(item.field(3), 1) not in CONSTANTS["narrative_obx3_loincs"]:
                    self.add("NARRATIVE-001", "OBX-3", item.line, "Structured narrative uses an OBX-3 code outside Table 7.14.")
        self.obx4(obx, style)
        if style == "CAP eCP":
            self.ecp(obx[3:])

    def metadata(self, obx: list[Segment], style: str) -> None:
        if len(obx) < 4:
            self.add("STYLE-002", "OBX", obx[0].line, "A synoptic report needs three metadata OBXs and content.")
            return
        expected_codes = CONSTANTS["metadata_loincs"]
        expected_types = ["ST" if style == "CAP eCP" else "TX", "CWE" if style == "CAP eCP" else "TX", "ST" if style == "CAP eCP" else "TX"]
        for index in range(3):
            item = obx[index]
            if item.field(1) != str(index + 1) or item.field(2) != expected_types[index] or _component(item.field(3), 1) != expected_codes[index] or _component(item.field(3), 3) != "LN":
                self.add("STYLE-002", f"OBX[{index + 1}]", item.line, "The metadata OBX set ID, datatype, LOINC, or coding system is incorrect.")
        if style == "CAP eCP" and (not ECP_RE.fullmatch(_component(obx[1].field(5), 1)) or _component(obx[1].field(5), 3) != "CAPECP"):
            self.add("ECP-001", "OBX[2]-5", obx[1].line, "The eCP template identifier is not a CAPECP Ckey.")

    def obx4(self, obx: list[Segment], style: str) -> None:
        seen: dict[tuple[str, str], int] = {}
        for item in obx:
            key = (_component(item.field(3), 1), _component(item.field(3), 3))
            if key[0]:
                seen[key] = seen.get(key, 0) + 1
        for item in obx:
            key = (_component(item.field(3), 1), _component(item.field(3), 3))
            if key[0] and seen.get(key, 0) > 1 and not item.field(4) and key[0] not in set(CONSTANTS["metadata_loincs"]):
                self.add("OBX4-001", "OBX-4", item.line, "Repeated OBX-3 identifiers require an Observation Sub-ID.")
            if item.field(4) and style != "CAP eCP" and not re.fullmatch(r"\d+(?:\.\d+)*", item.field(4)):
                self.add("OBX4-001", "OBX-4", item.line, "The Observation Sub-ID does not use numeric dot notation.")

    def ecp(self, content: list[Segment]) -> None:
        repeat_numbers: dict[str, set[int]] = {}
        prior_answers: set[str] = set()
        known_ids: set[str] = set()
        for item in content:
            question = _component(item.field(3), 1)
            match = ECP_RE.fullmatch(question)
            if not match:
                self.add("ECP-001", "OBX-3.1", item.line, "The question identifier is not a full Ckey.")
            else:
                base, suffix = match.group(1), match.group(2)
                known_ids.add(question)
                if suffix:
                    repeat_numbers.setdefault(base, set()).add(int(suffix))
                    if _component(item.field(3), 3) != "CAPECP.RPT" or _component(item.field(3), 7) != base or _component(item.field(3), 9) != "CAPECP":
                        self.add("ECP-002", "OBX-3", item.line, "Repeated question lacks CAPECP.RPT and its original ID triplet.")
                elif _component(item.field(3), 3) != "CAPECP":
                    self.add("ECP-001", "OBX-3.3", item.line, "A non-repeated eCP question must use CAPECP.")
            if item.field(2) == "CWE":
                answer = _component(item.field(5), 1)
                answer_match = ECP_RE.fullmatch(answer)
                if not answer_match:
                    self.add("ECP-001", "OBX-5.1", item.line, "The coded answer is not a full Ckey.")
                else:
                    answer_base, answer_suffix = answer_match.group(1), answer_match.group(2)
                    if answer_suffix and (_component(item.field(5), 3) != "CAPECP.RPT" or _component(item.field(5), 7) != answer_base or _component(item.field(5), 9) != "CAPECP"):
                        self.add("ECP-002", "OBX-5", item.line, "Repeated answer lacks CAPECP.RPT and its original ID triplet.")
                    elif not answer_suffix and _component(item.field(5), 3) != "CAPECP":
                        self.add("ECP-001", "OBX-5.3", item.line, "A non-repeated coded answer must use CAPECP.")
                    prior_answers.add(answer)
                    known_ids.add(answer)
            link = item.field(4)
            if link:
                bare = link[1:] if link.startswith("+") else link
                if not ECP_RE.fullmatch(bare):
                    self.add("ECP-003", "OBX-4", item.line, "The OBX-4 link is not a Ckey parent/LIR link.")
                elif not link.startswith("+") and bare not in prior_answers:
                    self.add("ECP-003", "OBX-4", item.line, "A bare LIR link does not reference a prior coded answer.")
        for base, numbers in repeat_numbers.items():
            highest = max(numbers)
            if numbers != set(range(1, highest + 1)):
                first_line = content[0].line if content else None
                self.add("ECP-002", "OBX-3.1", first_line, "Repeat suffixes are not contiguous from __1.")

    def spm_terminology(self, specimens: list[Segment]) -> None:
        allowed = set(CONSTANTS["spm9_laterality"])
        for specimen in specimens:
            for repetition in specimen.field(9).split("~") if specimen.field(9) else ():
                if _component(repetition, 3) == "SCT" and _component(repetition, 1) not in allowed:
                    self.add("SPM9-001", "SPM-9", specimen.line, "The SCT laterality code is not enumerated in the draft.")


def validate_message(text: str) -> ValidationReport:
    normalized = normalize_message(text)
    evaluator = Evaluator(_segments(normalized))
    evaluator.run()
    findings = tuple(sorted(evaluator.findings, key=lambda finding: (finding.line_number or 0, finding.rule_id, finding.location)))
    counts = {severity: sum(finding.severity == severity for finding in findings) for severity in ("error", "warning", "information")}
    styles = list(dict.fromkeys(evaluator.styles))
    detected = styles[0] if len(styles) == 1 else "mixed: " + ", ".join(styles) if styles else "not detected"
    return ValidationReport(
        schema_version=CATALOG["schema_version"], ruleset_version=CATALOG["ruleset_version"],
        profile=CATALOG["profile"], detected_report_style=detected, valid=counts["error"] == 0,
        counts=counts, findings=findings, coverage_notices=tuple(CATALOG["coverage_notices"]),
    )
