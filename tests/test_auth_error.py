"""Tests for _is_auth_error, the expired-token / permission classifier.

fetch_holdings uses this to decide whether to drop the cached FolioClient and
retry once with a fresh login. The suite already exercises the 401-via-response
path indirectly (test_folio_client_cache), but the typed-exception branch
(FolioAuthenticationError / FolioPermissionError) and the "not an auth error"
cases are only covered here.
"""

import types

import httpx
import pytest

from application import _is_auth_error
from folioclient import FolioAuthenticationError, FolioPermissionError


def _folio_exc(cls, status_code):
    """Build a real folioclient auth exception carrying an httpx response."""
    request = httpx.Request("GET", "https://okapi.example/x")
    response = httpx.Response(status_code, request=request)
    return cls(request=request, response=response)


@pytest.mark.parametrize("cls", [FolioAuthenticationError, FolioPermissionError])
def test_folio_auth_exceptions_are_auth_errors(cls):
    # Classified by type, regardless of the carried status code.
    assert _is_auth_error(_folio_exc(cls, 401)) is True


@pytest.mark.parametrize("status_code", [401, 403])
def test_response_status_401_or_403_is_auth_error(status_code):
    # A plain exception (e.g. httpx.HTTPStatusError) carrying a 401/403 response.
    exc = types.SimpleNamespace(response=types.SimpleNamespace(status_code=status_code))
    assert _is_auth_error(exc) is True


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 503])
def test_other_response_statuses_are_not_auth_errors(status_code):
    exc = types.SimpleNamespace(response=types.SimpleNamespace(status_code=status_code))
    assert _is_auth_error(exc) is False


def test_exception_without_response_is_not_auth_error():
    assert _is_auth_error(RuntimeError("boom")) is False


def test_exception_with_none_response_is_not_auth_error():
    # getattr(None, "status_code", None) -> None, which is not in (401, 403).
    assert _is_auth_error(types.SimpleNamespace(response=None)) is False
