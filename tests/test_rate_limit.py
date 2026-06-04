"""Rate limiting on /<sigel>/rtac and the per-sigel fast-track token.

A request whose ?token= matches the sigel's configured fast_track_token costs 0
and is never throttled (Libris's registered URL carries it); everyone else is
capped per client IP, and a throttled request still gets a valid (empty) RTAC
document.
"""

import types

import pytest
from lxml import etree

import application

from conftest import FakeFolioClient


def _items(xml_bytes):
    return etree.fromstring(xml_bytes).findall("Item")


def _fake_with_holdings():
    return FakeFolioClient(
        responses={
            "/instance-storage/instances": {"instances": [{"id": "i1"}]},
            "/rtac/": {"holdings": [{"id": "h1", "status": "Available"}]},
        }
    )


# --- _is_fast_track (unit) --------------------------------------------------


def _req(token, sigel):
    return types.SimpleNamespace(
        query_params={"token": token} if token is not None else {},
        path_params={"sigel": sigel} if sigel is not None else {},
    )


def test_fast_track_true_on_matching_token(libraries_dir, settings):
    libraries_dir("alpha", dict(settings, fast_track_token="s3cret"))
    assert application._is_fast_track(_req("s3cret", "alpha")) is True


def test_fast_track_false_on_wrong_token(libraries_dir, settings):
    libraries_dir("alpha", dict(settings, fast_track_token="s3cret"))
    assert application._is_fast_track(_req("nope", "alpha")) is False


def test_fast_track_false_without_token(libraries_dir, settings):
    libraries_dir("alpha", dict(settings, fast_track_token="s3cret"))
    assert application._is_fast_track(_req(None, "alpha")) is False


def test_fast_track_false_when_no_token_configured(libraries_dir, settings):
    libraries_dir("alpha", settings)  # no fast_track_token
    assert application._is_fast_track(_req("anything", "alpha")) is False


def test_fast_track_false_unknown_sigel(libraries_dir, settings):
    libraries_dir("alpha", dict(settings, fast_track_token="s3cret"))
    assert application._is_fast_track(_req("s3cret", "ghost")) is False


def test_cost_is_zero_only_for_fast_track(libraries_dir, settings):
    libraries_dir("alpha", dict(settings, fast_track_token="s3cret"))
    assert application._rtac_cost(_req("s3cret", "alpha")) == 0
    assert application._rtac_cost(_req("nope", "alpha")) == 1


# --- enforcement (integration) ----------------------------------------------


@pytest.fixture
def limited(monkeypatch):
    """Enable the limiter with a tiny limit and a clean store for one test."""
    monkeypatch.setattr(application, "RTAC_RATE_LIMIT", "3/minute")
    application.limiter.enabled = True
    application.limiter._storage.reset()
    yield
    application.limiter.enabled = False
    application.limiter._storage.reset()


def test_public_path_throttled_after_limit(
    client, libraries_dir, settings, monkeypatch, limited
):
    libraries_dir("alpha", settings)
    fake = _fake_with_holdings()
    monkeypatch.setattr(application, "get_folio_client", lambda sigel, s: fake)

    for _ in range(3):  # limit is 3/minute
        resp = client.get("/alpha/rtac", params={"Bib_ID": "1"})
        assert resp.status_code == 200
        assert _items(resp.content)[0].findtext("UniqueItemId") == "h1"
    assert len(fake.calls) == 6  # 3 requests * (search + rtac)

    # 4th is throttled: still valid XML, but FOLIO is NOT called again.
    resp = client.get("/alpha/rtac", params={"Bib_ID": "1"})
    assert resp.status_code == 200
    assert _items(resp.content)[0].findtext("Status") == "Okänd"
    assert len(fake.calls) == 6


def test_fast_track_token_is_never_throttled(
    client, libraries_dir, settings, monkeypatch, limited
):
    libraries_dir("alpha", dict(settings, fast_track_token="tok-xyz"))
    fake = _fake_with_holdings()
    monkeypatch.setattr(application, "get_folio_client", lambda sigel, s: fake)

    # Well past the limit, but every call carries the token -> all served.
    for _ in range(8):
        resp = client.get("/alpha/rtac", params={"Bib_ID": "1", "token": "tok-xyz"})
        assert resp.status_code == 200
        assert _items(resp.content)[0].findtext("UniqueItemId") == "h1"
    assert len(fake.calls) == 16  # 8 * (search + rtac), none skipped


def test_wrong_token_is_throttled_like_public(
    client, libraries_dir, settings, monkeypatch, limited
):
    libraries_dir("alpha", dict(settings, fast_track_token="right"))
    fake = _fake_with_holdings()
    monkeypatch.setattr(application, "get_folio_client", lambda sigel, s: fake)

    for _ in range(3):
        assert client.get(
            "/alpha/rtac", params={"Bib_ID": "1", "token": "wrong"}
        ).status_code == 200
    resp = client.get("/alpha/rtac", params={"Bib_ID": "1", "token": "wrong"})
    assert _items(resp.content)[0].findtext("Status") == "Okänd"
