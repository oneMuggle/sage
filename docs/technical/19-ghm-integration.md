# 19. ghm 外部计算集成

> 让 sage 的 LLM Agent 通过工具调用机制调用 ghm（激波管/风洞计算器）的 CLI 计算能力。
> 实施日期：2026-06-07 | 关联六边形架构：[18-hexagonal.md](./18-hexagonal.md)

---

## 1. 概述

**ghm** 是一个独立的 Python 项目（路径 `/home/fz/project/ghm`），提供激波管 / 风洞 / 喷管 / 平衡气体 / 等离子体等物理计算能力。它以 `python -m ghm core <sub> --json` 的 CLI 形式对外暴露能力，未来可打包为独立 exe。

sage 在 hex 架构基础上新增一个 `ComputePort`，通过 `SubprocessComputeAdapter` 调 ghm CLI，再用 `ComputeToolAdapter` 把每个 ghm operation 包装成 LLM tool，合并到现有 `ToolPort` 工具列表。LLM 在对话中可以主动选择并调用这些计算。

---

## 2. 架构层次

```
┌─────────────────────────────────────────────────────────────┐
│ Chat 前端 — 用户："算 mach 6.5 在 1000Pa/250K 的激波后参数"     │
└───────────────────────┬─────────────────────────────────────┘
                        │ POST /api/v1/chat
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ ChatService.run_turn (application 层)                        │
│   ├── llm.chat(messages, tools=[compute_shock, ...])         │
│   ├── tools.execute("compute_shock", args)                   │
│   └── 把 ToolResult 作为 TOOL message 加到会话                │
└───────────────────────┬─────────────────────────────────────┘
                        │ ToolPort.execute(name, args)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ ComputeToolAdapter (adapter 层) — 桥接 ToolPort ↔ ComputePort │
│   if name in compute_names:                                  │
│       result = await compute.execute(ComputeRequest(...))    │
│       return _to_tool_result(result)                         │
│   else:                                                       │
│       return await inner.execute(name, args)                 │
└───────────────────────┬─────────────────────────────────────┘
                        │ ComputePort.execute(req)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ SubprocessComputeAdapter (本期实现)                          │
│   1) ExecutableResolver.resolve() 按优先级解析入口            │
│   2) argv = resolver前缀 + cli_subcommand + flags + --json   │
│   3) asyncio.create_subprocess_exec(*argv)                    │
│   4) wait_for(communicate(), timeout=N)                       │
│   5) json.loads(stdout) → ComputeResult                       │
└───────────────────────┬─────────────────────────────────────┘
                        │ stdout (JSON)
                        ▼
                 ghm CLI 真实计算
```

---

## 3. 关键文件

| 路径 | 用途 |
|---|---|
| `backend/domain/compute.py` | 领域模型：`ComputeSpec / Request / Result / Error / ErrorType` |
| `backend/ports/compute.py` | `ComputePort` Protocol（`list_operations` + `execute`）|
| `backend/adapters/out/compute/_resolver.py` | `ExecutableResolver`：按优先级解析可执行文件 |
| `backend/adapters/out/compute/subprocess_adapter.py` | `SubprocessComputeAdapter`：asyncio subprocess + JSON 解析 + 错误映射 |
| `backend/adapters/out/compute/http_adapter.py` | `HttpComputeAdapter`：**预留空壳**，未来实现 |
| `backend/adapters/out/compute/mock_adapter.py` | 测试用内存实现 |
| `backend/adapters/out/tool/compute_tool_adapter.py` | `ComputeToolAdapter`：把 ComputePort 桥接为 ToolPort |
| `backend/config/ghm.yaml` | ghm 入口路径 + 6 个 operation 声明 |
| `backend/main.py:_build_compute_adapter` | 装配工厂（按 yaml.adapter 字段选 subprocess/http）|
| `backend/main.py:_build_chat_service` | 接入：若 ghm 启用则用 ComputeToolAdapter 包装 |

---

## 4. ExecutableResolver 路径解析

为兼容多种部署形态（开发期 conda、用户期独立 exe、未来 Tauri sidecar），引入路径解析器，按优先级查找 ghm 入口：

