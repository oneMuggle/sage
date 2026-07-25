"""attachment_resolver 核心单元测试 (Task 1).

覆盖:
- extract_mentions: 正则触发、扩展名分类、重复去重、无扩展跳过
- resolve_mentions: 每种 kind 调用对应 _digest_* (mock), 失败降级
- render_attachment_block: 空 list 返回空串; 单/多块分隔符
- process: 端到端 fixture

注: _digest_* 函数在 Task 2 才实现, 本 Task 的 resolve/process 测试用 unittest.mock.patch
    桩化 `_digest_ppt / _digest_word / _digest_excel` 让 extract/render/path 测试通过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.chat import attachment_resolver
from backend.chat.attachment_resolver import (
    OFFICE_EXTS,
    Mention,
    ResolvedBlock,
    extract_mentions,
    process,
    render_attachment_block,
    resolve_mentions,
)

# ─── extract_mentions ────────────────────────────────────────────


def test_extract_mentions_basic_pptx() -> None:
    mentions = extract_mentions("看一下 @foo.pptx 好吗")
    assert len(mentions) == 1
    assert mentions[0].path == "foo.pptx"
    assert mentions[0].kind == "office-ppt"


def test_extract_mentions_basic_docx_xlsx() -> None:
    mentions = extract_mentions("对比 @a.docx 和 @b.xlsx")
    kinds = {m.kind for m in mentions}
    assert kinds == {"office-word", "office-excel"}


def test_extract_mentions_path_with_slash() -> None:
    """绝对/相对路径都识别"""
    mentions = extract_mentions("@/tmp/workspace/proposal.pptx")
    assert mentions[0].path == "/tmp/workspace/proposal.pptx"
    assert mentions[0].kind == "office-ppt"


def test_extract_mentions_skips_pure_word() -> None:
    """不含 '/' 或 '.' 的纯单词 (如 @com) 不当 mention"""
    assert extract_mentions("see @com irc") == []


def test_extract_mentions_dedup() -> None:
    """同一 path 多次出现只取 1 个"""
    mentions = extract_mentions("@foo.pptx 与 @foo.pptx")
    assert len(mentions) == 1


def test_extract_mentions_skips_non_office_extensions() -> None:
    """非 office 后缀的 path 仍识别为 mention, kind=None (留作未来扩展点)"""
    mentions = extract_mentions("@notes.txt")
    assert len(mentions) == 1
    assert mentions[0].kind is None


def test_extract_mentions_empty_string() -> None:
    assert extract_mentions("") == []


def test_office_exts_is_frozen() -> None:
    assert frozenset({".pptx", ".docx", ".xlsx"}) == OFFICE_EXTS


# ─── resolve_mentions (mock _digest_*) ───────────────────────────


def _touch_office_file(tmp_path, filename):
    file_path = tmp_path / filename
    file_path.touch()
    return file_path


def test_resolve_mentions_skips_non_office(monkeypatch) -> None:
    """kind=None 的 mention 直接跳过"""
    mentions = [Mention(raw="@a.txt", path="a.txt", kind=None)]
    blocks = resolve_mentions(mentions, workspace="/w")
    assert blocks == []


def test_resolve_mentions_calls_ppt_digest(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        attachment_resolver,
        "_digest_ppt",
        lambda path, workspace: "PPT_DUMMY",
    )
    _touch_office_file(tmp_path, "x.pptx")
    mentions = [Mention(raw="@x.pptx", path="x.pptx", kind="office-ppt")]
    blocks = resolve_mentions(mentions, workspace=str(tmp_path))
    assert len(blocks) == 1
    assert blocks[0].digest_text == "PPT_DUMMY"
    assert blocks[0].source_ref == "x.pptx"


def test_resolve_mentions_calls_word_digest(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        attachment_resolver,
        "_digest_word",
        lambda path, workspace: "WORD_DUMMY",
    )
    _touch_office_file(tmp_path, "y.docx")
    mentions = [Mention(raw="@y.docx", path="y.docx", kind="office-word")]
    blocks = resolve_mentions(mentions, workspace=str(tmp_path))
    assert blocks[0].digest_text == "WORD_DUMMY"


def test_resolve_mentions_calls_excel_digest(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        attachment_resolver,
        "_digest_excel",
        lambda path, workspace: "EXCEL_DUMMY",
    )
    _touch_office_file(tmp_path, "z.xlsx")
    mentions = [Mention(raw="@z.xlsx", path="z.xlsx", kind="office-excel")]
    blocks = resolve_mentions(mentions, workspace=str(tmp_path))
    assert blocks[0].digest_text == "EXCEL_DUMMY"


def test_resolve_mentions_silently_skips_on_error(monkeypatch, caplog, tmp_path) -> None:
    """_digest_ppt 抛 OfficePathError 时, 本 mention 静默 skip + log warning"""
    from backend.office.errors import OfficePathError

    monkeypatch.setattr(
        attachment_resolver,
        "_digest_ppt",
        lambda path, workspace: (_ for _ in ()).throw(OfficePathError("boom", file_path=None)),
    )
    _touch_office_file(tmp_path, "bad.pptx")
    mentions = [Mention(raw="@bad.pptx", path="bad.pptx", kind="office-ppt")]
    blocks = resolve_mentions(mentions, workspace=str(tmp_path))
    assert blocks == []


def test_resolve_mentions_skips_path_outside_workspace(monkeypatch, tmp_path) -> None:
    outside_path = tmp_path.parent / "outside.pptx"
    outside_path.touch()
    digest_calls = []
    monkeypatch.setattr(
        attachment_resolver,
        "_digest_ppt",
        lambda path, workspace: digest_calls.append(path) or "P",
    )

    mentions = [Mention(raw=str(outside_path), path=str(outside_path), kind="office-ppt")]
    blocks = resolve_mentions(mentions, workspace=str(tmp_path))

    assert blocks == []
    assert digest_calls == []


def test_resolve_mentions_skips_oversized_file(monkeypatch, tmp_path) -> None:
    file_path = tmp_path / "large.pptx"
    file_path.write_bytes(b"too large")
    digest_calls = []
    monkeypatch.setattr(attachment_resolver, "MAX_ATTACHMENT_FILE_SIZE_BYTES", 1, raising=False)
    monkeypatch.setattr(
        attachment_resolver,
        "_digest_ppt",
        lambda path, workspace: digest_calls.append(path) or "P",
    )

    mentions = [Mention(raw="large.pptx", path="large.pptx", kind="office-ppt")]
    blocks = resolve_mentions(mentions, workspace=str(tmp_path))

    assert blocks == []
    assert digest_calls == []


def test_resolve_mentions_preserves_order(monkeypatch, tmp_path) -> None:
    """多个 mention 按出现顺序产出 blocks"""
    monkeypatch.setattr(
        attachment_resolver,
        "_digest_ppt",
        lambda p, w: "P",
    )
    monkeypatch.setattr(
        attachment_resolver,
        "_digest_word",
        lambda p, w: "W",
    )
    _touch_office_file(tmp_path, "a.pptx")
    _touch_office_file(tmp_path, "b.docx")
    text = "@a.pptx 然后 @b.docx"
    mentions = extract_mentions(text)
    blocks = resolve_mentions(mentions, workspace=str(tmp_path))
    assert [b.source_ref for b in blocks] == ["a.pptx", "b.docx"]


# ─── T3.M4 closure: _resolve_attachment_path 异常链 ───────────


def test_resolve_attachment_path_chains_cause_on_non_regular_file(
    monkeypatch, tmp_path
) -> None:
    """T3.M4 closure: resolved path 不是 regular file 时, 抛出的 OfficePathError
    必须保留底层 cause (PermissionError / OSError 等), 而不是裸 raise 丢上下文。
    """
    from backend.chat.attachment_resolver import _resolve_attachment_path
    from backend.office.errors import OfficePathError

    workspace_root = tmp_path
    candidate = workspace_root / "missing.pptx"

    # 让 Path.is_file() 抛 PermissionError, 模拟沙箱里 stat 失败
    def is_file_with_error(self, *args, **kwargs):  # noqa: ANN001
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "is_file", is_file_with_error)

    with pytest.raises(OfficePathError) as exc_info:
        _resolve_attachment_path(str(candidate), workspace_root)

    # 关键: __cause__ 必须链回底层 PermissionError
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, PermissionError)


def test_resolve_attachment_path_chains_cause_on_size_check(
    monkeypatch, tmp_path
) -> None:
    """T3.M4 closure (size branch): stat 抛 OSError 时, OfficeSizeLimitError
    必须保留 __cause__ — 后续 logger.warning 能看到根因。
    """
    from backend.chat.attachment_resolver import _resolve_attachment_path
    from backend.office.errors import OfficeSizeLimitError

    workspace_root = tmp_path
    file_path = workspace_root / "x.pptx"
    file_path.write_bytes(b"hi")

    # is_file 直接返回 True (不调真实 stat — 因为 stat 也被 patch).
    # 然后我们 patched stat 在 size 分支抛 OSError.
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    target_path = file_path.resolve()
    _real_stat = Path.stat

    def _patched_stat(self, *args, **kwargs):
        if str(self) == str(target_path):
            raise OSError(5, "I/O error", str(self))
        return _real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _patched_stat)

    with pytest.raises(OfficeSizeLimitError) as exc_info:
        _resolve_attachment_path(str(file_path), workspace_root)

    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, OSError)


# ─── render_attachment_block ─────────────────────────────────────


def test_render_empty_list_returns_empty_string() -> None:
    assert render_attachment_block([]) == ""


def test_render_single_block() -> None:
    blocks = [ResolvedBlock(source_ref="foo.pptx", digest_text="D1")]
    out = render_attachment_block(blocks)
    assert out.startswith("<attachments>")
    assert out.endswith("</attachments>")
    assert "=== foo.pptx ===" in out
    assert "D1" in out


def test_render_multiple_blocks_with_separator() -> None:
    blocks = [
        ResolvedBlock(source_ref="a.pptx", digest_text="A"),
        ResolvedBlock(source_ref="b.docx", digest_text="B"),
    ]
    out = render_attachment_block(blocks)
    assert "=== a.pptx ===" in out
    assert "=== b.docx ===" in out
    assert out.index("a.pptx") < out.index("b.docx")


# ─── process (top-level entry, mock digests) ─────────────────────


def test_process_no_mentions_returns_empty(monkeypatch) -> None:
    """无 @ → 返回空串"""
    assert process("hello world", workspace="/w") == ""


def test_process_happy_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(attachment_resolver, "_digest_ppt", lambda p, w: "D")
    _touch_office_file(tmp_path, "x.pptx")
    out = process("看 @x.pptx", workspace=str(tmp_path))
    assert "<attachments>" in out
    assert "=== x.pptx ===" in out
    assert "D" in out


def test_process_skips_non_office(monkeypatch) -> None:
    """@foo.txt 不触发任何 digest, 返回空串"""
    assert process("see @foo.txt", workspace="/w") == ""
