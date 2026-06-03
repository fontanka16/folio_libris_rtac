"""Tests for sigel discovery and settings loading (incl. path-traversal guard)."""

import pytest

import application
from application import available_sigels, load_settings


def test_available_sigels_lists_only_dirs_with_settings(libraries_dir):
    libraries_dir("alpha", {"okapi_url": "x"})
    libraries_dir("beta", {"okapi_url": "y"})
    # A directory without settings.json must not be reported.
    (libraries_dir.path / "no-settings").mkdir()
    assert available_sigels() == ["alpha", "beta"]


def test_available_sigels_is_sorted(libraries_dir):
    libraries_dir("zeta", {})
    libraries_dir("alpha", {})
    assert available_sigels() == ["alpha", "zeta"]


def test_available_sigels_missing_dir_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(application, "LIBRARIES_DIR", str(tmp_path / "does-not-exist"))
    assert available_sigels() == []


def test_load_settings_returns_parsed_json(libraries_dir):
    libraries_dir("alpha", {"okapi_url": "https://x", "tenant_id": "t"})
    loaded = load_settings("alpha")
    assert loaded["okapi_url"] == "https://x"
    assert loaded["tenant_id"] == "t"


def test_load_settings_unknown_sigel_raises(libraries_dir):
    libraries_dir("alpha", {})
    with pytest.raises(FileNotFoundError):
        load_settings("nope")


@pytest.mark.parametrize(
    "evil",
    [
        "../beta",
        "../../etc/passwd",
        "..",
        "alpha/../beta",
    ],
)
def test_load_settings_blocks_path_traversal(libraries_dir, evil):
    # Even though 'beta' exists, a traversal sigel is never in available_sigels()
    # and so is rejected before any path is opened.
    libraries_dir("alpha", {})
    libraries_dir("beta", {"secret": True})
    with pytest.raises(FileNotFoundError):
        load_settings(evil)
