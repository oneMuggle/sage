# R83 进程外插件宿主 Spec

> 日期：2026-10-21
> 分支：`feat/plugin-kernel-r78`（PR #2206）
> 前置：R78 插件契约与内核骨架、R80 bundle 收编、R81 harness 配置、R82 插件 REST/UI
> 本轮目标：让已安装插件第一次在**独立 Python 子进程**中真实加载、调用、崩溃隔离与停止；R82 的“已启用（记录）”继续只表示数据库状态，新增独立 runtime 状态表示代码是否正在运行。

---

## 1. 盘点结论与落位决策

### 1.1 已有资产

| 资产 | 现状 | R83 用法 |
| --- | --- | --- |
| `backend/plugins/manifest.py` | `PluginCapability.entry_point` 是自由字符串；能力类型为 `tool/skill/hook/mcp_server/command` | 第一垂直切片只托管带 `entry_point` 的 `tool` 能力；不改变已持久化 manifest 结构 |
| `backend/plugins/lifecycle.py` | SQLite 持久化插件记录、manifest、config 与审计事件 | 继续作为安装/启停的权威状态；新增 runtime 审计事件 |
| `backend/plugins/registry.py` | `CapabilityRegistry` 已实现但从未接线，无生产调用方 | worker 启动成功后注册进程外代理 handler；停止/崩溃时 `unregister_all` |
| `backend/mcp/client.py` | 成熟的长驻 stdio 子进程模式：stdout 读线程 + Queue deadline，避免 Windows `readline()` 永久阻塞 | 复用监督模式，但实现插件专用 JSON Lines/JSON-RPC 协议 |
| `backend/office/worker_job.py` | Windows Job Object：内存上限、活动进程数、kill-on-close，CREATE_SUSPENDED 后挂载 | Windows 下优先复用；挂载失败时明确降级并在状态中报告内存上限未强制 |
| `backend/remote_mcp/protocol.py` | JSON-RPC 报文、错误码、请求体上限与审计形态成熟 | 复用语义：`jsonrpc/id/method/params`、标准错误码、消息上限、审计事件；不直接耦合 HTTP/MCP session 实现 |
| `backend/domain/plugin.py` | R78 已定义 `FiberState` 六态 | runtime 对外状态沿用 `pending/loading/active/failed/unloading/disposed` 词汇 |
| `backend/api/plugin_routes.py` + 设置页 | R82 已有本地鉴权、生命周期 REST 与插件页 | 在同一 router/UI 上增加 runtime 操作，不新建第二套管理面 |

### 1.2 宿主落位

新增：

- `backend/plugins/host.py`：宿主侧进程监督、协议客户端、状态 DTO、能力代理注册、全局单例与 shutdown。
- `backend/plugins/host_worker.py`：子进程入口；仅依赖标准库，在导入插件代码前施加 POSIX 资源限额、重定向插件 stdout，并提供 JSON-RPC 循环。

选择既有 `backend/plugins` 子系统而不是新 hexagonal adapter 的原因：

1. `manifest/lifecycle/registry/plugin_routes` 已经形成一个自洽的 unmanaged 子系统，R82 也在此接线；
2. `architecture-policy.json` 中 backend-api 不依赖 adapters，把宿主放入 adapters 会迫使本轮额外改组合根与依赖策略；
3. R78 `PluginHostPort.load(plugin_id, apply, inject)` 接收的是宿主侧 callable，不接收 manifest/install_path/entry_point，不能直接表达跨进程加载。本轮不强行套用该端口；runtime 状态先与 `FiberState` 对齐，后续如需接入 Kernel Fiber，再补薄适配层。

### 1.3 DSH 边车

不做。既有决策的触发条件为：DSH ≥1.0 且公共插件 API 冻结 ≥2 个季度、出现 ≥5 个只能用 DSH 插件表达的目标插件、出现 ≥10 个一致的用户 issue，或 DSH 提供成熟沙箱/权限模型。本轮没有任何证据表明触发条件满足。R83 只交付 Sage 原生 Python 插件进程外宿主；DSH 施工图继续备而不用。

---

## 2. 核心语义

### 2.1 数据库状态与 runtime 状态分离

