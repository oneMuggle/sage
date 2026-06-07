# Sage Agent 调用 ghm 计算能力 — 实施方案

> 计划日期：2026-06-07
> 状态：草案，等待用户确认
> 负责人：—
> 关联代码：`backend/`（hex 架构）

---

## 1. 背景与目标

### 1.1 背景

- **sage** 是基于 Tauri + FastAPI sidecar 的桌面 AI 助手，hex 架构（PG2 已完成），LLM Agent 走 `ChatService.run_turn` 单轮调用 + ReAct 工具循环（计划 P3 落地）。
- **ghm**（`/home/fz/project/ghm`）是激波管/风洞计算器，提供完整 `python -m ghm core <subcmd> --json` CLI 接口（10 个真实现子命令）+ FastAPI Web 层（15 router，部分仍 stub）。
- 两个项目目前都在本机 `/home/fz/project/` 下开发，独立 conda 环境（`sage-backend` / `ghm`）。

### 1.2 目标

让 sage 中的 **LLM Agent** 在对话中能够通过工具调用机制（function calling / ReAct）主动选择并调用 ghm 提供的物理/气动计算能力，并将计算结果纳入对话上下文。

### 1.3 非目标（明确不做）

- 不在本期把 ghm 打进 Tauri 安装包（分发问题留待后续）。
- 不复刻 ghm 的 GUI 计算面板到 sage（用户已选"LLM Agent"路径）。
- 不修改 ghm 项目代码（接口已具备，按现状对接即可）。
- 不接入 ghm 中尚未实现的 router stub（仅接 CLI 已验证为真实现的子命令）。

### 1.4 用户已拍板的关键决策（2026-06-07）

| 决策 | 选择 |
|---|---|
| Agent 类型 | **LLM Agent**（chat 内通过 tool call 主动调用） |
| 进程关系 | **subprocess 调用 CLI**（`python -m ghm core <sub> --json`） |
| MVP 范围 | **6 个 core 通用计算**（shock / equilibrium / heatflux / nozzle / plasma / eqcomposition） |
| 分发形态 | **本机开发**（暂不考虑打包问题） |

---

## 2. 涉及的文件与模块

### 2.1 新增（共 11 个文件）

| 路径 | 用途 | 行数估计 |
|---|---|---|
| `backend/domain/compute.py` | 领域模型：`ComputeSpec / ComputeRequest / ComputeResult / ComputeError`（pure dataclass，遵守 domain 层无外部依赖约束） | ~80 |
| `backend/ports/compute.py` | `ComputePort` Protocol：`list_operations() / execute()` | ~50 |
| `backend/adapters/out/compute/__init__.py` | 子包初始化 | 5 |
| `backend/adapters/out/compute/subprocess_adapter.py` | `SubprocessComputeAdapter`：`asyncio.create_subprocess_exec` 包装，白名单 + 超时 + JSON 解析 | ~180 |
| `backend/adapters/out/compute/mock_adapter.py` | `MockComputeAdapter`：测试用预设响应 | ~60 |
| `backend/adapters/out/tool/compute_tool_adapter.py` | `ComputeToolAdapter`：把 `ComputePort` 暴露的 operations 包装为 `ToolSpec`，与现有 `InprocToolAdapter` 组合（实现 `ToolPort`） | ~140 |
| `backend/config/ghm.yaml` | ghm CLI 配置：python 可执行路径、ghm 项目路径、白名单子命令、各子命令的 JSON Schema | ~120 |
| `tests/unit/domain/test_compute.py` | 领域模型单测 | ~80 |
| `tests/unit/adapters/test_subprocess_compute_adapter.py` | subprocess adapter 单测（mock `asyncio.create_subprocess_exec`） | ~180 |
| `tests/unit/adapters/test_compute_tool_adapter.py` | tool adapter 单测（mock ComputePort） | ~150 |
| `tests/integration/test_ghm_compute_e2e.py` | E2E：真实调用 ghm（带 `@pytest.mark.requires_ghm` 标记，CI 可跳过） | ~120 |

### 2.2 修改（共 4 个文件）

