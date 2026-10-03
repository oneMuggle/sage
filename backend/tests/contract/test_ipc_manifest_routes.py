"""IPC manifest <-> real FastAPI app (T2 of the IPC contract gate).

electron/commands.ts maps every renderer ``invoke(cmd)`` to a backend ``(method, path)``.
``electron/ipc-manifest.json`` is that table as data (``npm run ipc:manifest``); this test asserts
that each manifest route exists in the *real* app. It enumerates ``app.routes`` rather than
regex-parsing route files: a regex pass once reported 118 existing routes as missing.

Why it exists: #857 dropped 13 commands the renderer still called, and a mapping can also point
at a route that was never written (``projects_create_session``). Backend tests call routes
directly and the renderer tests stub ``invoke``, so neither side could notice.

Known gaps live in ``electron/ipc-known-gaps.json`` (``manifestWithoutRoute``). The list only
shrinks: a new gap fails, and so does an entry that is no longer a gap.
Counterpart: electron/__tests__/ipc-contract.test.ts (T1/T3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from backend.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "electron" / "ipc-manifest.json"
KNOWN_GAPS = REPO_ROOT / "electron" / "ipc-known-gaps.json"

_PLACEHOLDER = re.compile(r"\{[^}]+\}")


def _route_pattern(path):
    """Regex for a FastAPI path: ``{x}`` is one segment, ``{x:path}`` may span several."""
    rx = ""
    for part in re.split(r"(\{[^}]+\})", path):
        if part.startswith("{") and part.endswith("}"):
            rx += ".+" if part.endswith(":path}") else "[^/]+"
        else:
            rx += re.escape(part)
    return re.compile("^" + rx + "$")


def _app_routes():
    routes = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            routes.append((set(methods), _route_pattern(path)))
    return routes


def _exists(routes, method, template):
    sample = _PLACEHOLDER.sub("x", template)
    return any(method in methods and pattern.match(sample) for methods, pattern in routes)


def test_every_ipc_manifest_route_exists_in_the_real_app():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["commands"]
    known = set(json.loads(KNOWN_GAPS.read_text(encoding="utf-8"))["manifestWithoutRoute"])
    assert len(manifest) > 100, "manifest looks empty - regenerate it with `npm run ipc:manifest`"

    routes = _app_routes()
    missing = sorted(
        cmd
        for cmd, entry in manifest.items()
        if not _exists(routes, entry["method"], entry["path"])
    )

    new = [cmd for cmd in missing if cmd not in known]
    assert not new, (
        "IPC commands map to backend routes that do not exist (404 at runtime):\n"
        + "\n".join(
            "  {} -> {} {}".format(c, manifest[c]["method"], manifest[c]["path"]) for c in new
        )
        + "\nAdd the backend route, or fix the mapping in electron/commands.ts."
    )

    stale = sorted(known - set(missing))
    assert not stale, (
        "No longer a gap - delete from electron/ipc-known-gaps.json (manifestWithoutRoute): "
        + ", ".join(stale)
    )
