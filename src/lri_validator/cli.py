from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .content_rules import validate_content
from .seer import DiskCache, MemoryCache, UrllibTransport, load_api_key
from .validator import UnsupportedInputError, validate_message


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lri-validate", description="Validate one NAACCR LRI ORU_R01 message.")
    parser.add_argument("path", help="Message file path, or - for standard input")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--content", action="store_true", help="Run the optional online SEER registry-content checks")
    parser.add_argument("--no-cache", action="store_true", help="Do not use the on-disk SEER response cache")
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


def _content_text(report: object | None) -> str:
    if report is None:
        return "Registry content: SKIPPED because syntax validation found errors"
    if report.status == "not-applicable":
        label = "NOT APPLICABLE"
    elif report.status == "partial":
        label = "INCOMPLETE"
    else:
        label = "PASS" if report.valid else "FAIL"
    lines = [
        f"Registry content: {label}",
        f"Findings: {report.counts['error']} error(s), {report.counts['warning']} warning(s), {report.counts['information']} information notice(s)",
    ]
    for finding in report.findings:
        line = f"line {finding.line_number}" if finding.line_number else "message"
        lines.append(f"{finding.severity.upper():11} {finding.rule_id:20} {finding.location} ({line}): {finding.message}")
    lines.append(report.attribution)
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
    content_report = None
    if args.content and report.valid:
        api_key, warning = load_api_key()
        if warning:
            print(f"lri-validate: warning: {warning}", file=sys.stderr)
        transport = UrllibTransport(api_key) if api_key else None
        cache = MemoryCache() if args.no_cache else DiskCache()
        content_report = validate_content(
            value,
            transport=transport,
            cache=cache,
            syntax_valid=report.valid,
        )
    if args.format == "json":
        if args.content:
            envelope = {
                "schema_version": report.schema_version,
                "syntax": report.to_dict(),
                "content": content_report.to_dict() if content_report else None,
            }
            print(json.dumps(envelope, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        output = _text(report)
        if args.content:
            output += "\n\n" + _content_text(content_report)
        print(output)
    return 0 if report.valid and (content_report is None or content_report.valid) else 1


if __name__ == "__main__":
    raise SystemExit(main())
