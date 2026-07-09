"""
文件工具 - 文件系统操作
"""

import os
from pathlib import Path

from .base import BaseTool, ToolResult, ToolSchema


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
        """历史 API：保留给外部调用方；推荐用基类 ``_enforce_workspace``。"""
        from .base import _is_safe_path as _base_is_safe_path

        return _base_is_safe_path(path, allowed_base)

    def execute(self, path: str, offset: int = 1, limit: int = 500, **kwargs) -> ToolResult:
        """
        读取文件

        Args:
            path: 文件路径
            offset: 起始行号
            limit: 读取行数

        M2: ``policy.max_read_bytes`` 字节上限——超限时**流式**读取（先于行
        切片），避免一次性 ``read_text`` 把大文件载入内存。截断时 content
        含 ``truncated=True, original_bytes, max_read_bytes``。
        M3: ``policy.workspace_root`` 路径守卫（resolve 后比对，拒 ..、越界、symlink 逃逸）。
        """
        blocked = self._enforce_workspace(path)
        if blocked is not None:
            return blocked
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

        M3: ``policy.workspace_root`` 路径守卫；越界直接拒写（不创建文件）。
        """
        blocked = self._enforce_workspace(path)
        if blocked is not None:
            return blocked
        try:
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
                    "bytes_written": len(content.encode("utf-8")),
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

        M2: ``policy.max_result_items`` 条数上限——超限时截断 ``items``；
        content 含 ``truncated``/``total_items``。
        M3: ``policy.workspace_root`` 路径守卫。
        """
        blocked = self._enforce_workspace(path)
        if blocked is not None:
            return blocked
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
