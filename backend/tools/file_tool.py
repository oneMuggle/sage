"""
文件工具 - 文件系统操作

M1 工具安全加固（移植 claw-code file_ops.rs 的边界/限额设计）:

- 读写非对称: WRITE 操作强制 workspace 边界（resolve 后前缀比对，同时拦
  ``../`` 穿越与符号链接逃逸）；READ 操作**不做**边界检查——与 claw-code
  的 read-vs-write asymmetry 一致，工作区外只读保持可用。
- 硬限额: 读 > 5 MiB / 写 > 10 MiB 直接报错（命名常量，不再静默截断到内存）。
- 二进制检测: 读取前嗅探首 8 KiB 的 NUL 字节，二进制文件报错而非返回乱码。
"""

import logging
import os
from pathlib import Path
from typing import Optional

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

# M1: 硬限额（claw-code file_ops.rs MAX_WRITE_SIZE 对应物）
MAX_READ_SIZE_BYTES = 5 * 1024 * 1024  # 5 MiB —— 超过报错，建议 offset/limit 分页
MAX_WRITE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MiB —— 超过报错
BINARY_SNIFF_BYTES = 8 * 1024  # 8 KiB —— 二进制嗅探窗口


def _path_within_workspace(target: str, workspace_root: str) -> bool:
    """WRITE 边界判定: realpath(target) 必须等于或位于 realpath(root) 之下。

    用 ``os.path.realpath`` 而非字符串前缀:

    - 先解析符号链接 → 工作区内指向外部的 symlink 写入会被拦下（claw-code
      file_ops.rs ``is_symlink_escape`` 的等价语义）;
    - ``startswith(root + os.sep)`` 避免 ``/foo/bar2`` 误匹配 ``/foo/bar``;
    - 允许等于 root 本身（极端情况: 直接操作根目录节点）。
    """
    resolved_target = os.path.realpath(str(Path(target).expanduser()))
    resolved_root = os.path.realpath(str(Path(workspace_root).expanduser()))
    return resolved_target == resolved_root or resolved_target.startswith(
        resolved_root + os.sep
    )


def _contains_binary_marker(file_path: Path) -> bool:
    """嗅探文件首 8 KiB 是否含 NUL 字节（二进制文件启发式）。"""
    try:
        with open(file_path, "rb") as f:
            head = f.read(BINARY_SNIFF_BYTES)
    except OSError:
        return False
    return b"\x00" in head


def _pre_read_checks(file_path: Path, original_bytes: int) -> Optional[ToolResult]:
    """M1 读取前置检查: 硬限额 + 二进制嗅探。

    返回 ``ToolResult(success=False)`` 表示拒绝（调用方直接返回）；
    返回 ``None`` 表示放行。拆成独立函数以保持 ``execute()`` 扁平。
    """
    if original_bytes > MAX_READ_SIZE_BYTES:
        return ToolResult(
            success=False,
            error=(
                f"file_too_large: 文件大小 {original_bytes} 字节超过读取上限 "
                f"{MAX_READ_SIZE_BYTES} 字节 (5 MiB)，请使用 offset/limit 参数分页读取"
            ),
        )
    if _contains_binary_marker(file_path):
        return ToolResult(
            success=False,
            error="binary_file: 检测到二进制文件，不支持读取文本内容",
        )
    return None