| 路径 | 改动 |
|---|---|
| `backend/main.py` | `_build_chat_service()` 中装配 `SubprocessComputeAdapter` 并通过 `ComputeToolAdapter` 包装注入 ToolPort | ~20 行新增 |
| `backend/requirements.txt` | 无新增依赖（asyncio / subprocess 都是 stdlib，pyyaml 已有） | 0 |
| `pyproject.toml` | `[tool.importlinter]` 增加 `compute` 端口/适配器层的允许导入规则 | ~5 行 |
| `docs/06-tools.md` | 在工具清单中追加 6 个 ghm 工具的说明（compute_shock / compute_equilibrium / ...） | ~50 行 |

### 2.3 配置文件示例

`backend/config/ghm.yaml`：
```yaml
ghm:
  enabled: true
  python: "/home/fz/anaconda3/envs/ghm/bin/python"
  project_dir: "/home/fz/project/ghm"
  timeout_seconds: 30
  operations:
    - name: compute_shock
      cli_args: ["core", "shock"]
      description: "理想气体正激波计算（输入马赫数、比热比、上游压力/温度）"
      params_schema:
        type: object
        required: [mach, gamma, p1, t1]
        properties:
          mach: {type: number, description: "上游马赫数"}
          gamma: {type: number, default: 1.4, description: "比热比"}
          p1:   {type: number, description: "上游压力 Pa"}
          t1:   {type: number, description: "上游温度 K"}
    - name: compute_equilibrium
      cli_args: ["core", "equilibrium"]
      description: "平衡气体性质（目前仅 species=air 的多项式近似）"
      params_schema:
        type: object
        required: [species, p, t]
        properties:
          species: {type: string, enum: ["air"]}
          p: {type: number, description: "压力 Pa"}
          t: {type: number, description: "温度 K"}
    # ... heatflux / nozzle / plasma / eqcomposition 同结构
```

---

## 3. 技术方案

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│ 前端 Chat 界面                                                │
│   用户："帮我算一下马赫数 6.5 在 P=1000Pa T=250K 时的激波后参数" │
└───────────────────────┬─────────────────────────────────────┘
                        │ POST /api/v1/chat
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ ChatService.run_turn (application 层)                        │
│   ├── llm.chat(messages, tools=[compute_shock, ...])         │
│   │      ↑ LLM 返回 tool_call: compute_shock(mach=6.5, ...)  │
│   ├── tools.execute_tool(name="compute_shock", args)         │
│   └── llm.chat(messages + tool_result)                       │
└───────────────────────┬─────────────────────────────────────┘
                        │ ToolPort.execute_tool
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ ComputeToolAdapter (adapter 层) — 桥接 ToolPort ↔ ComputePort │
│   把 ToolCall(name=compute_shock, args=...) 翻译为            │
│   ComputeRequest(operation="compute_shock", params=...)       │
└───────────────────────┬─────────────────────────────────────┘
                        │ ComputePort.execute
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ SubprocessComputeAdapter (adapter 层)                        │
│   1. 查 ghm.yaml，获取该 operation 的 cli_args               │
│   2. asyncio.create_subprocess_exec(                         │
│        "/home/fz/anaconda3/envs/ghm/bin/python",             │
│        "-m", "ghm", "core", "shock",                         │
│        "--mach", "6.5", "--p1", "1000", ...,                 │
│        "--json")                                              │
│   3. 等待 stdout, 30s timeout                                │
│   4. json.loads(stdout) → ComputeResult(success, output)     │
└───────────────────────┬─────────────────────────────────────┘
                        │ stdout (JSON)
                        ▼
                  ghm CLI 计算
```

### 3.2 端口接口设计

```python
# backend/domain/compute.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

@dataclass(frozen=True)
class ComputeSpec:
    """一个可调用的计算项的元数据。"""
    name: str
    description: str
    params_schema: dict[str, Any]   # JSON Schema，喂给 LLM 做参数校验

@dataclass(frozen=True)
class ComputeRequest:
    """计算调用入参。"""
    operation: str
    params: dict[str, Any]
    timeout_ms: int | None = None
    request_id: str | None = None   # 与 chat request_id 关联便于追溯

class ComputeErrorType(str, Enum):
    OPERATION_NOT_FOUND = "operation_not_found"
    INVALID_PARAMS = "invalid_params"
    TIMEOUT = "timeout"
    PROCESS_FAILED = "process_failed"     # 非零退出码
    OUTPUT_PARSE_ERROR = "output_parse_error"
    INTERNAL_ERROR = "internal_error"

