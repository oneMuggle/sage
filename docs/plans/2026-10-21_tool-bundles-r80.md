# R80 — tool 收编：硬编码装配 → bundle 注册

- 日期：2026-10-21
- 前置：R78（内核）、R79（hooks provider），同一 PR #2206
- 目标：把 `backend/tools/__init__.py::register_all_tools` 里 94 条平铺
  `registry.register(...)` 重组为**具名 bundle**，编排逻辑下沉到内核通用机制，
  等价性由**黄金对照测试**兜住。

## 1. 现状盘点

| 项 | 值 |
| --- | --- |
| `register_all_tools` 位置 | `backend/tools/__init__.py:144` |
| `registry.register(...)` 调用数 | 94 |
| 条件分支 | 仅 2 处：`network_policy.search_enabled()` / `fetch_enabled()` |
| 延迟 import | `AgentTool`（PEP 562 `__getattr__` 破循环）、`register_default_adapters`、`todo_mgmt_tool`、`backend.mcp` |
| 失败容错 | `register_mcp_tools` 包 `try/except`，只告警 |
| 已有基础设施 | `domain/risk.py::RiskClass` + `ToolRegistry.risk_of/declared_risks/classify` + `adapters/out/permission/permission_engine.py` **已是数据驱动** |

**结论：R80 缺的不是权限模型，是装配结构。**「权限 → RiskClass」那一半在更早的
轮次已经完成，本轮不碰，避免重复做功。

## 2. 设计

### 2.1 机制（内核，纯逻辑）

`backend/application/kernel/tool_install.py`（127 行）

```python
@dataclass(frozen=True)
class ToolBundle:
    name: str
    install: Callable[[ToolInstallContext], None]
    requires: Tuple[str, ...] = ()
    critical: bool = True

@dataclass
class ToolInstallContext:
    registry: Any
    policy: Any = None
    network_policy: Any = None
    scheduler_service_getter: Any = None
    todo_service_getter: Any = None
    capabilities: Dict[str, bool] = field(default_factory=dict)

@dataclass(frozen=True)
class InstallReport:
    installed: Tuple[str, ...]
    skipped: Tuple[str, ...]
    failed: Tuple[Tuple[str, str], ...]

def install_bundles(ctx, bundles, *, strict=True) -> InstallReport
```

四条契约：

1. **顺序保真**——按声明顺序安装，bundle 内按函数体顺序；
2. **能力门控**——`requires` 任一为假则整包跳过，取代散落的 `if network_policy.xxx_enabled():`；
3. **失败策略**——`strict=True` 首个 critical 异常上抛；`critical=False` 只记录（对应 MCP 那圈 `try/except`）；
4. **报告可核对**——`installed` 取自注册前后 `list_names()` 的差集，反映真实落库量而非声明量。

### 2.2 声明（`backend/tools/tool_bundles.py`，464 行）

94 个工具切成 **31 个具名 bundle**，排列顺序 = 注册顺序：

`shell` / `file` / `web_search` / `web_fetch` / `memory` / `code_exec` /
`memory_write` / `office_core` / `office_pdf` / `office_template` /
`office_analysis` / `office_journal` / `office_quality` / `edit_search` /
`agent_surface` / `runtime` / `skill` / `ask_user` / `subagent` / `file_summary` /
`git` / `checkpoint` / `symbol_search` / `browser` / `skill_save` / `multimodal` /
`sage_config` / `schedule` / `mcp` / `todo` / `design`

两个 bundle 带非默认属性：

- `web_search` → `requires=("network.search",)`
- `web_fetch` → `requires=("network.fetch",)`
- `mcp` → `critical=False`（注册失败只告警，不拖垮启动）

import 全部走 `.子模块` 而非 `from backend.tools import ...` —— 后者在包
`__init__` 未执行完时是循环，前者不会。

### 2.3 门面（`backend/tools/__init__.py`，461 → 519 行）

```python
def register_all_tools(...):
    policy = policy or ToolPolicy()
    network_policy = ... or load_network_policy()
    if tool_bundles_enabled():          # SAGE_KERNEL_TOOL_BUNDLES
        from .tool_bundles import install_default_bundles
        report = install_default_bundles(...)
        return
    _register_all_tools_legacy(...)     # R80 之前的平铺实现，原样保留
```

开关默认关 → 生产路径逐字节等价，与 R79 的 `SAGE_KERNEL_HOOKS` 同一策略。
旧实现整体改名为 `_register_all_tools_legacy`，作为对照基线与回滚路径，
**R81 再删**。

## 3. 验收

`backend/tests/unit/test_tool_bundles_parity.py`（16 例）——等价性主证据：

| 断言 | 覆盖 |
| --- | --- |
| `list_names()` 顺序与内容 | 3 档网络策略 × 2 条路径 |
| `declared_risks()` | 同上 |
| `get_schemas_for_llm()` 完整 schema | 同上 |
| 门控差额（ONLINE 独有 1 个 / INTRANET 独有 4 个） | 两条路径各一遍 |
| BUNDLES 声明不漏不重、报告与真实注册一致 | 假注册表 |
| getter 原样透传（schedule 3 个 / todo 5 个） | 按对象身份判断，不依赖属性名 |
| `execute_code` 的 registry 自引用仍是同一对象 | — |

`backend/tests/unit/test_kernel_tool_install.py`（23 例）——机制单测：
顺序保真 / 能力门控 / strict 抛 / critical 豁免 / 报告差集 / 开关解析（11 组取值）。

**实测**：`legacy 94 tools / 0.26s`，`bundle 94 tools / 0.02s`，名字、风险、schema
三者全等。

## 4. 一个实测陷阱（写进测试）

Windows 上 `ssl.create_default_context()` 读系统证书库 **每次约 2 秒**；94 个工具里
有 9 个会构造 httpx 客户端，一次全量装配因此要 **18.5 秒**。首版测试按 3 档 × 2 路径
跑 6 次装配 = 111 秒，看起来像死锁。

处置：`_fast_tls` fixture（module 级 autouse）共享一个不加载系统证书库的
`SSLContext`，并在 `ssl.create_default_context` 上打补丁 —— 装配降到 0.26 秒，
39 例合计 9 秒。**不放宽断言，只去掉与等价性无关的 IO 成本。**

## 5. 风险与边界

| 风险 | 处置 |
| --- | --- |
| 分组时漏掉/重复某个 register | 对照测试断言名字集合 + 顺序 + 数量；`install_bundles` 报告与真实注册做差集核对 |
| 延迟 import 时机变化（`AgentTool` 循环）| bundle 函数体在 `register_all_tools` 调用期执行，此时包已完整 |
| `register_default_adapters()` 被调两次 | 该函数本身幂等（内部按 language 去重），且调用位置不变 |
| MCP 注册被 strict 吞掉 | 用 `critical=False` 表达，不依赖 bundle 内部 try/except |
| 两份实现漂移 | 本轮结束即 R81 删 legacy；账本记录截止轮次 |

**不动**：权限模型（`RiskClass` / `PermissionEnforcer`）、工具实现、装配的默认行为。
**不新增**第三方依赖。

## 6. 交付

| 文件 | 行数 | 说明 |
| --- | --- | --- |
| `backend/application/kernel/tool_install.py` | 127 | 新增，机制 |
| `backend/tools/tool_bundles.py` | 464 | 新增，声明 |
| `backend/tools/__init__.py` | 461 → 519 | 门面 + legacy 改名 |
| `backend/tests/unit/test_kernel_tool_install.py` | 200 | 新增，机制单测 |
| `backend/tests/unit/test_tool_bundles_parity.py` | 213 | 新增，等价性对照 |
