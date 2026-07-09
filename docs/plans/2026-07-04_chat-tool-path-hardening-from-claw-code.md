# Chat/工具执行链路加固方案（参考 claw-code）

> **日期**: 2026-07-04
> **分支**: main
> **范围**: 参考 `/home/fz/project/claw-code` 的设计纪律，对 sage **主 chat 单轮 + 工具执行链路** 做三方向加固：结构化可观测性、显式限制、权限与安全边界。
> **定位**: 前序 `docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md` 已把 claw-code 的经验借鉴到 **orchestration / 多 Agent lane 层**（并落地了 `backend/orchestration/permission.py`）。本方案是**互补角度**——把同一批原则接到 **`ChatService` 主链路**，两者不重叠。
> **目标读者**: 后端加固阶段的开发者

---

## 1. 背景与目标

claw-code 是 Rust CLI-agent 生态（完整 `claw` + 精简 `claw-analog` + 独立 `claw-rag-service`），技术栈与 sage（Electron + React + Python FastAPI 桌面应用）完全不同，因此可借鉴的是其**设计纪律**而非代码。其 `concept.md` §4 列出四条核心原则：**安全默认、显式限制、Agent 可观测、模块化**。

sage 架构已相当成熟，claw-code 的多数分层它**已具备**（RAG 已是独立 HTTP 客户端 `adapters/out/rag/client.py`、LLM 有 `mock_adapter.py`、Prometheus 指标、file/stdout 事件适配器）。但对照发现主 chat 链路上有三处明显差距，本方案逐一补齐。

**目标**（三方向，均可独立验证）：

1. **结构化可观测性** — 事件流引入带 `schema` + `format_version` 的类型化信封（envelope），补齐 `run_start / turn_start / tool_result / run_end` 语义事件，`FileEventAdapter` / `StdoutEventAdapter` 统一 NDJSON。
2. **显式限制与可预测失败** — 在工具分发唯一收口处引入统一 `ToolPolicy`（byte 上限、结果条数上限、超时），并给 `ChatService` 补 tool-call 回合守卫。杜绝 OOM / 无限挂起。
3. **权限与安全边界** — 复用**已存在但未接线**的 `PermissionPreset` / `LanePermission`，把它接到主 chat 工具路径；激活 `file_tool` 里的死代码 `_is_safe_path`；补 `..` / 符号链接 / 绝对路径越界拒绝；`CliConfirmationAdapter` 改 fail-closed。

**非目标**（本轮不做）：headless/claw-analog 式 CLI 自动化面；RAG ANN 化；重构 orchestration lane 层。

---

## 2. 现状勘察结论（带 file:line 证据）

### 2.1 可观测性现状

| 组件 | 位置 | 现状 |
| --- | --- | --- |
| 事件端口 | `backend/ports/observability.py:29-34` | `EventPort.emit(event_type: str, payload: dict[str, Any])` — 无 schema、无 version、无 run_id |
| 文件适配器 | `backend/adapters/out/event/file_adapter.py:48-55` | 写 `{ts, type, payload}` 到 `backend/data/audit/audit.jsonl` — 已是 NDJSON，但**无 schema/format_version** |
| 事件目录 | `file_adapter.py:16-38` | `AuditEventType` 仅 5 个名字：`chat_message_sent / chat_response_completed / tool_invoked / session_created / settings_changed` |
| stdout 适配器 | `stdout_adapter.py:15-17` | 明文 `[event] type: json` —**非 NDJSON** |
| 主链路 | `backend/application/services/chat_service.py:163-364` `_run_turn_inner` | 单轮编排；发出点：`chat_message_sent`(172)、`llm.chat`(257)、`llm_error`(274)、`chat_response_completed`(318)、`tool_invoked`(425)、`tool.execute`(434)、`tool_failed`(443) |
| 传输 | `backend/api/chat_stream_registry.py` | NDJSON over 分块 HTTP `GET /chat/stream/{id}` |

**缺口**：无 `run_start/run_end/turn_start`；成功分支**只落库+打点，不发 `tool_result` 事件**（`tool_invoked` 有、对称的结果事件没有）；payload 无版本化信封。

### 2.2 限制现状

