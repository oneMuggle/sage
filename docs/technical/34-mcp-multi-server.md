# 34 · MCP 多服务器管理（M3）

> 范围：`backend/mcp/`（client / config / pool / tool）、`backend/api/mcp_routes.py`、
> 前端 Settings MCP Tab、Electron IPC `mcp_*` 路由。

Sage 通过 [Model Context Protocol](https://modelcontextprotocol.io)（JSON-RPC 2.0 over
stdio）接入外部工具服务器。M3 把子系统从"单个硬编码 drawio 服务器"升级为
**多服务器架构**：结构化配置、并行尽力发现、逐服务器故障隔离、降级状态报告、
REST 管理面与 Settings UI。

## 1. 配置（backend/mcp/config.py）

```python
@dataclass(frozen=True)
class ServerConfig:
    name: str                     # slug: ^[a-z0-9_-]{1,64}$
    command: str
    args: Tuple[str, ...] = ()
    env: Dict[str, str] = {}
    enabled: bool = True
    required: bool = False        # 失败时进 failed_required 报告
    timeout_seconds: float = 30.0 # 握手/响应超时（逐服务器）
```

**加载顺序**：内置默认（drawio，仅当 `packages/drawio-mcp-server/dist/index.js`
存在时启用——保留 M3 前行为）**合并** 用户配置
`$SAGE_USER_DATA_DIR/mcp_servers.json`（env 未设时回退
`backend/data/mcp_servers.json`，与 scheduled-tasks 存储同约定）。用户条目按
`name` 覆盖内置。文件缺失/损坏 → 默认值 + WARNING 日志，**启动绝不因 MCP 配置崩溃**。

**为什么不用 settings_repo**：该仓库是扁平 KV 偏好桶（值序列化为 JSON 字符串）；
MCP 服务器定义是结构化、需 schema 校验、需原子写、可手工编辑的记录。独立 JSON
文件（`{"version": 1, "servers": [...]}`，temp+rename 原子写）让契约显式。

## 2. 生命周期决策：删除异步 lifecycle，实现同步池状态

M3 前的 `backend/mcp/lifecycle/`（async MCPLifecycleManager + CREATED→INITIALIZING→
READY→RUNNING⇄PAUSED→SHUTDOWN）**已整体删除**：

1. 生产客户端 `McpClient` 是同步阻塞 stdio；接线异步管理器需在每个状态转换架
   执行器桥——零收益的双线程模型。
2. 其状态建模"单个泛化服务"（数据库式资源 + pause/resume），而非 N 个独立
   stdio 子进程；PAUSED 对 stdio 子进程无意义（暂停的子进程就是死的）。
3. 死代码：除自身测试外无任何导入者。

替代方案——`backend/mcp/pool.py` 的最小同步逐服务器状态机：

```
DISCOVERING → READY     握手 + tools/list 成功
DISCOVERING → FAILED    启动/握手错误（逐服务器隔离）
READY       → FAILED    子进程会话中途死亡
FAILED      → READY     调用时重连 / 后台重发现
*           → DISABLED  config.enabled = false
```

逐服务器记录 `ServerRecord`：`state / tool_count / tool_specs / last_error /
last_state_change / attempts / client`。

## 3. 强化客户端池（backend/mcp/pool.py）

- **并行尽力发现**：`ThreadPoolExecutor`（≤8 worker），每服务器 future 超时 =
  `timeout_seconds + 5s`。单服务器失败只翻自己的状态，不阻塞其他服务器。
- **故障隔离**：死亡服务器的工具调用返回干净错误
  `MCP 服务器 X 不可用: <reason>`，异常被 `McpTool.execute` 收敛为
  `ToolResult(success=False)`，不影响其他服务器的工具。
- **重连策略**：调用时检测到死客户端 → **一次**立即重连；失败则本次调用报错 +
  **后台**重发现（60s 冷却，`threading.Timer` 每服务器单定时器，非逐调用）。
- **工具命名空间**：`mcp__<server>__<tool>`（**LLM 可见变更**：M3 前为
  `<server>__<tool>`，如 `drawio__render_diagram` → `mcp__drawio__render_diagram`；
  与 claw-code 约定一致）。命名空间使跨服务器冲突结构性不可能；重复注册仍走
  "首个获胜 + WARNING" 守卫。
- **动态注册**：池以弱引用跟踪所有调用过 `register_mcp_tools()` 的
  `ToolRegistry`；REST API 新增/启用服务器后立即向存活注册表广播新工具，
  无需重启；禁用/删除时反注册。

## 4. 降级状态报告

```python
McpStatusReport(generated_at, servers=(ServerStatusEntry(
    name, state, tool_count, last_error, since, required), ...))
# 派生属性
report.all_ready        # 全部 READY
report.degraded         # 存在 FAILED
report.failed_required  # 存在 FAILED 且 required=True
```

设计参考 claw-code `rust/crates/runtime/src/mcp.rs` 的 `McpDiscoveryFailure` /
`McpDegradedReport`（逐服务器失败记录 + 降级模式报告）。

## 5. REST API（backend/api/mcp_routes.py，挂载 /api/v1）

| 方法 | 路径 | 语义 | 成功 | 失败 |
|------|------|------|------|------|
| GET | `/mcp/status` | 状态报告（**恒 200**，状态在 body） | report JSON | — |
| GET | `/mcp/servers` | 合并后配置列表；env 键名含 `key/token/secret/password`（大小写不敏感）的值 → `"***"`；含 `builtin` 标志 | `{servers: [...]}` | — |
| POST | `/mcp/servers` | 校验 + 持久化 + 触发该服务器发现 | `{ok, name, state}` | 语义校验 400 `{error}`；schema 违规 422 |
| PATCH | `/mcp/servers/{name}` | 合并补丁 `enabled?/timeout_seconds?`；持久化 + 按需启动/停止 | `{ok, name, state}` | 404 未知；400 非法值 |
| DELETE | `/mcp/servers/{name}` | 删除用户条目 + 反注册工具；**内置 drawio 无用户覆盖时 400** | `{ok, name}` | 400 / 404 |

pydantic 模型用 v1/v2 双兼容 `class Config: extra = "forbid"`（release/win7 LTS
分支钉 pydantic 1.10）。

## 6. 前端（Settings 第 7 个 Tab）

- `src/pages/settings/McpTab.tsx`：服务器表（名称/状态徽章 READY 绿 · DISCOVERING
  琥珀 · FAILED 红 · DISABLED 灰 / 工具数 / last_error 悬浮全文 / 启用 Toggle /
  删除按钮——内置禁用并提示），添加表单（name slug 客户端校验、command 必填、
  空格分隔 args、required 勾选），刷新按钮。
- `src/shared/api/mcpClient.ts`：5 个 IPC 包装（snake_case 后端契约直出）。
- `electron/commands.ts`：`mcp_status / mcp_servers / mcp_server_add /
  mcp_server_update / mcp_server_delete`。`mcp_server_add` 走 `rawBody` 旁路——
  IPC 桥的 `camelToSnakeKeys` 会把用户定义的 env 键名 `PATH` 腐蚀成 `_p_a_t_h`，
  该路由跳过转换，由客户端直接发送 snake_case。
- i18n：`settings.mcp.*` zh + en。

## 7. 测试

| 层 | 位置 | 规模 |
|----|------|------|
| 单元（config） | `backend/tests/unit/mcp/test_mcp_config.py` | 校验/冻结/内置检测/损坏回退/原子写/合并 |
| 单元（pool） | `backend/tests/unit/mcp/test_mcp_pool.py` | 并行隔离/重连/冷却/报告/增删改/弱引用广播（FakeMcpClient 经 client_factory 缝注入） |
| 契约 | `backend/tests/api/test_mcp_routes.py` | 5 端点 + env 脱敏 + 内置禁删 + 持久化 |
| 集成故障演练 | `backend/tests/integration/test_mcp_fault_drill.py` + `backend/tests/fixtures/mcp_mock_server.py` | 两个真实 stdio 子进程；杀一个 → 另一个照常应答、状态一 FAILED 一 READY、干净错误；重启后恢复 |
| 前端 | `src/pages/settings/__tests__/McpTab.test.tsx`、`electron/__tests__/{commands,invoke}.test.ts` | 徽章渲染/开关/表单校验/内置禁删；IPC 路由 guard + rawBody |