- `plugins.status` 仍是 R82 的 `installed/enabled/disabled/uninstalled`。
- `enable` **不执行代码**。应用启动、后端重启、安装、恢复、启用都不会自动拉起旧插件进程。
- 只有用户显式调用 runtime start（设置页按钮或 REST）才启动子进程。
- runtime start 只允许 `enabled` 记录；并以 DB 中 `manifest/config/install_path` 为权威输入。若旧记录 manifest 为空，允许回退读取 `install_path/plugin.json`，但插件名必须与记录一致。
- `disable`、`uninstall` 前必须先停止 runtime；配置更新前也停止 runtime，避免继续以旧配置执行。配置保存后需显式重新 start。
- runtime 状态只存内存，不跨后端重启恢复；后端重启后统一回到 `pending`，符合“默认拒绝、不装了就先跑”的信任原则。

### 2.2 第一垂直切片的插件契约

只加载 manifest 中 `type="tool"` 且有 `entry_point` 的能力。`skill/hook/mcp_server/command` 以及无 entry point 的 tool 会被列为不支持；若插件没有任何可托管 tool，start 返回明确错误，不启动空进程。

支持的 `entry_point` 形式：

1. **首选**：`module.submodule:function_or_class`
2. **兼容**：`module.submodule.function_or_class`
3. **兼容**：`module.submodule`，且模块定义 `run`、`execute`、`handler` 或 `main` 之一

目标解析规则：

- 函数：直接调用；
- 类：无参实例化，优先调用 `execute(...)`，其次调用实例本身；
- 普通对象：优先 `execute(...)`，其次要求对象可调用；
- 返回 awaitable 时，worker 用独立事件循环等待结果。

调用参数规则：

- 目标签名只有一个位置参数，且参数名为 `args/arguments/data/input/params/payload/request` 时，传入完整 arguments dict；
- 单参数目标且 arguments 恰好只有一个同名键时，传入该键的值；
- 其余情况按 `**arguments` 展开；
- 结果必须是 JSON 可序列化值。

配置注入：

- worker 在导入插件模块前设置 `SAGE_PLUGIN_NAME`、`SAGE_PLUGIN_ROOT`、`SAGE_PLUGIN_CONFIG_JSON`；
- 若模块或实例提供 `configure(config)`，worker 在加载后调用一次；
- 配置更新不做热重载，宿主停进程后由用户重新 start。

### 2.3 进程与协议

宿主用当前 Python 解释器启动：

```text
<sys.executable> -u <backend/plugins/host_worker.py>
```

进程约束：

- `cwd = install_path`；
- `shell=False`，不经 shell；
- stdin/stdout 为二进制管道，stderr 独立管道；
- stdout 读线程把完整行放入 Queue，宿主按 deadline 等待，避免 Windows 同步 readline 永久阻塞；
- 每个 worker 同时只允许一个 in-flight 请求，避免响应串扰；
- worker 保存原始 stdout buffer 作为协议通道，再把 `sys.stdout` 重定向到 stderr，插件 `print()` 不污染协议；
- stderr 读线程保留有界尾部（默认 8000 字符），状态接口可读。

协议为一行一个 JSON 对象的 JSON-RPC 2.0：

| method | params | result |
| --- | --- | --- |
| `initialize` | `protocol_version`、插件名/根目录、config、capabilities、limits | 已加载能力、pid、限额实际生效情况 |
| `ping` | `{}` | pid、插件名 |
| `tools/list` | `{}` | 已加载 tool 列表 |
| `tools/call` | `name`、`arguments` | 插件返回值 |
| `shutdown` | `{}` | `{}`，随后 worker 退出 |

默认限额：

| 限额 | 默认值 | 行为 |
| --- | ---: | --- |
| 启动/握手超时 | 10s | 终止进程，状态 `failed` |
| 单次调用超时 | 30s | 终止进程，状态 `failed`，不自动重启 |
| 关闭超时 | 3s | 先优雅 shutdown，超时 terminate，最后 kill/进程树清理 |
| 单条消息上限 | 1 MiB | 请求在发送前拒绝；过大的结果返回结构化错误且 worker 可继续存活；协议行超限则终止 |
| 内存上限 | 512 MiB | Windows 优先 Job Object；POSIX 由 worker 在导入插件前设置 rlimit |
| CPU 累计上限 | 300s | POSIX rlimit；Windows 第一版以墙钟请求超时为主 |
| stderr 尾部 | 8000 字符 | 超出丢弃旧内容 |