| 维度 | 位置 | 现状 |
| --- | --- | --- |
| 分发收口 | `backend/adapters/out/tool/inproc_adapter.py:57` / `compute_tool_adapter.py:63` | 所有工具经此 `execute()`；**无 `asyncio.wait_for`、无超时、无 byte 上限** |
| ToolResult | port 侧 `{success, output, error, metadata}`；内部 `backend/tools/base.py:22-37` | — |
| 回合守卫 | `chat_service.py:163-364` | **无循环、无 max-turns 守卫**（"单轮设计"）；legacy `backend/core/legacy/agent.py:449` `run_loop` 有 `max_iterations`(478-497) |
| read_file | `backend/tools/file_tool.py:55,77` | 仅 500 行上限；`path.read_text()` **先整文件入内存再切片**（大文件 OOM） |
| list_dir | `file_tool.py:180-219` | `iterdir()` **无条数上限** |
| web_fetch | `backend/tools/web_tool.py:166` | 10000 char 截断（在 `response.text` 物化**之后**） |
| 分散超时 | `web_tool.py:15/144`(30s)、`terminal.py:102/108`(30s)、`subprocess_adapter.py:190`(30s)、`mcp/client.py:131`(5s 启动) | **硬编码分散、非中心强制** |
| 配置 | `backend/config.yaml:23-29`(memory)、`backend/config/ghm.yaml:12`(compute timeout) | **无 tools 上限段** |

**缺口**：无中心工具超时；无 byte 上限；无结果条数上限；主链路无回合守卫。

### 2.3 权限/安全现状

**关键发现——原语已存在但未接线**：

- `backend/orchestration/permission.py:13-18` 已定义 `PermissionPreset {AUDIT, EXPLAIN, IMPLEMENT}`；`LanePermission.check`(38-69) 在 AUDIT/EXPLAIN 下已拦 `write_file/delete_file/execute/shell`；`_check_path_access`(71-84) 已用 `Path.resolve()` + `relative_to(allowed_dir)`——**但仅当 `allowed_paths` 非空时**。
- `backend/orchestration/executor.py:210` `_build_permission` **恒传空列表** → 路径守卫永不生效。
- `backend/tools/file_tool.py:37-53` 有 `_is_safe_path`（resolve + startswith 校验）**但是死代码，从未被调用**；`execute`(55-95) 只做 `Path(path).expanduser()`——**无 resolve、无 `..` 拒绝、绝对路径畅通**。`WriteFileTool`(125-154)、`ListDirTool` 同样。
- `backend/tools/terminal.py` 仅子串黑名单 `DANGEROUS_PATTERNS`(21-31)，`subprocess.run(cwd=用户参数)`(108)——**无沙箱**。
- MCP：`backend/mcp/tool.py` `McpTool.execute` 直接 `client.call_tool`——**无 allow/deny、无 consent**。
- `backend/adapters/out/skill_script/cli_confirmation.py` `confirm()`：**回调为 None 时自动放行 True**——非 fail-closed。
- 审计：`audit.jsonl` 不记录 resolved_path、不记录 allow/deny 决策。

**缺口**：死代码未激活；`allowed_paths` 恒空；terminal 仅黑名单；MCP 无门禁；确认默认放行；无符号链接/`..` 检查；审计缺路径与决策字段。

---

## 3. 技术方案

三方向按依赖/风险排序为 M1→M2→M3。M1（可观测）最低风险且为 M3 的审计决策提供落地信封；M2、M3 同在工具分发收口处叠加。以下接口均为**设计草图**，实现以现有类型为准。

### 3.1 M1 · 结构化可观测性

**新增类型化事件信封**（`backend/domain/agent_event.py`，新文件）：

```python
# 设计草图
AGENT_EVENT_SCHEMA = "sage.agent.event"
AGENT_EVENT_FORMAT_VERSION = 1

@dataclass(frozen=True)
class AgentEvent:
    schema: str            # 恒为 AGENT_EVENT_SCHEMA
    format_version: int    # 恒为 AGENT_EVENT_FORMAT_VERSION
    event_type: str        # run_start / turn_start / llm_call / tool_call / tool_result / run_end / *_error
    run_id: str            # 每次 run_turn 一个
    seq: int               # run 内自增序号
    ts: str                # iso8601
    data: dict[str, Any]   # 事件专属载荷
```

**改造点**：

