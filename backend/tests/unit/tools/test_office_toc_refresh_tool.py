"""R156 — Word 目录刷新工具（office_refresh_toc）单元测试。

覆盖：schema 契约、ToolExecutionContext 缺失、file_path 校验链（空白/
相对路径/非 .docx/文件不存在/大小写放行）、刷新失败与成功
（model_dump 透传）、workspace 解析（无绑定回退输入父目录）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.domain.risk import RiskClass
from backend.tools.office_toc_refresh_tool import OfficeRefreshTocTool

pytestmark = pytest.mark.unit


def _ctx(session_id="s1", gen=1):
    return SimpleNamespace(session_id=session_id, binding_generation=gen)


@pytest.fixture()
def ctx_patched(monkeypatch):
    """默认提供一个已绑定会话的 ToolExecutionContext。"""
    ctx = _ctx()
    monkeypatch.setattr(
        "backend.tools.context.current_tool_context", lambda: ctx
    )
    return ctx


@pytest.fixture()
def patch_refresh(monkeypatch):
    """patch 惰性导入的 refresh_toc_page_numbers，捕获 (target, workspace)。"""
    import backend.office.toc_refresh as toc_mod

    state = {"ok": True, "error": None, "calls": []}

    def fake_refresh(target, workspace):
        state["calls"].append((target, workspace))
        if state["ok"]:
            return SimpleNamespace(ok=True, model_dump=lambda: {"pages": [1, 2, 3]})
        return SimpleNamespace(ok=False, error="word not installed")

    monkeypatch.setattr(toc_mod, "refresh_toc_page_numbers", fake_refresh)
    return state


def _make_doc(tmp_path, name="doc.docx"):
    p = tmp_path / name
    p.write_bytes(b"PK")
    return p


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_schema_contract():
    schema = OfficeRefreshTocTool().schema
    assert schema.name == "office_refresh_toc"
    assert schema.parameters["required"] == ["file_path"]
    assert OfficeRefreshTocTool.risk == RiskClass.WRITE_LOCAL
    assert OfficeRefreshTocTool.requires_tool_context is True


def test_missing_tool_context_rejected(monkeypatch):
    monkeypatch.setattr("backend.tools.context.current_tool_context", lambda: None)
    out = OfficeRefreshTocTool().execute(file_path="C:/ws/doc.docx")
    assert out.success is False
    assert out.error == "missing_tool_context"


# ---------------------------------------------------------------------------
# 参数校验链
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, "", "   ", 123])
def test_file_path_blank_or_non_string_rejected(ctx_patched, patch_refresh, bad):
    out = OfficeRefreshTocTool().execute(file_path=bad)
    assert out.success is False
    assert out.error == "file_path_required"


def test_relative_path_rejected(ctx_patched, patch_refresh):
    out = OfficeRefreshTocTool().execute(file_path="relative/doc.docx")
    assert out.success is False
    assert "absolute" in out.error


def test_non_docx_rejected(ctx_patched, patch_refresh, tmp_path):
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"x")
    out = OfficeRefreshTocTool().execute(file_path=str(target))
    assert out.success is False
    assert "unsupported_file_type" in out.error


def test_missing_file_rejected(ctx_patched, patch_refresh, tmp_path):
    out = OfficeRefreshTocTool().execute(file_path=str(tmp_path / "ghost.docx"))
    assert out.success is False
    assert "file_not_found" in out.error


# ---------------------------------------------------------------------------
# 刷新分派
# ---------------------------------------------------------------------------


def test_uppercase_docx_accepted(ctx_patched, patch_refresh, tmp_path):
    target = tmp_path / "DOC.DOCX"
    target.write_bytes(b"PK")
    out = OfficeRefreshTocTool().execute(file_path=str(target))
    assert out.success is True


def test_refresh_failure_maps_to_error_prefix(ctx_patched, patch_refresh, tmp_path):
    patch_refresh["ok"] = False
    patch_refresh["error"] = "word not installed"
    target = _make_doc(tmp_path)
    out = OfficeRefreshTocTool().execute(file_path=str(target))
    assert out.success is False
    assert "toc_refresh_failed" in out.error
    assert "word not installed" in out.error


def test_refresh_success_returns_model_dump(ctx_patched, patch_refresh, tmp_path):
    target = _make_doc(tmp_path)
    out = OfficeRefreshTocTool().execute(file_path=str(target))
    assert out.success is True
    assert out.content == {"pages": [1, 2, 3]}
    touched, workspace = patch_refresh["calls"][0]
    assert touched == target.resolve()  # 绝对路径
    assert workspace == target.parent  # 无绑定 → 回退输入父目录
