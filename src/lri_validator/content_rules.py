from __future__ import annotations

from itertools import combinations
from typing import Callable

from .content import CONTENT, ContentExtraction, GroupExtraction, extract_content
from .model import ContentReport, Finding
from .seer import Cache, DiskCache, SeerClient, SeerError, Transport, UrllibTransport, algorithm_for_year, load_api_key
from .validator import CATALOG, validate_message


RULES = CATALOG["rules"]


def _template(key: str | None) -> dict[str, object] | None:
    return next((item for item in CONTENT["templates"] if item["key"] == key), None)


def _table_contains(table: dict[str, object], value: str) -> bool:
    rows = table.get("rows")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        expression = str(row[0]).strip()
        for part in (piece.strip() for piece in expression.split(",")):
            if part == value:
                return True
            if "-" in part:
                low, high = part.split("-", 1)
                if low.isdigit() and high.isdigit() and value.isdigit() and len(low) == len(high) == len(value):
                    if int(low) <= int(value) <= int(high):
                        return True
    return False


class _Evaluation:
    def __init__(self, extraction: ContentExtraction) -> None:
        self.extraction = extraction
        self.findings: list[Finding] = []
        self.coverage = list(CONTENT["coverage_notices"])
        self.failure_kinds: set[str] = set()
        self.skipped_online = False
        self.blocked_online = False

    def add(self, rule_id: str, group: GroupExtraction | None, line: int | None, message: str, *, location: str | None = None) -> None:
        rule = RULES[rule_id]
        default_location = f"ORDER_OBSERVATION[{group.index}]" if group else "message"
        self.findings.append(Finding(
            severity=rule["severity"],
            rule_id=rule_id,
            location=location or default_location,
            line_number=line,
            message=message,
            expected_behavior=rule["expected"],
            source_section=rule["section"],
        ))

    def api_failure(self, error: SeerError | str, group: GroupExtraction | None = None) -> None:
        kind = error.kind if isinstance(error, SeerError) else error
        if kind in self.failure_kinds:
            return
        self.failure_kinds.add(kind)
        if kind in {"authentication", "rate-limit", "network", "budget"}:
            self.blocked_online = True
        labels = {
            "no-key": "No SEER API key was available",
            "authentication": "SEER rejected the API key",
            "rate-limit": "SEER rate limiting or access policy blocked a request",
            "network": "A SEER network request failed",
            "bad-response": "SEER returned an unusable response",
            "budget": "The content-check request budget was reached",
            "bad-input": "No pinned SEER algorithm covers the extracted year",
        }
        self.add("CONTENT-API-01", group, group.line_number if group else None, labels.get(kind, "A SEER request failed") + "; affected online checks were skipped.")

    def call(self, group: GroupExtraction | None, function: Callable[[], object]) -> object | None:
        if self.blocked_online:
            self.skipped_online = True
            return None
        try:
            return function()
        except SeerError as error:
            self.api_failure(error, group)
            self.skipped_online = True
            return None


def _local_checks(evaluation: _Evaluation) -> None:
    for group in evaluation.extraction.groups:
        for field, line in group.conflicts:
            evaluation.add(
                "CONTENT-EXTRACT-01",
                group,
                line,
                f"Conflicting {field} candidates were found, so that field was not sent or checked.",
                location=f"ORDER_OBSERVATION[{group.index}].{field}",
            )
        template = _template(group.template_key)
        prefixes = template.get("site_prefixes", []) if template else []
        if group.site and prefixes and not any(group.site.startswith(prefix) for prefix in prefixes):
            evaluation.add(
                "CONTENT-SITE-01",
                group,
                group.site_line,
                "The extracted primary-site code does not match the recognized template family.",
                location=f"ORDER_OBSERVATION[{group.index}].site",
            )
        if group.site_assumed_nos:
            evaluation.coverage.append(f"Order group {group.index}: a three-character topography code was normalized to its NOS subsite.")
        if group.template_line and not group.template_key:
            evaluation.coverage.append(
                f"Order group {group.index}: template metadata was present but did not match a configured template family; template-coherence checks were skipped."
            )
        if group.year_source:
            evaluation.coverage.append(
                f"Order group {group.index}: the year used for SEER selection was inferred from {group.year_source}; it is not a dedicated registry diagnosis date."
            )


