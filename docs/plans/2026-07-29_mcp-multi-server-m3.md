# M3 — MCP 多服务器 + 生命周期

> 状态：✅ 已完成（2026-07-29，分支 `feat/mcp-multi-server`）
> 技术文档：[docs/technical/34-mcp-multi-server.md](../technical/34-mcp-multi-server.md)

## 背景与目标

M3 之前，MCP 子系统只支持一个硬编码服务器（drawio），客户端池无故障隔离、
无状态可观测性；`backend/mcp/lifecycle/` 是一套从未接线的异步生命周期代码。
本里程碑把 MCP 升级为多服务器架构：结构化配置、并行发现、逐服务器故障隔离、
降级状态报告、REST 管理面 + 设置页 UI。

## 实施步骤

- [x] 多服务器配置 schema（`ServerConfig` 不可变数据类：name/command/args/env/enabled/required/timeout_seconds）
- [x] JSON 配置文件 `$SAGE_USER_DATA_DIR/mcp_servers.json`：内置 drawio 与用户配置按名合并（用户覆盖内置）；损坏文件回退默认 + 告警，绝不崩启动；原子写入（temp+rename）；slug 校验 `^[a-z0-9_-]{1,64}$`
- [x] lifecycle 接线或删除：**已删除** `backend/mcp/lifecycle/`（异步/同步不匹配、泛化服务模型不适配 stdio 子进程、死代码），在 `backend/mcp/pool.py` 实现最小同步状态机 `DISCOVERING/READY/FAILED/DISABLED` + 逐服务器记录（state/tool_count/last_error/last_state_change/attempts）
- [x] 强化客户端池：`ThreadPoolExecutor` 并行尽力发现（逐服务器超时）；单服务器失败不阻塞其他；调用时检测死客户端 → 一次立即重连，后台 60s 冷却重发现（非逐调用）
- [x] 工具命名空间 `mcp__<server>__<tool>`（LLM 可见变更，原为 `<server>__<tool>`）；跨服务器冲突首个获胜 + 告警
- [x] 降级报告 `McpStatusReport`（generated_at + servers[{name,state,tool_count,last_error,since,required}] + all_ready/degraded/failed_required）
- [x] REST API `/api/v1/mcp/*`：GET status / GET servers（env 脱敏 key/token/secret/password）/ POST servers / PATCH servers/{name} / DELETE servers/{name}（内置 drawio 禁删 → 400）
- [x] 动态注册：新增/启用服务器后工具经弱引用注册表广播，无需重启
- [x] Settings UI 第 7 个 Tab "MCP"：状态徽章表（READY 绿 / DISCOVERING 琥珀 / FAILED 红 / DISABLED 灰）、启用开关、添加表单（slug 客户端校验）、删除（内置禁用+提示）、刷新
- [x] Electron IPC 路由 mcp_status/mcp_servers/mcp_server_add(rawBody)/mcp_server_update/mcp_server_delete + guard 测试
- [x] i18n zh+en（settings.mcp.*）
- [x] 故障演练（集成测试）：两个真实 stdio mock 服务器，杀一个 → 另一个照常应答、状态一 FAILED 一 READY、被杀服务器工具调用返回干净错误；重启后重连恢复
- [x] 测试：47 单元（config 14 + pool/tool 33）+ 18 路由契约 + 5 集成故障演练；ruff clean；py3.8 py_compile clean；vitest 8+31+16 新测试；tsc/tsc:electron/eslint clean

## 风险与决策记录

- **lifecycle 删除而非接线**：生产 McpClient 是同步阻塞 stdio，接线异步管理器需在每个状态转换架执行器桥，零收益双线程模型；PAUSED 对 stdio 子进程无意义。详见 `pool.py` 模块 docstring。
- **不用 settings_repo**：服务器定义是结构化受校验记录，JSON 文件是唯一事实源（模块 docstring 已论证）。
- **env 键名腐蚀防护**：IPC 桥 `camelToSnakeKeys` 会把 `PATH` 变成 `_p_a_t_h`；mcp_server_add 走 `rawBody` 旁路，客户端直接发 snake_case。