@dataclass(frozen=True)
class ComputeError:
    type: ComputeErrorType
    message: str
    details: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ComputeResult:
    success: bool
    output: dict[str, Any] | None = None     # 解析后的 JSON 结果
    raw_stdout: str | None = None             # 原始 stdout，便于调试
    raw_stderr: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    error: ComputeError | None = None
```

```python
# backend/ports/compute.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from backend.domain.compute import ComputeRequest, ComputeResult, ComputeSpec

@runtime_checkable
class ComputePort(Protocol):
    """外部计算能力的端口抽象。"""

    def list_operations(self) -> list[ComputeSpec]:
        """列出当前可用的计算操作（用于注册到 ToolRegistry）。"""
        ...

    async def execute(self, req: ComputeRequest) -> ComputeResult:
        """执行一次计算。永不抛异常，失败时返回 success=False。"""
        ...
```

### 3.3 SubprocessComputeAdapter 关键设计

- **白名单子命令**：仅允许 `ghm.yaml` 中显式声明的 operation，**禁止任意命令拼接**（与 `tools/terminal.py` 的黑名单不同，这里走严格白名单）。
- **参数注入方式**：根据 `params_schema` 中的字段类型，按 `--{key} {value}` 拼到 argv（boolean 字段映射为 `--{key}` flag）。复杂参数（如 `--config k=v` 数组形式）通过 schema 的 `x-cli-style` 扩展字段标记。
- **超时**：`asyncio.wait_for(proc.communicate(), timeout=N)`，超时即 `proc.kill()` + `wait()`，返回 `ComputeErrorType.TIMEOUT`。
- **JSON 解析**：使用 `--json` 全局开关，保证 stdout 是合法 JSON；失败时回退用 `raw_stdout` + `OUTPUT_PARSE_ERROR`。
- **退出码语义**：参考 ghm 的 `__main__.py:8-12`，`0 / 1 / 2 / 3` 分别映射到 success / `PROCESS_FAILED` / `INVALID_PARAMS` / `PROCESS_FAILED`（缺依赖）。
- **观测埋点**：每次 execute 写一条 `sage_tool_invocations_total{tool="compute_shock"}` 计数 + `sage_tool_duration_seconds` 直方图，复用 `MetricPort`。
- **审计**：通过 `EventPort.emit("compute.execute", {operation, params, exit_code, duration_ms})` 写 audit jsonl。

### 3.4 ComputeToolAdapter 设计（关键桥接层）

```python
# backend/adapters/out/tool/compute_tool_adapter.py
class ComputeToolAdapter:
    """把 ComputePort 暴露的 operations 包装为 ToolPort 接口。
    
    与 InprocToolAdapter 通过 CompositeToolAdapter 组合，
    或直接替换为本 Adapter 并把 InprocToolAdapter 注入它作为 fallback。
    """
    def __init__(self, compute: ComputePort, inner: ToolPort):
        self._compute = compute
        self._inner = inner   # 9 个内置工具仍走原路径
        self._compute_names = {s.name for s in compute.list_operations()}

    def list_tools(self) -> list[ToolSpec]:
        # 内置工具 + 把 ComputeSpec 翻译为 ToolSpec
        compute_tools = [self._to_tool_spec(s) for s in self._compute.list_operations()]
        return self._inner.list_tools() + compute_tools

    async def execute_tool(self, call: ToolCall) -> ToolResult:
        if call.name in self._compute_names:
            result = await self._compute.execute(
                ComputeRequest(operation=call.name, params=call.arguments)
            )
            return self._to_tool_result(result)
        return await self._inner.execute_tool(call)
```

### 3.5 装配点（`main.py` 改动）

```python
# backend/main.py - _build_chat_service
def _build_chat_service() -> ChatService:
    # 1. 新增：装配 ComputePort
    from backend.adapters.out.compute.subprocess_adapter import SubprocessComputeAdapter
    compute = SubprocessComputeAdapter(config_path="backend/config/ghm.yaml")
    
    # 2. 把 ComputePort 通过 ComputeToolAdapter 包装成增强版 ToolPort
    from backend.adapters.out.tool.compute_tool_adapter import ComputeToolAdapter
    tools = ComputeToolAdapter(
        compute=compute,
        inner=InprocToolAdapter(),
    )
    
    return ChatService(
        llm=HttpxLLMAdapter(),
        tools=tools,             # ← 从 InprocToolAdapter 升级为 ComputeToolAdapter
        skills=None,
        storage=SqliteStorageAdapter(),
        metrics=PrometheusMetricAdapter(),
        events=FileEventAdapter(),
    )
