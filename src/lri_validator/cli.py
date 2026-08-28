from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .validator import UnsupportedInputError, validate_message


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lri-validate", description="Validate one NAACCR LRI ORU_R01 message.")
    parser.add_argument("path", help="Message file path, or - for standard input")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _text(report: object) -> str:
    lines = [
        f"NAACCR LRI: {'PASS' if report.valid else 'FAIL'}",
        f"Style: {report.detected_report_style}",
        f"Findings: {report.counts['error']} error(s), {report.counts['warning']} warning(s), {report.counts['information']} information notice(s)",
    ]
    for finding in report.findings:
        line = f"line {finding.line_number}" if finding.line_number else "message"
        lines.append(f"{finding.severity.upper():11} {finding.rule_id:20} {finding.location} ({line}): {finding.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.path == "-":
            value = sys.stdin.read()
        else:
            value = Path(args.path).read_text(encoding="utf-8-sig")
        report = validate_message(value)
    except (OSError, UnicodeError, UnsupportedInputError) as exc:
        print(f"lri-validate: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_text(report))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
