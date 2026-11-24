"""Tests for backend.cli.web — the web-fallback launcher logic.

These cover the pure/seam-injected pieces so the packaged SageWeb.cmd and the
dev sage-web.bat share one tested implementation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from backend.cli import web

# ── build_web_url ────────────────────────────────────────────────────────────


def test_build_web_url_includes_token() -> None:
    assert web.build_web_url(8765, "abc123") == "http://127.0.0.1:8765/?token=abc123"


def test_build_web_url_quotes_unsafe_token_chars() -> None:
    url = web.build_web_url(9000, "a b/c+d&e")
    assert url.startswith("http://127.0.0.1:9000/?token=")
    assert " " not in url
    assert "%26" in url  # '&' encoded so it can't split query params


# ── pick_port ────────────────────────────────────────────────────────────────


def test_pick_port_returns_preferred_when_free() -> None:
    assert web.pick_port(8765, is_free=lambda _p: True) == 8765


def test_pick_port_skips_occupied_ports() -> None:
    free_at = 8767
    is_free = lambda p: p >= free_at  # noqa: E731
    assert web.pick_port(8765, is_free=is_free) == free_at


def test_pick_port_raises_when_all_busy() -> None:
    with pytest.raises(web.WebFallbackError):
        web.pick_port(8765, is_free=lambda _p: False, attempts=3)


# ── find_modern_browser ──────────────────────────────────────────────────────


def test_find_modern_browser_returns_first_existing_candidate() -> None:
    env = {"ProgramFiles": r"C:\Program Files"}
    target = Path(r"C:\Program Files") / r"Google\Chrome\Application\chrome.exe"
    found = web.find_modern_browser(env, exists=lambda p: p == target, os_name="nt")
    assert found == ("Google Chrome", target)


def test_find_modern_browser_prefers_chrome_over_firefox() -> None:
    env = {
        "ProgramFiles": r"C:\Program Files",
        "LOCALAPPDATA": r"C:\Users\user\AppData\Local",
    }
    chrome = Path(r"C:\Users\user\AppData\Local") / r"Google\Chrome\Application\chrome.exe"
    firefox = Path(r"C:\Program Files") / r"Mozilla Firefox\firefox.exe"
    found = web.find_modern_browser(env, exists=lambda p: p in (chrome, firefox), os_name="nt")
    assert found is not None
    assert found[0] == "Google Chrome"


def test_find_modern_browser_none_off_windows() -> None:
    assert web.find_modern_browser({}, exists=lambda _p: True, os_name="posix") is None


def test_find_modern_browser_none_when_absent() -> None:
    assert (
        web.find_modern_browser(
            {"ProgramFiles": r"C:\Program Files"}, exists=lambda _p: False, os_name="nt"
        )
        is None
    )


# ── prepare_runtime_env ──────────────────────────────────────────────────────


def test_prepare_runtime_env_sets_web_mode_and_token() -> None:
    env: Dict[str, str] = {}
    port, token = web.prepare_runtime_env(env, is_free=lambda _p: True)

    assert env["SAGE_WEB_MODE"] == "1"
    assert token
    assert len(token) >= 20
    assert env["SAGE_LOCAL_AUTH_TOKEN"] == token
    assert env["PYTHON_BACKEND_PORT"] == str(port)
    assert port == web.DEFAULT_PORT
    assert env["BACKEND_URL"] == f"http://127.0.0.1:{port}"


def test_prepare_runtime_env_preserves_provided_token() -> None:
    env = {"SAGE_LOCAL_AUTH_TOKEN": "fixed-token"}
    _, token = web.prepare_runtime_env(env, is_free=lambda _p: True)
    assert token == "fixed-token"


def test_prepare_runtime_env_uses_requested_port() -> None:
    env = {"PYTHON_BACKEND_PORT": "9100"}
    port, _ = web.prepare_runtime_env(env, is_free=lambda _p: True)
    assert port == 9100
    assert env["BACKEND_URL"] == "http://127.0.0.1:9100"


# ── resolve_dist_path / ensure_dist ─────────────────────────────────────────


def test_resolve_dist_path_honours_env_override(tmp_path: Path) -> None:
    assert web.resolve_dist_path({"SAGE_WEB_DIST_PATH": str(tmp_path)}) == tmp_path


def test_resolve_dist_path_default_points_at_repo_dist_web() -> None:
    resolved = web.resolve_dist_path({})
    assert resolved.name == "dist-web"
    # parents[2] of backend/cli/web.py is the repo root, which contains backend/
    assert (resolved.parent / "backend").is_dir()


def test_ensure_dist_raises_when_index_missing(tmp_path: Path) -> None:
    with pytest.raises(web.WebFallbackError):
        web.ensure_dist(tmp_path)


def test_ensure_dist_passes_when_index_present(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    web.ensure_dist(tmp_path)  # no raise


# ── wait_for_health ─────────────────────────────────────────────────────────


class _Resp:
    status = 200

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def test_wait_for_health_true_on_200() -> None:
    assert web.wait_for_health(8765, timeout=1.0, opener=lambda *a, **k: _Resp()) is True


def test_wait_for_health_false_on_timeout() -> None:
    def _boom(*_a: object, **_k: object) -> object:
        raise OSError("refused")

    assert web.wait_for_health(8765, timeout=0.05, interval=0.01, opener=_boom) is False


# ── main ─────────────────────────────────────────────────────────────────────


def test_main_exits_2_when_dist_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "prepare_runtime_env", lambda environ, **_: (8765, "t"))
    monkeypatch.setenv("SAGE_WEB_DIST_PATH", str(tmp_path))

    assert web.main(["--no-browser"]) == 2
