"""Tests for create_rtac_response against a fake FolioClient."""

from application import create_rtac_response

from conftest import FakeFolioClient


def test_returns_holdings_for_first_matching_instance():
    fake = FakeFolioClient(
        responses={
            "/instance-storage/instances": {"instances": [{"id": "i1"}, {"id": "i2"}]},
            "/rtac/": {"holdings": [{"id": "h1"}, {"id": "h2"}]},
        }
    )
    holdings = create_rtac_response(fake, "?query=(x)")
    assert holdings == [{"id": "h1"}, {"id": "h2"}]
    # First the instance search, then the rtac lookup for the first instance.
    assert fake.calls == ["/instance-storage/instances?query=(x)", "/rtac/i1"]


def test_no_matching_instance_returns_empty_without_rtac_call():
    fake = FakeFolioClient(
        responses={"/instance-storage/instances": {"instances": []}}
    )
    assert create_rtac_response(fake, "?query=(x)") == []
    assert fake.calls == ["/instance-storage/instances?query=(x)"]


def test_missing_instances_key_returns_empty():
    fake = FakeFolioClient(responses={"/instance-storage/instances": {}})
    assert create_rtac_response(fake, "?query=(x)") == []


def test_instance_without_holdings_returns_empty():
    fake = FakeFolioClient(
        responses={
            "/instance-storage/instances": {"instances": [{"id": "i1"}]},
            "/rtac/": {"holdings": []},
        }
    )
    assert create_rtac_response(fake, "?query=(x)") == []