### 2.4 环境与安全边界

宿主不继承完整环境，只保留操作系统/Python 运行所需白名单（路径、临时目录、语言、证书路径等），并覆盖：

- `PYTHONPATH=<plugin root>`
- `PYTHONIOENCODING=utf-8`
- `PYTHONUNBUFFERED=1`
- `PYTHONDONTWRITEBYTECODE=1`
- `SAGE_PLUGIN_NAME`、`SAGE_PLUGIN_ROOT`

父进程中的 API key、token 等业务秘密不会因默认继承而进入插件进程。插件 config 只通过 initialize 报文传入。

必须明示：**子进程是崩溃隔离，不是安全沙箱。** 插件仍以当前 OS 用户身份运行，可以访问该用户能访问的文件与网络；manifest 权限在 R82 是展示与安装确认语义，R83 不宣称已做内核级文件/网络权限强制。显式 start 是本地已认证用户对本机代码的运行确认。未来若要托管不可信第三方代码，需另行引入 OS 沙箱、签名/完整性校验与权限 broker。

### 2.5 失败、停止与能力注册

- 启动成功后，宿主把每个 tool 代理注册到全局 `CapabilityRegistry`；代理 handler 接收 arguments dict 并转发给 worker。
- 若能力名已被其他插件注册，start 失败且不留下半注册状态。
- 显式 stop、调用超时、协议损坏、进程退出都会注销该插件全部代理。
- 普通插件业务异常返回结构化错误，但 worker 保持 `active`；只有超时、崩溃、协议损坏与加载失败才进入 `failed`。
- 宿主不自动重启崩溃插件；`restart` 必须是显式操作，并累计 `restart_count`。
- FastAPI lifespan shutdown 调用 `shutdown_plugin_hosts()`，顺序对齐现有 MCP client pool 的关闭方式。

---

## 3. REST 与 UI

### 3.1 REST

在既有 `/api/v1/plugins` router 上新增，所有端点继续要求本地鉴权：

| 端点 | 说明 |
| --- | --- |
| `GET /plugins/{name}/runtime` | 读取 runtime 状态 |
| `POST /plugins/{name}/runtime/start` | 显式启动已 enabled 插件 |
| `POST /plugins/{name}/runtime/stop` | 幂等停止 |
| `POST /plugins/{name}/runtime/restart` | 显式重启 |
| `POST /plugins/{name}/runtime/invoke` | `{capability, arguments}`，调用一个已加载 tool |

插件列表与详情响应新增 `runtime` 字段，保持旧字段不变。runtime 操作在线程池执行同步进程监督逻辑，避免阻塞 FastAPI 事件循环。

审计事件新增：`runtime_started`、`runtime_stopped`、`runtime_restarted`、`runtime_failed`、`runtime_invoked`、`runtime_invoke_failed`。事件 detail 只记能力名、pid、错误码等有界信息，不记录 arguments/config 内容。

错误映射：

- 插件不存在：404
- DB 状态不允许 start、runtime 未运行、能力冲突：409
- manifest 无可托管能力、entry point 不合法、调用参数不合法：422
- worker 崩溃/协议损坏/插件抛错：502
- 启动或调用超时：504

### 3.2 设置页

- 插件卡同时显示 DB 状态与 runtime 状态，避免再把 enabled 误解为正在运行。
- enabled 插件可 Start；running 插件可 Stop/Restart。
- 详情区展示 pid、重启次数、已加载能力、最近错误与 stderr 尾部。
- 详情区提供最小调用器：选择 tool、编辑 JSON arguments、执行并展示 JSON 结果/错误。
- 边界文案改为：启用记录不会自动运行代码；Start 会以当前 OS 用户在独立子进程中加载插件，进程隔离不是安全沙箱；保存配置会先停止 runtime。
- manifest 模板的 `entry_point` 改为首选形式 `tools.example_tool:run`。

前端 runtime 详情抽为 `PluginRuntimePanel.tsx`，避免 `PluginsTab.tsx` 超过架构行数上限。

---

## 4. 文件计划

### 新增

- `backend/plugins/host.py`
- `backend/plugins/host_process.py`
- `backend/plugins/host_worker.py`
- `backend/tests/unit/test_plugin_host.py`
- `src/pages/settings/PluginRuntimePanel.tsx`
- `docs/plans/2026-10-21_out-of-process-plugin-host-r83.md`（本 spec 入仓版）

