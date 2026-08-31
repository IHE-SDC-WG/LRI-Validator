# NAACCR LRI validator

This project validates one HL7 v2.5.1 `ORU^R01^ORU_R01` cancer-pathology message against locally computable requirements in the pinned May 2026 LRI ballot draft. It is an implementation aid, not an HL7 or NIST certification service.

Syntax validation is offline. An optional, user-started registry-content check can query the SEER API for site and histology compatibility, schema-specific field domains, hematopoietic morphology, NAACCR allowed codes, site recode, and multiple-primary rules.

## Funding acknowledgment

This work was conducted under the following Centers for Disease Control and Prevention (CDC) Notice of Funding Opportunity (NOFO):

- **NOFO number:** `CDC-RFA-DP-23-0008-03-CONT26`
- **Program:** National Partnerships to Promote Cancer Surveillance Standards and Support Data Quality and Operations of National Programs of Cancer Registries (NPCR)
- **CDC center:** National Center for Chronic Disease Prevention and Health Promotion (NCCDPHP)

## Browser use

Open `dist/naaccr-lri-validator.html` directly from Finder. Paste a message or choose one `.hl7`, `.er7`, or `.txt` file, then select **Validate message**. The syntax check has no remote dependencies, makes no network requests, and does not use cookies or browser storage.

Some browser launch paths block scripts in a directly opened local HTML file. If the page reports that its controls did not start, serve the same file on the loopback interface from the repository root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Then open <http://127.0.0.1:8000/naaccr-lri-validator.html>. Stop the optional server with `Ctrl-C`.

The finding list can be filtered by severity. Selecting a finding focuses the associated message line. JSON and print reports omit the raw message and arbitrary clinical text.

## Registry content check (optional, online)

The content panel appears only after a syntax-valid message contains extractable registry codes. All bundled examples include independently synthetic site and histology data and can run the SEER check. Before any request, the panel lists each normalized message-derived item, its message line, and the value proposed for transmission. You must enter a [free SEER API key](https://api.seer.cancer.gov/login) and select **Check registry content**. Returned requests use readable descriptions; each description can be opened to inspect the exact method, URL, body, cache state, and HTTP status.

The browser sends only the extracted fields listed in the review panel. Primary site, histology, behavior, and diagnosis year are sent when applicable. Laterality is sent only when two order groups qualify for a multiple-primary comparison. Grade is checked locally against SEER reference data and is not sent. Follow-up calls also send SEER algorithm, version, schema, table, NAACCR item, and disease identifiers. The full HL7 message, patient identifiers, provider identifiers, facility identifiers, and arbitrary narrative text are never sent.

The extractor can read an ICD-O topography from the structured specimen type or source-site fields, SPM-4 and SPM-8, as well as from report observations. LRI does not carry a dedicated registry diagnosis-date item in this flow. When a year is available, the validator infers it from SPM-17 first and OBR-7 second, labels that source in the report, and includes a coverage notice.

These codes are sensitive clinical metadata. SEER and network operators can also observe the API account and source IP address. The page keeps the API key only in memory, sends it in the `X-SEERAPI-Key` header, and never includes it in reports. Close the tab on a shared workstation.

Results use pinned EOD 3.3, TNM 2.1, CS 02.05.50, and NAACCR 26 data. The SEER disease database and site-recode service expose mutable endpoints, so those cached responses expire after seven days. SEER currently documents a limit of 5,000 calls per 60 minutes per account. Each run has an additional local cap of 40 calls.

Content status has three meanings:

- `complete`: every applicable online check finished.
- `partial`: one or more checks were skipped because of missing codes, an ambiguous schema, no key, a request failure, or the call cap.
- `not-applicable`: no site or histology code was extracted, so no SEER request was needed.

A partial report can have no error findings, but the browser labels it **INCOMPLETE**, not PASS.

## Python and CLI

Python 3.10 or later is required. The package pins HL7apy 1.3.5 for HL7 v2.5.1 parsing.

```sh
uv sync --extra test
uv run lri-validate tests/fixtures/valid/cap-ecp.hl7
uv run lri-validate message.hl7 --format json
cat message.hl7 | uv run lri-validate -
```

Add `--content` to run the optional SEER checks. Set `SEER_API_KEY`, or create `~/.seerapi` containing an `apikey=` line. The CLI warns when that file is readable by group or other users.

```sh
SEER_API_KEY="..." uv run lri-validate --content tests/fixtures/valid/breast-synoptic-summary.hl7
uv run lri-validate --content --no-cache message.hl7 --format json
```

The default CLI text and JSON formats are unchanged. With `--content`, JSON becomes an envelope containing `syntax` and `content`; content is `null` when syntax errors prevent the online stage. The default cache is `${XDG_CACHE_HOME:-~/.cache}/lri-validator/seer/`. `--no-cache` uses a process-only memory cache.

CLI exit codes are `0` when completed checks contain no errors, `1` when syntax or content errors are found, and `2` for unreadable or unsupported input. A partial no-key or request-failure report exits `0` unless a completed local or online check found an error.

The public API is:

```python
from lri_validator import validate_content, validate_message

syntax_report = validate_message(message_text)
content_report = validate_content(message_text, syntax_valid=syntax_report.valid)
```

## Coverage boundary

The syntax catalog covers message identity, delimiters, segment structure, required and expected-when-known fields, cardinality, set IDs, NG-FRU and NAACCR profile identifiers, eight NAACCR identifier rules, local date/status relationships, the five report styles, table-listed report/section LOINCs, OBX-4 patterns, CAP eCP identifier/repeat/link syntax, and draft-enumerated SPM-9 laterality codes.

The optional content stage uses conservative extraction. Conflicting candidates are skipped. It does not claim complete cancer staging, reportability determination, CAP eCP dictionary validation, or full terminology membership. Schema field checks apply only when the selected SEER schema publishes a table for an extracted value.

## Build and test

`src/lri_validator/catalog.json` is the versioned source for constants, severity, source references, content configuration, and coverage notices. The HTML build injects that catalog and both JavaScript engines.

```sh
uv run python scripts/build_html.py
uv run pytest
git diff --check
```

Tests are offline. `tests/fixtures/seer/` contains recorded public SEER responses keyed by canonical method, URL, and body. Maintainers can refresh them with a real key:

```sh
SEER_API_KEY="..." uv run python scripts/record_seer_fixtures.py
```

The build is deterministic. The tracked HTML contains exactly one `fetch(` call site, restricted to `https://api.seer.cancer.gov/rest/`, and has no external script, style, image, form, or link attributes.

Current artifact SHA-256:

```text
ccabe3d441914a7ca6dd3104742cb0f88704c6fd926c88c10a084eab59a64326  dist/naaccr-lri-validator.html
```

## Privacy

Local syntax validation does not transmit or persist the message. The optional content check transmits only the values disclosed in its panel. Reports and cache entries contain normalized registry codes, public SEER response data, and request metadata; they do not contain the raw message or arbitrary narrative text.

All tracked HL7 fixtures are independently synthetic and contain no patient, provider, facility, accession, or message values copied from a real source. See [NOTICE.md](NOTICE.md) for attribution and use limits.
