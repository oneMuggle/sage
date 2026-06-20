# g002: 工具执行 (Tool Execution) 验证映射

> Sage 工具系统 — 基于 `BaseTool` 抽象的 9 种内置工具 + MCP 动态工具，
> 由 `ToolRegistry` 统一管理，通过 `InprocToolAdapter` 桥接至六角架构 `ToolPort`。

---

**状态**: 🔴 未验证  
**维护者**: @backend-team  
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- 职责 1：**工具注册与发现** — `ToolRegistry` 管理工具生命周期（register/unregister/get/list/exists），提供 OpenAI function-calling 格式的 Schema 输出
- 职责 2：**终端命令执行** — `TerminalTool` 执行 Shell 命令，含危险命令黑名单拦截和超时控制
- 职责 3：**文件操作** — `ReadFileTool` / `WriteFileTool` / `ListDirTool` 提供文件读写和目录列表功能
- 职责 4：**Web 工具** — `WebSearchTool`（DuckDuckGo HTML 搜索）和 `WebFetchTool`（HTTP GET + 内容截断）
- 职责 5：**安全计算** — `CalculatorTool` 通过 AST 解析实现安全的数学表达式求值（仅允许白名单函数）
- 职责 6：**记忆工具** — `MemorySearchTool` / `MemorySaveTool` 桥接记忆系统（g001）
- 职责 7：**工具 Schema 输出** — `get_schemas_for_llm()` 生成 LLM 可消费的工具描述

### 不负责

- 非职责 1：工具权限的用户级授权管理（由 API 层 / 前端控制）
- 非职责 2：MCP 协议通信（由 `backend/mcp/` 模块负责）
- 非职责 3：工具执行的可观测性埋点（由 `ChatService` 通过 `MetricPort` / `EventPort` 负责）

### 依赖

- 依赖 `subprocess` 标准库：终端命令执行
- 依赖 `httpx`（WebFetchTool）或 `requests`：HTTP 请求
- 依赖 g001：`MemorySearchTool` / `MemorySaveTool` 调用 `MemoryManager`

---

## 2. 接口契约

### 2.1 输入断言

| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|
| `tool.name` | `str` | 非空，kebab-case | `assert tool.name and tool.name.replace('_', '').isalnum()` |
| `command` (TerminalTool) | `str` | 非空，不含危险模式 | `assert command and not tool._is_dangerous(command)` |
| `timeout` (TerminalTool) | `int` | > 0，≤ 300 | `assert 0 < timeout <= 300` |
| `file_path` (ReadFileTool) | `str` | 非空，文件存在 | `assert file_path and os.path.exists(file_path)` |
| `expression` (CalculatorTool) | `str` | 仅含数字/运算符/白名单函数 | AST 验证无非法节点 |
| `query` (WebSearchTool) | `str` | 非空，长度 < 500 | `assert query and len(query) < 500` |
| `url` (WebFetchTool) | `str` | 合法 URL 格式 | `urllib.parse.urlparse(url).scheme in ('http', 'https')` |

### 2.2 输出断言

| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|
| `ToolResult.success` | `bool` | 必须为 `True` 或 `False` | `assert isinstance(result.success, bool)` |
| `ToolResult.content` | `Any` | 成功时非 None | `if result.success: assert result.content is not None` |
| `ToolResult.error` | `str \| None` | 失败时非 None | `if not result.success: assert result.error is not None` |
| `ToolSchema.name` | `str` | 与 `tool.name` 一致 | `assert schema.name == tool.name` |
| `ToolSchema.parameters` | `dict` | 符合 JSON Schema 格式 | `assert 'type' in schema.parameters` |

### 2.3 错误处理

| 错误场景 | 错误类型 | 处理方式 |
|----------|----------|----------|
| 危险命令被拦截 | `ToolResult(success=False, error=...)` | 返回拒绝原因，不执行命令 |
| 命令执行超时 | `subprocess.TimeoutExpired` | 返回 `ToolResult(success=False, error="命令执行超时")` |
| 工具不存在 | `ToolCallError` | `SageAgent.execute_tool()` 抛出 `ToolCallError` |
| CalculatorTool 非法表达式 | `ValueError` | AST 验证失败，返回错误 |
| 文件不存在 | `FileNotFoundError` | ReadFileTool 返回 `ToolResult(success=False)` |
| Web 请求失败 | `httpx.RequestError` | WebFetchTool 返回 `ToolResult(success=False, error=...)` |
| 工具执行异常 | `Exception` | 捕获并包装为 `ToolResult(success=False, error=str(e))` |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: 工具名称唯一性