- `EventPort`（`ports/observability.py`）**保持 `emit(event_type, payload)` 签名不变**（向后兼容），新增便捷方法 `emit_event(event: AgentEvent)`，内部序列化为带信封的 dict。
- `FileEventAdapter.emit`（`file_adapter.py:48`）：每行补 `schema` + `format_version`（若 payload 未带则用默认值包裹），保持 `audit.jsonl` 兼容。
- `StdoutEventAdapter.emit`（`stdout_adapter.py:15`）：改为输出纯 NDJSON 行。
- `AuditEventType`（`file_adapter.py:16`）扩充：`run_start / turn_start / llm_call / tool_result / run_end`（`llm_error / tool_failed` 已在用，一并纳入枚举）。
- `ChatService._run_turn_inner`（`chat_service.py:163-364`）注入发出点：
  - `run_start` — 进入 run_turn（现 `chat.run_turn` span，158 行处）生成 `run_id`。
  - `turn_start` — `_run_turn_inner` 顶部（163）。
  - `tool_result` — `_execute_tool_calls`（412）成功分支补发（当前 459-463 只落库+打点），与 `tool_invoked`(425) 对称。
  - `run_end` — run_turn 返回处（364），带 `status` 与 `seq` 总数。
- `chat_stream_registry.py` 生产端：入队前用信封序列化，保证前端/electron 拿到版本化 NDJSON。

**验证**：`audit.jsonl` 每行含 `schema="sage.agent.event"` + `format_version`；一次带工具调用的 run 产出 `run_start → turn_start → llm_call → tool_call → tool_result → run_end` 完整序列且 `seq` 单调；新增 integration 测试断言序列与信封字段。

### 3.2 M2 · 显式限制与可预测失败

**新增统一策略**（`backend/domain/tool_policy.py`，新文件）：

```python
# 设计草图
@dataclass(frozen=True)
class ToolPolicy:
    timeout_seconds: float = 30.0      # 中心超时（覆盖分散硬编码）
    max_output_bytes: int = 256_000    # 单次工具输出上限
    max_result_items: int = 200        # list/search 类条数上限
    max_read_bytes: int = 2_000_000    # read_file 字节上限（先于行切片）
    max_tool_calls_per_run: int = 25   # run 内工具调用总数守卫
```

**改造点**：

- **中心超时** — `InprocToolAdapter.execute`（`inproc_adapter.py:57`）与 `ComputeToolAdapter.execute`（`compute_tool_adapter.py:63`）用 `await asyncio.wait_for(inner, timeout=policy.timeout_seconds)` 包裹；超时统一返回 `ToolResult(success=False, error="tool_timeout")`——**可预测失败**。
- **byte 上限** — `read_file`（`file_tool.py:77`）改为**流式/限量读取**，超 `max_read_bytes` 截断并在 `metadata` 标 `truncated=True`；分发处对任意工具的 `output` 超 `max_output_bytes` 统一截断。
- **条数上限** — `list_dir`（`file_tool.py:198`）`iterdir()` 加 `max_result_items` 上限；`skill_md/resources.py:83` 的 `rglob("*")` 同步加限。
- **回合守卫** — `ChatService._execute_tool_calls`（412）累计计数，超 `max_tool_calls_per_run` 停止并发 `run_end(status="tool_budget_exceeded")`（对齐 legacy `agent.py:611` 的 `max_iterations_exceeded` 语义）。
- **配置化** — `backend/config.yaml` 新增 `tools:` 段承载上述键；`ToolPolicy.from_config()` 加载，缺省用 dataclass 默认。分散的 30s 硬编码逐步改为读 `policy.timeout_seconds`。

**验证**：单测——超大文件 read 被 byte 截断且不 OOM；慢工具（mock sleep）触发 `tool_timeout`；`list_dir` 于大目录被条数截断；构造 >25 次工具调用触发预算守卫。

### 3.3 M3 · 权限与安全边界

**思路：接线 + 激活现有原语，尽量不造新轮子。**

**改造点**：