def _check_schema_fields(
    evaluation: _Evaluation,
    client: SeerClient,
    group: GroupExtraction,
    algorithm: str,
    version: str,
    schema: dict[str, object],
) -> None:
    inputs = [item for item in schema.get("inputs", []) if isinstance(item, dict)]
    available = {
        "site": group.site,
        "hist": group.histology,
        "behavior": group.behavior,
        "year_dx": group.year,
        "grade_path": group.grade,
        "grade_clin": group.grade,
        "grade": group.grade,
    }
    missing = sorted({
        str(item.get("key"))
        for item in inputs
        if item.get("used_for_staging") is True
        and item.get("default") is None
        and not available.get(str(item.get("key")))
    })
    if missing:
        evaluation.add(
            "CONTENT-FIELD-02",
            group,
            group.line_number,
            f"The selected schema has {len(missing)} non-default staging input(s) that were not extracted: {', '.join(missing)}.",
        )

    checks: list[tuple[str, str | None, int | None, list[str]]] = [
        ("CONTENT-FIELD-01", group.behavior, group.behavior_line, ["behavior"]),
        ("CONTENT-FIELD-03", group.grade, group.grade_line, ["grade_path", "grade_clin", "grade"]),
    ]
    for rule_id, value, line, keys in checks:
        if value is None:
            continue
        input_definition = next((item for key in keys for item in inputs if item.get("key") == key and item.get("table")), None)
        if input_definition is None:
            evaluation.coverage.append(f"Order group {group.index}: the selected schema did not publish a table for the extracted {keys[-1]} value.")
            continue
        table_id = str(input_definition["table"])
        table = evaluation.call(group, lambda table_id=table_id: client.table(algorithm, version, table_id))
        if isinstance(table, dict) and not _table_contains(table, value):
            field_name = "behavior" if rule_id == "CONTENT-FIELD-01" else "grade"
            evaluation.add(
                rule_id,
                group,
                line,
                f"The extracted {field_name} code is not present in the selected schema's value table.",
                location=f"ORDER_OBSERVATION[{group.index}].{field_name}",
            )


def _check_dictionary(evaluation: _Evaluation, client: SeerClient, group: GroupExtraction) -> None:
    for field_name, value, line in (
        ("laterality", group.laterality, group.laterality_line),
        ("grade", group.grade, group.grade_line),
    ):
        if value is None:
            continue
        item_number = CONTENT["naaccr_items"][field_name]
        item = evaluation.call(group, lambda item_number=item_number: client.naaccr_item(CONTENT["naaccr_version"], item_number))
        if not isinstance(item, dict):
            continue
        allowed = item.get("allowed_codes")
        if not isinstance(allowed, list) or not allowed:
            evaluation.coverage.append(f"Order group {group.index}: NAACCR item {item_number} did not publish a discrete allowed-code list.")
            continue
        codes = {str(entry.get("code")) for entry in allowed if isinstance(entry, dict) and entry.get("code") is not None}
        if value not in codes:
            evaluation.add(
                "CONTENT-DICT-01",
                group,
                line,
                f"The extracted {field_name} code is not in NAACCR item {item_number}'s allowed-code list.",
                location=f"ORDER_OBSERVATION[{group.index}].{field_name}",
            )


