"""Tests for create_rtac_response against a fake FolioClient.

create_rtac_response resolves the instance via FolioClient, then fetches holdings
from the backend chosen by ``rtac_backend``: ``"rtac-cache"`` / ``"edge"`` /
``"rtac"`` (default). ``{}`` settings exercise the default mod-rtac backend.
"""

import pytest

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


# --- rtac-cache backend -----------------------------------------------------


def test_rtac_cache_backend_uses_gateway_path():
    fake = FakeFolioClient(
        responses={
            "/instance-storage/instances": {"instances": [{"id": "i1"}]},
            "/rtac-cache/": {"holdings": [{"id": "h1", "permanentLoanType": "Can circulate"}]},
        }
    )
    holdings = create_rtac_response(fake, {"rtac_backend": "rtac-cache"}, "?query=(x)")
    assert holdings == [{"id": "h1", "permanentLoanType": "Can circulate"}]
    # Resolved via the gateway (okapi token) — search then /rtac-cache/{id}.
    assert fake.calls == ["/instance-storage/instances?query=(x)", "/rtac-cache/i1"]


# --- edge backend (rtac_backend="edge", apiKey auth) ------------------------


def test_edge_backend_uses_apikey_and_maps_params(monkeypatch):
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
        "rtac_backend": "edge",
        "edge_rtac_url": "https://edge.example/",
        "edge_rtac_api_key": "KEY123",
        "full_periodicals": True,
        "lang": "sv",
    }
    holdings = create_rtac_response(fake, settings, "?query=(x)")

    assert holdings == [{"id": "h1"}]
    # Search via FolioClient; holdings via edge — no gateway /rtac call.
    assert fake.calls == ["/instance-storage/instances?query=(x)"]
    assert captured["edge_url"] == "https://edge.example/"
    assert captured["instance_id"] == "i1"
    assert captured["params"] == {"fullPeriodicals": "true", "lang": "sv"}
    # Authenticated by apiKey (Authorization header) — no okapi headers.
    assert captured["headers"]["Authorization"] == "KEY123"
    assert "x-okapi-token" not in captured["headers"]


def test_edge_backend_defaults_full_periodicals_false_and_omits_lang(monkeypatch):
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": [{"id": "i1"}]}}
    )
    captured = {}
    monkeypatch.setattr(
        application, "_edge_rtac_request",
        lambda u, i, params, h: captured.update(params=params) or {"holdings": []},
    )
    create_rtac_response(
        fake,
        {"rtac_backend": "edge", "edge_rtac_url": "https://e", "edge_rtac_api_key": "K"},
        "?query=(x)",
    )
    assert captured["params"] == {"fullPeriodicals": "false"}  # no lang key


def test_edge_backend_uses_env_fallbacks(monkeypatch):
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": [{"id": "i1"}]}}
    )
    captured = {}
    monkeypatch.setattr(application, "EDGE_RTAC_URL", "https://env-edge.example")
    monkeypatch.setattr(application, "EDGE_RTAC_API_KEY", "ENVKEY")
    monkeypatch.setattr(
        application, "_edge_rtac_request",
        lambda u, i, params, h: captured.update(edge_url=u, key=h["Authorization"]) or {"holdings": []},
    )
    create_rtac_response(fake, {"rtac_backend": "edge"}, "?query=(x)")
    assert captured["edge_url"] == "https://env-edge.example"
    assert captured["key"] == "ENVKEY"


def test_edge_backend_without_url_or_key_raises(monkeypatch):
    monkeypatch.setattr(application, "EDGE_RTAC_URL", None)
    monkeypatch.setattr(application, "EDGE_RTAC_API_KEY", None)
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": [{"id": "i1"}]}}
    )
    with pytest.raises(RuntimeError, match="edge backend needs"):
        create_rtac_response(fake, {"rtac_backend": "edge"}, "?query=(x)")


def test_unknown_backend_raises():
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": [{"id": "i1"}]}}
    )
    with pytest.raises(RuntimeError, match="Unknown rtac_backend"):
        create_rtac_response(fake, {"rtac_backend": "bogus"}, "?query=(x)")
