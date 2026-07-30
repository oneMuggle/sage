"""A17 — Code Diff 生成服务(纯函数,零 I/O)。

工具执行层(``backend/tools/file_tool.py``)在写文件前后捕获内容,
调用本模块生成 unified diff 与统计信息,挂到
``ToolResult.metadata['code_diff']``;前端 ``CodeDiffViewer`` 经
OBSERVING 事件的 ``parsed.metadata`` 通道渲染(与 imageData 同款机制)。

参考:
- ``/home/fz/project/LLM_Simple/main.py:206-234`` — 写前/写后捕获 + emit
- ``/home/fz/project/pi/packages/coding-agent/src/core/tools/edit-diff.ts`` —
  unified patch 生成 + context lines

大小护栏(防止大文件写穿 SSE / 前端内存):

- ``MAX_DIFF_CONTENT_BYTES``:old/new 任一侧超限 → metadata 省略
  ``old_content``/``new_content``(前端降级渲染 ``unified_diff``)。
- ``MAX_UNIFIED_DIFF_BYTES``:unified diff 超限 → 截断并标
  ``diff_truncated=True``。
- ``MAX_CAPTURE_BYTES``:调用方读旧内容的硬上限(本模块提供
  ``should_skip_capture`` 判定)。
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, Optional

# old/new 单侧内容上限(64 KB):超限则不随 metadata 下发全文,
# 前端仅拿到 unified_diff 做降级渲染。
MAX_DIFF_CONTENT_BYTES = 64 * 1024

# unified diff 文本上限(32 KB):超限截断。
MAX_UNIFIED_DIFF_BYTES = 32 * 1024

# 写前读旧内容的硬上限(1 MB):超限整体跳过 diff 捕获。
MAX_CAPTURE_BYTES = 1024 * 1024

# unified diff 两侧上下文行数(与 pi edit-diff.ts 默认一致:4 行;
# 这里取 3 行以贴近 git 默认,减少 payload)。
DEFAULT_CONTEXT_LINES = 3


def should_skip_capture(byte_size: int) -> bool:
    """文件字节数超 ``MAX_CAPTURE_BYTES`` 时返回 True(调用方跳过捕获)。"""
    return byte_size > MAX_CAPTURE_BYTES


def generate_unified_diff(
    path: str,
    old_content: str,
    new_content: str,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> str:
    """生成标准 unified diff 文本(``---`` / ``+++`` / ``@@`` hunk)。

    与 ``git diff`` 输出同构:header 用 ``a/<path>`` / ``b/<path>``,
    便于未来直接落 patch 文件或导出。

    实现注记:用 ``splitlines()`` + ``lineterm=""`` 而非
    ``splitlines(keepends=True)``——后者对**无尾换行**的末行会把
    ``-old`` 与 ``+new`` 两行粘连成一行(``-old+new``),破坏 hunk 结构。
    """
    display_path = path.lstrip("/")
    diff_iter = difflib.unified_diff(
        old_content.splitlines(),
        new_content.splitlines(),
        fromfile="a/" + display_path,
        tofile="b/" + display_path,
        n=context_lines,
        lineterm="",
    )
    text = "\n".join(diff_iter)
    return text + "\n" if text else ""


def count_changes(unified_diff: str) -> tuple:
    """统计 unified diff 的 (+additions, -deletions) 行数。

    跳过 ``---`` / ``+++`` 文件头行。
    """
    additions = 0
    deletions = 0
    for line in unified_diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def build_code_diff_metadata(
    path: str,
    old_content: str,
    new_content: str,
    is_new_file: bool = False,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> Optional[Dict[str, Any]]:
    """构建 ``code_diff`` metadata dict;内容无变化时返回 ``None``。

    Returns:
        - ``None`` — old == new,无需展示 diff。
        - ``{path, is_new_file, unified_diff, additions, deletions,
           [old_content, new_content], [diff_truncated]}``。
          old/new 任一侧超 ``MAX_DIFF_CONTENT_BYTES`` 时省略全文键,
          前端据 ``unified_diff`` 降级渲染。
    """
    if old_content == new_content:
        return None

    unified = generate_unified_diff(path, old_content, new_content, context_lines)
    # 统计基于截断**前**的完整 diff(截断后 + 行可能被切掉)
    additions, deletions = count_changes(unified)

    diff_truncated = False
    unified_bytes = len(unified.encode("utf-8"))
    if unified_bytes > MAX_UNIFIED_DIFF_BYTES:
        # 按字符截断(UTF-8 下字符数 ≤ 字节数,截断后字节数必然达标);
        # 丢弃尾部不完整 hunk 是可接受的——前端渲染时仅缺少末尾上下文。
        unified = unified[: MAX_UNIFIED_DIFF_BYTES]
        diff_truncated = True

    metadata: Dict[str, Any] = {
        "path": path,
        "is_new_file": is_new_file,
        "unified_diff": unified,
        "additions": additions,
        "deletions": deletions,
    }
    if diff_truncated:
        metadata["diff_truncated"] = True

    # 全文仅在双侧均不超限时下发(前端 react-diff-viewer 高亮渲染用)
    old_bytes = len(old_content.encode("utf-8"))
    new_bytes = len(new_content.encode("utf-8"))
    if old_bytes <= MAX_DIFF_CONTENT_BYTES and new_bytes <= MAX_DIFF_CONTENT_BYTES:
        metadata["old_content"] = old_content
        metadata["new_content"] = new_content

    return metadata
