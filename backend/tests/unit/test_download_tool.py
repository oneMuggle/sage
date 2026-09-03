"""http_download 单元测试：流式落盘 + 大小上限 + 路径边界 + 文件名净化。"""

from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.tools.download_tool import (
    HttpDownloadTool,
    derive_filename,
    sanitize_filename,
)

pytestmark = [pytest.mark.unit]

_BASE = "https://mirror.example.internal"


def _tool(tmp_path, **kw):
    return HttpDownloadTool(
        policy=ToolPolicy(workspace_root=str(tmp_path)),
        network_policy=NetworkPolicy(
            mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",)
        ),
        **kw,
    )


def test_schema_declares_url_required():
    tool = HttpDownloadTool()
    assert tool.schema.name == "http_download"
    assert tool.schema.parameters["required"] == ["url"]


def test_download_streams_to_workspace(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(
            return_value=Response(200, content=b"%PDF-1.4 body", headers={"content-length": "13"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is True
    written = tmp_path / "paper.pdf"
    assert written.read_bytes() == b"%PDF-1.4 body"
    assert result.content["bytes_written"] == 13
    assert result.content["filename"] == "paper.pdf"


def test_download_rejects_when_declared_length_exceeds_cap(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/big.pdf").mock(
            return_value=Response(200, content=b"X" * 10, headers={"content-length": "999999"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/big.pdf", max_bytes=1000)

    assert result.success is False
    assert "content_length_exceeds_limit" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_aborts_and_cleans_when_server_lies_about_length(tmp_path):
    """Content-Length 是服务器说的，不可信 —— 按实际字节数中断并删半成品。"""
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/liar.pdf").mock(
            return_value=Response(200, content=b"X" * 5000, headers={"content-length": "10"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/liar.pdf", max_bytes=1000)

    assert result.success is False
    assert "download_exceeds_limit" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_without_content_length_still_works(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/nolen.bin").mock(return_value=Response(200, content=b"Y" * 50))
        result = _tool(tmp_path).execute(url=f"{_BASE}/nolen.bin")

    assert result.success is True
    assert (tmp_path / "nolen.bin").stat().st_size == 50


def test_download_requires_bound_workspace():
    """workspace_root 未绑定 → 拒绝。_enforce_workspace 此时会放行，不能只靠它。"""
    tool = HttpDownloadTool(
        policy=ToolPolicy(),
        network_policy=NetworkPolicy(
            mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",)
        ),
    )
    result = tool.execute(url=f"{_BASE}/x.pdf")

    assert result.success is False
    assert "workspace_not_bound" in result.error


def test_download_rejects_absolute_filename(tmp_path):
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.pdf", filename="/etc/passwd")

    assert result.success is False
    assert "filename_must_be_relative" in result.error


def test_download_rejects_filename_escaping_workspace(tmp_path):
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.pdf", filename="../../escape.bin")

    assert result.success is False
    assert "path_outside_workspace" in result.error or "filename" in result.error


def test_download_honors_network_policy(tmp_path):
    result = _tool(tmp_path).execute(url="https://evil.example.com/x.pdf")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_download_offline_mode_rejects(tmp_path):
    tool = HttpDownloadTool(
        policy=ToolPolicy(workspace_root=str(tmp_path)),
        network_policy=NetworkPolicy(mode=NetworkMode.OFFLINE),
    )
    result = tool.execute(url=f"{_BASE}/x.pdf")

    assert result.success is False
    assert "network_mode_offline" in result.error


def test_download_http_error_leaves_no_file(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/missing.pdf").mock(return_value=Response(404, content=b"nope"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/missing.pdf")

    assert result.success is False
    assert list(tmp_path.iterdir()) == []


def test_download_network_exception_is_wrapped(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/oops.pdf").mock(side_effect=httpx.ConnectError("conn refused"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/oops.pdf")

    assert result.success is False
    assert "失败" in result.error


def test_download_does_not_overwrite_existing_file(tmp_path):
    (tmp_path / "paper.pdf").write_bytes(b"original")
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(return_value=Response(200, content=b"new"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is True
    assert (tmp_path / "paper.pdf").read_bytes() == b"original"
    # 冲突时落到带后缀的新名字，不覆盖原文件
    assert result.content["filename"] != "paper.pdf"
    assert Path(result.content["path"]).read_bytes() == b"new"


# ---------- 文件名净化 ----------


@pytest.mark.parametrize(
    ("url", "disposition", "expected"),
    [
        (f"{_BASE}/files/论文A.pdf", None, "论文A.pdf"),
        (f"{_BASE}/d?id=1", None, "d"),
        (f"{_BASE}/a/../../etc/passwd", None, "passwd"),
        (f"{_BASE}/x.pdf", 'attachment; filename="../../etc/passwd"', "passwd"),
        (f"{_BASE}/x.pdf", 'attachment; filename="报告 2026.docx"', "报告 2026.docx"),
        (f"{_BASE}/x.pdf", "attachment; filename*=UTF-8''%E8%AE%BA%E6%96%87.pdf", "论文.pdf"),
        (f"{_BASE}/x.pdf", 'attachment; filename="C:\\Windows\\evil.exe"', "evil.exe"),
        (f"{_BASE}/x.pdf", 'attachment; filename="..."', "download.bin"),
        (f"{_BASE}/", None, "download.bin"),
        (f"{_BASE}/%2e%2e%2f%2e%2e%2fpasswd", None, "passwd"),
    ],
)
def test_derive_filename(url, disposition, expected):
    assert derive_filename(url, disposition) == expected


@pytest.mark.parametrize("name", ["/etc/passwd", "..\\..\\evil", "a/b/c.txt"])
def test_sanitize_filename_strips_path_separators(name):
    out = sanitize_filename(name)
    assert "/" not in out
    assert "\\" not in out
    assert ".." not in out


def test_sanitize_filename_removes_nul_byte():
    assert sanitize_filename("a\x00b.pdf") == "ab.pdf"


def test_sanitize_filename_caps_length():
    assert len(sanitize_filename("L" * 300 + ".pdf")) == 120
