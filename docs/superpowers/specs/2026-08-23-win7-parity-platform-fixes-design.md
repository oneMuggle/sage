# Win7 与主分支平台能力修复 Design

> 状态: 设计中
> 日期: 2026-08-23
> 分支策略: `main` 与 `release/win7` 双轨维护，按需 cherry-pick，不合并分支。

## 1. 背景与目标

Win7 实际运行暴露出一组跨层问题：LM Studio 模型无法稳定使用、流式回复抢夺历史阅读位置、记忆保存/搜索契约错误、文件与 Office 工具不可见、知识库能力未进入普通 Agent、三级记忆会话摘要不完整，以及时间和工作区设置缺少明确语义。

本设计的目标不是重写已有子系统，而是：

1. 修复已经存在的接口契约错误和用户可见回归；
2. 将已有的 Office、Wiki/RAG、`list_dir` 和 LLM proxy 能力接到真实 Agent/桌面链路；
3. 建立可持久化、可检索、可展示的会话摘要；
4. 明确定义 UTC instant、用户时区和 workspace settings；
5. 让每项共性修复可以在 `main` 与 Python 3.8/Pydantic 1 的 `release/win7` 上独立验证。

## 2. 已确认的现状

### 2.1 记忆

`WorkingMemory`、`EpisodicMemory`、`SemanticMemory` 已存在，`MemoryManager.memorize()` 是当前三层写入入口，`search_memories()` 是检索入口。

当前两个确定的生产 bug：

- `MemorySaveTool` 调用同步 `MemoryManager.remember()` 后，把字符串 ID 交给事件循环执行，造成保存已经发生但工具报告失败；
- `MemorySearchTool` 将 `query/context` 传给保存接口 `remember()`，导致 `unexpected keyword argument 'query'`。

工作记忆摘要目前存于内存 `_summaries`；SQLite snapshot 保存消息但不保存摘要、entities 或 variables。压缩时摘要会被写成 episodic 记忆，但没有独立摘要 API/UI 契约。

### 2.2 LLM 与流式 UI

LM Studio 可通过现有 OpenAI-compatible proxy 间接使用，但 endpoint 没有显式协议类型，未知 URL 的 provider 启发式识别不稳定。proxy 已支持 `/v1` 去重和 SSE/chunk 转发。

`Chat.tsx` 在每次 content/reasoning/tool-call 更新时无条件把滚动容器设置到末尾，没有 sticky-bottom 状态。

### 2.3 工具、Office 与知识库

- `list_dir` 已实现并注册，canonical name 是 `list_dir`；缺口主要可能是 alias、profile 白名单或自建空 registry；
- `office_list`、`office_read`、`office_create` 已实现；读工具依赖 request-scoped `ToolExecutionContext`；编辑、版本、归档、恢复不纳入本设计；
- Wiki ingest、token search、vector search、RRF 和 RAG chat 已实现为独立 Wiki API，但普通 Agent 没有知识库工具；
- `release/win7` 的 `requirements-py38.txt` 没有 Office 解析依赖，是 Win7 Office 能力缺口；
- Office 二进制文件不能直接走当前基于 `read_text()` 的知识库 ingest，需要显式文本抽取适配。

### 2.4 时间与工作区

后端主要保存裸 epoch milliseconds，缺少统一字段语义和前端用户时区 formatter。`AppSettings` 没有 timezone 字段。

当前 workspace 是 session 到目录的绑定，不是独立 workspace settings。没有稳定 workspace identity、settings blob、继承优先级或 GET/PATCH settings API。

### 2.5 Win7 打包运行时日志新增发现

真实 Win7 packaged 运行日志补充确认以下问题，这些问题属于本设计范围，优先级高于业务能力接线：