def _check_hematopoietic(evaluation: _Evaluation, client: SeerClient, group: GroupExtraction) -> None:
    if group.histology is None or int(group.histology) < int(CONTENT["heme_histology_min"]):
        return
    if group.behavior is None:
        evaluation.skipped_online = True
        evaluation.coverage.append(f"Order group {group.index}: hematopoietic lookup was skipped because no behavior code was extracted.")
        return
    morphology = f"{group.histology}/{group.behavior}"
    search = evaluation.call(group, lambda: client.disease_search(morphology))
    if not isinstance(search, dict):
        return
    results = search.get("results")
    if not isinstance(results, list) or not results:
        evaluation.add("CONTENT-HEME-01", group, group.histology_line, "The extracted hematopoietic morphology was not found in the SEER disease database.")
        return
    exact = None
    for result in results[:10]:
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            continue
        detail = evaluation.call(group, lambda disease_id=result["id"]: client.disease(disease_id))
        if isinstance(detail, dict) and detail.get("icdO3_morphology") == morphology:
            exact = detail
            break
    if exact is None:
        if not evaluation.failure_kinds:
            evaluation.add("CONTENT-HEME-01", group, group.histology_line, "The extracted hematopoietic morphology was not found as an exact SEER disease code.")
        return
    validity = exact.get("valid")
    if group.year and isinstance(validity, dict):
        start = validity.get("start")
        end = validity.get("end")
        year = int(group.year)
        if (isinstance(start, int) and year < start) or (isinstance(end, int) and year > end):
            evaluation.add("CONTENT-HEME-02", group, group.year_line, "The diagnosis year is outside the SEER validity range for the extracted morphology.")


def _online_group_checks(evaluation: _Evaluation, client: SeerClient, group: GroupExtraction) -> None:
    if not group.site or not group.histology:
        evaluation.skipped_online = True
        evaluation.coverage.append(f"Order group {group.index}: site and histology are both needed for staging and site-recode checks.")
        _check_hematopoietic(evaluation, client, group)
        _check_dictionary(evaluation, client, group)
        return
    if group.year is None:
        evaluation.skipped_online = True
        evaluation.coverage.append(
            f"Order group {group.index}: no year was extracted, so current EOD data were used and year-sensitive coverage is incomplete."
        )
    try:
        algorithm, version = algorithm_for_year(group.year)
    except SeerError as error:
        evaluation.api_failure(error, group)
        evaluation.skipped_online = True
        return
    schemas = evaluation.call(
        group,
        lambda: client.schema_lookup(
            algorithm,
            version,
            site=group.site,
            histology=group.histology,
            behavior=group.behavior if group.behavior in {"0", "1", "2", "3"} else None,
            year=group.year,
        ),
    )
    if isinstance(schemas, list):
        if not schemas:
            evaluation.add("CONTENT-COMBO-01", group, group.site_line or group.histology_line, "The pinned staging algorithm returned no schema for the extracted site and histology.")
        elif len(schemas) > 1:
            evaluation.add("CONTENT-COMBO-02", group, group.site_line or group.histology_line, f"The pinned staging algorithm returned {len(schemas)} schemas; schema-specific field checks were skipped.")
            evaluation.skipped_online = True
        else:
            schema_id = schemas[0].get("id")
            if not isinstance(schema_id, str):
                evaluation.api_failure(SeerError("bad-response", "Schema id is missing."), group)
                evaluation.skipped_online = True
            else:
                template = _template(group.template_key)
                expected = template.get("expected_schema_ids", []) if template else []
                if expected and schema_id not in expected:
                    evaluation.add("CONTENT-COMBO-03", group, group.template_line or group.site_line, "The selected SEER schema does not match the recognized template family.")
                schema = evaluation.call(group, lambda: client.schema(algorithm, version, schema_id))
                if isinstance(schema, dict):
                    _check_schema_fields(evaluation, client, group, algorithm, version, schema)

    recode = evaluation.call(
        group,
        lambda: client.site_recode(
            group.site,
            group.histology,
            group.behavior if group.behavior in {"0", "1", "2", "3"} else None,
        ),
    )
    if isinstance(recode, dict):
        site_group = str(recode.get("site_group"))
        evaluation.add("CONTENT-RECODE-01", group, group.site_line, f"SEER site-recode group: {site_group}.")
        template = _template(group.template_key)
        expected_recode = template.get("expected_recode_codes", []) if template else []
        if expected_recode and site_group not in expected_recode:
            evaluation.add("CONTENT-RECODE-02", group, group.template_line or group.site_line, "The SEER site-recode group does not match the recognized template family.")
    _check_hematopoietic(evaluation, client, group)
    _check_dictionary(evaluation, client, group)