class ReadFileTool(BaseTool):
    """读取文件工具"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_file",
            description="读取文件内容。支持文本文件和代码文件。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "offset": {"type": "integer", "description": "起始行号 (默认 1)"},
                    "limit": {"type": "integer", "description": "读取行数 (默认 500)"},
                },
                "required": ["path"],
            },
        )

    def _is_safe_path(self, path: str, allowed_base: str) -> bool:  # noqa: F811 — 保留为外部 API
        """历史 API：保留给外部调用方；M1 起 READ 不再强制 workspace 边界。"""
        from .base import _is_safe_path as _base_is_safe_path

        return _base_is_safe_path(path, allowed_base)

    def execute(self, path: str, offset: int = 1, limit: int = 500, **kwargs) -> ToolResult:
        """
        读取文件

        Args:
            path: 文件路径
            offset: 起始行号
            limit: 读取行数

        M1: READ 不做 workspace 边界检查（读写非对称，claw-code 设计）;
            超过 ``MAX_READ_SIZE_BYTES`` 直接报错并建议 offset/limit;
            首 8 KiB 含 NUL → 二进制文件报错。
        M2: ``policy.max_read_bytes`` 字节上限（≤ 5 MiB 的文件）——超限时
            **流式**读取（先于行切片）并标记 ``truncated=True``。
        """
        if self._policy.workspace_root:
            logger.debug(
                "read_file: workspace_root 已设置但 READ 不做边界检查 (读写非对称): %s", path
            )
        try:
            file_path = Path(path).expanduser()

            if not file_path.exists():
                return ToolResult(success=False, error=f"文件不存在: {path}")

            if not file_path.is_file():
                return ToolResult(success=False, error=f"不是文件: {path}")

            # 检查权限
            if not os.access(file_path, os.R_OK):
                return ToolResult(success=False, error="无读取权限")

            original_bytes = file_path.stat().st_size

            # M1: 硬限额 + 二进制嗅探（拒绝时返回错误 ToolResult）
            blocked = _pre_read_checks(file_path, original_bytes)
            if blocked is not None:
                return blocked

            max_bytes = self._policy.max_read_bytes
            truncated = original_bytes > max_bytes

            if truncated:
                # 流式读取：仅读 max_bytes 字节到内存
                with open(file_path, "rb") as f:
                    raw_bytes = f.read(max_bytes)
                content = raw_bytes.decode("utf-8", errors="replace")
            else:
                content = file_path.read_text(encoding="utf-8", errors="replace")

            lines = content.split("\n")

            # 处理分页
            start = max(0, offset - 1)
            end = min(len(lines), start + limit)
            selected_content = "\n".join(lines[start:end])

            return ToolResult(
                success=True,
                content={
                    "total_lines": len(lines),
                    "content": selected_content,
                    "path": str(file_path.resolve()),
                    "truncated": truncated,
                    "original_bytes": original_bytes,
                    "max_read_bytes": max_bytes if truncated else None,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WriteFileTool(BaseTool):
    """写入文件工具"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="write_file",
            description="写入内容到文件。如果文件存在则覆盖。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                    "append": {"type": "boolean", "description": "是否追加模式 (默认 false)"},
                },
                "required": ["path", "content"],
            },
        )

    def execute(self, path: str, content: str, append: bool = False, **kwargs) -> ToolResult:
        """
        写入文件

        Args:
            path: 文件路径
            content: 文件内容
            append: 是否追加模式

        M1: workspace 边界强制（realpath 前缀比对，拦 ``../`` 穿越 + symlink
            逃逸）；未绑定 workspace 时不检查（保留当前行为）+ debug 日志。
            内容超过 ``MAX_WRITE_SIZE_BYTES`` (10 MiB) 直接报错。
        """
        root = self._policy.workspace_root
        if root:
            if not _path_within_workspace(path, root):
                resolved = os.path.realpath(str(Path(path).expanduser()))
                return ToolResult(
                    success=False,
                    error=(
                        f"path_outside_workspace: 写入目标 resolve 后 ({resolved}) 不在 "
                        f"workspace 根目录 ({root}) 之内，拒绝写入"
                    ),
                )
        else:
            logger.debug("write_file: 未绑定 workspace_root，跳过边界检查: %s", path)

        try:
            # M1: 写入硬限额（按 UTF-8 编码后字节数计）
            content_bytes = len(content.encode("utf-8"))
            if content_bytes > MAX_WRITE_SIZE_BYTES:
                return ToolResult(
                    success=False,
                    error=(
                        f"content_too_large: 内容 {content_bytes} 字节超过写入上限 {MAX_WRITE_SIZE_BYTES} 字节 (10 MiB)"
                    ),
                )

            file_path = Path(path).expanduser()

            # 检查目录是否存在
            file_path.parent.mkdir(parents=True, exist_ok=True)

            mode = "a" if append else "w"
            with open(file_path, mode, encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                success=True,
                content={
                    "path": str(file_path.resolve()),
                    "bytes_written": content_bytes,
                    "mode": mode,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ListDirTool(BaseTool):
    """列出目录工具"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="list_dir",
            description="列出目录内容",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径"},
                    "all": {"type": "boolean", "description": "是否显示隐藏文件 (默认 true)"},
                },
                "required": ["path"],
            },
        )

    def execute(self, path: str, all: bool = True, **kwargs) -> ToolResult:
        """
        列出目录

        Args:
            path: 目录路径
            all: 是否显示隐藏文件

        M1: list_dir 属 READ 能力——不做 workspace 边界检查（读写非对称）。
        M2: ``policy.max_result_items`` 条数上限——超限时截断 ``items``；
            content 含 ``truncated``/``total_items``。
        """
        if self._policy.workspace_root:
            logger.debug(
                "list_dir: workspace_root 已设置但 READ 不做边界检查 (读写非对称): %s", path
            )
        try:
            dir_path = Path(path).expanduser()

            if not dir_path.exists():
                return ToolResult(success=False, error=f"目录不存在: {path}")

            if not dir_path.is_dir():
                return ToolResult(success=False, error=f"不是目录: {path}")

            items = []
            for item in dir_path.iterdir():
                if not all and item.name.startswith("."):
                    continue
                items.append(
                    {
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                    }
                )

            total_items = len(items)
            max_items = self._policy.max_result_items
            truncated = total_items > max_items

            # 排序：目录在前，文件在后，按名称排序
            items.sort(key=lambda x: (x["type"] != "dir", x["name"]))
            if truncated:
                items = items[:max_items]

            return ToolResult(
                success=True,
                content={
                    "path": str(dir_path.resolve()),
                    "items": items,
                    "truncated": truncated,
                    "total_items": total_items,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