- `doctor` 使用 `E:\ProgramData\anaconda2\python.exe` 或 PATH 中的 `python`，而不是 bundled interpreter；以 `-m backend.cli.doctor` 启动时没有正确的 package root/PYTHONPATH，产生 `ModuleNotFoundError: No module named 'backend'`。日志中的 doctor 失败不能代表 bundled backend 本身失败。
- backend supervisor 在旧进程、健康检查、退出回调和重启定时器之间存在竞态：多个 `backend spawned` 重叠、重复 kill orphan、`[Errno 10048]` 端口占用、backend 刚返回 `/health` 便退出，随后 renderer 大量 `ECONNREFUSED`。当前 `backend ready` 事件可能只是端口探测成功，不是被当前 child process 身份绑定的稳定就绪状态。
- 同一日志窗口出现两个 Electron `main: process started`（不同 PID），需要核对 Electron single-instance lock；若未加锁，两个主进程各自启动 supervisor 会直接造成 backend ownership、端口和 IPC 竞态。
- renderer 在 backend 真正 ready 前已执行 settings/session/theme/scheduler IPC，导致启动阶段错误风暴；`backend:disconnected`/`backend:reconnected` 事件在 renderer 侧又被报告为 unknown event，说明 IPC 事件契约未统一。
- packaged frontend 调用了 `get_evolution_status` 和 `get_evolution_logs`，但 `electron/commands.ts` 不支持，说明前端 bundle、命令路由和后端能力存在版本漂移。
- settings payload 仍向后端提交 `memory_server_sync` 和 `orch.max_concurrent_subagents` 这类未规范化字段，而后端只接受 camelCase 白名单；这是设置 schema/canonicalization 漂移，不只是单个字段缺失。
- bundled backend 输出中文出现乱码，说明 Windows console/child-process stdout 的编码协议未统一；日志可读性和错误诊断因此受损。
- 外部 HTTPS 请求因 `CERTIFICATE_VERIFY_FAILED` 返回 502，说明 bundled Python 的 CA 证书路径/环境变量在真实 Win7 包中仍未可靠生效；不能只依赖开发环境或 conda 的 certifi。
- backend 启动时 `Wiki MCP Server` 因缺少 `mcp` 包降级，且后续显示 `No MCP tools available`。若 MCP 是可选功能，UI/doctor 必须明确报告 disabled；若知识库/MCP 是本次目标，则 bundled/Win7 依赖和启动验证必须覆盖它。
- chat 请求中的 `model=/mnt/workspace/model` 是 Windows packaged 环境下的 Linux 风格路径，且 provider 被记录为 `custom`。模型配置需要区分 provider、model id 和本地文件路径，并在跨平台加载时拒绝或迁移无效路径；不能把路径当作 LM Studio 模型 ID。
- Proactor 事件循环出现 `WinError 10038`，通常与连接被强制关闭后 transport callback 仍被调度有关；重启/取消/stream attach 的 teardown 必须具备幂等关闭和 Windows Proactor 回归测试。
- `backend` 启动日志使用本地时间（例如 `15:49`），Electron 外层 JSON 日志使用 UTC `Z`（例如 `07:49Z`）；两种时间本身相差 UTC+8，但当前没有统一字段标注，排查时容易误判启动顺序、scheduler 触发时间和超时。日志协议必须明确全部机器可读时间使用 UTC，展示层再按用户时区转换。
- 安装包可能不是当前源码对应产物：frontend bundle 调用 source `COMMAND_ROUTES` 中不存在的命令、doctor 使用旧路径、settings 发送旧字段，说明缺少 build commit/version/branch/manifest 可追踪性。必须在 packaged app、Electron main、frontend bundle 和 backend 启动日志中输出同一 build ID，并在 CI 做命令/schema/asset provenance 校验。

## 3. 范围与非目标

### 3.1 本次范围

- 记忆保存和搜索契约修复；
- sticky-bottom 流式阅读体验；
- LM Studio OpenAI-compatible 显式配置/测试；
- `list_dir` 统一命名与三条 Agent 链路接线；
- Win7 Office 依赖和 Office create/list/read 闭环；
- Wiki/RAG 作为受权限和 workspace 根约束的 Agent 工具；
- Office 文档文本抽取后进入知识库；
- 会话摘要持久化、检索、API 和 UI；
- `Asia/Shanghai` 默认时区及 IANA 时区配置；
- workspace settings 最小模型、API 和继承规则。

### 3.2 不在范围

