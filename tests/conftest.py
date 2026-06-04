"""Shared fixtures and fakes for the RTAC test suite.

The application reads its library configuration from ``application.LIBRARIES_DIR``
at call time (never caching it), so tests point that global at a temp directory
instead of touching the real ``libraries/`` tree.
"""

import json

import pytest
from fastapi.testclient import TestClient

import application


# --- Fakes ------------------------------------------------------------------


class FakeFolioClient:
    """Stand-in for folioclient.FolioClient.

    Records every requested path and answers ``folio_get_single_object`` from a
    prefix-keyed ``responses`` mapping (so a single query string still matches
    its endpoint). Set ``error`` to make every call raise.
    """

    def __init__(self, responses=None, error=None,
                 gateway_url="https://okapi.example", tenant_id="tenant",
                 okapi_token="faketoken"):
        self.responses = responses or {}
        self.error = error
        self.gateway_url = gateway_url
        self.tenant_id = tenant_id
        self.okapi_token = okapi_token
        self.calls = []
        self.closed = False

    def folio_get_single_object(self, path):
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        for prefix, value in self.responses.items():
            if path.startswith(prefix):
                return value
        return {}

    def close(self):
        self.closed = True


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def libraries_dir(tmp_path, monkeypatch):
    """Point application.LIBRARIES_DIR at an empty temp dir.

    Returns a helper that writes ``<sigel>/settings.json`` and yields the sigel.
    """
    monkeypatch.setattr(application, "LIBRARIES_DIR", str(tmp_path))

    def make_sigel(sigel, settings):
        sigel_dir = tmp_path / sigel
        sigel_dir.mkdir()
        (sigel_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )
        return sigel

    make_sigel.path = tmp_path
    return make_sigel


@pytest.fixture
def settings():
    """A complete, valid settings dict (sunflower-style)."""
    return {
        "okapi_url": "https://okapi.example",
        "tenant_id": "diku",
        "username": "diku_admin",
        "password": "admin",
        "identifier_type_ids": {
            "Bib_ID": [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
            "ONR": [],
            "ISSN": ["33333333-3333-3333-3333-333333333333"],
            "ISBN": ["44444444-4444-4444-4444-444444444444"],
        },
    }


@pytest.fixture(autouse=True)
def clear_client_cache():
    """Keep the module-level FolioClient cache from leaking between tests."""
    application._client_cache.clear()
    yield
    application._client_cache.clear()


@pytest.fixture(autouse=True)
def rate_limiter_off():
    """Disable the rate limiter for tests that don't target it.

    The limiter is process-global with in-memory state; left on, its counters
    would leak across the many rtac calls in the suite. Tests that exercise it
    re-enable it (and reset the store) themselves.
    """
    application.limiter.enabled = False
    application.limiter._storage.reset()
    yield
    application.limiter.enabled = False
    application.limiter._storage.reset()


@pytest.fixture
def client():
    """TestClient that lets the registered exception handler win.

    ServerErrorMiddleware re-raises after sending the handler's response, so
    ``raise_server_exceptions=False`` is what mirrors a real HTTP client.
    """
    return TestClient(application.application, raise_server_exceptions=False)
