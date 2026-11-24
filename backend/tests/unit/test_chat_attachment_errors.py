"""附件上传错误路径与口径一致性测试 (2026-11-24)

覆盖目标:
- A 错误可见性: 真实 error / error_code, HTTP 状态码规范
- B GBK 编码兼容
- C 无点文件名白名单 (Makefile/Dockerfile)
- D 孤儿文件治理: 失败路径不留磁盘痕迹
"""

from __future__ import annotations

import io

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import chat_attachment_routes


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_attachment_routes, "MEDIA_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(chat_attachment_routes.router, prefix="/api/v1")
    return TestClient(app)


def _disk_count(tmp_path) -> int:
    return sum(1 for _ in tmp_path.rglob("*") if _.is_file())


# ── 成功路径 ───────────────────────────────────────────────────────────


def test_utf8_txt_success(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={"file": ("a.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["media_ref"]["id"]
    assert body["api_url"].startswith("/api/v1/media/")
    assert body.get("text", "").startswith("hello")
    assert _disk_count(tmp_path) == before + 2


def test_gbk_txt_success_with_fallback(tmp_path, monkeypatch) -> None:
    """B: GBK 编码 txt 回退解码后成功上传, 不再返回 unsupported_encoding"""
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={
            "file": ("greeting.txt", io.BytesIO("你好世界".encode("gbk")), "text/plain")
        },
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["media_ref"]["id"]
    assert "你好世界" in body.get("text", "")
    assert _disk_count(tmp_path) == before + 2


def test_gb18030_txt_success_with_fallback(tmp_path, monkeypatch) -> None:
    """B: GB18030 也覆盖(兼容更老的 Windows 编码)"""
    client = _client(tmp_path, monkeypatch)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={
            "file": (
                "greeting.txt",
                io.BytesIO("你好世界".encode("gb18030")),
                "text/plain",
            )
        },
    )
    assert resp.status_code == 200, resp.json()


def test_makefile_success(tmp_path, monkeypatch) -> None:
    """C: 无点文件名 Makefile 在白名单内, 成功上传"""
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={"file": ("Makefile", io.BytesIO(b"all:\n\techo hi\n"), "")},
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["media_ref"]["id"]
    assert _disk_count(tmp_path) == before + 2


def test_dockerfile_success(tmp_path, monkeypatch) -> None:
    """C: 无点文件名 Dockerfile 在白名单内"""
    client = _client(tmp_path, monkeypatch)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={
            "file": (
                "Dockerfile",
                io.BytesIO(b"FROM python:3.10\nRUN pip install x\n"),
                "",
            )
        },
    )
    assert resp.status_code == 200, resp.json()


# ── 失败路径 (A 错误可见性 + E 状态码规范) ──────────────────────────────


def test_unsupported_extension_returns_415(tmp_path, monkeypatch) -> None:
    """A/E: .exe 类型不被接受 -> 415 Unsupported Media Type"""
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={
            "file": (
                "virus.exe",
                io.BytesIO(b"MZ\x90\x00"),
                "application/x-msdownload",
            )
        },
    )
    assert resp.status_code == 415
    body = resp.json()
    assert body["error_code"] == "unsupported_type"
    assert "error" in body
    assert _disk_count(tmp_path) == before


def test_unknown_filename_without_extension_returns_415(tmp_path, monkeypatch) -> None:
    """C: 无点文件名 LICENSE 不在白名单 -> 415"""
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={"file": ("LICENSE", io.BytesIO(b"MIT License..."), "")},
    )
    assert resp.status_code == 415
    body = resp.json()
    assert body["error_code"] == "unsupported_type"
    assert _disk_count(tmp_path) == before


def test_too_large_returns_413(tmp_path, monkeypatch) -> None:
    """A/E: >25MB -> 413 Payload Too Large"""
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    huge = b"\x00" * (chat_attachment_routes.MAX_ATTACHMENT_SIZE + 1)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={"file": ("huge.txt", io.BytesIO(huge), "text/plain")},
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error_code"] == "too_large"
    assert _disk_count(tmp_path) == before


def test_binary_garbage_rejected_as_unsupported(tmp_path, monkeypatch) -> None:
    """A: 完全非文本、非音频、非文档 -> 415"""
    client = _client(tmp_path, monkeypatch)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={
            "file": (
                "mystery.bin",
                io.BytesIO(b"\x00\x01\x02\x03"),
                "application/octet-stream",
            )
        },
    )
    assert resp.status_code == 415
    body = resp.json()
    assert body["error_code"] == "unsupported_type"


# ── 孤儿文件治理 (D) ───────────────────────────────────────────────────


def test_no_orphan_files_on_any_failure(tmp_path, monkeypatch) -> None:
    """D: 所有失败路径必须不留磁盘痕迹"""
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    cases = [
        ("virus.exe", b"MZ\x90\x00", "application/x-msdownload"),
        ("LICENSE", b"MIT", ""),
        ("a.txt", b"\x00" * (chat_attachment_routes.MAX_ATTACHMENT_SIZE + 1), "text/plain"),
    ]
    for name, data, ct in cases:
        client.post(
            "/api/v1/chat/attachments",
            files={"file": (name, io.BytesIO(data), ct)},
        )
    assert _disk_count(tmp_path) == before, (
        f"expected 0 orphans, got {_disk_count(tmp_path) - before}"
    )


# ── PDF 解析失败 (A/E) ─────────────────────────────────────────────────


def test_damaged_pdf_returns_422_parse_failed(tmp_path, monkeypatch) -> None:
    """A/E: 损坏 PDF -> 422 parse_failed, 不留孤儿"""
    client = _client(tmp_path, monkeypatch)
    before = _disk_count(tmp_path)
    resp = client.post(
        "/api/v1/chat/attachments",
        files={
            "file": ("broken.pdf", io.BytesIO(b"%PDF-1.4\n%%EOF"), "application/pdf")
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "parse_failed"
    assert _disk_count(tmp_path) == before
