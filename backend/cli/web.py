# ruff: noqa: T201
"""Web-fallback launcher: serve the browser UI from the local backend.

Used by both the packaged ``SageWeb.cmd`` (bundled Python) and the developer
``scripts/sage-web.bat``. It mints (or reuses) a local auth token, picks a free
port, waits for ``/health``, then opens the default browser — no curl/node
required (Win7 ships neither).

Usage::

    python -m backend.cli.web [--no-browser]
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable, Mapping, MutableMapping, Optional, Sequence, Tuple

DEFAULT_PORT = 8765
PORT_SEARCH_ATTEMPTS = 10
DEFAULT_HEALTH_TIMEOUT = 30.0


class WebFallbackError(RuntimeError):
    """Raised when the launcher cannot proceed (e.g. missing frontend build)."""


# ── URL / port helpers ───────────────────────────────────────────────────────


def build_web_url(port: int, token: str) -> str:
    """Return the browser URL carrying the local auth token as a query param."""
    quoted = urllib.parse.quote(token, safe="")
    return f"http://127.0.0.1:{port}/?token={quoted}"


def _port_is_free(port: int) -> bool:
    # No SO_REUSEADDR: on Windows that can let us "bind" an already-listening
    # port, defeating the purpose of the probe.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(
    preferred: int,
    *,
    is_free: Optional[Callable[[int], bool]] = None,
    attempts: int = PORT_SEARCH_ATTEMPTS,
) -> int:
    """Return ``preferred`` if free, else the next free port within ``attempts``."""
    check = is_free or _port_is_free
    for offset in range(attempts):
        candidate = preferred + offset
        if check(candidate):
            return candidate
    raise WebFallbackError(
        f"端口 {preferred}-{preferred + attempts - 1} 均被占用，无法启动网页模式。"
    )


# ── environment ──────────────────────────────────────────────────────────────


def prepare_runtime_env(
    environ: MutableMapping[str, str],
    *,
    is_free: Optional[Callable[[int], bool]] = None,
) -> Tuple[int, str]:
    """Populate *environ* for web mode; return the chosen ``(port, token)``.

    Must be called before importing ``backend.main`` — ``is_web_mode()`` is
    evaluated at import time.
    """
    environ["SAGE_WEB_MODE"] = "1"

    token = environ.get("SAGE_LOCAL_AUTH_TOKEN") or secrets.token_urlsafe(32)
    environ["SAGE_LOCAL_AUTH_TOKEN"] = token

    try:
        preferred = int(environ.get("PYTHON_BACKEND_PORT", DEFAULT_PORT))
    except ValueError:
        preferred = DEFAULT_PORT
    port = pick_port(preferred, is_free=is_free)
    environ["PYTHON_BACKEND_PORT"] = str(port)
    environ["BACKEND_URL"] = f"http://127.0.0.1:{port}"
    return port, token


# ── frontend build ───────────────────────────────────────────────────────────


def resolve_dist_path(environ: Mapping[str, str]) -> Path:
    """Resolve the ``dist-web`` directory (env override or repo/install default)."""
    override = environ.get("SAGE_WEB_DIST_PATH")
    if override:
        return Path(override)
    # backend/cli/web.py -> parents[2] is the repo root (or resources/ when
    # packaged as .pyc; both hold a sibling dist-web/).
    return Path(__file__).resolve().parents[2] / "dist-web"


def ensure_dist(dist_path: Path) -> None:
    """Raise :class:`WebFallbackError` if the web build is missing."""
    index = dist_path / "index.html"
    if not index.is_file():
        raise WebFallbackError(
            f"未找到网页前端产物：{index}\n"
            "请在源码目录运行 `npm run build:web`，或重新安装 Sage。"
        )


# ── health / browser ─────────────────────────────────────────────────────────


def wait_for_health(
    port: int,
    *,
    timeout: float = DEFAULT_HEALTH_TIMEOUT,
    interval: float = 0.5,
    opener: Optional[Callable[..., object]] = None,
) -> bool:
    """Poll ``/health`` until it returns 200 or *timeout* elapses.

    Uses urllib rather than curl so it works on a bare Windows 7 box.
    """
    open_fn = opener or urllib.request.urlopen
    health_url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open_fn(health_url, timeout=2) as response:  # type: ignore[union-attr]
                if getattr(response, "status", 200) == 200:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(interval)
    return False


def _open_browser_when_ready(port: int, url: str) -> None:
    if wait_for_health(port):
        try:
            if not webbrowser.open(url):
                print(f"[Sage Web] 无法自动打开浏览器，请手动访问：{url}")
        except webbrowser.Error:
            print(f"[Sage Web] 无法自动打开浏览器，请手动访问：{url}")
    else:
        print(f"[Sage Web] 后端未在预期时间内就绪，请检查日志。可手动访问：{url}")


# ── entry point ──────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli.web",
        description="以浏览器模式启动 Sage 本地后端。",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="只启动服务，不自动打开浏览器。",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    port, token = prepare_runtime_env(os.environ)
    dist_path = resolve_dist_path(os.environ)
    try:
        ensure_dist(dist_path)
    except WebFallbackError as exc:
        print(f"[Sage Web] {exc}", file=sys.stderr)
        return 2

    url = build_web_url(port, token)
    print(f"[Sage Web] 前端：{dist_path}")
    print(f"[Sage Web] 请在浏览器访问：{url}")
    print("[Sage Web] 按 Ctrl+C 停止服务。")

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready, args=(port, url), daemon=True
        ).start()

    # Import after the environment is in place so is_web_mode() sees it.
    import uvicorn

    from backend.main import app

    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