**定义**：`ToolRegistry` 中每个工具名称唯一，重复注册覆盖旧工具并记录警告。

**验证方法**：
```python
def verify_tool_name_uniqueness(registry: ToolRegistry) -> bool:
    """验证工具名称唯一性"""
    names = registry.list_names()
    return len(names) == len(set(names))
```

**检查频率**：
- [x] 每次 register() 调用后

**测试用例**：
```python
def test_tool_name_uniqueness():
    """测试工具注册不会导致名称重复"""
    from backend.tools.registry import ToolRegistry
    from backend.tools.calculator import CalculatorTool

    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(CalculatorTool())  # 重复注册，覆盖

    assert len(registry.list()) == 1
    assert verify_tool_name_uniqueness(registry)
```

#### 不变量 2: ToolResult 结构完整性

**定义**：每个 `ToolResult` 必须包含 `success` 字段；成功时 `content` 不为 None；失败时 `error` 不为 None。

**验证方法**：
```python
def verify_tool_result_structure(result: ToolResult) -> bool:
    """验证 ToolResult 结构完整性"""
    if not isinstance(result.success, bool):
        return False
    if result.success and result.content is None:
        return False
    if not result.success and result.error is None:
        return False
    return True
```

**检查频率**：
- [x] 每次工具执行后

**测试用例**：
```python
def test_all_tools_return_valid_structure():
    """测试所有内置工具返回结构完整的 ToolResult"""
    from backend.tools.registry import ToolRegistry
    from backend.tools import register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)

    for tool_schema in registry.list():
        tool = registry.get(tool_schema.name)
        result = tool.execute()  # 空参数预期失败
        assert verify_tool_result_structure(result), \
            f"工具 {tool.name} 返回了结构不完整的 ToolResult"
```

#### 不变量 3: 危险命令拦截

**定义**：`TerminalTool` 必须拦截所有 `DANGEROUS_PATTERNS` 中的命令模式。

**验证方法**：
```python
def verify_dangerous_command_blocking(tool: TerminalTool) -> bool:
    """验证危险命令全部被拦截"""
    test_commands = [
        "rm -rf /",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4",
        "chmod -R 000 /",
        ":(){ :|:& };:",
    ]
    return all(tool._is_dangerous(cmd) for cmd in test_commands)
```

**检查频率**：
- [x] 每次 execute() 调用前

**测试用例**：
```python
def test_dangerous_command_blocking():
    """测试危险命令黑名单"""
    from backend.tools.terminal import TerminalTool

    tool = TerminalTool()
    assert verify_dangerous_command_blocking(tool)

    result = tool.execute(command="rm -rf /")
    assert result.success is False
    assert "拒绝" in result.error
```

### 3.2 行为不变量

#### 超时强制执行

**定义**：`TerminalTool` 执行必须在指定超时时间内完成。超时后返回 `ToolResult(success=False)`。

**验证方法**：
```python
def test_timeout_enforcement():
    """测试工具超时控制"""
    from backend.tools.terminal import TerminalTool

    tool = TerminalTool()
    result = tool.execute(command="sleep 60", timeout=2)
    assert result.success is False
    assert "超时" in result.error
```

#### 工具 Schema 对 LLM 格式正确

**定义**：`get_schemas_for_llm()` 返回的每个 Schema 必须包含 `name`, `description`, `parameters` 三键。

**验证方法**：
```python
def test_llm_schema_format():
    """测试 LLM Schema 输出格式"""
    from backend.tools.registry import ToolRegistry
    from backend.tools import register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    schemas = registry.get_schemas_for_llm()

    for s in schemas:
        assert "name" in s and isinstance(s["name"], str)
        assert "description" in s and isinstance(s["description"], str)
        assert "parameters" in s and isinstance(s["parameters"], dict)
```

### 3.3 性能不变量

#### 工具注册延迟 < 1ms

**定义**：`register()` 和 `get()` 操作延迟低于 1ms。

