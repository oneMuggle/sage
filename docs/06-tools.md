# Sage - 工具系统

> **P2 备注（2026-06-06）**：工具系统已纳入六边形架构。
> 旧 `backend/tools/registry.py` 包装为 `backend/adapters/out/tool/inproc_adapter.py`（`InprocToolAdapter`），
> 通过 `ToolPort` Protocol 暴露给 `backend/application/services/chat_service.py`。
> 详细架构请阅读 [`docs/technical/18-hexagonal.md`](./technical/18-hexagonal.md)。

## 6.1 工具系统概述

### 6.1.1 设计目标

工具系统让 Agent 能够:

1. 执行外部操作 (文件系统、网络、终端)
2. 扩展能力边界
3. 完成复杂多步骤任务

### 6.1.2 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        Tool System                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────┐   ┌─────────────────┐                   │
│   │  ToolRegistry   │   │  ToolExecutor   │                   │
│   │   (注册表)      │   │   (执行器)      │                   │
│   └────────┬────────┘   └────────┬────────┘                   │
│            │                     │                              │
│            ▼                     ▼                              │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                      Tool Registry                       │  │
│   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │  │
│   │  │terminal │ │  file   │ │   web   │ │ memory  │ ...   │  │
│   │  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6.2 内置工具

### 6.2.1 工具清单

| 工具名        | 功能            | 权限       | 异步 |
| ------------- | --------------- | ---------- | ---- |
| terminal      | 执行 Shell 命令 | terminal   | ✅   |
| read_file     | 读取文件内容    | file:read  | ✅   |
| write_file    | 写入文件内容    | file:write | ✅   |
| list_dir      | 列出目录内容    | file:read  | ✅   |
| web_search    | 网络搜索        | network    | ✅   |
| web_fetch     | 获取网页内容    | network    | ✅   |
| calculator    | 数学计算        | none       | ❌   |
| memory_search | 搜索记忆        | memory     | ✅   |
| memory_save   | 保存记忆        | memory     | ✅   |
| delegate_task | 委托子任务      | none       | ✅   |

### 6.2.2 Terminal 工具

```python
# backend/tools/terminal.py
import asyncio
import shlex
from typing import Dict, Any

from .base import BaseTool, ToolSchema

class TerminalTool(BaseTool):
    """终端工具 - 执行 shell 命令"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="terminal",
            description="""执行终端命令。
警告: 这是一个强大的工具，请仅在用户明确要求时使用。
注意: Windows 7 上建议使用 PowerShell 命令。""",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令"
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作目录 (可选)"
                    },
                    "timeout": {
                        "type": "number",
                        "description": "超时时间(秒)，默认 30"
                    }
                },
                "required": ["command"]
            }
        )

    async def execute(
        self,
        command: str,
        cwd: str = None,
        timeout: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """执行命令"""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )

                return {
                    "success": process.returncode == 0,
                    "returncode": process.returncode,
                    "stdout": stdout.decode('utf-8', errors='replace'),
                    "stderr": stderr.decode('utf-8', errors='replace')
                }
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "error": f"命令执行超时 ({timeout}s)",
                    "returncode": -1
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "returncode": -1
            }
```

### 6.2.3 File 工具

```python
# backend/tools/file_tool.py
import os
import asyncio
from pathlib import Path
from typing import Dict, Any, List

from .base import BaseTool, ToolSchema

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

    async def execute(
        self,
        path: str,
        offset: int = 1,
        limit: int = 500,
        **kwargs
    ) -> Dict[str, Any]:
        """读取文件"""
        try:
            file_path = Path(path).expanduser()

            if not file_path.exists():
                return {"success": False, "error": f"文件不存在: {path}"}

            if not file_path.is_file():
                return {"success": False, "error": f"不是文件: {path}"}

            # 检查权限
            if not os.access(file_path, os.R_OK):
                return {"success": False, "error": "无读取权限"}

            content = file_path.read_text(encoding='utf-8', errors='replace')
            lines = content.split('\n')

            return {
                "success": True,
                "total_lines": len(lines),
                "content": '\n'.join(lines[offset-1:offset-1+limit]),
                "path": str(file_path)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


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

    async def execute(
        self,
        path: str,
        content: str,
        append: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """写入文件"""
        try:
            file_path = Path(path).expanduser()

            # 检查目录是否存在
            file_path.parent.mkdir(parents=True, exist_ok=True)

            mode = 'a' if append else 'w'
            file_path.write_text(content, encoding='utf-8')

            return {
                "success": True,
                "path": str(file_path),
                "bytes_written": len(content.encode('utf-8'))
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


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

    async def execute(
        self,
        path: str,
        all: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """列出目录"""
        try:
            dir_path = Path(path).expanduser()

            if not dir_path.exists():
                return {"success": False, "error": f"目录不存在: {path}"}

            if not dir_path.is_dir():
                return {"success": False, "error": f"不是目录: {path}"}

            items = []
            for item in dir_path.iterdir():
                if not all and item.name.startswith('.'):
                    continue
                items.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })

            return {
                "success": True,
                "path": str(dir_path),
                "items": sorted(items, key=lambda x: (x['type'] != 'dir', x['name']))
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
```

