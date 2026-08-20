"""Tests for the import-time SSL CA bootstrap helper.

These tests extract only the production helper AST so importing this test module
never imports ``backend.main`` or triggers the real certifi bootstrap.
"""

import ast
import os
from pathlib import Path
from typing import Callable, Optional

import pytest


@pytest.fixture(autouse=True)
def _isolate_ssl_env():
    """Keep SSL environment variables isolated from the test process.

    This fixture deliberately does not depend on pytest's ``monkeypatch``
    fixture. Because pytest runs teardown code in LIFO order, this fixture's
    yield-teardown runs after ``monkeypatch``'s teardown — restoring the
    state that existed before the test even when production code writes
    directly to ``os.environ``.

    The pre-test snapshot distinguishes variables that were *present*
    (possibly empty) from variables that were *absent*, so both cases are
    restored exactly.
    """
    variables = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
    # Capture pre-test state: only existing entries go into ``original``;
    # variables that were absent are remembered in ``missing`` so teardown
    # can pop any stray value the test left behind.
    original = {variable: os.environ[variable] for variable in variables if variable in os.environ}
    for variable in variables:
        os.environ.pop(variable, None)

    yield

    # Teardown — runs after ``monkeypatch``'s teardown (LIFO), so we only
    # need to undo anything our setup or the helper might have written
    # directly. Restore the exact pre-test state.
    for variable in variables:
        os.environ.pop(variable, None)
    for variable, value in original.items():
        os.environ[variable] = value


def _load_helper():
    """Load the production helper without running ``backend.main`` imports."""
    source_path = Path(__file__).parents[2] / "main.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "configure_ssl_ca_bundle"
    )
    namespace = {"os": os, "Callable": Callable, "Optional": Optional, "Path": Path}
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source_path), "exec"), namespace)
    return namespace["configure_ssl_ca_bundle"]


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

    def failing_where():
        raise RuntimeError("test failure")

    assert configure(failing_where) is None
    assert "SSL_CERT_FILE" not in os.environ