- 不将 `release/win7` 合并到 `main`，不删除该分支；
- 不把 main 的 Python 3.11 依赖直接复制到 Win7；
- 不实现完整 Office edit/version/archive/restore 流程；
- 不重写 Wiki 向量库或 RRF 算法；
- 不把 `memory_search` 改名冒充知识库 RAG；
- 不把所有历史裸时间字段一次性迁移为 RFC3339；本次先建立明确的 epoch-ms 语义和统一展示层；
- 不在本次引入远程 workspace 服务或多用户 RBAC。

## 4. 设计方案

### 4.1 分批交付

#### 批次零：打包启动与运行时稳定性

1. doctor 必须使用与 backend spawn 相同的 bundled interpreter、工作目录和 package root；doctor 失败时记录真实解释器路径、`sys.path` 摘要和可诊断错误，不再使用 PATH 中的 `python`。
2. Electron packaged app 必须先取得 single-instance lock；重复启动只把参数/激活请求转发给已有 main，不创建第二个 supervisor 或 backend。
3. backend supervisor 对每次启动分配唯一 generation/child PID/ownership token，启动、健康检查、退出和 restart timer 只允许当前 generation 改变状态；同一时刻最多一个 Sage backend child，重启前等待旧进程退出并确认端口释放。
4. `backend ready` 只能在当前 child PID 返回带匹配 ownership token 的 `/health` 后发出；renderer 的初始 IPC 请求在 ready 前排队或返回可识别的 `backend_not_ready`，不得产生无界错误风暴。`backend:disconnected`/`backend:reconnected` 统一纳入 IPC event contract 并由 renderer 消费。
5. 对 Electron `COMMAND_ROUTES` 做启动时/CI 契约校验，确保 packaged frontend 调用的 `get_evolution_status`、`get_evolution_logs` 等命令均有 route，或前端 bundle 不再调用已移除命令。
5. settings canonicalizer 同时处理历史 snake_case 输入和当前 camelCase 输出；清理 `memory_server_sync`、`orch.max_concurrent_subagents` 等过期字段，增加 packaged bundle 的 GET/PUT round-trip 测试。
6. bundled child stdout/stderr 统一使用 UTF-8 解码并保留原始 bytes 的错误回退；日志中不得出现不可读的中文替换字符。
7. packaged HTTPS 请求显式验证并加载 bundled CA bundle（如 certifi），覆盖 Windows 环境变量、安装路径和代理场景；证书失败须报告可操作的诊断信息，不允许关闭 TLS 验证。
8. MCP 按产品策略二选一并写入打包契约：若 Wiki MCP 是可选项，doctor/UI 明确显示 disabled 和缺失依赖；若是本次必需能力，则把 `mcp` 及其依赖加入 Win7/bundled requirements 并做启动 smoke。
9. 模型配置拆分 `provider`、`model_id` 和可选 `local_model_path`；Windows packaged 环境拒绝 `/mnt/...` 等不属于当前平台的路径，并把 LM Studio 模型名作为模型 ID 而不是文件路径。
10. stream attach、interrupt、child kill 和 uvicorn shutdown 使用幂等 teardown，增加 Windows Proactor 下 `WinError 10038`、客户端提前断开和重复重启回归测试。

#### 批次一：契约和用户体验修复

1. `MemorySaveTool` 直接调用同步 `memorize()`；工具层不创建或驱动事件循环。若未来需要异步写入，新增明确命名的 `async_memorize` adapter，不复用同步方法名。
2. `MemorySearchTool` 调用 `search_memories(query, memory_type, limit)`；`all` 映射为 `None`，并保留 working/episodic/semantic 的类型过滤语义。
3. Chat 滚动使用底部阈值判断：只有更新前用户在底部时才跟随；用户向上滚动时保留位置；发送新消息时执行一次显式滚底；提供可访问的回到底部动作。
4. endpoint 增加明确的 `protocol` 字段，取值至少包含 `openai-compatible`；LM Studio 使用该协议语义。保存时规范化 base URL，兼容已有配置迁移。
5. 增加 LM Studio mock：模型发现、空 API key、带/不带 `/v1`、普通 completion、SSE 流。
6. canonical tool name 固定为 `list_dir`。对 `list-dir` 不做隐式执行；如保留兼容 alias，必须在 registry 层显式映射并测试权限、schema 和审计名称。