- **接线 PermissionMode 到主链路** — `ChatService` 增加 `permission_preset`（默认 `IMPLEMENT`，可由会话/设置下传），在 `_execute_tool_calls`（`chat_service.py:412`）调用工具**前**用 `LanePermission.check(action_type, tool_name, path)`（复用 `orchestration/permission.py:38-69`）做门禁；被拒返回 `ToolResult(success=False, error="permission_denied")` 并发 `tool_result` 事件（decision=denied）。
- **激活路径守卫** — 给主链路提供非空 `workspace_root`（来源：会话工作目录 / `SAGE_USER_DATA_DIR` / 配置），使 `_check_path_access`（`permission.py:71-84`）真正生效；同时**激活 `file_tool._is_safe_path`**（`file_tool.py:37-53`）：`read/write/list` 三个 `execute` 入口一律先 `resolve()` 再校验落在 `workspace_root` 内，拒绝 `..`、绝对越界、**符号链接逃逸**（`resolve(strict=False)` 后再比对）。
- **terminal 门禁** — `TerminalTool` 在黑名单之外，增加 PermissionMode 门（AUDIT/EXPLAIN 直接拒 `shell`），`cwd` 限制在 `workspace_root` 内。
- **MCP 门禁** — `McpTool.execute`（`mcp/tool.py`）在 `client.call_tool` 前查 `LanePermission` / allow-list。
- **确认 fail-closed** — `CliConfirmationAdapter.confirm`（`cli_confirmation.py`）回调为 None 时**默认拒绝**（当前默认放行）。
- **审计增强** — `tool_result` 事件（M1 已建）补 `resolved_path` 与 `permission_decision` 字段，`audit.jsonl` 由此可回答"谁在什么模式下写了哪个路径"。

**验证**：AUDIT 预设下 `write_file/terminal` 被拒且落审计；`../../etc/passwd`、绝对路径、workspace 外符号链接均被拒；`IMPLEMENT` 预设正常放行；MCP 工具在受限预设下被拦；确认回调缺失时默认拒绝。

---

## 4. 实施步骤（里程碑，可独立验证）

### M1 · 结构化可观测性
- [x] 新增 `backend/domain/agent_event.py`（`AgentEvent` + schema/version 常量 + `envelope()` + `RunEventScope`）
- [x] `FileEventAdapter` / `StdoutEventAdapter` 输出信封化 NDJSON（每行 schema+format_version；stdout 改纯 NDJSON）
- [x] 扩充 `AuditEventType`（新增 run/turn/llm/tool_result/run_end 常量，`all()` 保持 5 类不变）
- [x] `ChatService` 注入 `run_start / turn_start / tool_result / run_end`（补对称结果事件，run_id + 单调 seq）
- [ ] `chat_stream_registry` 生产端信封化 —— **暂缓**：该流承载 legacy agent 事件、直连 Electron NDJSON 解析，属前端契约变更，需前端侧联调后再做（对应 §6 首行风险）
- [x] 测试：`test_agent_event` / `test_event_adapters_envelope` / `test_chat_service_run_events`（完整事件序列 + 信封字段 + `seq` 单调）

### M2 · 显式限制
- [x] 新增 `backend/domain/tool_policy.py`（`ToolPolicy` frozen dataclass + `from_config(dict)`）
- [x] `InprocToolAdapter` / `ComputeToolAdapter` 中心 `asyncio.wait_for` 超时 + output byte 截断（Python 3.10 兼容：catch `asyncio.TimeoutError, TimeoutError` 双名）
- [x] `BaseTool.__init__(policy=None)`；`register_all_tools(registry, policy=None)` 透传；`InprocToolAdapter` 在注册时把 `self._policy` 注入
- [x] `read_file` 流式读取（先于行切片）；超 `max_read_bytes` 截断并标 `truncated/original_bytes/max_read_bytes`
- [x] `list_dir` `iterdir` 条数截断 `max_result_items`；content 含 `truncated/total_items`
- [x] `ChatService` 工具调用预算守卫 `_execute_tool_calls -> bool`；`_run_turn_inner` 据此 `run_end(status="tool_budget_exceeded" if exceeded else "ok")`
- [x] `backend/config.yaml` 新增 `tools:` 段；`backend/application/services/tool_config.py: load_tool_policy_from_config(path)` 读取并构造 `ToolPolicy`；缺段/缺文件降级默认
- [x] 测试：26 个新增（M2a=5、M2b=6、M2c=7、M2d=3、M2e=5）；后端全套 1468 passed（无 failure）；mypy domain strict 干净；ruff 全绿

### M3 · 权限与安全边界
- [x] 激活 `file_tool._is_safe_path`（移到 `BaseTool`）；3 入口 resolve + `relative_to` 严格比对；`_enforce_workspace` 拒 .. / 符号链接 / 绝对越界
- [x] `ToolPolicy` 加 `workspace_root: str | None = None` 字段
- [x] `ChatService` 下传 `permission_preset`/`permission_allowed_paths`/`permission_denied_tools`；构造 `LanePermission`；`_execute_tool_calls` 在工具执行前 `LanePermission.check(AgentAction)` 门禁；被拒返回 `permission_denied` + `permission_decision=denied`
- [x] `CliConfirmationAdapter` 改 fail-closed（callback=None 默认 False）；更新既有 `test_skill_md_confirm` 断言
- [x] `tool_result` 事件补 `resolved_path` + `permission_decision` 字段
- [ ] `TerminalTool` PermissionMode 门 + cwd 限界 — **暂缓**：核心权限语义已通过 `LanePermission` 在主链路落地，terminal 细化接线留 follow-up PR
- [ ] `McpTool.execute` 前置权限查 — **暂缓**：同上，核心已覆盖
- [x] 测试：21 个新增（M3a=9 + M3b=5 + M3c/d=6 + skill_md_confirm=1 改）；后端全套 1488 passed；mypy domain strict 干净；ruff 全绿

