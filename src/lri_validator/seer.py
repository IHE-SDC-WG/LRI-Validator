from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .validator import CATALOG


CONTENT = CATALOG["content"]
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
SITE_RE = re.compile(r"^C\d{3}$")
HIST_RE = re.compile(r"^\d{4}$")
BEHAVIOR_RE = re.compile(r"^[0-9]$")
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
LATERALITY_RE = re.compile(r"^[0-9]$")
GRADE_RE = re.compile(r"^[0-9A-Z.]{1,8}$")
MORPHOLOGY_RE = re.compile(r"^\d{4}/[0-9]$")
MISSING = object()


class SeerError(RuntimeError):
    def __init__(self, kind: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


class Transport(Protocol):
    def __call__(self, method: str, url: str, body: dict[str, object] | None) -> tuple[int, object]: ...


class UrllibTransport:
    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        if not api_key.strip():
            raise ValueError("A non-empty SEER API key is required.")
        self._api_key = api_key.strip()
        self._timeout = timeout

    def __call__(self, method: str, url: str, body: dict[str, object] | None) -> tuple[int, object]:
        payload = None if body is None else json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json", "X-SEERAPI-Key": self._api_key}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status_code = response.status
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            raw = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SeerError("network", "The SEER API request could not be completed.") from exc
        if not raw:
            return status_code, None
        try:
            return status_code, json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SeerError("bad-response", "The SEER API returned a non-JSON response.", status=status_code) from exc


@dataclass(frozen=True, slots=True)
class CachedResponse:
    stored_at: float
    status: int
    data: object


class Cache(Protocol):
    def get(self, key: str, *, max_age: int | None) -> CachedResponse | object: ...
    def put(self, key: str, response: CachedResponse) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._values: dict[str, CachedResponse] = {}

    def get(self, key: str, *, max_age: int | None) -> CachedResponse | object:
        response = self._values.get(key, MISSING)
        if response is MISSING:
            return MISSING
        assert isinstance(response, CachedResponse)
        if max_age is not None and time.time() - response.stored_at > max_age:
            return MISSING
        return response

    def put(self, key: str, response: CachedResponse) -> None:
        self._values[key] = response


class DiskCache:
    def __init__(self, root: Path | None = None) -> None:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.root = root or base / "lri-validator" / "seer"

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str, *, max_age: int | None) -> CachedResponse | object:
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            response = CachedResponse(
                stored_at=float(payload["stored_at"]),
                status=int(payload["status"]),
                data=payload["data"],
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return MISSING
        if max_age is not None and time.time() - response.stored_at > max_age:
            return MISSING
        return response

    def put(self, key: str, response: CachedResponse) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        value = json.dumps(
            {"stored_at": response.stored_at, "status": response.status, "data": response.data},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        descriptor, temporary = tempfile.mkstemp(prefix=".seer-", suffix=".tmp", dir=self.root)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(value)
                handle.write("\n")
            os.replace(temporary, self._path(key))
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def load_api_key(env: dict[str, str] | None = None, path: Path | None = None) -> tuple[str | None, str | None]:
    environ = os.environ if env is None else env
    value = environ.get("SEER_API_KEY", "").strip()
    if value:
        return value, None
    config = path or Path.home() / ".seerapi"
    try:
        mode = stat.S_IMODE(config.stat().st_mode)
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    key = next((line.split("=", 1)[1].strip() for line in lines if line.strip().startswith("apikey=")), "")
    warning = None
    if mode & 0o077:
        warning = f"{config} is readable by group or other users; use chmod 600."
    return key or None, warning


def algorithm_for_year(year: str | None) -> tuple[str, str]:
    numeric = int(year) if year and YEAR_RE.fullmatch(year) else 9999
    for entry in CONTENT["algorithm_by_year"]:
        if numeric >= int(entry["from_year"]):
            return entry["algorithm"], entry["version"]
    raise SeerError("bad-input", "No pinned SEER staging algorithm covers the extracted diagnosis year.")


def _validated(value: str, pattern: re.Pattern[str], name: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"Invalid {name} value.")
    return value


class SeerClient:
    def __init__(
        self,
        transport: Transport,
        *,
        cache: Cache | None = None,
        max_calls: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._transport = transport
        self._cache = cache or MemoryCache()
        self._max_calls = int(max_calls or CONTENT["max_api_calls"])
        self._clock = clock
        self._network_calls = 0
        self._queries: list[dict[str, object]] = []
        self._base = CONTENT["seer_base_url"]

    @property
    def queries(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(query) for query in self._queries)

    @property
    def network_calls(self) -> int:
        return self._network_calls

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
        mutable: bool = False,
    ) -> object:
        if method not in {"GET", "POST"} or path.startswith("/") or ".." in path:
            raise ValueError("Invalid SEER request path.")
        url = self._base + path
        if query:
            url += "?" + urllib.parse.urlencode(sorted(query.items()))
        if not url.startswith(self._base):
            raise ValueError("Blocked non-SEER request URL.")
        canonical = json.dumps(
            {"method": method, "url": url, "body": body},
            sort_keys=True,
            separators=(",", ":"),
        )
        cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        max_age = int(CONTENT["cache_ttl_seconds"]) if mutable else None
        cached = self._cache.get(cache_key, max_age=max_age)
        if cached is not MISSING:
            assert isinstance(cached, CachedResponse)
            self._queries.append({"method": method, "url": url, "body": body, "cached": True, "status": cached.status})
            return cached.data
        if self._network_calls >= self._max_calls:
            self._queries.append({"method": method, "url": url, "body": body, "cached": False, "status": "budget"})
            raise SeerError("budget", "The registry-content request budget was reached.")
        self._network_calls += 1
        try:
            status_code, data = self._transport(method, url, body)
        except SeerError:
            self._queries.append({"method": method, "url": url, "body": body, "cached": False, "status": "network"})
            raise
        self._queries.append({"method": method, "url": url, "body": body, "cached": False, "status": status_code})
        if status_code == 401:
            raise SeerError("authentication", "The SEER API rejected the API key.", status=status_code)
        if status_code in {403, 429}:
            raise SeerError("rate-limit", "The SEER API rate limit or access policy blocked the request.", status=status_code)
        if status_code < 200 or status_code >= 300:
            raise SeerError("bad-response", f"The SEER API returned HTTP {status_code}.", status=status_code)
        response = CachedResponse(self._clock(), status_code, data)
        self._cache.put(cache_key, response)
        return data

    def schema_lookup(
        self,
        algorithm: str,
        version: str,
        *,
        site: str,
        histology: str,
        behavior: str | None = None,
        year: str | None = None,
    ) -> list[dict[str, object]]:
        algorithm = _validated(algorithm, TOKEN_RE, "algorithm")
        version = _validated(version, TOKEN_RE, "version")
        body: dict[str, object] = {
            "site": _validated(site, SITE_RE, "site"),
            "hist": _validated(histology, HIST_RE, "histology"),
        }
        if behavior is not None:
            body["behavior"] = _validated(behavior, BEHAVIOR_RE, "behavior")
        if year is not None:
            body["year_dx"] = _validated(year, YEAR_RE, "year")
        data = self._request("POST", f"staging/{algorithm}/{version}/schemas/lookup", body=body)
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise SeerError("bad-response", "The SEER schema lookup response has an unexpected shape.")
        return data

    def schema(self, algorithm: str, version: str, schema_id: str) -> dict[str, object]:
        parts = [_validated(value, TOKEN_RE, name) for value, name in ((algorithm, "algorithm"), (version, "version"), (schema_id, "schema id"))]
        data = self._request("GET", f"staging/{parts[0]}/{parts[1]}/schema/{parts[2]}")
        if not isinstance(data, dict) or not isinstance(data.get("inputs"), list):
            raise SeerError("bad-response", "The SEER schema response has an unexpected shape.")
        return data

    def table(self, algorithm: str, version: str, table_id: str) -> dict[str, object]:
        parts = [_validated(value, TOKEN_RE, name) for value, name in ((algorithm, "algorithm"), (version, "version"), (table_id, "table id"))]
        data = self._request("GET", f"staging/{parts[0]}/{parts[1]}/table/{parts[2]}")
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise SeerError("bad-response", "The SEER staging table response has an unexpected shape.")
        return data

    def naaccr_item(self, version: str, item: str) -> dict[str, object]:
        version = _validated(version, TOKEN_RE, "NAACCR version")
        item = _validated(item, re.compile(r"^\d{1,4}$"), "NAACCR item")
        data = self._request("GET", f"naaccr/{version}/{item}")
        if not isinstance(data, dict):
            raise SeerError("bad-response", "The SEER NAACCR item response has an unexpected shape.")
        return data

    def disease_search(self, morphology: str) -> dict[str, object]:
        morphology = _validated(morphology, MORPHOLOGY_RE, "morphology")
        version = _validated(CONTENT["disease_version"], TOKEN_RE, "disease version")
        data = self._request(
            "GET",
            f"disease/{version}",
            query={"q": morphology, "type": "HEMATO"},
            mutable=True,
        )
        if not isinstance(data, dict) or not ({"results", "total", "count"} & set(data)):
            raise SeerError("bad-response", "The SEER disease search response has an unexpected shape.")
        return data

    def disease(self, disease_id: str) -> dict[str, object]:
        version = _validated(CONTENT["disease_version"], TOKEN_RE, "disease version")
        disease_id = _validated(disease_id, TOKEN_RE, "disease id")
        data = self._request("GET", f"disease/{version}/id/{disease_id}", mutable=True)
        if not isinstance(data, dict):
            raise SeerError("bad-response", "The SEER disease response has an unexpected shape.")
        return data

    def same_primary(self, morphology1: str, morphology2: str, year1: str, year2: str) -> dict[str, object]:
        version = _validated(CONTENT["disease_version"], TOKEN_RE, "disease version")
        query = {
            "d1": _validated(morphology1, MORPHOLOGY_RE, "morphology"),
            "d2": _validated(morphology2, MORPHOLOGY_RE, "morphology"),
            "year1": _validated(year1, YEAR_RE, "year"),
            "year2": _validated(year2, YEAR_RE, "year"),
        }
        data = self._request("GET", f"disease/{version}/same_primary", query=query, mutable=True)
        if not isinstance(data, dict) or "is_same" not in data:
            raise SeerError("bad-response", "The SEER same-primary response has an unexpected shape.")
        return data

    def site_recode(self, site: str, histology: str, behavior: str | None) -> dict[str, object]:
        algorithm = _validated(CONTENT["site_recode_algorithm"], TOKEN_RE, "site-recode algorithm")
        query = {
            "site": _validated(site, SITE_RE, "site"),
            "hist": _validated(histology, HIST_RE, "histology"),
        }
        if behavior is not None:
            query["behavior"] = _validated(behavior, BEHAVIOR_RE, "behavior")
        data = self._request("GET", f"recode/sitegroup/{algorithm}", query=query, mutable=True)
        if not isinstance(data, dict) or "site_group" not in data:
            raise SeerError("bad-response", "The SEER site-recode response has an unexpected shape.")
        return data

    def mph(self, first: dict[str, str], second: dict[str, str]) -> dict[str, object]:
        def item(values: dict[str, str]) -> dict[str, str]:
            result = {
                "primary_site": _validated(values["site"], SITE_RE, "site"),
                "histology_icd_o3": _validated(values["hist"], HIST_RE, "histology"),
            }
            optional = {
                "behavior": ("behavior_icd_o3", BEHAVIOR_RE),
                "laterality": ("laterality", LATERALITY_RE),
                "year": ("date_of_diagnosis_year", YEAR_RE),
            }
            for source, (target, pattern) in optional.items():
                if values.get(source) is not None:
                    result[target] = _validated(values[source], pattern, source)
            return result

        data = self._request("POST", "mph", body={"input1": item(first), "input2": item(second)}, mutable=True)
        if not isinstance(data, dict) or "result" not in data:
            raise SeerError("bad-response", "The SEER multiple-primary response has an unexpected shape.")
        return data