| 优先级 | 来源 | yaml 字段 | 适用场景 |
|---|---|---|---|
| 1 | 环境变量 | `GHM_EXECUTABLE_PATH` | 临时覆盖（调试 / CI） |
| 2 | yaml 显式路径 | `subprocess.executable_path` | 打包后的用户机器 |
| 3 | Tauri sidecar | `subprocess.sidecar_name` | **本期预留**，未来桌面分发 |
| 4 | conda python -m | `subprocess.python_module` | **当前开发** |
| 5 | PATH 查找 | `subprocess.path_lookup_name` | 系统装的 ghm-cli |
| ❌ | 全部失败 → `ExecutableNotFoundError` | — | 工具不注册到 LLM |

**任一字段为 `null` 时跳过该级别**。解析结果在 `ExecutableResolver` 实例内缓存，多次 `resolve()` 不重复查询文件系统。

---

## 5. 部署形态配置示例

### 5.1 当前开发（conda python -m）

```yaml
# backend/config/ghm.yaml
ghm:
  enabled: true
  adapter: subprocess
  subprocess:
    executable_path: null
    sidecar_name: null
    python_module:
      python: "/home/fz/anaconda3/envs/ghm/bin/python"
      working_dir: "/home/fz/project/ghm"
      module: "ghm"
    path_lookup_name: "ghm-cli"
```

### 5.2 ghm 打包为独立 exe 后（用户期）

```yaml
ghm:
  enabled: true
  adapter: subprocess
  subprocess:
    executable_path: "C:/Program Files/ghm/ghm-cli.exe"   # 仅改这一行
    sidecar_name: null
    python_module: null         # 不再需要
    path_lookup_name: "ghm-cli"
```

或环境变量临时覆盖：

```bash
export GHM_EXECUTABLE_PATH="/usr/local/bin/ghm-cli"
```

### 5.3 关闭 ghm 集成

```yaml
ghm:
  enabled: false   # 总开关；ComputePort 不装配，工具不暴露
```

### 5.4 切换到 HTTP 模式（**未来**）

```yaml
ghm:
  enabled: true
  adapter: http          # 切换到 HTTP（本期会抛 NotImplementedError）
  http:
    base_url: "http://127.0.0.1:8000"
    timeout_seconds: 30
```

---

## 6. operations 声明结构

每个 operation 是 yaml 中的一个条目，subprocess 与 http 模式共享 schema：

```yaml
operations:
  - name: compute_shock                         # LLM 看到的工具名
    cli_subcommand: ["core", "shock"]           # subprocess 模式拼到 argv
    http_endpoint: "/api/shock/calculate"       # http 模式（预留）
    description: "正激波计算 — 输入..."          # 喂给 LLM 用于选择
    params_schema:                              # JSON Schema，透传为 LLM tool parameters
      type: object
      required: [mach, gamma, p1, t1]
      properties:
        mach:  {type: number, description: "上游马赫数"}
        gamma: {type: number, default: 1.4}
        p1:    {type: number, description: "上游压力 (Pa)"}
        t1:    {type: number, description: "上游温度 (K)"}
```

**MVP 已接入的 6 个 operation**：

| 工具名 | 物理意义 | 必填参数 |
|---|---|---|
| `compute_shock` | 理想气体正激波 | mach / gamma / p1 / t1 |
| `compute_equilibrium` | 平衡气体性质 | species / p / t |
| `compute_heatflux` | 驻点热流（Fay-Riddell）| rho / u / t |
| `compute_nozzle` | 准一维等熵喷管面积比 | gamma / p0 / t0 / area_ratio |
| `compute_plasma` | 等离子体频率（经验公式）| p_atm / t |
| `compute_eqcomposition` | 平衡组分 | gas / mode / t |

---

## 7. 参数映射规则

`SubprocessComputeAdapter._params_to_args` 把 `dict` 翻译为 CLI flag：

| 输入 | 输出 |
|---|---|
| `{"mach": 6.5}` | `["--mach", "6.5"]` |
| `{"area_ratio": 2.5}` | `["--area-ratio", "2.5"]` （snake_case → kebab-case）|
| `{"verbose": True}` | `["--verbose"]` （boolean True 仅 flag）|
| `{"verbose": False}` | `[]` （boolean False 跳过）|
| `{"config": ["k=v", "k2=v2"]}` | `["--config", "k=v", "k2=v2"]` （列表展开）|

---

## 8. 错误处理