---

## 5. 涉及文件与模块

| 领域 | 主要文件 | 动作 |
| --- | --- | --- |
| 可观测 | `backend/domain/agent_event.py` | 新增 |
| 可观测 | `backend/ports/observability.py` | 加 `emit_event` |
| 可观测 | `backend/adapters/out/event/{file,stdout}_adapter.py` | 信封化 NDJSON |
| 可观测/限制/权限 | `backend/application/services/chat_service.py` | 事件注入 + 预算守卫 + 权限门 |
| 限制 | `backend/domain/tool_policy.py` | 新增 |
| 限制/权限 | `backend/adapters/out/tool/{inproc,compute_tool}_adapter.py` | 中心超时 + output 截断 |
| 限制/权限 | `backend/tools/file_tool.py` | byte 限量 + 激活 `_is_safe_path` |
| 权限 | `backend/orchestration/permission.py` | 复用（可能小幅扩展 action 映射） |
| 权限 | `backend/tools/terminal.py`、`backend/mcp/tool.py`、`backend/adapters/out/skill_script/cli_confirmation.py` | 门禁 / fail-closed |
| 配置 | `backend/config.yaml` | 新增 `tools:` 段 |

---

## 6. 风险评估与依赖

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| 事件信封改动破坏前端/electron NDJSON 解析 | 中 | `format_version` 递增 + 向后兼容 payload；前端先容错读取；M1 加解析测试 |
| 中心超时误杀合法长工具（大 web_fetch / 长 terminal） | 中 | 超时可配置 + 按工具类别覆盖；默认取现有 30s 不变，仅收口强制 |
| 路径守卫收紧后既有会话读绝对路径失败 | 中 | `workspace_root` 默认取宽松根（用户数据目录）；`IMPLEMENT` 预设保持放行；灰度开关 |
| `CliConfirmation` 改 fail-closed 影响自动化技能 | 低 | 仅在无回调时改默认；显式注入自动确认回调的路径不受影响 |
| audit.jsonl 字段增加影响下游消费 | 低 | 只增字段不改旧字段；schema 版本化 |
| 与 legacy `agent.py` run_loop 双路径不一致 | 低 | 本轮聚焦 `ChatService`；legacy 守卫已有，policy 逐步共享 |

**依赖**：
- Python 后端环境 `sage-backend`（conda，Python 3.11）——所有 `pytest/ruff/mypy` 必须在此环境跑，勿污染 base。
- `backend/orchestration/permission.py`（前序 2026-06-26 计划产物）——M3 直接复用。
- 无新增第三方依赖。

---

## 7. 与现有计划/分支的关系

- **不替换**任何现有计划；与 `2026-06-26_multi-agent-optimization-from-claw-code.md` 互补（那份接 orchestration lane 层，本份接 ChatService 主链路）。
- **分支约束**：本方案在 **main** 实施。`release/win7` 为长期共存 LTS 分支，**不主动合并**；如需同步，按项目规则用 cherry-pick 并单独验证（注意 py38 依赖差异）。
- 落地后按 feature-development 规范：完成的功能点并入 `docs/technical/` 对应章节，然后删除本 plan 文件。

---

## 8. 建议执行顺序与开关

1. **M1 先行**（低风险、立即可见、为 M3 审计铺路）。
2. **M2 次之**（收口超时 + byte/条数上限，杜绝 OOM/挂起）。
3. **M3 最后**（复杂度最高，复用 M1 审计信封记录权限决策）。

每个里程碑独立 PR、独立 CI、独立 code review；M3 涉及安全语义，合并前走 `security-reviewer` 复核。建议 `workspace_root` 与 `permission_preset` 加会话级开关，先默认宽松（`IMPLEMENT` + 宽 root）灰度，观察审计日志后再收紧默认值。
