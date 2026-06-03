"""Tests for the per-sigel FolioClient cache (DoS-amplification guard)."""

import threading
import types

import pytest

import application
from application import fetch_holdings, get_folio_client

from conftest import FakeFolioClient


@pytest.fixture
def fake_clock(monkeypatch):
    holder = {"t": 1000.0}
    monkeypatch.setattr(application.time, "monotonic", lambda: holder["t"])
    return holder


@pytest.fixture
def login_counter(monkeypatch):
    """Replace the real login with a counter that hands out distinct clients."""
    calls = {"n": 0}

    def fake_new(settings):
        calls["n"] += 1
        return ("client", calls["n"])

    monkeypatch.setattr(application, "_new_folio_client", fake_new)
    return calls


def test_first_call_logs_in_and_caches(fake_clock, login_counter):
    client = get_folio_client("alpha", {})
    assert client == ("client", 1)
    assert login_counter["n"] == 1


def test_second_call_within_ttl_reuses_client(fake_clock, login_counter):
    first = get_folio_client("alpha", {})
    second = get_folio_client("alpha", {})
    assert first is second
    assert login_counter["n"] == 1  # no second login


def test_call_after_ttl_logs_in_again(fake_clock, login_counter, monkeypatch):
    monkeypatch.setattr(application, "FOLIO_CLIENT_TTL", 300.0)
    get_folio_client("alpha", {})
    fake_clock["t"] += 301  # past the TTL
    again = get_folio_client("alpha", {})
    assert again == ("client", 2)
    assert login_counter["n"] == 2


def test_different_sigels_get_separate_clients(fake_clock, login_counter):
    a = get_folio_client("alpha", {})
    b = get_folio_client("beta", {})
    assert a != b
    assert login_counter["n"] == 2


def test_concurrent_cold_burst_triggers_single_login(login_counter):
    """A cold-cache burst for one sigel must log in once, not once per thread."""
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results = []

    def worker():
        barrier.wait()  # release all threads together to maximise overlap
        results.append(get_folio_client("alpha", {}))

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert login_counter["n"] == 1
    assert all(r is results[0] for r in results)


# --- auth-error refresh (expired-token recovery) ----------------------------


class _AuthError(Exception):
    """Mimics requests.HTTPError carrying a 401 response."""

    def __init__(self, status_code=401):
        super().__init__("auth")
        self.response = types.SimpleNamespace(status_code=status_code)


def test_fetch_holdings_refreshes_client_on_auth_error(monkeypatch):
    stale = FakeFolioClient(error=_AuthError(401))
    fresh = FakeFolioClient(
        responses={
            "/instance-storage/instances": {"instances": [{"id": "i1"}]},
            "/rtac/": {"holdings": [{"id": "h1"}]},
        }
    )
    clients = iter([stale, fresh])
    monkeypatch.setattr(application, "get_folio_client", lambda sigel, s: next(clients))
    invalidated = []
    monkeypatch.setattr(application, "_invalidate_client", invalidated.append)

    holdings = fetch_holdings("alpha", {}, "?query=(x)")

    assert holdings == [{"id": "h1"}]
    assert invalidated == ["alpha"]  # the stale client was dropped before retry


def test_fetch_holdings_does_not_retry_non_auth_error(monkeypatch):
    fake = FakeFolioClient(error=RuntimeError("boom"))
    calls = []

    def get_client(sigel, s):
        calls.append(sigel)
        return fake

    monkeypatch.setattr(application, "get_folio_client", get_client)

    with pytest.raises(RuntimeError):
        fetch_holdings("alpha", {}, "?query=(x)")
    assert calls == ["alpha"]  # no second lookup / no retry


def test_invalidate_client_closes_and_drops(monkeypatch):
    fake = FakeFolioClient()
    monkeypatch.setattr(application, "_new_folio_client", lambda s: fake)

    get_folio_client("alpha", {})  # caches `fake`
    assert "alpha" in application._client_cache

    application._invalidate_client("alpha")

    assert "alpha" not in application._client_cache
    assert fake.closed is True  # the dropped client's pool was closed
