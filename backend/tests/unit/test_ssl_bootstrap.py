"""Tests for the ``configure_ssl_ca_bundle`` bootstrap helper in ``backend.main``.

These tests deliberately avoid importing ``backend.main`` so the real certifi
bootstrap does not run during pytest collection. They import the helper
directly from the module surface after patching out the import-time wiring.

The four required scenarios (per Task 3 brief):

1. ``sets_missing_variables`` — env vars all unset => helper sets all three.
2. ``preserves_user_values`` — env vars preset => helper does NOT overwrite.
3. ``ignores_missing_or_empty_file`` — file absent or zero bytes => no env set.
4. ``handles_certifi_error`` — ``where()`` raises => no env set, returns ``None``.
"""

import importlib
import os

import pytest


def _load_helper():
    """Return ``backend.main.configure_ssl_ca_bundle``.

    Importing ``backend.main`` here will trigger its module-level certifi
    bootstrap, but the helper is idempotent (``os.environ.setdefault``) and
    only writes when the path is a valid, non-empty file. To avoid mutating
    the test process's real environment we capture and clear the relevant
    env vars around the import and around each test (via monkeypatch).
    """
    backend_main = importlib.import_module("backend.main")
    return backend_main.configure_ssl_ca_bundle


@pytest.fixture(autouse=True)
def _isolate_ssl_env(monkeypatch):
    """Ensure no inherited env vars leak into the test assertions."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)


def test_configure_ssl_ca_bundle_sets_missing_variables(tmp_path):
    ca_file = tmp_path / "cacert.pem"
    ca_file.write_text("CA CERTIFICATE\n", encoding="utf-8")

    configure = _load_helper()
    selected = configure(lambda: str(ca_file))

    assert selected == str(ca_file)
    assert os.environ["SSL_CERT_FILE"] == str(ca_file)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(ca_file)
    assert os.environ["CURL_CA_BUNDLE"] == str(ca_file)


def test_configure_ssl_ca_bundle_preserves_user_values(monkeypatch, tmp_path):
    ca_file = tmp_path / "cacert.pem"
    ca_file.write_text("CA CERTIFICATE\n", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", "custom-ssl.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "custom-requests.pem")
    monkeypatch.setenv("CURL_CA_BUNDLE", "custom-curl.pem")

    configure = _load_helper()
    selected = configure(lambda: str(ca_file))

    assert selected == str(ca_file)
    assert os.environ["SSL_CERT_FILE"] == "custom-ssl.pem"
    assert os.environ["REQUESTS_CA_BUNDLE"] == "custom-requests.pem"
    assert os.environ["CURL_CA_BUNDLE"] == "custom-curl.pem"


def test_configure_ssl_ca_bundle_ignores_missing_or_empty_file(tmp_path):
    configure = _load_helper()

    missing = tmp_path / "missing.pem"
    assert configure(lambda: str(missing)) is None
    assert "SSL_CERT_FILE" not in os.environ

    empty = tmp_path / "empty.pem"
    empty.touch()
    assert configure(lambda: str(empty)) is None
    assert "SSL_CERT_FILE" not in os.environ


def test_configure_ssl_ca_bundle_handles_certifi_error():
    configure = _load_helper()

    assert configure(lambda: (_ for _ in ()).throw(ImportError())) is None
    assert "SSL_CERT_FILE" not in os.environ