**验证方法**：
```python
import time

def test_registry_latency():
    """测试工具注册和查找延迟"""
    from backend.tools.registry import ToolRegistry
    from backend.tools.calculator import CalculatorTool

    registry = ToolRegistry()
    tool = CalculatorTool()

    start = time.perf_counter()
    registry.register(tool)
    register_time = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    registry.get("calculator")
    get_time = (time.perf_counter() - start) * 1000

    assert register_time < 1, f"register 延迟 {register_time:.2f}ms"
    assert get_time < 1, f"get 延迟 {get_time:.2f}ms"
```

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: 工具执行超时

**触发条件**：
- `TerminalTool` 执行的命令超过 `timeout`（默认 30 秒）
- `WebFetchTool` 请求的外部 URL 响应缓慢

**影响**：
- 严重性：中
- 影响范围：单个工具调用失败，不阻塞其他工具和对话

**恢复策略**：
1. `subprocess.run(timeout=...)` 抛出 `TimeoutExpired` 时捕获
2. 返回 `ToolResult(success=False, error="命令执行超时 (Xs)")`
3. 不重试（避免资源泄漏）

**验证测试**：
```python
def test_terminal_tool_timeout():
    """测试终端工具超时处理"""
    from backend.tools.terminal import TerminalTool

    tool = TerminalTool()
    result = tool.execute(command="sleep 60", timeout=1)
    assert result.success is False
    assert "超时" in result.error
```

### 4.2 失败模式 2: 危险命令被拒绝

**触发条件**：
- LLM 生成包含危险模式的命令（如 `rm -rf /`、`dd if=/dev/zero`）

**影响**：
- 严重性：低（预期安全行为）
- 影响范围：该工具调用返回失败，错误信息回传 LLM

**恢复策略**：
1. `_is_dangerous()` 返回 `True` 时不执行命令
2. 返回 `ToolResult(success=False, error="危险命令被拒绝")`
3. 错误信息传达给 LLM，LLM 可调整命令重试

**验证测试**：
```python
def test_dangerous_command_rejection():
    """测试危险命令被正确拦截"""
    from backend.tools.terminal import TerminalTool

    tool = TerminalTool()
    dangerous_commands = ["rm -rf /", "dd if=/dev/zero of=/dev/sda", "mkfs.ext4"]
    for cmd in dangerous_commands:
        result = tool.execute(command=cmd)
        assert result.success is False
        assert "拒绝" in result.error
```

### 4.3 失败模式 3: 工具不存在

**触发条件**：
- LLM 返回 `tool_calls` 中包含未注册的工具名称
- 工具被 unregister 后仍有待处理的调用

**影响**：
- 严重性：低
- 影响范围：该工具调用返回错误信息

**恢复策略**：
1. `ToolRegistry.get(name)` 返回 `None`
2. `SageAgent.run_loop()` 设置 `result_content = f"[错误] 工具不存在: {name}"`
3. 错误信息作为 tool message 回传 LLM

**验证测试**：
```python
def test_tool_not_found_handling():
    """测试工具不存在时的处理"""
    from backend.tools.registry import ToolRegistry

    registry = ToolRegistry()
    assert registry.get("nonexistent_tool") is None
    assert registry.exists("nonexistent_tool") is False
```

### 4.4 失败模式 4: CalculatorTool 非法表达式

**触发条件**：
- 提交的表达式包含非法操作（如 `__import__('os').system('rm -rf /')`）

**影响**：
- 严重性：高（安全风险）
- 影响范围：CalculatorTool 拒绝执行

**恢复策略**：
1. AST 解析并验证节点白名单
2. 非法节点 → `ToolResult(success=False, error="非法表达式")`
3. 不执行任何代码

