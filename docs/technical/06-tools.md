# Sage - 工具系统

> **P2 备注（2026-06-06）**：工具系统已纳入六边形架构。
> 旧 `backend/tools/registry.py` 包装为 `backend/adapters/out/tool/inproc_adapter.py`（`InprocToolAdapter`），
> 通过 `ToolPort` Protocol 暴露给 `backend/application/services/chat_service.py`。
> 详细架构请阅读 [`docs/technical/18-hexagonal.md`](./18-hexagonal.md)。

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

#### 登录态与多账号：`web_fetch` / `http_download`

两个出网工具共用同一套凭据解析链路（`backend/tools/credential_vault.py`）：先确定 `credential_domain`，再由 `resolve_credential()` 解出要附加的请求头（`Cookie`，或 `credential_set` 设置的 `Authorization` 等头部凭据）。

**参数与推断优先级**（`http_download` 的取值顺序，`web_fetch` 同构）：

1. **显式 `credential_domain`**：非空时直接使用，不做推断。
2. **从 URL 主机名自动推断**：未传 `credential_domain` 时，取 `urlparse(url).hostname` 调 `find_credential_for_host()`，在所有凭据档案里做 RFC 6265 域匹配（`.cnki.net` 命中 `cnki.net` 及其任意子域），**多候选取域名最长者**（最具体匹配），跳过已过期或无可用 cookie 的档案。命中后写回 `credential_domain`。
3. **`account_id` 决定账号维度**：非空时先经 `browser_account_service.resolve_vault_account_id()` 从账号注册表 ID 解析到凭据库维度（默认账号 → `None`，未知账号原样透传），再传给推断与 `resolve_credential()`。
   - `account_id` 为空 / 默认账号 → 只匹配**平铺（默认账号）**档案；
   - 指定账号 → 只匹配 `domain::account_id` 命名档案，因此命名账号的凭据必须显式传 `account_id` 才会被推断命中。

解析成功后，凭据头**只附加到凭据域命中的重定向 hop**；跨域重定向（如 302 到第三方 SSO）自动剥离，避免凭据外带。失败时返回明确状态：`credential_expired`（凭据全部过期）、`credential_insecure_scheme`（头部凭据不附加到明文 `http`，本地回环除外）、`credential_not_found`、`credential_domain_mismatch`（目标 host 不在档案域内）；带凭据仍被踢到登录页时，`http_download` 返回 `login_required`。

`http_download` 与 `web_fetch` 对齐的点：`credential_domain`（含自动推断）、`account_id`、`resolve_credential()` 的账号口径一致。「登录一次」后，两个工具都自动带态，不必分别传参。

#### `mode=files` 的文件探测也带凭据

`web_fetch mode=files` 会对页面内候选文件链接做首块探测（流式 `GET` 读首块即关），判断它是真实文件还是登录页 / 中转页。探测复用主请求解析出的同一份凭据头：

- `execute()` 里 `resolve_credential()` 得到的 `credential_headers`，透传到 `_finalize_files()` → `_probe_file_url()`；
- 探测客户端默认头为 `{**default_headers(), **credential_headers}`，即凭据头与主请求**同一份**（同一个 `resolution.headers`）。

与主抓取请求的差异（均属非凭据头或链路行为，不影响登录态本身）：

| 维度 | 主抓取（`_get_with_redirects`） | 文件探测（`_probe_file_url`） |
| --- | --- | --- |
| 凭据头附加范围 | 仅 `cookie_domain_matches` 命中的 hop | 直接附加到探测 URL（不再做域匹配） |
| `Accept` | 默认浏览器式 `Accept` | 覆盖为 `*/*` |
| `Accept-Encoding` | 强制 `identity`（便于比对 `Content-Length`） | 不强制 |
| 重定向 | 跟随并对每一跳重新校验 | 不跟随，返回 `probe=redirect` + `final_url` |
| 重试 / 限速 | 走 `retrying_send()` | 单次 `client.send()`，不重试 |

效果：登录墙后的文件链接不会再因为拿到登录页 HTML 而被误判为 `probe=html`，能正确给出 `probe=file` / `detected_type` / `content_length`。探测只发生在 `mode=files`，最多探测 top N（`FILES_PROBE_TOP_N = 5`，且不超过 `max_result_items`）。

#### 文献子系统的快路径（`SageToolDriver.fetch_text`）

文献子系统通过 `SageToolDriver` 把 `sage.call` 桥接成 `BrowserDriver`，快路径实现位于 `backend/literature/sage_driver.py` 与 `backend/literature/search.py`：

