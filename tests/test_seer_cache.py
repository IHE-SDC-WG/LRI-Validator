from __future__ import annotations

import json
import time

from lri_validator.seer import CachedResponse, DiskCache, MemoryCache, MISSING, SeerClient


def test_memory_cache_prevents_repeat_transport_calls() -> None:
    calls = []

    def transport(method, url, body):
        calls.append((method, url, body))
        return 200, []

    client = SeerClient(transport, cache=MemoryCache())
    client.schema_lookup("eod_public", "3.3", site="C504", histology="8500")
    client.schema_lookup("eod_public", "3.3", site="C504", histology="8500")
    assert len(calls) == 1
    assert client.queries[-1]["cached"] is True


def test_disk_cache_permissions_expiry_and_corruption(tmp_path) -> None:
    cache = DiskCache(tmp_path / "seer")
    cache.put("fresh", CachedResponse(time.time(), 200, {"ok": True}))
    path = cache.root / "fresh.json"
    assert path.stat().st_mode & 0o077 == 0
    assert cache.get("fresh", max_age=60).data == {"ok": True}

    cache.put("old", CachedResponse(time.time() - 120, 200, []))
    assert cache.get("old", max_age=60) is MISSING
    (cache.root / "broken.json").write_text("not-json", encoding="utf-8")
    assert cache.get("broken", max_age=None) is MISSING


def test_disk_cache_payload_is_codes_only(tmp_path) -> None:
    cache = DiskCache(tmp_path / "seer")
    cache.put("entry", CachedResponse(time.time(), 200, {"site": "C504", "hist": "8500"}))
    payload = json.loads((cache.root / "entry.json").read_text())
    assert payload["data"] == {"site": "C504", "hist": "8500"}
