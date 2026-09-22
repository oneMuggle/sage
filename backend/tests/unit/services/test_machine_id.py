"""Unit tests for backend/utils/machine_id.py (plan §5.2 / spec §7.1)."""

import hashlib

import pytest

from backend.utils import machine_id as mid


@pytest.fixture(autouse=True)
def _fresh_cache():
    mid.reset_cache()
    yield
    mid.reset_cache()


def test_machine_id_is_64_hex_and_cached():
    first = mid.machine_id()
    assert len(first) == 64
    assert all(c in "0123456789abcdef" for c in first)
    assert mid.machine_id() == first


def test_machine_id_matches_documented_formula(monkeypatch):
    """hostname|username|machine-guid, UTF-8 with errors='replace'."""
    import getpass

    monkeypatch.setattr(mid.socket, "gethostname", lambda: "host-a")
    monkeypatch.setattr(mid, "hardware_id", lambda: "guid-1")
    # Non-ASCII usernames are the norm on the target platform (Chinese Windows).
    monkeypatch.setattr(getpass, "getuser", lambda: "用户")
    expected = hashlib.sha256("host-a|用户|guid-1".encode("utf-8", "replace")).hexdigest()
    assert mid.machine_id() == expected


def test_reset_cache_recomputes(monkeypatch):
    before = mid.machine_id()
    monkeypatch.setattr(mid.socket, "gethostname", lambda: "another-host")
    assert mid.machine_id() == before  # cached
    mid.reset_cache()
    assert mid.machine_id() != before


def test_machine_id_survives_component_failures(monkeypatch):
    def boom():
        raise OSError("component unavailable")

    import getpass

    monkeypatch.setattr(mid.socket, "gethostname", boom)
    monkeypatch.setattr(getpass, "getuser", boom)
    assert len(mid.machine_id()) == 64


def test_hardware_id_falls_back_to_mac(monkeypatch):
    monkeypatch.setattr(mid, "_windows_machine_guid", lambda: "")
    monkeypatch.setattr(mid, "_linux_machine_id", lambda: "")
    value = mid.hardware_id()
    assert isinstance(value, str) and value


def test_hardware_id_prefers_platform_guid(monkeypatch):
    monkeypatch.setattr(mid, "_windows_machine_guid", lambda: "win-guid")
    monkeypatch.setattr(mid, "_linux_machine_id", lambda: "linux-guid")
    assert mid.hardware_id() == "win-guid"
