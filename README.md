# NAACCR LRI offline validator

This project validates one HL7 v2.5.1 `ORU^R01^ORU_R01` cancer-pathology message against locally computable requirements in the pinned May 2026 LRI ballot draft. It is an implementation aid, not an HL7 or NIST certification service.

## Browser use

Open `dist/naaccr-lri-validator.html` directly from Finder. Paste a message or choose one `.hl7`, `.er7`, or `.txt` file, then select **Validate message**. The page has no remote dependencies, makes no network requests, and does not use cookies or browser storage.

Some browser launch paths block scripts in a directly opened local HTML file. If the page reports that its interactive controls did not start, serve the same file on the loopback interface from the repository root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Then open <http://127.0.0.1:8000/naaccr-lri-validator.html>. Stop the optional server with `Ctrl-C`. It accepts connections only from this computer, and validation still occurs entirely in the browser tab.

The finding list can be filtered by severity. Selecting a finding focuses the associated message line. JSON and print reports contain finding metadata only; they exclude the raw message and clinical values.

## Python and CLI

Python 3.10 or later is required. The package pins HL7apy 1.3.5 for HL7 v2.5.1 parsing.

```sh
uv sync --extra test
uv run lri-validate tests/fixtures/valid/cap-ecp.hl7
uv run lri-validate message.hl7 --format json
cat message.hl7 | uv run lri-validate -
```

The public API is:

```python
from lri_validator import validate_message

report = validate_message(message_text)
```

CLI exit codes are `0` when no errors are found, `1` when validation errors are found, and `2` for unreadable or unsupported input. Version 1 rejects batches, multiple messages, and incomplete MLLP frames.

## Coverage boundary

The rule catalog covers message identity, delimiters, segment structure, required and expected-when-known fields, cardinality, set IDs, NG-FRU and NAACCR profile identifiers, eight NAACCR identifier rules, local date/status relationships, the five report styles, table-listed report/section LOINCs, OBX-4 patterns, CAP eCP identifier/repeat/link syntax, and draft-enumerated SPM-9 laterality codes.

The validator does not claim terminology membership checks for `_NAACCR` companion tables, the unresolved SPM-4 SNOMED CT subset, annual reportability lists, the CAP eCP dictionary, or other external releases. CAP eCP content is checked for syntax and message relationships, not against CAP-controlled artifacts.

## Build and test

`src/lri_validator/catalog.json` is the versioned source for constants, severity, source references, and coverage notices. The HTML build injects that catalog into the browser implementation.

```sh
uv run python scripts/build_html.py
uv run pytest
git diff --check
```

The build is deterministic. `dist/naaccr-lri-validator.html` remains tracked so it can be used without Python or a web server.

## Privacy

Messages stay in the current process or browser tab. The project does not log, transmit, or persist message content. The tracked fixtures are independently synthetic and contain no patient, provider, facility, accession, or message values from the ballot draft.

See [NOTICE.md](NOTICE.md) for source attribution and use limits.