#### 批次二：Win7 工具与 Office 闭环

1. 在 `requirements-py38.txt` 中加入兼容 Python 3.8/Pydantic 1 的 `python-docx`、`python-pptx`、`openpyxl` 版本，并单独在 py38 CI 验证导入。
2. 确认 legacy SageAgent、hex ChatService、profile 白名单都能看到并执行 `list_dir`。
3. 保持 Office 工具的 session binding + generation 授权模型；补齐 Win7 的工具注册和 Electron IPC 断言。
4. `office_create` 生成的文档必须写入 `office_documents` 登记，随后可被 `office_list` 列出、`office_read` 读取；失败时不留下半成品登记或泄露绝对路径。
5. 只补 create/list/read round-trip，不扩展编辑、版本、归档和恢复。

#### 批次三：知识库与会话摘要

1. 新增受 ToolPolicy 和 workspace root 约束的 `wiki_search`、`wiki_answer` Agent 工具；工具调用复用既有 Wiki search/RAG service，不直接暴露任意文件路径。
2. 新增 Office 文本抽取 adapter：DOCX/PPTX/XLSX 通过既有 reader 输出受限文本，再进入 Wiki ingest；限制单文件大小、文本字节数和解析耗时。
3. 定义会话摘要记录：

```text
SessionSummary {
  id: string
  session_id: string
  source_turn_id: string | null
  content: string
  created_at_ms: integer
  updated_at_ms: integer
  status: "pending" | "ready" | "failed"
}
```

4. 会话压缩或 turn 完成时生成摘要；摘要生成失败保留 `failed` 状态和可诊断错误，不伪装为普通事实。摘要持久化到专用表或明确的 episodic subtype，推荐专用 `session_summaries` 表以避免与普通事实混淆。
5. 检索优先级定义为：working context → 当前 session summary → episodic/semantic 长期记忆。不同 session 不得互相注入摘要。
6. API 增加按 session 查询摘要和三层记忆列表的明确字段；修复 `type=None` 只返回 episodic、page 未转 offset 的问题。前端 Memory 页面显示 summary/working/core 来源，并保留来源 session 跳转。

#### 批次四：时区与 workspace settings

1. 内部和数据库时间继续保存 UTC instant 的 epoch milliseconds，字段/文档明确 `*_ms` 单位；禁止把本地 naive datetime 写入持久层。
2. `AppSettings.timezone` 使用 IANA 名称，默认 `Asia/Shanghai`；后端 `zoneinfo.ZoneInfo` 校验，非法值返回 422；前端提供可搜索选择并显示当前 UTC offset。
3. 建立统一前端 `formatInstant(ms, timezone)`，所有会话、记忆、Office、摘要展示优先使用设置中的 timezone。
4. 新增 workspace settings 最小模型：

```text
WorkspaceSettings {
  workspace_id: string
  workspace_path: string
  timezone: string | null
  locale: string | null
  default_model: string | null
  knowledge_base: object | null
  updated_at_ms: integer
}
```

当前 identity 以规范化 workspace path 派生，后续可以迁移到稳定 UUID；API 使用 session binding 解析 workspace，不允许客户端任意指定未绑定路径。
5. 新增 workspace settings GET/PATCH/DELETE 或 clear-inherited API，明确 `null` 表示继承而不是写入空字符串。配置优先级：

```text
session override > workspace settings > app settings > product default
```

6. session workspace binding 继续只负责路径关联、generation 和权限，不承载 settings。

## 5. 数据流与错误处理

### 5.1 记忆

工具输入在边界处校验 content/query、memory_type、limit 和 tags。写入失败返回结构化 tool error；不会吞掉已写入 ID，也不会让聊天流失败。搜索统一返回 `{items, total, page, page_size}` 或项目现有等价 envelope。

### 5.2 流式 UI

滚动状态由容器 scroll listener 维护，使用固定阈值而非每 token 猜测。滚动动作仅影响 UI，不改变消息存储。流结束、失败和组件卸载都必须清理 listener/timer。

### 5.3 工具与文件

