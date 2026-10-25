# Workspace MCP — M5b：Office 只读与记忆 / Wiki 检索

> 基于 `2026-09-26-workspace-mcp-server.md` 第 114 行的 M5 范围；M5a（审批 + token 加密）见 `2026-09-26-workspace-mcp-m5a-approval.md`。

## 目标
为远程工作区增加 4 个**只读**工具，分别受两项新权限控制，二者默认关闭。

| 工具 | 权限 | 说明 |
|---|---|---|
| `office_read` | `office` | 读取 .docx/.xlsx/.pptx/.pdf/.csv；section = summary（默认）/ head / all；`formulas` 用于 Excel |
| `office_lint_word` | `office` | 按 FormatSpec 校验 .docx，返回违规清单 |
| `wiki_search` | `memory` | 只检索本工作区的 wiki |
| `memory_search` | `memory` | 检索 Sage 长期记忆，仅支持 `user` / `global` 作用域 |

## 设计
- **不复用** `OfficeReadTool` / `MemorySearchTool` 等 BaseTool：它们依赖聊天会话上下文（`current_tool_context`、doc_id、会话绑定），远程调用没有这些。改为直接调用底层 `backend.office.{word,excel,ppt,pdf}.read_*`、`word_lint.lint_docx`、`backend.wiki.search.search_wiki` 和 `MemoryManager.search_memories`。
- **路径**：统一走 `remote_path.resolve`（只接受相对路径，逐段 lstat，拒绝符号链接、junction 和受保护路径），再按后缀白名单过滤；文件上限 50 MiB。
- **输出**：pydantic `model_dump(mode="json")` 后，递归把本机绝对路径改写成相对路径。`all` 模式上限 256K 字符，`head` 模式上限 64K 字符；超出时逐步对半截短最大的列表字段，并标记 `truncated=true`。解析异常统一返回 `OFFICE_READ_FAILED: <异常类型>`，不泄露路径和堆栈。
- **记忆隐私**：
  - 不提供 `session` / `project` 作用域：远程调用没有 Sage 会话，这两个作用域可能串到其他会话。
  - 不返回工作记忆（`working`）。
  - 字段按白名单输出，单条内容截断到 4000 字符，最多 50 条。
  - `ask` 审批模式下每次 `memory_search` 都要本地确认（risk=`private`，UI 显示为 suspicious）。
- **store**：`PERMISSION_KEYS` 增加 `office` 和 `memory`，新建工作区时均为 false。`public_view` 会补全缺失的键：旧配置缺少这些键时显示为 false，协议层用 `.get` 判断，结果同样是拒绝。
- **workspace_info** 增加返回 `office` / `memory` 两个布尔值。
- **UI**：`RemoteWorkspacesTab` 的权限复选框增加 Office 和“记忆”两项（标签在 M4 已预留）。
- **避免循环导入**：`knowledge.build_tools(RemoteTool, _schema, _PATH)` 由 `tools.py` 注入调用。

## 测试
`backend/tests/unit/test_remote_mcp_knowledge.py` 覆盖：
- 默认权限和旧配置的显示；
- 未授权时拒绝；
- docx summary/head 读取，且结果中不含绝对路径；
- 越界路径、不支持的类型、不存在的文件；
- lint 的参数校验和正常结果；
- 截断逻辑；
- 记忆的作用域/类型限制、working 过滤、字段白名单、截断；
- wiki 的 limit 上限和根目录；
- 审批规则。

需在 py311 和 py38 下都运行。