### 6.2.4 Web 工具

```python
# backend/tools/web_tool.py
import httpx
from typing import Dict, Any

from .base import BaseTool, ToolSchema

class WebSearchTool(BaseTool):
    """网络搜索工具"""

    def __init__(self):
        super().__init__()
        self.client = httpx.AsyncClient(timeout=30.0)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description="搜索网络信息。返回搜索结果列表。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量 (默认 5)"
                    }
                },
                "required": ["query"]
            }
        )

    async def execute(
        self,
        query: str,
        limit: int = 5,
        **kwargs
    ) -> Dict[str, Any]:
        """搜索"""
        try:
            # TODO: 接入真实搜索 API (Google, Bing, DuckDuckGo)
            # 目前返回模拟数据
            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "title": f"关于 {query} 的结果 1",
                        "url": "https://example.com/1",
                        "snippet": f"这是关于 {query} 的第一条搜索结果..."
                    },
                    {
                        "title": f"关于 {query} 的结果 2",
                        "url": "https://example.com/2",
                        "snippet": f"这是关于 {query} 的第二条搜索结果..."
                    }
                ][:limit]
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class WebFetchTool(BaseTool):
    """获取网页内容"""

    def __init__(self):
        super().__init__()
        self.client = httpx.AsyncClient(timeout=30.0)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description="获取网页内容",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "网页 URL"
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "最大获取长度 (默认 10000)"
                    }
                },
                "required": ["url"]
            }
        )

    async def execute(
        self,
        url: str,
        max_length: int = 10000,
        **kwargs
    ) -> Dict[str, Any]:
        """获取网页"""
        try:
            response = await self.client.get(url)
            response.raise_for_status()

            content = response.text[:max_length]

            return {
                "success": True,
                "url": url,
                "status_code": response.status_code,
                "content": content,
                "content_type": response.headers.get("content-type", "")
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
```

### 6.2.5 Memory 工具

```python
# backend/tools/memory_tool.py
from typing import Dict, Any, List

from .base import BaseTool, ToolSchema

class MemorySearchTool(BaseTool):
    """记忆搜索工具"""

    def __init__(self, memory_manager):
        super().__init__()
        self.memory = memory_manager

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="memory_search",
            description="搜索记忆内容",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["all", "episodic", "semantic"],
                        "description": "记忆类型 (默认 all)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量 (默认 5)"
                    }
                },
                "required": ["query"]
            }
        )

    async def execute(
        self,
        query: str,
        memory_type: str = "all",
        limit: int = 5,
        **kwargs
    ) -> Dict[str, Any]:
        """搜索记忆"""
        try:
            results = await self.memory.remember(
                query=query,
                context={"memory_type_filter": memory_type}
            )

            return {
                "success": True,
                "query": query,
                "results": results[:limit] if results else []
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class MemorySaveTool(BaseTool):
    """记忆保存工具"""

    def __init__(self, memory_manager):
        super().__init__()
        self.memory = memory_manager

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="memory_save",
            description="保存重要信息到记忆",
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记忆的内容"
                    },
                    "importance": {
                        "type": "integer",
                        "description": "重要性 1-10 (默认 5)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表"
                    }
                },
                "required": ["content"]
            }
        )

    async def execute(
        self,
        content: str,
        importance: int = 5,
        tags: List[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """保存记忆"""
        try:
            await self.memory.memorize(
                content=content,
                memory_type="episodic",
                importance=importance,
                metadata={"tags": tags or []}
            )

            return {
                "success": True,
                "content": content,
                "importance": importance
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
```

### 6.2.6 Calculator 工具

```python
# backend/tools/calculator.py
import ast
import operator
from typing import Dict, Any

from .base import BaseTool, ToolSchema

class CalculatorTool(BaseTool):
    """计算器工具 - 安全数学计算"""

    # 支持的运算符
    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
    }

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="calculator",
            description="进行数学计算。支持: +, -, *, /, **, %。",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如: 2 + 2, (10 + 5) * 2"
                    }
                },
                "required": ["expression"]
            }
        )

    async def execute(self, expression: str, **kwargs) -> Dict[str, Any]:
        """计算表达式"""
        try:
            # 安全计算 - 只允许数字和运算符
            result = self._safe_eval(expression)

            return {
                "success": True,
                "expression": expression,
                "result": result
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"计算错误: {str(e)}"
            }

    def _safe_eval(self, expr: str) -> float:
        """安全求值"""
        node = ast.parse(expr, mode='eval')
        return self._eval_node(node.body)

    def _eval_node(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numbers allowed")

        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)
            if op_type in self.OPERATORS:
                return self.OPERATORS[op_type](left, right)
            raise ValueError(f"Unsupported operator: {op_type}")

        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_type = type(node.op)
            if op_type in self.OPERATORS:
                return self.OPERATORS[op_type](operand)
            raise ValueError(f"Unsupported operator: {op_type}")

        raise ValueError(f"Unsupported expression: {ast.dump(node)}")
```