**验证测试**：
```python
def test_calculator_blocks_code_injection():
    """测试计算器阻止代码注入"""
    from backend.tools.calculator import CalculatorTool

    tool = CalculatorTool()
    malicious = ["__import__('os').system('ls')", "exec('print(1)')"]
    for expr in malicious:
        result = tool.execute(expression=expr)
        assert result.success is False
```

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/verification/g002/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/verification/g002/ -v --cov=backend/tools
```

**覆盖范围**：
- [ ] ToolRegistry register/unregister/get/list/exists/clear
- [ ] TerminalTool 命令执行 + 危险命令拦截 + 超时
- [ ] CalculatorTool 安全 AST 求值 + 非法表达式拒绝
- [ ] ReadFileTool / WriteFileTool / ListDirTool 文件操作
- [ ] WebSearchTool / WebFetchTool 网络请求（mock）
- [ ] ToolResult / ToolSchema 数据结构验证
- [ ] get_schemas_for_llm() OpenAI 格式输出

### 5.2 集成测试

**位置**：`tests/integration/g002/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/integration/g002/ -v
```

**覆盖范围**：
- [ ] ToolRegistry → InprocToolAdapter → ToolPort 桥接
- [ ] ChatService._execute_tool_calls() 端到端
- [ ] SageAgent.run_loop() ReAct 工具调用循环
- [ ] MemorySearchTool / MemorySaveTool 与 g001 集成

### 5.3 属性测试

**位置**：`tests/property/g002/`

**使用的库**：`hypothesis`

**测试的属性**：
- [ ] ToolResult 结构完整性：任何工具任何输入都返回结构完整的 ToolResult
- [ ] 工具注册幂等性：register → unregister → register 状态一致
- [ ] 危险命令拦截完整性：所有 DANGEROUS_PATTERNS 均被拦截

### 5.4 性能测试

**位置**：`tests/performance/g002/`

**测试的指标**：
- [ ] 工具注册延迟 < 1ms
- [ ] CalculatorTool 求值延迟 < 5ms
- [ ] ToolRegistry.get() 延迟 < 0.1ms

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 工具调用延迟 P95 | 直方图 | < 5s | > 30s | Prometheus (`sage_tool_invocations_total`) |
| 工具错误率 | 计数器 | < 5% | > 20% | Prometheus (`sage_errors_total{layer="tool"}`) |
| 危险命令拦截次数 | 计数器 | - | > 100/天 | 日志 |
| 超时率 | 计数器 | < 2% | > 10% | Prometheus |

### 6.2 业务指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 已注册工具数 | 仪表 | 9+ | < 9 | ToolRegistry.list_names() |
| ReAct 步数分布 | 直方图 | < 5 步/请求 | > 10 步 | Prometheus (`sage_react_steps_per_request`) |

### 6.3 健康检查

**端点**：`GET /health/tools`

**返回格式**：
```json
{
  "status": "healthy",
  "checks": {
    "registry": "ok",
    "registered_count": 9,
    "tool_names": ["calculator", "terminal", "read_file", "write_file",
                   "list_dir", "web_search", "web_fetch", "memory_search", "memory_save"]
  },
  "timestamp": "2026-06-19T12:00:00Z"
}
```

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| 性能测试 | 🔴 | 0% | - |
| 属性测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| 工具名称唯一性 | ❌ | - |
| ToolResult 结构完整性 | ❌ | - |
| 危险命令拦截 | ❌ | - |
| 超时强制执行 | ❌ | - |
| Schema LLM 格式 | ❌ | - |

### 7.3 失败模式测试

| 失败模式 | 检测测试 | 恢复测试 | 状态 |
|----------|----------|----------|------|
| 工具执行超时 | ❌ | ❌ | 🔴 |
| 危险命令拒绝 | ❌ | ❌ | 🔴 |
| 工具不存在 | ❌ | ❌ | 🔴 |
| 非法表达式注入 | ❌ | ❌ | 🔴 |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @backend-team |

---

## 9. 参考

- [BaseTool / ToolSchema / ToolResult](../../backend/tools/base.py) — 工具基类与数据结构
- [ToolRegistry](../../backend/tools/registry.py) — 工具注册表
- [TerminalTool](../../backend/tools/terminal.py) — 终端命令执行
- [CalculatorTool](../../backend/tools/calculator.py) — 安全数学计算
- [ReadFileTool / WriteFileTool / ListDirTool](../../backend/tools/file_tool.py) — 文件操作
- [WebSearchTool / WebFetchTool](../../backend/tools/web_tool.py) — Web 工具
- [MemorySearchTool / MemorySaveTool](../../backend/tools/memory_tool.py) — 记忆工具
- [ToolPort](../../backend/ports/tool.py) — 六角架构工具端口
