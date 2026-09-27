"""Sage Workspace MCP Server —— 通过 MCP 远程访问本地工作区。

方案：``docs/plans/2026-09-26-workspace-mcp-server.md``。

- ``remote_path``：远程路径校验（LocalBridge ``files.cjs`` parts/resolve 同款）
- ``store``：工作区 + token + 权限的原子持久化
- ``jobs``：会话归属的命令任务
- ``tools``：远程工具集
- ``protocol``：JSON-RPC / Streamable HTTP 会话处理
- ``listener``：独立端口 uvicorn 监听器（默认关闭）
- ``admin_routes``：主 API（受 local_auth 保护）上的管理端点
"""

DEFAULT_PORT = 8767
SERVER_NAME = "sage-workspace"
SERVER_VERSION = "0.1.0"