所有文件操作继续经过现有 path safety、ToolPolicy、workspace binding 和 generation 检查。知识库工具输出只返回相对路径/文档标识，不返回绝对 workspace path。Office parser、embedding 或 RAG 失败时返回结构化降级结果，不能静默声称已完成。

### 5.4 时间与设置

设置写入走现有 canonicalizer 和 app settings blob；新增字段必须同时加入前端类型、默认值、snake/camel canonicalization、legacy/hex route contract 和 reset 逻辑。时间展示失败时回退 UTC，而不是回退操作系统本地时区。

### 5.5 打包启动与运行时

supervisor 的状态机必须以 `child_generation` 为 authority，状态至少区分 `starting`、`ready`、`stopping`、`exited` 和 `restarting`。健康检查只接受当前 generation，旧 child 的迟到退出事件不得杀掉新 child。每个启动周期记录合成诊断字段：`generation`、`pid`、`interpreter`、`working_directory`、`port`、`health_status` 和 `exit_code`。

doctor、backend、Electron IPC 和 frontend bundle 共用一个版本化 capability/command manifest。缺失能力必须在启动诊断中标为 `disabled` 或 `incompatible`，不能表现为反复重试的网络错误。

### 5.6 TLS、编码与 Windows teardown

网络 TLS 始终启用证书验证，CA 路径通过 bundled interpreter 自身可解析的资源确定。子进程输出按 UTF-8 解码，无法解码时保留转义字节摘要。关闭路径采用幂等 guard，先停止新请求和 stream attach，再取消后台任务、关闭连接、等待 child 退出，最后释放端口。

## 6. 文件与模块边界

### 后端

- `backend/tools/memory_tool.py`
- `backend/memory/manager.py`、`working.py`、`episodic.py`
- `backend/tools/file_tool.py`、`backend/tools/__init__.py`、agent profile/registry
- `backend/office/*`、`backend/tools/office_tool.py`、`office_create_tool.py`
- `backend/wiki/*`、新增知识库工具模块
- `backend/api/legacy_routes.py`、`wiki_routes.py`、workspace/settings routes
- `backend/data/database.py`、settings repository/canonicalizer
- `backend/requirements-py38.txt`、bundled requirements 和依赖 manifest
- `backend/cli/doctor.py`、backend CLI checks 与 bundled launcher
- `backend/main.py`、`backend/api/llm_proxy_routes.py`、stream/uvicorn teardown
- `backend/config.yaml`、CA/bootstrap 和 MCP optional dependency manifest
- `electron/backendLauncher.ts`、`electron/main.ts`、`electron/commands.ts`、IPC event types
- `src/shared/api/desktopInvoke.ts`、启动 readiness/error queue 和 settings canonicalization

- `src/features/send-message/useChat.ts`
- `src/pages/Chat.tsx`、滚动容器/消息列表相关组件
- `src/entities/setting/types.ts`、settings client、General/Endpoints 页面
- `src/features/manage-endpoints/api.ts`
- `src/shared/api/memoryApi.ts`、knowledge/workspace API
- `src/pages/Memory.tsx`、`src/widgets/memory/MemoryBrowser.tsx`
- `electron/commands.ts`、`preload.ts`、Office/Wiki IPC

### 测试与文档

- Electron packaged build manifest/provenance tests
- Electron single-instance lock and duplicate-launch tests
- backend launcher/doctor/supervisor readiness and single-child tests
- ownership-token/child-generation stale-event tests
- IPC command/event manifest parity tests
- Windows UTF-8 log, bundled CA/TLS and Proactor teardown tests
- Chat auto-scroll/stream tests
- provider proxy/LM Studio fixture tests
- tool registry/profile/list-dir tests
- Office round-trip and Win7 dependency/import tests
- Wiki agent tool and Office ingest tests
- session summary persistence/restart/isolation tests
- settings schema/timezone/workspace API/UI tests
- main and Win7 technical/user documentation updates

## 7. 分支与兼容策略

