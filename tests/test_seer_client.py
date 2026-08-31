from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from lri_validator import validate_content
from lri_validator.seer import MemoryCache, SeerClient, SeerError, UrllibTransport, algorithm_for_year, load_api_key
from tests.support import CONTENT_FIXTURES, FixtureTransport


def test_typed_client_uses_recorded_endpoint_contracts() -> None:
    transport = FixtureTransport()
    client = SeerClient(transport, cache=MemoryCache())
    schemas = client.schema_lookup("eod_public", "3.3", site="C504", histology="8500", behavior="3", year="2026")
    assert [schema["id"] for schema in schemas] == ["breast"]
    schema = client.schema("eod_public", "3.3", "breast")
    assert any(item["key"] == "behavior" for item in schema["inputs"])
    table = client.table("eod_public", "3.3", "behavior")
    assert ["3", "Malignant Primary"] in table["rows"]
    item = client.naaccr_item("26", "410")
    assert any(code["code"] == "2" for code in item["allowed_codes"])
    recode = client.site_recode("C504", "8500", "3")
    assert recode["site_group"] == "26000"


@pytest.mark.parametrize(
    "call",
    [
        lambda client: client.schema_lookup("eod_public", "3.3", site="C504?patient=x", histology="8500"),
        lambda client: client.schema_lookup("eod_public/../../x", "3.3", site="C504", histology="8500"),
        lambda client: client.schema("eod_public", "3.3", "breast/../../x"),
        lambda client: client.disease_search("9732/3?q=ZZPOISONZZ"),
        lambda client: client.site_recode("C504", "8500", "3&name=x"),
    ],
)
def test_hostile_builder_input_is_rejected_before_transport(call) -> None:
    transport = FixtureTransport()
    client = SeerClient(transport, cache=MemoryCache())
    with pytest.raises(ValueError):
        call(client)
    assert transport.calls == []


def test_outbound_privacy_audit_allows_only_codes_and_seer_origin() -> None:
    transport = FixtureTransport()
    value = (CONTENT_FIXTURES / "poison.hl7").read_text()
    report = validate_content(value, transport=transport, cache=MemoryCache(), syntax_valid=True)
    serialized = json.dumps(transport.calls)
    assert "ZZPOISONZZ" not in serialized
    assert "ZZPOISONZZ" not in json.dumps(report.to_dict())
    allowed_body_keys = {"site", "hist", "behavior", "year_dx", "input1", "input2"}
    allowed_mph_keys = {"primary_site", "histology_icd_o3", "behavior_icd_o3", "laterality", "date_of_diagnosis_year"}
    for method, url, body in transport.calls:
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.seer.cancer.gov"
        assert parsed.path.startswith("/rest/")
        for values in parse_qs(parsed.query).values():
            assert all(re.fullmatch(r"[A-Za-z0-9./_-]+", value) for value in values)
        if body:
            assert set(body) <= allowed_body_keys
            for pair in (body.get("input1"), body.get("input2")):
                if pair:
                    assert set(pair) <= allowed_mph_keys


def test_key_loading_prefers_environment_and_warns_on_open_file(tmp_path: Path) -> None:
    path = tmp_path / ".seerapi"
    path.write_text("apikey=file-key\n", encoding="utf-8")
    path.chmod(0o644)
    assert load_api_key({"SEER_API_KEY": " env-key "}, path) == ("env-key", None)
    key, warning = load_api_key({}, path)
    assert key == "file-key"
    assert warning and "chmod 600" in warning
    path.chmod(0o600)
    assert load_api_key({}, path) == ("file-key", None)


def test_transport_repr_does_not_expose_key() -> None:
    assert "secret-value" not in repr(UrllibTransport("secret-value"))


def test_year_selects_pinned_algorithm() -> None:
    assert algorithm_for_year("2026") == ("eod_public", "3.3")
    assert algorithm_for_year("2017") == ("tnm", "2.1")
    assert algorithm_for_year("2004") == ("cs", "02.05.50")
    with pytest.raises(SeerError) as exc:
        algorithm_for_year("2003")
    assert exc.value.kind == "bad-input"


@pytest.mark.parametrize(
    "status,kind",
    [(401, "authentication"), (429, "rate-limit"), (500, "bad-response")],
)
def test_http_error_taxonomy(status: int, kind: str) -> None:
    client = SeerClient(lambda _method, _url, _body: (status, {}), cache=MemoryCache())
    with pytest.raises(SeerError) as exc:
        client.schema_lookup("eod_public", "3.3", site="C504", histology="8500")
    assert exc.value.kind == kind


def test_network_and_budget_taxonomy() -> None:
    def failed(_method, _url, _body):
        raise SeerError("network", "offline")

    with pytest.raises(SeerError) as exc:
        SeerClient(failed, cache=MemoryCache()).schema_lookup("eod_public", "3.3", site="C504", histology="8500")
    assert exc.value.kind == "network"

    client = SeerClient(lambda _method, _url, _body: (200, []), cache=MemoryCache(), max_calls=1)
    client.schema_lookup("eod_public", "3.3", site="C504", histology="8500")
    with pytest.raises(SeerError) as exc:
        client.schema_lookup("eod_public", "3.3", site="C501", histology="8500")
    assert exc.value.kind == "budget"
    assert client.network_calls == 1
