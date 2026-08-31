from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lri_validator import validate_content
from lri_validator.seer import MemoryCache, SeerClient, UrllibTransport, load_api_key


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tests" / "fixtures" / "seer"


def canonical_request(method: str, url: str, body: dict[str, object] | None) -> str:
    return json.dumps({"method": method, "url": url, "body": body}, sort_keys=True, separators=(",", ":"))


class RecordingTransport:
    def __init__(self, delegate: UrllibTransport) -> None:
        self.delegate = delegate
        self.entries: dict[str, tuple[int, object]] = {}

    def __call__(self, method: str, url: str, body: dict[str, object] | None) -> tuple[int, object]:
        status, data = self.delegate(method, url, body)
        self.entries[canonical_request(method, url, body)] = (status, data)
        return status, data


def record() -> int:
    api_key, warning = load_api_key()
    if warning:
        print(f"warning: {warning}")
    if not api_key:
        raise SystemExit("SEER_API_KEY or a private ~/.seerapi apikey entry is required.")
    transport = RecordingTransport(UrllibTransport(api_key))
    cache = MemoryCache()
    fixtures = [
        *sorted((ROOT / "tests" / "fixtures" / "valid").glob("*.hl7")),
        ROOT / "tests" / "fixtures" / "content" / "two-group-mph.hl7",
    ]
    for fixture in fixtures:
        validate_content(fixture.read_text(encoding="utf-8"), transport=transport, cache=cache, syntax_valid=True)
    client = SeerClient(transport, cache=cache)
    client.schema_lookup("eod_public", "3.3", site="C999", histology="1234", behavior="3", year="2026")
    client.site_recode("C999", "1234", "3")
    client.schema_lookup("eod_public", "3.3", site="C349", histology="8140", behavior="3")
    client.site_recode("C349", "8140", "3")
    client.schema_lookup("eod_public", "3.3", site="C504", histology="8500", year="2026")
    client.site_recode("C504", "8500", None)
    client.schema_lookup("eod_public", "3.3", site="C421", histology="9999", behavior="3", year="2026")
    client.site_recode("C421", "9999", "3")
    client.disease_search("9999/3")
    client.same_primary("9732/3", "9732/3", "2026", "2026")

    DESTINATION.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict[str, object]] = {}
    for request, (status, data) in sorted(transport.entries.items()):
        digest = hashlib.sha256(request.encode("utf-8")).hexdigest()[:20]
        filename = f"response-{digest}.json"
        (DESTINATION / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        index[request] = {"status": status, "file": filename}
    (DESTINATION / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded {len(index)} SEER responses in {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(record())
