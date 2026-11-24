from __future__ import annotations

import asyncio
import io
import json
import zipfile

import httpx
import pytest

from backend.adapters.out.document_parse.mineru_client import MineruClient
from backend.adapters.out.document_parse.mineru_errors import (
    MineruAuthError,
    MineruTimeoutError,
)


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("markdown.md", "# parsed")
        zf.writestr("middle_json.json", json.dumps({"pages": [1]}))
    return buf.getvalue()


def _handler(record: list):
    state = {"polls": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        record.append(
            (request.method, request.url.path, request.headers.get("authorization"))
        )
        path = request.url.path
        if request.method == "POST" and path.endswith("/v1/tasks"):
            return httpx.Response(
                200,
                json={
                    "task_id": "t1",
                    "status": "waiting-file",
                    "files": [
                        {
                            "file_id": "f1",
                            "file_name": "a.pdf",
                            "status": "waiting-file",
                            "upload": {
                                "url": "/files/f1",
                                "headers": {"x-presigned": "1"},
                            },
                        }
                    ],
                },
            )
        if request.method == "PUT" and path.endswith("/files/f1"):
            assert request.headers.get("x-presigned") == "1"
            return httpx.Response(200)
        if path.endswith("/v1/tasks/t1"):
            state["polls"] += 1
            done = state["polls"] >= 2
            return httpx.Response(
                200,
                json={
                    "task_id": "t1",
                    "status": "completed" if done else "pending",
                    "files": [
                        {
                            "file_id": "f1",
                            "file_name": "a.pdf",
                            "status": "completed" if done else "running",
                            "result_url": "/v1/files/f1/content",
                        }
                    ],
                },
            )
        if path.endswith("/v1/files/f1/content"):
            return httpx.Response(200, content=_zip_bytes())
        return httpx.Response(
            404, json={"error": {"code": "not_found", "message": path}}
        )

    return handle


def test_parse_bytes_happy_path() -> None:
    record: list = []
    client = MineruClient(
        "http://mineru.local:8000",
        api_key="k",
        poll_interval=0.0,
        transport=httpx.MockTransport(_handler(record)),
    )
    out = asyncio.run(client.parse_bytes(b"%PDF-1.4", "a.pdf", tier="standard"))
    assert out.markdown == "# parsed"
    assert out.structured == {"pages": [1]}
    assert record[0][0] == "POST"
    assert record[0][2] == "Bearer k"
    assert any(r[0] == "PUT" for r in record)


def test_auth_error_is_mapped() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"code": "invalid_api_key", "message": "bad key"}}
        )

    client = MineruClient(
        "http://mineru.local:8000", transport=httpx.MockTransport(handle)
    )
    with pytest.raises(MineruAuthError) as exc:
        asyncio.run(client.parse_bytes(b"x", "a.pdf"))
    assert exc.value.code == "invalid_api_key"


def test_timeout_cancels_task() -> None:
    seen: list = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/v1/tasks"):
            return httpx.Response(
                200,
                json={
                    "task_id": "t2",
                    "status": "pending",
                    "files": [
                        {
                            "file_id": "f2",
                            "file_name": "a.pdf",
                            "status": "pending",
                        }
                    ],
                },
            )
        if request.url.path.endswith("/v1/tasks/t2/cancel"):
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "task_id": "t2",
                "status": "running",
                "files": [
                    {"file_id": "f2", "file_name": "a.pdf", "status": "running"}
                ],
            },
        )

    client = MineruClient(
        "http://mineru.local:8000",
        poll_interval=0.0,
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(MineruTimeoutError):
        asyncio.run(client.parse_bytes(b"x", "a.pdf", timeout_seconds=0.0))
    assert any(path.endswith("/v1/tasks/t2/cancel") for _, path in seen)


def test_probe_reports_auth_mode() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/usage"):
            return httpx.Response(200, json={"access_level": "registered"})
        return httpx.Response(404)

    client = MineruClient(
        "http://mineru.local:8000", api_key="k", transport=httpx.MockTransport(handle)
    )
    info = asyncio.run(client.probe())
    assert info["reachable"] is True
    assert info["serverAuthMode"] == "bearer"
    assert info["accessLevel"] == "registered"


def test_probe_never_raises_on_transport_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = MineruClient(
        "http://mineru.local:8000", transport=httpx.MockTransport(handle)
    )
    info = asyncio.run(client.probe())
    assert info["reachable"] is False
    assert info["reason"] == "unreachable"