def _pair_checks(evaluation: _Evaluation, client: SeerClient) -> None:
    eligible = [group for group in evaluation.extraction.groups if group.site and group.histology]
    for first, second in combinations(eligible, 2):
        if (
            first.behavior and second.behavior and first.year and second.year
            and int(first.histology or 0) >= int(CONTENT["heme_histology_min"])
            and int(second.histology or 0) >= int(CONTENT["heme_histology_min"])
        ):
            same = evaluation.call(
                first,
                lambda: client.same_primary(
                    f"{first.histology}/{first.behavior}",
                    f"{second.histology}/{second.behavior}",
                    first.year,
                    second.year,
                ),
            )
            if isinstance(same, dict):
                classification = "the same primary" if same.get("is_same") is True else "different primaries"
                evaluation.add("CONTENT-MPH-01", first, first.line_number, f"SEER hematopoietic rules classify groups {first.index} and {second.index} as {classification}.")
        result = evaluation.call(first, lambda: client.mph(first.outbound_codes(), second.outbound_codes()))
        if isinstance(result, dict):
            classification = str(result.get("result", "UNKNOWN"))
            step = result.get("step")
            suffix = f" at rule {step}" if isinstance(step, str) and step else ""
            evaluation.add("CONTENT-MPH-01", first, first.line_number, f"SEER multiple-primary rules classify groups {first.index} and {second.index} as {classification}{suffix}.")


def validate_content(
    text: str,
    *,
    transport: Transport | None = None,
    cache: Cache | None = None,
    syntax_valid: bool | None = None,
) -> ContentReport:
    syntax_report = validate_message(text)
    syntax_ok = syntax_report.valid if syntax_valid is None else syntax_valid
    extraction = extract_content(text)
    evaluation = _Evaluation(extraction)
    _local_checks(evaluation)
    client = None
    key_warning = None
    if transport is None:
        api_key, key_warning = load_api_key()
        if api_key:
            transport = UrllibTransport(api_key)
    if key_warning:
        evaluation.coverage.append(key_warning)
    if not extraction.has_registry_codes:
        status = "not-applicable"
        evaluation.coverage.append("No registry site or histology codes were extracted, so no SEER request was needed.")
    elif not syntax_ok:
        status = "partial"
        evaluation.skipped_online = True
        evaluation.coverage.append("Online content checks were skipped because syntax validation found errors.")
    elif transport is None:
        status = "partial"
        evaluation.api_failure("no-key")
        evaluation.skipped_online = True
    else:
        client = SeerClient(transport, cache=cache or DiskCache())
        for group in extraction.groups:
            _online_group_checks(evaluation, client, group)
        _pair_checks(evaluation, client)
        status = "partial" if evaluation.failure_kinds or evaluation.skipped_online else "complete"
    findings = tuple(sorted(evaluation.findings, key=lambda finding: (finding.line_number or 0, finding.rule_id, finding.location)))
    counts = {severity: sum(finding.severity == severity for finding in findings) for severity in ("error", "warning", "information")}
    return ContentReport(
        schema_version=CONTENT["schema_version"],
        content_ruleset_version=CONTENT["content_ruleset_version"],
        profile=CATALOG["profile"],
        based_on={
            "ruleset_version": syntax_report.ruleset_version,
            "detected_report_style": syntax_report.detected_report_style,
            "syntax_valid": syntax_ok,
        },
        status=status,
        valid=counts["error"] == 0,
        counts=counts,
        findings=findings,
        extraction=extraction.to_dict(),
        queries=client.queries if client else (),
        coverage_notices=tuple(dict.fromkeys(evaluation.coverage)),
        attribution=CONTENT["attribution"],
    )