| 场景 | `ComputeErrorType` | 触发条件 |
|---|---|---|
| LLM 调未声明的 operation | `OPERATION_NOT_FOUND` | yaml 未声明 |
| ghm CLI argparse 错误 | `INVALID_PARAMS` | 退出码 = 2 |
| 子进程退出非零 | `PROCESS_FAILED` | 退出码 ∈ {1, 3, 其他} |
| 子进程超时 | `TIMEOUT` | yaml.timeout_seconds 或 ComputeRequest.timeout_ms |
| stdout 不是合法 JSON | `OUTPUT_PARSE_ERROR` | exit_code=0 但 JSON 解析失败 |
| ExecutableResolver 全失败 | `INTERNAL_ERROR` | `details.tried` 列出所有尝试 |
| spawn 异常（如 OSError）| `INTERNAL_ERROR` | 未预期异常自动收敛，不冒泡 |

**所有错误都被 `ComputePort.execute` 统一收敛为 `ComputeResult(success=False, error=...)`**，永不抛异常给 ChatService。

---

## 9. 装配点（main.py）

```python
def _build_chat_service() -> ChatService:
    inner_tools = InprocToolAdapter()
    compute = _build_compute_adapter()         # 按 ghm.yaml 装配 ComputePort
    if compute is not None:
        tools = ComputeToolAdapter(compute=compute, inner=inner_tools)
    else:
        tools = inner_tools                    # ghm 关闭 → 回退到原行为
    return ChatService(..., tools=tools, ...)
```

- 若 `backend/config/ghm.yaml` 不存在 / `enabled: false` → `_build_compute_adapter` 返回 `None` → ChatService 用纯 `InprocToolAdapter`（向后兼容旧部署）。
- 若启用 → 用 `ComputeToolAdapter` 包装：`list_tools()` 返回 inner 工具 + 计算工具，`execute(name, args)` 按名路由。

---

## 10. 测试覆盖

| 文件 | 单测数 | 覆盖 |
|---|---|---|
| `tests/unit/test_compute_domain.py` | 14 | dataclass / Protocol 一致性 |
| `tests/unit/test_compute_resolver.py` | 14 | 4 条解析路径 + 优先级 + 缓存 + 失败 |
| `tests/unit/test_subprocess_compute_adapter.py` | 24 | 6 个错误分支 + 成功路径 + argv 拼装 |
| `tests/unit/test_http_compute_adapter.py` | 3 | 空壳行为 + list_operations 一致 |
| `tests/unit/test_compute_tool_adapter.py` | 12 | 路由分发 + 翻译 + 异常降级 |
| `tests/integration/test_ghm_compute_e2e.py` | 2 | 端到端真打 ghm |
| **合计** | **69** | — |

**E2E 跳过条件**：`@requires_ghm`，仅在 `GHM_PYTHON` 指向的 conda python 可执行 + `GHM_PROJECT_DIR` 存在 + `API_MODE=hex` 时跑。CI 上可设 `GHM_TEST_DISABLED=1` 强制跳过。

---

## 11. 与现有架构契合

- ✅ 完全遵循 hex 六层结构（domain → ports → adapters → application → api）
- ✅ `domain/compute.py` 零外部依赖（仅 stdlib）
- ✅ import-linter `hexagonal-architecture` 契约 KEPT（150 文件 / 250 依赖）
- ✅ 复用现有可观测性基础设施（MetricPort `sage_tool_invocations_total` 自动计数 / EventPort `tool_invoked` 事件）
- ✅ 不影响 legacy 路径（仅 hex 路径生效）
- ✅ 不影响双分支：`enabled: false` 即可关闭整个 compute 能力
- ✅ 无新增 PyPI 依赖（asyncio / subprocess / shutil 是 stdlib，pyyaml 已有）

---

## 12. 后续演进路径

| 演进项 | 触发条件 | 改动量 |
|---|---|---|
| **接入 ghm-cli.exe 真分发** | ghm 项目方提供 `ghm-cli.spec` 并出产物 | 改 `ghm.yaml: executable_path` 一行 |
| **启用 Tauri sidecar** | 桌面应用分发给非开发用户 | 改 `tauri.conf.json` + 改 `ghm.yaml: sidecar_name` |
| **HttpComputeAdapter 真实现** | subprocess 冷启动延迟 > 2s 影响 chat 体验 | 补完 `http_adapter.py`（约 200 行）+ 启动时拉起 `ghm gui web` |
| **常驻 worker（高频调用优化）** | HTTP 模式仍不够快 | ghm 项目侧新增 stdin loop 模式 |
| **接入 nozzle-contour / exptube-range** | core 6 项稳定 ≥ 2 周 | 加 operation 到 yaml + 处理文件 I/O 参数 |

---

_本文档版本：v1.0（2026-06-07 首次实施）_
