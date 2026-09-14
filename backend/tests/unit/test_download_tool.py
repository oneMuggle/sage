"""http_download 单元测试：流式落盘 + 大小上限 + 路径边界 + 文件名净化。"""

import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import Response

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.tools import download_tool
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


@pytest.mark.skipif(
    os.name == "nt",
    reason="用例依赖 POSIX 绝对路径语义（/abs/... 在 Windows 非绝对）",
)
def test_download_rejects_absolute_filename(tmp_path):
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.pdf", filename="/etc/passwd")

    assert result.success is False
    if os.name == "nt":
        # Windows 上 "/etc/passwd" 无盘符不算绝对路径，落进工作区边界拒绝；
        # 两条路径都是安全拒绝，语义等价。
        assert "path_outside_workspace" in result.error
    else:
        assert "filename_must_be_relative" in result.error


def test_download_rejects_filename_escaping_workspace(tmp_path):
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.pdf", filename="../../escape.bin")

    assert result.success is False
    assert "path_outside_workspace" in result.error or "filename" in result.error


def test_download_honors_network_policy(tmp_path):
    result = _tool(tmp_path).execute(url="https://evil.example.com/x.pdf")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_download_follows_relative_redirect_and_returns_final_url(tmp_path):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{_BASE}/start").mock(
            return_value=Response(302, headers={"location": "/paper.pdf"})
        )
        mock.get(f"{_BASE}/paper.pdf").mock(return_value=Response(200, content=b"pdf"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/start")

    assert result.success is True
    assert result.content["url"] == f"{_BASE}/paper.pdf"
    assert (tmp_path / "paper.pdf").read_bytes() == b"pdf"


def test_download_rejects_redirect_to_non_whitelisted_host(tmp_path):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{_BASE}/start").mock(
            return_value=Response(302, headers={"location": "https://evil.example.com/file"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/start")

    assert result.success is False
    assert "host_not_allowed" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_sets_tls_verification_for_each_target(tmp_path, monkeypatch):
    calls = []
    original_client = httpx.Client

    class RecordingClient(original_client):
        def __init__(self, *args, **kwargs):
            calls.append(kwargs.get("verify"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("backend.tools.download_tool.httpx.Client", RecordingClient)
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET,
        allowed_hosts=("*.example.internal",),
        insecure_tls_hosts=("mirror.example.internal",),
    )
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(return_value=Response(200, content=b"pdf"))
        tool = HttpDownloadTool(
            policy=ToolPolicy(workspace_root=str(tmp_path)), network_policy=policy
        )
        result = tool.execute(url=f"{_BASE}/paper.pdf")

    assert result.success is True
    assert calls[-1] is False


def test_download_rejects_malformed_ipv6_url(tmp_path):
    result = _tool(tmp_path).execute(url="http://[bad")

    assert result.success is False
    assert "无效的 URL" in result.error


def test_download_offline_rejects(tmp_path):
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


def test_download_exclusive_race_preserves_existing_file(tmp_path):
    target = tmp_path / "paper.pdf"
    target.write_bytes(b"owner's file")
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(return_value=Response(200, content=b"new"))
        with ExitStack() as stack:
            stack.enter_context(
                patch("backend.tools.download_tool._unique_path", return_value=target)
            )
            stack.enter_context(
                patch(
                    "backend.tools.download_tool._open_exclusive",
                    side_effect=FileExistsError("already exists"),
                )
            )
            result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is False
    assert "下载失败" in result.error
    assert target.read_bytes() == b"owner's file"


def test_download_records_artifact_after_success(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/artifact.bin").mock(return_value=Response(200, content=b"payload"))
        with patch.object(HttpDownloadTool, "_record_artifact") as record:
            result = _tool(tmp_path).execute(url=f"{_BASE}/artifact.bin")

    assert result.success is True
    record.assert_called_once_with(str(tmp_path / "artifact.bin"), 7)


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


# ---------- 断点续传（Round 5 D1） ----------


def test_resume_after_mid_stream_failure(tmp_path, monkeypatch):
    """首段写入后瞬态断流 → Range 续传拼接完整文件。"""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("range"))
        if request.headers.get("range") is None:
            def gen():
                yield b"AAABBB"
                raise httpx.ReadError("connection reset")

            return httpx.Response(200, content=gen())
        return httpx.Response(
            206,
            content=b"CCC",
            headers={"content-range": "bytes 6-8/9"},
        )

    monkeypatch.setattr(download_tool, "_CHUNK_BYTES", 2)
    with respx.mock(base_url=_BASE) as mock:
        mock.get("/big.bin").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/big.bin")

    assert result.success is True
    assert Path(result.content["path"]).read_bytes() == b"AAABBBCCC"
    assert result.content["resumed_bytes"] == 3
    assert calls[0] is None
    assert calls[1] == "bytes=6-"


def test_restart_when_server_ignores_range(tmp_path, monkeypatch):
    """服务器不理会 Range（回 200 全量）→ 丢弃半截文件整段重来。"""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("range"))
        if request.headers.get("range") is None:
            if len(calls) == 1:
                def gen():
                    yield b"AAABBB"
                    raise httpx.ReadError("connection reset")

                return httpx.Response(200, content=gen())
            return httpx.Response(200, content=b"AAABBBCCC")
        return httpx.Response(200, content=b"AAABBBCCC")

    monkeypatch.setattr(download_tool, "_CHUNK_BYTES", 2)
    with respx.mock(base_url=_BASE) as mock:
        mock.get("/big.bin").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/big.bin")

    assert result.success is True
    assert Path(result.content["path"]).read_bytes() == b"AAABBBCCC"
    assert result.content["resumed_bytes"] == 0
    assert len(calls) == 3  # 失败 → 续传尝试（服务器忽略 Range）→ 丢弃后整段重来


def test_retry_budget_exhausted_cleans_partial(tmp_path, monkeypatch):
    """每次都中途断流且预算耗尽 → 失败并清理半截文件。"""
    def handler(request: httpx.Request) -> httpx.Response:
        def gen():
            yield b"PARTIAL"
            raise httpx.ReadError("reset again")

        return httpx.Response(200, content=gen())

    monkeypatch.setattr(download_tool, "_CHUNK_BYTES", 2)
    with respx.mock(base_url=_BASE) as mock:
        mock.get("/big.bin").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/big.bin")

    assert result.success is False
    assert "download_retry_exhausted" in result.error
    assert not (tmp_path / "big.bin").exists()


def test_http_status_error_does_not_retry(tmp_path):
    """4xx/5xx 属确定性失败——不进入续传重试。"""
    with respx.mock(base_url=_BASE) as mock:
        route = mock.get("/gone.bin").mock(return_value=Response(404, text="nope"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/gone.bin")

    assert result.success is False
    assert route.call_count == 1


def test_credential_download_does_not_resume(tmp_path, monkeypatch):
    """凭据下载不续传（登录态时效）——中断即失败，不拼错误数据。"""
    import os
    import unittest.mock

    os.environ["SAGE_SECRET_SCHEME"] = "test"

    from backend.tools.credential_vault import save_credential

    class _Repo:
        def __init__(self):
            self.data = {}

        def get(self, key):
            return self.data.get(key)

        def set(self, key, value, **kw):
            self.data[key] = value

    repo = _Repo()
    save_credential(
        ".example.internal",
        [{"name": "SID", "value": "s", "domain": ".example.internal", "path": "/"}],
        repo=repo,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        def gen():
            yield b"AAABBB"
            raise httpx.ReadError("reset")

        return httpx.Response(200, content=gen())

    monkeypatch.setattr(download_tool, "_CHUNK_BYTES", 2)
    with unittest.mock.patch(
        "backend.data.settings_repo.SettingsRepository", return_value=repo
    ), respx.mock(base_url=_BASE) as mock:
        mock.get("/paper.pdf").mock(side_effect=handler)
        result = _tool(tmp_path).execute(
            url=f"{_BASE}/paper.pdf", credential_domain=".example.internal"
        )

    assert result.success is False
    assert "download_interrupted" in result.error
    assert not (tmp_path / "paper.pdf").exists()
