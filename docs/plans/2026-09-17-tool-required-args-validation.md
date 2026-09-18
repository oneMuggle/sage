# 工具 required 参数验证（fix/tool-required-args-validation）

## 背景与目标

win7 alpha.40 安装包中，使用 `office_read` 工具时报错 `missing_required_argument: doc_id`。

**根本原因**：`backend/core/legacy/agent.py` 的工具执行入口没有在调用 `tool.execute(**args)` 前检查 required 参数是否存在。LLM 漏传必需参数时，Python 抛出 `TypeError: execute() missing 1 required positional argument`，被 `except Exception` 捕获后变成不友好的 `[工具错误] ...` 消息，LLM 再将其"翻译"为自然语言错误展示给用户。

**目标**：在 JSON 参数解析成功后、M6 hooks 之前，添加 required 参数存在性验证。缺失时回传友好错误消息 `[参数错误] 工具 {name} 缺少必需参数: [...]。请提供这些参数后重新调用。`，LLM 可据此修正参数重试。

## 影响范围

所有在 schema 中声明了 `required` 字段的工具（不限于 office 系列），包括：

| 工具 | required 参数 |
|------|--------------|
| `office_read` | `doc_id` |
| `office_archive` | `doc_id` |
| `office_restore` | `doc_id` |
| `office_update` | `ops` |
| `office_analyze` | `operations` |
| `office_lint` | `file_path`, `format_spec` |
| `office_repair` | `file_path`, `format_spec` |
| `office_pdf` (generate) | `output_path`, `paragraphs` |
| `office_journal` | `file_path` / `content` / `user_request` |
| `office_bibtex` | `text` |
| `office_template` | `data` |
| 其他工具的 required 参数 | ... |

## 涉及的文件

- `backend/core/legacy/agent.py` — 添加工具 required 参数验证（~15 行）
- `backend/tests/unit/test_tool_required_args.py` — 新增单元测试

## 技术方案

### 插入位置

`agent.py` 第 1347 行（`continue`，JSON 解析失败处理后）与第 1349 行（M6 HOOKS BEGIN 注释）之间。

### 验证逻辑

```python
# L7+: required 参数存在性校验——工具执行前拦截缺失参数,
# 避免 Python TypeError 被 except Exception 捕获后变成不友好的
# "[工具错误] execute() missing 1 required positional argument" 消息。
# 与 hooks/runner.py:validate_modified_args 同构的轻量检查。
_schema_tool = self.tool_registry.get(tc.name)
if _schema_tool is not None:
    _schema_required = _schema_tool.schema.parameters.get("required", [])
    if isinstance(_schema_required, list):
        _missing = [k for k in _schema_required if k not in args]
        if _missing:
            _missing_content = (
                f"[参数错误] 工具 {tc.name} 缺少必需参数: {_missing}。"
                "请提供这些参数后重新调用。"
            )
            yield AgentEvent(
                state=AgentState.OBSERVING,
                iteration=i,
                tool_call=ToolCallRequest(id=tc.id, name=tc.name, arguments=args),
                tool_result=ToolCallResult(
                    tool_call_id=tc.id,
                    content=_missing_content,
                    is_error=True,
                ),
                agent_id=self.agent_id,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": _missing_content,
                }
            )
            continue
```

### 设计要点

1. **与现有 JSON 解析错误处理同构**：不发 ACTING 事件（工具并未执行），发 OBSERVING + is_error=True
2. **在 M6 hooks 之前**：避免 hook 拿到不完整参数做无意义处理
3. **`args` 非 dict 时的安全性**：`k not in args` 对 dict 有效；run_loop 主路径在 JSON 解析后没有 `isinstance(args, dict)` 检查——需加防御，非 dict 时走已有的参数错误路径

### 风险

- 低风险：仅添加验证逻辑，不改变现有工具执行路径
- 向后兼容：之前 LLM 传了所有 required 参数的场景完全不受影响

## 实施步骤

- [x] 步骤 1：在 `backend/core/legacy/agent.py` 第 1347-1349 行间插入 required 参数验证（含 `isinstance(args, dict)` 防御）
- [x] 步骤 2：编写单元测试 `backend/tests/unit/test_tool_required_args.py`（6 个测试用例）
- [x] 步骤 3：运行相关测试验证（6/6 新测试通过；agent_tool_loop 6/6 通过；office+agent 1165 passed 无回归）

## 风险评估

- 变更范围小（~20 行核心逻辑 + 测试），不触及工具执行/权限/hooks 子系统
- 已有 `validate_modified_args` 作为参考实现，逻辑一致
- 不影响并行批次路径（`_auto_approve_read_batch` 已在前置检查中拦截非法参数）