1. 所有实现先在 `feat/win7-parity-platform-fixes` 或其子 feature 分支完成。
2. `main` 使用 Python 3.11/Pydantic 2；`release/win7` 使用 Python 3.8/Pydantic 1。代码避免 PEP 604、`zip(strict=)` 等 Win7 不支持语法。
3. 共性修复拆成可 cherry-pick 的功能性提交；Win7 适配单独提交依赖、类型兼容和 Electron 差异。
4. 严禁 merge `release/win7` 到 `main`，严禁删除 Win7 分支。
5. 每个批次在 main 先跑定向测试，再在 Win7 工作树用 py38 环境验证；不把 main requirements 自动复制到 Win7。

## 8. 验收标准

### 8.1 打包运行时

- doctor 使用 bundled interpreter 且 package root 正确；
- 任意时刻最多一个当前 generation backend child，连续重启不产生端口占用或 renderer 错误风暴；
- Electron 重复启动不会创建第二个 main/supervisor/backend；
- `backend ready` 与当前 PID、generation 和 ownership token 绑定，IPC event/command manifest 与 packaged bundle 一致；
- settings GET/PUT 在旧 snake_case 输入和当前 camelCase 输出间稳定 round-trip；
- bundled 日志统一 UTC、中文可读，并包含 build ID；
- Win7 HTTPS 请求通过 bundled CA 验证，缺失 CA、MCP disabled 和模型路径错误均有明确诊断；
- stream 取消、backend kill/restart 和 shutdown 不产生 `WinError 10038`。

### 8.2 功能

- LM Studio 可完成模型发现、空 key 普通回复和 SSE 流式回复；
- 用户向上滚动历史时，流式回复不会抢回底部；
- 记忆保存返回真实 ID，搜索支持 `all/episodic/semantic/working`，不再出现 loop/query 参数错误；
- `list_dir` 在 legacy、hex、profile 三条链路可见且可执行；
- Win7 Office 依赖可导入，create -> list -> read round-trip 通过；
- Agent 可通过受限工具搜索/回答知识库问题；Office 文本可进入 ingest；
- 会话摘要可跨进程持久化、按 session 隔离、被检索并在 UI 展示；
- 默认时间按 `Asia/Shanghai` 展示，非法 timezone 被拒；
- workspace settings 可读、更新、清除继承，不同 workspace 互不污染。

### 质量与安全

- 所有新增边界输入有 schema/path/size/limit 校验；
- 不返回绝对 workspace path；
- 无 `asyncio.run()` 嵌套运行 loop 的生产工具路径；
- 关键新增逻辑有 unit、integration 和必要的 Electron/E2E 测试；
- main 与 Win7 定向 suite 通过，覆盖率目标不低于项目约定的 80%；
- 代码审查必须包含通用、TypeScript、Python 和安全审查。

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| main 与 Win7 记忆生命周期架构不同 | 先修工具公共契约，再分别适配队列与 legacy lifecycle，不直接 cherry-pick 大块架构 |
| 新增 RAG 工具扩大文件访问面 | 复用 workspace binding、ToolPolicy、path safety，只允许 workspace scope |
| Office 解析依赖与 py38 wheel 不兼容 | 固定已验证版本，在 py38 CI 先跑 import 和最小 round-trip |
| 摘要生成增加 LLM 调用和延迟 | 使用后台队列，状态化记录，失败不阻塞聊天响应 |
| epoch-ms 与历史裸字段并存 | 先规范新增/展示字段，兼容旧数据；禁止隐式单位转换 |
| workspace path 作为 identity 可被移动 | 当前明确记录限制；后续以稳定 workspace UUID 迁移，不在本次暗中改变绑定语义 |
| Wiki embedding/hnsw 可选依赖失败 | 显式报告 token fallback 状态，增加 bundled 与 py38 依赖契约测试 |

## 10. 交付顺序

- [ ] 批次一：记忆、流式滚动、LM Studio、`list_dir` 契约修复
- [ ] 批次二：Win7 Office 依赖与 Office round-trip
- [ ] 批次三：Agent 知识库工具、Office ingest、会话摘要闭环
- [ ] 批次四：时区与 workspace settings
- [ ] main 定向验证、代码审查与安全审查
- [ ] Win7 py38 定向验证和 cherry-pick 适配
- [ ] 技术手册与用户手册归档更新
