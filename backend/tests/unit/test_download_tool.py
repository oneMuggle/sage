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
    PART_META_SUFFIX,
    PART_SUFFIX,
    HttpDownloadTool,
    derive_filename,
    sanitize_filename,
)

pytestmark = [pytest.mark.unit]

_BASE = "https://mirror.example.internal"


@pytest.fixture()(autouse=True)
def sleep_calls(monkeypatch):
    """重试退避不真睡；记录等待秒数供断言。"""
    waits = []
    monkeypatch.setattr(download_tool, "_sleep", waits.append)
    return waits


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
    """平台中立的绝对文件名拒绝：按平台给出等价的绝对路径。"""
    absolute = (
        os.path.join(str(tmp_path.anchor), "etc", "passwd")
        if os.name == "nt"
        else "/etc/passwd"
    )
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.pdf", filename=absolute)

    assert result.success is False
    # 两条拒绝路径都是安全等价：相对性检查或工作区边界检查
    assert (
        "filename_must_be_relative" in result.error
        or "path_outside_workspace" in result.error
    )


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


def test_download_network_exception_is_wrapped(tmp_path, sleep_calls):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        route = mock.get("/oops.pdf").mock(side_effect=httpx.ConnectError("conn refused"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/oops.pdf")

    assert result.success is False
    assert "download_failed" in result.error
    assert "ConnectError" in result.error
    # 默认重试 3 次 → 共 4 次请求，3 次退避等待
    assert route.call_count == 4
    assert len(sleep_calls) == 3
    assert list(tmp_path.iterdir()) == []


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


# ---------- Round 5 B1：可靠性 ----------


def _meta(tmp_path, name):
    import json

    return json.loads((tmp_path / (name + PART_META_SUFFIX)).read_text(encoding="utf-8"))


def test_download_sends_browser_headers_and_identity_encoding(tmp_path):
    seen = {}

    def handler(request):
        seen.update(dict(request.headers))
        return Response(200, content=b"pdf")

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is True
    assert "Chrome/" in seen["user-agent"]
    assert seen["accept-encoding"] == "identity"
    assert seen["referer"] == f"{_BASE}/"
    assert seen["accept"] == "*/*"


def test_download_referer_override(tmp_path):
    seen = {}

    def handler(request):
        seen["referer"] = request.headers.get("referer")
        return Response(200, content=b"pdf")

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(side_effect=handler)
        _tool(tmp_path).execute(
            url=f"{_BASE}/paper.pdf", referer="https://portal.example.internal/list"
        )

    assert seen["referer"] == "https://portal.example.internal/list"


def test_download_retries_on_5xx_then_succeeds(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        route = mock.get("/flaky.pdf").mock(
            side_effect=[Response(503), Response(502), Response(200, content=b"%PDF-ok")]
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/flaky.pdf")

    assert result.success is True
    assert route.call_count == 3
    assert result.content["attempts"] == 3
    assert (tmp_path / "flaky.pdf").read_bytes() == b"%PDF-ok"
    assert not (tmp_path / ("flaky.pdf" + PART_SUFFIX)).exists()
    assert not (tmp_path / ("flaky.pdf" + PART_META_SUFFIX)).exists()


def test_download_retries_zero_disables_retry(tmp_path, sleep_calls):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        route = mock.get("/once.pdf").mock(return_value=Response(503))
        result = _tool(tmp_path).execute(url=f"{_BASE}/once.pdf", retries=0)

    assert result.success is False
    assert route.call_count == 1
    assert sleep_calls == []
    assert "HTTP 503" in result.error


def test_download_honors_retry_after_on_429(tmp_path, sleep_calls):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/limited.pdf").mock(
            side_effect=[
                Response(429, headers={"retry-after": "7"}),
                Response(200, content=b"%PDF-ok"),
            ]
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/limited.pdf")

    assert result.success is True
    assert sleep_calls == [7.0]


def test_download_retry_after_is_capped(tmp_path, sleep_calls):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/limited.pdf").mock(
            side_effect=[
                Response(503, headers={"retry-after": "3600"}),
                Response(200, content=b"%PDF-ok"),
            ]
        )
        _tool(tmp_path).execute(url=f"{_BASE}/limited.pdf")

    assert sleep_calls == [60.0]


def test_download_does_not_retry_403_and_gives_guidance(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        route = mock.get("/forbidden.pdf").mock(return_value=Response(403))
        result = _tool(tmp_path).execute(url=f"{_BASE}/forbidden.pdf")

    assert result.success is False
    assert route.call_count == 1
    assert "http_403" in result.error
    assert "credential_domain" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_does_not_retry_404(tmp_path, sleep_calls):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        route = mock.get("/missing.pdf").mock(return_value=Response(404))
        result = _tool(tmp_path).execute(url=f"{_BASE}/missing.pdf")

    assert result.success is False
    assert route.call_count == 1
    assert sleep_calls == []


def test_download_backoff_is_exponential(tmp_path, sleep_calls):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/down.pdf").mock(return_value=Response(500))
        _tool(tmp_path).execute(url=f"{_BASE}/down.pdf", retries=3)

    assert len(sleep_calls) == 3
    # 1·2^0, 1·2^1, 1·2^2 各加 ≤25% jitter
    assert 1.0 <= sleep_calls[0] <= 1.25
    assert 2.0 <= sleep_calls[1] <= 2.5
    assert 4.0 <= sleep_calls[2] <= 5.0


def test_download_html_instead_of_pdf_is_rejected(tmp_path):
    login = (
        b"<!DOCTYPE html><html><head><title>Login</title></head><body>Please sign in</body></html>"
    )
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        route = mock.get("/paper.pdf").mock(
            return_value=Response(200, content=login, headers={"content-type": "text/html"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is False
    assert "html_instead_of_file" in result.error
    assert "Please sign in" in result.error
    assert "credential_domain" in result.error
    assert route.call_count == 1  # 不重试
    assert list(tmp_path.iterdir()) == []


def test_download_html_with_pdf_content_type_is_rejected(tmp_path):
    """Content-Type 撒谎说 pdf，首块却是 HTML —— 按魔数判定。"""
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/dl?id=9").mock(
            return_value=Response(
                200,
                content=b"<html><body>captcha</body></html>",
                headers={"content-type": "application/pdf"},
            )
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/dl?id=9")

    assert result.success is False
    assert "html_instead_of_file" in result.error


def test_download_html_page_without_file_expectation_is_saved(tmp_path):
    """URL 与 Content-Type 都不暗示文件类型 → 存 HTML 是用户本意，不拦。"""
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/page").mock(
            return_value=Response(
                200, content=b"<html>hi</html>", headers={"content-type": "text/html"}
            )
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/page", filename="page.html")

    assert result.success is True
    assert (tmp_path / "page.html").read_bytes() == b"<html>hi</html>"


def test_download_incomplete_keeps_part_when_resumable(tmp_path):
    """声明 100 字节只到 40 字节且服务器支持 Range → 保留 .part，重试走续传。"""
    calls = []

    def handler(request):
        calls.append(request.headers.get("range"))
        if len(calls) == 1:
            return Response(
                200,
                content=b"A" * 40,
                headers={"content-length": "100", "accept-ranges": "bytes", "etag": '"v1"'},
            )
        assert request.headers.get("range") == "bytes=40-"
        assert request.headers.get("if-range") == '"v1"'
        return Response(
            206,
            content=b"B" * 60,
            headers={"content-range": "bytes 40-99/100", "content-length": "60"},
        )

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/big.bin").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/big.bin")

    assert result.success is True
    assert calls == [None, "bytes=40-"]
    assert result.content["resumed"] is True
    assert result.content["attempts"] == 2
    assert result.content["total_bytes"] == 100
    data = (tmp_path / "big.bin").read_bytes()
    assert data == b"A" * 40 + b"B" * 60
    assert not (tmp_path / ("big.bin" + PART_SUFFIX)).exists()


def test_download_incomplete_without_range_support_redownloads(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.headers.get("range"))
        if len(calls) == 1:
            return Response(200, content=b"A" * 40, headers={"content-length": "100"})
        return Response(200, content=b"C" * 100, headers={"content-length": "100"})

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/norange.bin").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/norange.bin")

    assert result.success is True
    assert calls == [None, None]
    assert result.content["resumed"] is False
    assert (tmp_path / "norange.bin").read_bytes() == b"C" * 100


def test_download_incomplete_exhausted_leaves_part_and_hints(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/stall.bin").mock(
            return_value=Response(
                200, content=b"A" * 10, headers={"content-length": "50", "accept-ranges": "bytes"}
            )
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/stall.bin", retries=1)

    assert result.success is False
    assert "incomplete_download" in result.error
    assert ".part 已保留" in result.error
    part = tmp_path / ("stall.bin" + PART_SUFFIX)
    assert part.exists()
    meta = _meta(tmp_path, "stall.bin")
    assert meta["url"] == f"{_BASE}/stall.bin"
    assert meta["accept_ranges"] is True
    assert meta["total"] == 50
    assert not (tmp_path / "stall.bin").exists()


def test_download_resumes_from_leftover_part_on_new_call(tmp_path):
    """上次调用留下的 .part → 新调用同 URL 自动续传。"""
    import json

    (tmp_path / ("paper.pdf" + PART_SUFFIX)).write_bytes(b"%PDF-" + b"x" * 15)
    (tmp_path / ("paper.pdf" + PART_META_SUFFIX)).write_text(
        json.dumps(
            {
                "url": f"{_BASE}/paper.pdf",
                "etag": '"e1"',
                "total": 30,
                "accept_ranges": True,
            }
        ),
        encoding="utf-8",
    )
    seen = {}

    def handler(request):
        seen["range"] = request.headers.get("range")
        seen["if_range"] = request.headers.get("if-range")
        return Response(
            206,
            content=b"y" * 10,
            headers={"content-range": "bytes 20-29/30", "content-length": "10"},
        )

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is True
    assert seen == {"range": "bytes=20-", "if_range": '"e1"'}
    assert result.content["resumed"] is True
    assert (tmp_path / "paper.pdf").read_bytes() == b"%PDF-" + b"x" * 15 + b"y" * 10
    assert not (tmp_path / ("paper.pdf" + PART_SUFFIX)).exists()
    assert not (tmp_path / ("paper.pdf" + PART_META_SUFFIX)).exists()


def test_download_resume_disabled_ignores_part(tmp_path):
    import json

    (tmp_path / ("paper.pdf" + PART_SUFFIX)).write_bytes(b"old")
    (tmp_path / ("paper.pdf" + PART_META_SUFFIX)).write_text(
        json.dumps({"url": f"{_BASE}/paper.pdf", "accept_ranges": True}), encoding="utf-8"
    )
    seen = {}

    def handler(request):
        seen["range"] = request.headers.get("range")
        return Response(200, content=b"%PDF-new")

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf", resume=False)

    assert result.success is True
    assert seen["range"] is None
    # 旧 .part 被 _unique_path 视为占用 → 落到带后缀名字，不碰旧半成品
    assert result.content["filename"] == "paper-1.pdf"
    assert (tmp_path / ("paper.pdf" + PART_SUFFIX)).read_bytes() == b"old"


def test_download_server_ignores_range_restarts_from_scratch(tmp_path):
    import json

    (tmp_path / ("f.bin" + PART_SUFFIX)).write_bytes(b"stale")
    (tmp_path / ("f.bin" + PART_META_SUFFIX)).write_text(
        json.dumps({"url": f"{_BASE}/f.bin", "accept_ranges": True, "etag": '"old"'}),
        encoding="utf-8",
    )
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        # If-Range 不匹配 → 服务器回 200 全量
        mock.get("/f.bin").mock(return_value=Response(200, content=b"FRESH-CONTENT"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/f.bin")

    assert result.success is True
    assert result.content["resumed"] is False
    assert (tmp_path / "f.bin").read_bytes() == b"FRESH-CONTENT"


def test_download_416_with_matching_total_finalizes(tmp_path):
    import json

    (tmp_path / ("done.bin" + PART_SUFFIX)).write_bytes(b"0123456789")
    (tmp_path / ("done.bin" + PART_META_SUFFIX)).write_text(
        json.dumps({"url": f"{_BASE}/done.bin", "accept_ranges": True, "total": 10}),
        encoding="utf-8",
    )
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/done.bin").mock(
            return_value=Response(416, headers={"content-range": "bytes */10"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/done.bin")

    assert result.success is True
    assert result.content["bytes_written"] == 10
    assert (tmp_path / "done.bin").read_bytes() == b"0123456789"


def test_download_sha256_mismatch_deletes_file(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/x.bin").mock(return_value=Response(200, content=b"abc"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/x.bin", expected_sha256="0" * 64)

    assert result.success is False
    assert "sha256_mismatch" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_sha256_match_reports_digest(tmp_path):
    import hashlib

    digest = hashlib.sha256(b"abc").hexdigest()
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/x.bin").mock(return_value=Response(200, content=b"abc"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/x.bin", expected_sha256=digest.upper())

    assert result.success is True
    assert result.content["sha256"] == digest


def test_download_rejects_malformed_sha256(tmp_path):
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.bin", expected_sha256="zz")
    assert result.success is False
    assert "invalid_expected_sha256" in result.error


def test_download_uses_split_timeouts(tmp_path, monkeypatch):
    seen = {}
    original_client = httpx.Client

    class RecordingClient(original_client):
        def __init__(self, *args, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("backend.tools.download_tool.httpx.Client", RecordingClient)
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/t.bin").mock(return_value=Response(200, content=b"x"))
        _tool(tmp_path).execute(url=f"{_BASE}/t.bin")

    timeout = seen["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == 30.0
    assert timeout.connect == 15.0


def test_download_mid_stream_error_resumes(tmp_path):
    """流中途 ReadError → 保留 .part → 重试以 Range 续传。

    httpx.iter_bytes 按块缓冲：首块 64 KiB 填满前出错不会产出任何字节（此时
    无半成品，走干净重试）；所以让流先产出 > 64 KiB 再中断。
    """
    chunk = 64 * 1024
    total = chunk + 1000
    calls = []

    def first_stream():
        yield b"A" * chunk
        yield b"A" * 10
        raise httpx.ReadError("connection reset")

    def handler(request):
        calls.append(request.headers.get("range"))
        if len(calls) == 1:
            return Response(
                200,
                stream=_IterStream(first_stream()),
                headers={"content-length": str(total), "accept-ranges": "bytes"},
            )
        assert request.headers.get("range") == f"bytes={chunk}-"
        return Response(
            206,
            content=b"B" * 1000,
            headers={
                "content-range": f"bytes {chunk}-{total - 1}/{total}",
                "content-length": "1000",
            },
        )

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/reset.bin").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/reset.bin")

    assert result.success is True, result.error
    assert calls == [None, f"bytes={chunk}-"]
    assert result.content["resumed"] is True
    assert (tmp_path / "reset.bin").read_bytes() == b"A" * chunk + b"B" * 1000


def test_download_error_before_first_chunk_retries_cleanly(tmp_path):
    """首块都没读到就断 → 无半成品、不发 Range，干净重试。"""
    calls = []

    def dead_stream():
        raise httpx.ReadError("reset early")
        yield b""  # noqa: RET503 — 使函数成为生成器

    def handler(request):
        calls.append(request.headers.get("range"))
        if len(calls) == 1:
            return Response(
                200, stream=_IterStream(dead_stream()), headers={"accept-ranges": "bytes"}
            )
        return Response(200, content=b"%PDF-ok")

    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/early.pdf").mock(side_effect=handler)
        result = _tool(tmp_path).execute(url=f"{_BASE}/early.pdf")

    assert result.success is True
    assert calls == [None, None]
    assert result.content["resumed"] is False
    assert not (tmp_path / ("early.pdf" + PART_SUFFIX)).exists()


class _IterStream(httpx.SyncByteStream):
    def __init__(self, gen):
        self._gen = gen

    def __iter__(self):
        yield from self._gen

    def close(self):
        pass