### 修改

- `backend/plugins/lifecycle.py`：补公开 `record_event` 审计入口。
- `backend/plugins/__init__.py`：导出宿主公共类型与 registry。
- `backend/api/plugin_routes.py`：runtime 端点、响应字段、停机联动与审计。
- `backend/main.py`：lifespan shutdown 时停止全部插件进程；同步更新架构 baseline 的单文件行数。
- `architecture-baseline.json`：仅把 `backend/main.py` 的 baseline 从 1275 更新到 1283（新增 8 行 shutdown 接线）。
- `backend/tests/api/test_plugin_routes.py`：runtime REST 契约与联动测试。
- `src/shared/api/pluginClient.ts`：runtime 类型、反序列化与五组调用。
- `src/shared/api/__tests__/pluginClient.test.ts`
- `src/pages/settings/PluginsTab.tsx`
- `src/pages/settings/__tests__/PluginsTab.test.tsx`
- `docs/plans/plugin-evo-index.md`：R83 勾账，下一轮指向 R84。

---

## 5. 验收与测试矩阵

### 宿主单测

1. 函数型、单 dict 参数型、类/async `execute` 三种入口都可加载与调用。
2. `CapabilityRegistry` 代理可调用；stop 后代理消失。
3. 未 enabled、无可托管能力、坏 entry point、导入失败均 fail-closed。
4. 插件 `print()` 不破坏协议；父进程秘密环境变量不可见；cwd 与 `PYTHONPATH` 指向插件根。
5. 插件业务异常不杀 worker；崩溃（`os._exit`）与超时使 runtime 进入 `failed`，宿主进程保持可用且代理被注销。
6. 超大结果返回结构化错误；restart 累计次数并生成新 pid。

### REST 测试

1. 列表/详情带默认 `pending` runtime，不自动执行 enabled 插件。
2. start/invoke/stop/restart 真实走子进程并回显结果。
3. 未 enabled start 返回 409；未运行 invoke 返回 409。
4. disable/uninstall/config update 会先停止正在运行的 worker。
5. runtime 操作写入审计事件且不记录参数内容。

### 前端测试

1. client 的 runtime 路径、payload 与 snake_case 反序列化正确。
2. 设置页显示 DB 状态与 runtime 状态两套语义。
3. Start/Stop/Restart 按钮按状态出现/禁用并调用对应 client。
4. 调用器可提交 JSON arguments，展示结果，并对非法 JSON 本地拦截。

### 门禁

- Python 定向 pytest、Ruff、import-linter、architecture-check。
- 定向 Vitest、TypeScript/生产 build。
- 提交后等待 PR #2206 的 CI 与 E2E 全绿，更新总账与 PR 评论。

### 本地实测记录（2026-10-21）

- 后端相关 7 个测试文件共 **111 passed**：新增宿主单测 4 例、插件 REST 11 例，其余为 lifecycle/manifest/domain/kernel 既有覆盖。
- 前端定向 **19 passed**：`pluginClient` 10 例 + `PluginsTab` 9 例。
- Ruff、py38 兼容脚本、静默异常 ratchet、TypeScript、定向 ESLint、Vite/Electron 生产 build、architecture-check 均通过。
- Windows 实测中 worker 成功挂载 Job Object，runtime 状态报告 `memory_limit_enforced=true`；POSIX worker 在本地 Linux 冒烟中报告 memory/CPU rlimit 均已生效。
- import-linter 在当前远端 Python 环境未安装，留待 PR CI 的 `sage-backend` 环境复核。

---

## 6. 明确不做

- 不把进程外 tool 自动暴露给 LLM `ToolRegistry`；本轮只接既有 `CapabilityRegistry` 与设置页/REST 调用器。接入 Agent 工具面需要单独处理 schema、风险分级、审批与预算，不能顺带绕过工具治理。
- 不执行 `skill/hook/mcp_server/command`；MCP server 继续走既有 MCP client/pool，其他类型待各自契约成熟。
- 不做插件市场、下载、解压、签名与完整性校验。
- 不做自动重启、崩溃退避、多 worker 并发调用与流式响应。
- 不做 Node/DSH 边车，不实现 Cordis ABI 兼容。
- 不宣称 OS 安全沙箱与 manifest 权限强制。