- **`SageToolDriver.fetch_text(url)`**：调用 `sage.call("web_fetch", url=url, mode="text")`，成功则更新驱动的 `_url` / `_title` 并返回正文文本；登录墙、反爬、工具异常或空正文一律返回 `None`。它只走 HTTP——`web_fetch` 自身在 `render=auto` 下可能内部拉起受控 headless 浏览器渲染，但**不经过交互浏览器会话**。
- **`search_with_profile()` 的优先级**：
  - `search.mode == "interactive"` → **只走浏览器**（在真实页面里输入检索词并提交），提前返回，**绝不**走快路径；
  - `search.mode == "url"` → 先 `render_search_url()` 生成检索 URL，再 `_fast_fetch_text()` 走快路径；取到正文即以该文本作为 `SearchObservation.snapshot` 返回；取不到（`None`）则回落 `driver.navigate(url, wait_for=...)` + `driver.snapshot()`，行为与改动前一致。
  - `_fast_fetch_text()` 用 `getattr(driver, "fetch_text", None)` 鸭子探测：驱动不实现 `fetch_text` 即视为不支持。`BrowserDriver` Protocol **未新增必选方法**，既有自定义驱动（含测试假驱动）零改动。
- **`_ensure_browser()` 惰性拉起浏览器**：在 `click` / `click_text` / `type_text` / `press_key` 交互前调用；仅当驱动**尚无页面**（`_browser_ready` 为假）且已知 `_url` 时，补一次 `browser_navigate` 到 `_url` 并置 `_browser_ready = True`。快路径只走 HTTP、浏览器此时没有页面，靠它保证「快路径检索 + 后续点 DOM 元素下载」的组合可用；`navigate()` 已置位的驱动不会重复导航。
- 只有 `search.mode: url` 的 profile 会真正用到快路径；随包唯一的 `xueshu789.yaml` 是 `search.mode: interactive`，仍全程走浏览器（PDF 下载必须点 `a.downloadlink`，直连截断 URL 会失败）。

#### 设计取舍

| 取舍 | 结论 | 理由 |
| --- | --- | --- |
| `http_download` 自动推断是否要求显式 `account_id` | 否；仅在传入时才解析为凭据库账号维度 | 与 `web_fetch` 保持一致；多账号场景由调用方显式传 `account_id` 即可，默认账号零参数可用 |
| 文件探测是否复用主请求凭据头 | 是，`{**default_headers(), **credential_headers}` | 登录墙后的文件链接必须带同一套登录态，才能探测出真实类型而非登录页 HTML |
| 快路径失败语义 | 一律回落浏览器，不抛错 | 快路径是纯增量优化，不得改变既有行为；任何失败都等价于「没有快路径」 |
| 交互前是否补浏览器导航 | 是，`_ensure_browser()` 惰性补 `browser_navigate` | 快路径只走 HTTP，浏览器无页面时点 DOM 元素必失败 |
| 是否改 `BrowserDriver` Protocol | 否，用 `getattr` 鸭子探测 `fetch_text` | 既有自定义驱动零改动不被破坏 |

明确不做的部分：`web_search` 不加 cookie（公开搜索引擎无需登录态，站内检索改用 `web_fetch` / `browser_*`）；`browser_*` 工具行为不变（浏览器本就走登录态）；`literature-research` 的 `interactive` 检索与 PDF 下载不迁移到快路径。

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

## ghm 外部计算工具（PG3.x）

> 通过 `ComputePort` 桥接 ghm（激波管/风洞计算器）CLI，把 6 个物理计算包装为 LLM tool。
> 详细架构：[`technical/19-ghm-integration.md`](./19-ghm-integration.md)。

启用条件：`backend/config/ghm.yaml: ghm.enabled = true`。关闭时这些工具不会出现在 LLM 工具列表，对现有行为零影响。

### 已接入的 6 个 compute 工具

| 工具名 | 物理意义 | 必填参数 |
|---|---|---|
| `compute_shock` | 理想气体正激波 | mach / gamma / p1 / t1 |
| `compute_equilibrium` | 平衡气体性质 | species / p / t |
| `compute_heatflux` | 驻点热流（Fay-Riddell）| rho / u / t |
| `compute_nozzle` | 准一维等熵喷管面积比 | gamma / p0 / t0 / area_ratio |
| `compute_plasma` | 等离子体频率（经验公式）| p_atm / t |
| `compute_eqcomposition` | 平衡组分 | gas / mode / t |

### 路径解析（ExecutableResolver）

ghm 可执行文件按优先级查找：

1. 环境变量 `GHM_EXECUTABLE_PATH`
2. yaml `subprocess.executable_path`（独立 exe 路径）
3. yaml `subprocess.sidecar_name`（Tauri sidecar，**本期预留**）
4. yaml `subprocess.python_module`（开发期 conda `python -m ghm`）
5. yaml `subprocess.path_lookup_name`（系统 PATH 兜底）

任一字段为 `null` 时跳过。全部失败 → `ComputePort` 返回 `INTERNAL_ERROR`，工具自动不注册。

### HTTP 升级（预留）

> **M0 决策（2026-07-28）**：原 `HttpComputeAdapter` 空壳已删除（YAGNI），当前仅支持 `adapter: subprocess`。未来若 subprocess 冷启动延迟（~600ms）成为瓶颈，再按当时需求实现 `ComputePort` 的 HTTP 版本（sage 通过 httpx 调 `ghm gui web` 的 HTTP 服务）。

---

_文档版本: v1.0_
