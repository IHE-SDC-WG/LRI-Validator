from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def javascript_literal(value: object, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=indent).replace("<", "\\u003c")


def data_script(catalog: object, samples: dict[str, str]) -> str:
    lines = ["window.__LRI_CATALOG__ = " + javascript_literal(catalog, indent=2) + ";", "window.__LRI_SAMPLES__ = {};"]
    for name, message in samples.items():
        message_lines = message.splitlines()
        encoded_lines = ",\n  ".join(javascript_literal(line) for line in message_lines)
        suffix = ' + "\\n"' if message.endswith(("\r", "\n")) else ""
        lines.append(
            "window.__LRI_SAMPLES__[" + javascript_literal(name) + "] = [\n  "
            + encoded_lines + '\n].join("\\n")' + suffix + ";"
        )
    script = "\n".join(lines)
    if max(map(len, script.splitlines())) > 1000:
        raise ValueError("Generated data script contains an unexpectedly long line.")
    return script


def build() -> Path:
    template = (ROOT / "web" / "template.html").read_text(encoding="utf-8")
    validator = (ROOT / "web" / "validator.js").read_text(encoding="utf-8")
    content = (ROOT / "web" / "content.js").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    catalog = json.loads((ROOT / "src" / "lri_validator" / "catalog.json").read_text(encoding="utf-8"))
    sample_paths = [
        *sorted((ROOT / "tests" / "fixtures" / "valid").glob("*.hl7")),
        *sorted((ROOT / "tests" / "fixtures" / "negative").glob("*.hl7")),
    ]
    samples = {path.stem: path.read_text(encoding="utf-8") for path in sample_paths}
    output = (template.replace("/*__DATA__*/", data_script(catalog, samples))
        .replace("/*__VALIDATOR__*/", validator)
        .replace("/*__CONTENT__*/", content)
        .replace("/*__APP__*/", app))
    destination = ROOT / "dist" / "naaccr-lri-validator.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(output, encoding="utf-8")
    return destination


if __name__ == "__main__":
    print(build())
