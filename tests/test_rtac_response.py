"""Tests for create_rtac_response against a fake FolioClient.

create_rtac_response resolves the instance via FolioClient, then fetches holdings
from edge-rtac (when ``edge_rtac_url`` is set) or falls back to mod-rtac's
``/rtac/{id}`` via the gateway. ``{}`` settings exercise the mod-rtac fallback.
"""

import application
from application import create_rtac_response

from conftest import FakeFolioClient


# --- mod-rtac fallback (no edge_rtac_url) -----------------------------------


def test_returns_holdings_for_first_matching_instance():
    fake = FakeFolioClient(
        responses={
            "/instance-storage/instances": {"instances": [{"id": "i1"}, {"id": "i2"}]},
            "/rtac/": {"holdings": [{"id": "h1"}, {"id": "h2"}]},
        }
    )
    holdings = create_rtac_response(fake, {}, "?query=(x)")
    assert holdings == [{"id": "h1"}, {"id": "h2"}]
    # First the instance search, then the mod-rtac lookup for the first instance.
    assert fake.calls == ["/instance-storage/instances?query=(x)", "/rtac/i1"]


def test_no_matching_instance_returns_empty_without_rtac_call():
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": []}}
    )
    assert create_rtac_response(fake, {}, "?query=(x)") == []
    assert fake.calls == ["/instance-storage/instances?query=(x)"]


def test_missing_instances_key_returns_empty():
    fake = FakeFolioClient(responses={"/instance-storage/instances": {}})
    assert create_rtac_response(fake, {}, "?query=(x)") == []


def test_instance_without_holdings_returns_empty():
    fake = FakeFolioClient(
        responses={
            "/instance-storage/instances": {"instances": [{"id": "i1"}]},
            "/rtac/": {"holdings": []},
        }
    )
    assert create_rtac_response(fake, {}, "?query=(x)") == []


# --- edge-rtac (edge_rtac_url configured) -----------------------------------


def test_edge_rtac_used_when_url_configured(monkeypatch):
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": [{"id": "i1"}]}}
    )
    captured = {}

    def fake_edge(edge_url, instance_id, params, headers):
        captured.update(
            edge_url=edge_url, instance_id=instance_id, params=params, headers=headers
        )
        return {"instanceId": instance_id, "holdings": [{"id": "h1"}]}

    monkeypatch.setattr(application, "_edge_rtac_request", fake_edge)
    settings = {
        "edge_rtac_url": "https://edge.example/",
        "full_periodicals": True,
        "lang": "sv",
    }
    holdings = create_rtac_response(fake, settings, "?query=(x)")

    assert holdings == [{"id": "h1"}]
    # Instance search via FolioClient; holdings via edge — no mod-rtac /rtac/ call.
    assert fake.calls == ["/instance-storage/instances?query=(x)"]
    assert captured["edge_url"] == "https://edge.example/"
    assert captured["instance_id"] == "i1"
    assert captured["params"] == {"fullPeriodicals": "true", "lang": "sv"}
    assert captured["headers"]["x-okapi-token"] == fake.okapi_token
    assert captured["headers"]["x-okapi-tenant"] == fake.tenant_id
    assert captured["headers"]["x-okapi-url"] == fake.gateway_url


def test_edge_rtac_defaults_full_periodicals_false_and_omits_lang(monkeypatch):
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": [{"id": "i1"}]}}
    )
    captured = {}

    def fake_edge(edge_url, instance_id, params, headers):
        captured["params"] = params
        return {"holdings": []}

    monkeypatch.setattr(application, "_edge_rtac_request", fake_edge)
    create_rtac_response(fake, {"edge_rtac_url": "https://edge.example"}, "?query=(x)")
    assert captured["params"] == {"fullPeriodicals": "false"}  # no lang key


def test_edge_rtac_url_from_env_when_settings_omit_it(monkeypatch):
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": [{"id": "i1"}]}}
    )
    captured = {}

    def fake_edge(edge_url, instance_id, params, headers):
        captured["edge_url"] = edge_url
        return {"holdings": [{"id": "h9"}]}

    monkeypatch.setattr(application, "EDGE_RTAC_URL", "https://env-edge.example")
    monkeypatch.setattr(application, "_edge_rtac_request", fake_edge)
    holdings = create_rtac_response(fake, {}, "?query=(x)")
    assert holdings == [{"id": "h9"}]
    assert captured["edge_url"] == "https://env-edge.example"
    assert fake.calls == ["/instance-storage/instances?query=(x)"]  # no /rtac/ fallback