```

### 3.6 ReAct 多轮兼容性说明

- hex 路径当前 `ChatService.run_turn` 是**单轮**（`chat_service.py:128-152` 注释明确"PG2.9 阶段只做单轮"），P3 才会落地多轮。
- 但**单轮模式下 LLM 仍能发起 tool_call**（OpenAI/Claude 协议都支持），只是不会自动二次调用 LLM 总结。
- 因此：MVP 阶段在 hex 下，工具会被调用、结果会返回，但**前端要明确展示 "tool_call + tool_result"**，由 LLM 等下一轮用户消息再 follow-up。
- 多轮自动跟进等待 P3 ReAct 落地后即自动可用，**本方案不阻塞**。

### 3.7 配置驱动 vs 硬编码的取舍

**选择配置驱动（YAML）**，理由：
1. ghm 升级时（增加新 subcmd）只改 YAML，不改 Python。
2. 不同环境可换 python 可执行路径（开发机 / CI / 用户机器）。
3. 与现有 `backend/config.yaml` 模式一致，pyyaml 已是依赖。
4. params_schema 直接复用为 LLM tool 的 schema，零重复定义。

---

## 4. 实施步骤（分解为可独立验证的里程碑）

### Milestone 1：领域 + 端口骨架（独立可测）

- [ ] 步骤 1.1：写 `backend/domain/compute.py`（4 个 dataclass + 1 个 Enum）
- [ ] 步骤 1.2：写 `backend/ports/compute.py`（ComputePort Protocol）
- [ ] 步骤 1.3：写 `tests/unit/domain/test_compute.py`（dataclass 构造、frozen 校验、Enum 值）
- [ ] 步骤 1.4：`pyproject.toml` 加 import-linter 规则（domain 不依赖外部、ports 仅依赖 domain）
- [ ] 步骤 1.5：跑 `pytest tests/unit/domain/test_compute.py && lint-imports` 全绿

**验证标准**：单测全过 + import-linter 报告零违规。

---

### Milestone 2：SubprocessComputeAdapter（独立可测）

- [ ] 步骤 2.1：写 `backend/config/ghm.yaml`，先写 1 个 operation（`compute_shock`）
- [ ] 步骤 2.2：写 `backend/adapters/out/compute/subprocess_adapter.py`：
  - YAML 加载 + 校验
  - `list_operations()` 实现
  - `execute()` 实现（asyncio subprocess + timeout + json.loads）
  - 各 `ComputeErrorType` 分支处理
- [ ] 步骤 2.3：写 `backend/adapters/out/compute/mock_adapter.py`（仿 `mock_llm_adapter.py`）
- [ ] 步骤 2.4：写 `tests/unit/adapters/test_subprocess_compute_adapter.py`：
  - mock `asyncio.create_subprocess_exec`（用 `unittest.mock.AsyncMock`）
  - 测试 6 个错误分支 + 1 个成功路径
- [ ] 步骤 2.5：手工集成测试：在 `sage-backend` 环境跑一个 python 脚本调用 `SubprocessComputeAdapter.execute()` 真打 `ghm core shock`，确认能拿到结果

**验证标准**：单测全过 + 手工脚本能拿到 ghm 计算结果。

---

### Milestone 3：ComputeToolAdapter 桥接（独立可测）

- [ ] 步骤 3.1：写 `backend/adapters/out/tool/compute_tool_adapter.py`：
  - `list_tools()` 合并内置工具 + 计算工具
  - `execute_tool()` 路由到 ComputePort 或 inner
  - ComputeSpec → ToolSpec 翻译（注意 `params_schema` 直传）
  - ComputeResult → ToolResult 翻译（success 路径用 `output`，失败用 `error.message`）
- [ ] 步骤 3.2：写 `tests/unit/adapters/test_compute_tool_adapter.py`：
  - 用 `MockComputeAdapter` + mock `InprocToolAdapter`
  - 验证路由分发正确（计算工具走 compute，内置工具走 inner）
  - 验证错误降级（compute 失败时 ToolResult 标记 success=False 但不抛异常）
- [ ] 步骤 3.3：把 ghm.yaml 补齐到 6 个 operation（shock / equilibrium / heatflux / nozzle / plasma / eqcomposition）

**验证标准**：单测全过 + `list_tools()` 返回 9 个内置 + 6 个 compute = 15 个工具。

---

### Milestone 4：装配 + E2E 真实调用（端到端可验证）

- [ ] 步骤 4.1：改 `backend/main.py:_build_chat_service` 接入 ComputeToolAdapter
- [ ] 步骤 4.2：写 `tests/integration/test_ghm_compute_e2e.py`（`@pytest.mark.requires_ghm` 跳过开关）：
  - 启动 sage 后端 → POST `/api/v1/chat` 一条"算 mach 6.5 的激波后参数"
  - mock LLM 返回 tool_call(compute_shock, ...)
  - 验证最终 ChatResponse 包含 tool_call + tool_result
  - 验证 audit jsonl 写入了 compute.execute 事件
- [ ] 步骤 4.3：手工开发联调：
  - `conda activate sage-backend && python backend/main.py`
  - 用真实 LLM（在 sage 设置里配好 OpenAI/Claude key）
  - chat: "用激波管计算器算一下马赫数 6.5, 比热比 1.4, 上游压力 1000 Pa, 温度 250 K 时的激波后参数"
  - 观察 LLM 是否能正确选择 compute_shock 并填充参数

**验证标准**：E2E 测试通过 + 真实 LLM 能成功调用一次计算并返回结果。

---

### Milestone 5：文档与收尾

- [ ] 步骤 5.1：更新 `docs/06-tools.md`，在工具清单追加 6 个 ghm 工具的描述和示例
- [ ] 步骤 5.2：更新 `docs/12-plan.md`（如果有 P3 ReAct 章节）补充"compute 工具已就绪，待 ReAct 落地后自动支持多轮"
- [ ] 步骤 5.3：写 `docs/technical/15-ghm-integration.md`（按项目文档规范的新章节）
- [ ] 步骤 5.4：更新 `docs/technical/README.md` 章节目录
- [ ] 步骤 5.5：删除本计划文件 `docs/plans/2026-06-07_ghm-compute-integration.md`（按项目规范，归档后删除）

**验证标准**：文档完整 + 新章节可点开阅读 + plans 目录已清空本文件。

---

## 5. 风险评估与依赖

### 5.1 风险矩阵

| 风险 | 等级 | 影响 | 缓解措施 |
|---|---|---|---|
| ghm 进程冷启动慢（每次 spawn Python + import numpy） | **中** | 单次调用 1-3s，连续调用累计延迟显著 | M1：可接受（教科书公式本身就秒级）；M2 可考虑常驻 worker（启 ghm web 服务） |
| LLM 不会主动选 compute 工具 | **中** | 用户问"算激波参数"但 LLM 走通用回答 | params_schema 的 description 要写好；在 system prompt 提示"涉及激波/风洞计算时优先调用 compute_ 工具" |
| ghm CLI 输出格式变更 | **低** | 解析失败 | E2E 测试覆盖；ghm 升级时跟进 |
| ghm 路径硬编码到配置 | **低** | 换机器要改 ghm.yaml | 用 env 变量覆盖 yaml 字段；本机 MVP 阶段无影响 |
| subprocess 异步泄漏（kill 后子进程未回收） | **中** | 长期运行内存泄漏 | timeout 分支强制 `await proc.wait()`；用 `psutil` 二次验证 |
| LLM 把私密数据带到 ghm 参数 | **低** | params 进 audit jsonl | EventPort 已记录；与现有 LLM 调用同等保护级别 |
| 双轨架构变更（legacy/hex 同时存在） | **低** | 本方案只接 hex 路径 | 在文档明确说明 |
| Python 3.8 兼容（release/win7 分支） | **低** | win7 分支无 ghm 也能跑 | ghm 可选启用（`enabled: false` 关闭整个 ComputePort） |

### 5.2 外部依赖

- **ghm 项目**：必须保持 `python -m ghm core <sub> --json` 的接口稳定。已确认 ghm `pyproject.toml:57` 的 `ghm` entry point + 6 个 core 子命令实现完整。
- **ghm 的 conda 环境**：`/home/fz/anaconda3/envs/ghm/bin/python` 路径稳定可用（已验证）。
- **numpy / scipy**：ghm 的硬依赖，conda env `ghm` 已装。
- **sage-backend 环境**：无新增 PyPI 依赖（pyyaml / asyncio / subprocess 都是 stdlib 或已有）。

### 5.3 与现有架构的兼容性

- ✅ 符合 6 层 hex 架构：新增 1 个 port + 2 个 adapter + 1 个 domain 模块，不破坏现有 5 层 import-linter 规则。
- ✅ 符合"domain 无外部依赖"约定：`compute.py` 仅用 stdlib。
- ✅ 复用现有可观测性基础设施（MetricPort / EventPort）。
- ✅ 复用现有测试模板（mock_adapter / pytest-asyncio）。
- ✅ 不影响 legacy 路径（仅 hex 路径生效）。
- ✅ 不影响双分支（main / release/win7）：通过 `enabled: false` 配置可关闭整个 compute 能力。

### 5.4 估时

| 阶段 | 预估工时 |
|---|---|
| M1 领域+端口 | 1.5 h |
| M2 SubprocessAdapter | 3 h |
| M3 ComputeToolAdapter | 2 h |
| M4 装配 + E2E | 2 h |
| M5 文档 | 1.5 h |
| **总计** | **~10 h** |

复杂度等级：**MEDIUM**

---

## 6. 后续可选演进（不在本期范围）

| 演进项 | 触发条件 |
|---|---|
| **接入 ghm 的 nozzle-contour / exptube-range**（涉及文件 I/O） | core 6 项稳定运行 ≥ 2 周后 |
| **改走 HTTP（ghm gui web）**：把 sage 改为 httpx 调用 ghm FastAPI | 单次冷启动延迟 > 2s 影响体验时 |
| **打进 Tauri 安装包**：用 PyInstaller 把 ghm 打成 sidecar | 分发给非开发用户时 |
| **HttpComputeAdapter**：新增第二个 ComputePort 实现 | 演进到 HTTP 模式时 |
| **常驻 ghm worker**：用 asyncio.subprocess 持有长连接 stdin/stdout | 调用频率高时 |
| **跨项目能力**：把 ComputePort 抽象成"任意 CLI 工具"的通用桥接 | 类似 ghm 的项目增多时 |

---

## 7. 决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-06-07 | Agent 类型 = LLM Agent（非后端 service / 非前端面板） | 用户选择，最契合"AI 助手"产品定位 |
| 2026-06-07 | 通信 = subprocess CLI（非 HTTP / 非 import） | 用户选择；ghm CLI 真实现完整，零运维成本 |
| 2026-06-07 | MVP 范围 = 6 个 core 子命令 | 用户选择；都是 flat dict in/out，接入复杂度最低 |
| 2026-06-07 | 分发 = 本机开发（不打包） | 用户选择；MVP 阶段不需要解决跨机器分发 |
| 2026-06-07 | 配置 = YAML 驱动（非硬编码） | 与 backend/config.yaml 风格一致；ghm 升级不改代码 |
| 2026-06-07 | 工具命名 = `compute_*` 前缀 | 与内置 9 个工具明显区分，便于 LLM 识别 |
| 2026-06-07 | 6 个 core 工具一次性全开 | 都是 flat dict + JSON 即用，无需逐个验证 |

---

## 8. 等待用户确认

**请确认以下内容后再开始实施：**

1. ✅ 是否同意整体技术方案（hex 架构 + ComputePort + SubprocessAdapter + ComputeToolAdapter 桥接）？
2. ✅ Milestone 划分（M1-M5）是否符合预期？是否需要把 M4 拆为 M4a/M4b（先 mock LLM 后真 LLM）？
3. ✅ 6 个 core 工具是否一次性全开，还是先打通 1 个（如 compute_shock）作为 POC？
4. ✅ 配置文件路径 `backend/config/ghm.yaml` 是否合理？还是放到 `backend/config.yaml` 内一个 `compute` 段？
5. ✅ 工具命名前缀 `compute_*` 是否合适？还是用 `ghm_*` 更明确（如 `ghm_shock`）？

**确认后请回复"proceed" / "modify: ..." / "different approach: ..."**

**默认推荐**：按本方案全部 5 个 M 一次性推进，6 个工具一次性接入，工具命名用 `compute_*` 前缀。