---

## 6.3 工具注册

### 6.3.1 初始化

```python
# backend/tools/__init__.py
from .registry import ToolRegistry
from .terminal import TerminalTool
from .file_tool import ReadFileTool, WriteFileTool, ListDirTool
from .web_tool import WebSearchTool, WebFetchTool
from .memory_tool import MemorySearchTool, MemorySaveTool
from .calculator import CalculatorTool

def create_default_registry(memory_manager=None) -> ToolRegistry:
    """创建默认工具注册表"""
    registry = ToolRegistry()

    # 注册内置工具
    registry.register(TerminalTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(CalculatorTool())

    # 记忆工具
    if memory_manager:
        registry.register(MemorySearchTool(memory_manager))
        registry.register(MemorySaveTool(memory_manager))

    return registry
```

### 6.3.2 权限控制

```python
# backend/tools/permissions.py
from enum import Enum
from typing import Set

class Permission(Enum):
    TERMINAL = "terminal"
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    NETWORK = "network"
    MEMORY = "memory"

class PermissionManager:
    """权限管理器"""

    def __init__(self):
        self._granted: Set[Permission] = {
            Permission.FILE_READ,
            Permission.FILE_WRITE,
            Permission.NETWORK,
            Permission.MEMORY,
        }

    def grant(self, permission: Permission):
        self._granted.add(permission)

    def revoke(self, permission: Permission):
        self._granted.discard(permission)

    def check(self, permission: Permission) -> bool:
        return permission in self._granted

    def check_tool(self, tool_name: str) -> bool:
        """检查工具权限"""
        tool_permissions = {
            "terminal": Permission.TERMINAL,
            "read_file": Permission.FILE_READ,
            "write_file": Permission.FILE_WRITE,
            "list_dir": Permission.FILE_READ,
            "web_search": Permission.NETWORK,
            "web_fetch": Permission.NETWORK,
            "memory_search": Permission.MEMORY,
            "memory_save": Permission.MEMORY,
            "calculator": None,
        }

        required = tool_permissions.get(tool_name)
        if required is None:
            return True

        return self.check(required)
```

---

## 6.4 委托任务

### 6.4.1 DelegateTool

```python
# backend/tools/delegate.py
from typing import Dict, Any
import asyncio

from .base import BaseTool, ToolSchema

class DelegateTool(BaseTool):
    """任务委托工具 - 并行执行多个子任务"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="delegate_task",
            description="委托子任务给其他 Agent 并行执行",
            parameters={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "goal": {"type": "string"},
                                "context": {"type": "string"},
                                "skills": {"type": "array", "items": {"type": "string"}}
                            },
                            "required": ["goal"]
                        },
                        "description": "子任务列表"
                    }
                },
                "required": ["tasks"]
            }
        )

    async def execute(self, tasks: list, **kwargs) -> Dict[str, Any]:
        """执行委托"""
        try:
            # 并行执行所有任务
            results = await asyncio.gather(
                *[self._run_task(task) for task in tasks],
                return_exceptions=True
            )

            return {
                "success": True,
                "results": [
                    r if not isinstance(r, Exception) else {"error": str(r)}
                    for r in results
                ]
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _run_task(self, task: dict) -> Dict[str, Any]:
        """运行单个任务"""
        # TODO: 实现实际的子 Agent 调用
        await asyncio.sleep(0.1)  # 模拟
        return {"goal": task.get("goal"), "status": "completed"}
```

---

## 6.5 工具执行日志

### 6.5.1 日志记录

```python
# backend/tools/logger.py
import time
import sqlite3

class ToolLogger:
    """工具使用日志"""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def log(
        self,
        tool_name: str,
        args: dict,
        result: dict,
        status: str,
        duration_ms: int,
        session_id: str = None
    ):
        """记录工具调用"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO tool_usage
            (id, session_id, tool_name, tool_args, tool_result, status, duration_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            session_id,
            tool_name,
            json.dumps(args),
            json.dumps(result),
            status,
            duration_ms,
            int(time.time())
        ))
        self.db.commit()
```

---

_文档版本: v1.0_
