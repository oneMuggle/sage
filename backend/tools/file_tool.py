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
                    "path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "起始行号 (默认 1)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "读取行数 (默认 500)"
                    }
                },
                "required": ["path"]
            }
        )

    def _is_safe_path(self, path: str, allowed_base: str) -> bool:
        """
        检查路径是否在允许的基础目录内

        Args:
            path: 文件路径
            allowed_base: 允许的基础目录

        Returns:
            是否安全
        """
        try:
            file_path = Path(path).expanduser().resolve()
            allowed_path = Path(allowed_base).resolve()
            return str(file_path).startswith(str(allowed_path))
        except Exception:
            return False

    def execute(self, path: str, offset: int = 1, limit: int = 500, **kwargs) -> ToolResult:
        """
        读取文件

        Args:
            path: 文件路径
            offset: 起始行号
            limit: 读取行数
        """
        try:
            file_path = Path(path).expanduser()

            if not file_path.exists():
                return ToolResult(success=False, error=f"文件不存在: {path}")

            if not file_path.is_file():
                return ToolResult(success=False, error=f"不是文件: {path}")

            # 检查权限
            if not os.access(file_path, os.R_OK):
                return ToolResult(success=False, error="无读取权限")

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
                    "path": str(file_path.resolve())
                }
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
                    "path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容"
                    },
                    "append": {
                        "type": "boolean",
                        "description": "是否追加模式 (默认 false)"
                    }
                },
                "required": ["path", "content"]
            }
        )

    def execute(self, path: str, content: str, append: bool = False, **kwargs) -> ToolResult:
        """
        写入文件

        Args:
            path: 文件路径
            content: 文件内容
            append: 是否追加模式
        """
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
                    "mode": mode
                }
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
                    "path": {
                        "type": "string",
                        "description": "目录路径"
                    },
                    "all": {
                        "type": "boolean",
                        "description": "是否显示隐藏文件 (默认 true)"
                    }
                },
                "required": ["path"]
            }
        )

    def execute(self, path: str, all: bool = True, **kwargs) -> ToolResult:
        """
        列出目录

        Args:
            path: 目录路径
            all: 是否显示隐藏文件
        """
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
                items.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })

            # 排序：目录在前，文件在后，按名称排序
            items.sort(key=lambda x: (x["type"] != "dir", x["name"]))

            return ToolResult(
                success=True,
                content={
                    "path": str(dir_path.resolve()),
                    "items": items
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
