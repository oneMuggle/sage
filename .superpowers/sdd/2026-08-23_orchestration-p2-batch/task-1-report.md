# Task 1 实施报告：子任务 schema 结构化返回

## 改动文件

- `backend/orchestration/subagent_runner.py`
  - 新增 `extract_json_payload()`，按整段 JSON、代码围栏、嵌入对象三种形态提取 JSON object。
  - `SubagentRunner` 从 `task.parameters["output_schema"]` 读取可选 dict；声明 schema 时向 user prompt 注入硬性 JSON 输出要求和 schema 内容。
  - 对最终原文提取并调用既有 `validate_against_schema()`；通过后以 `ensure_ascii=False` 和 `separators=(",", ":")` 输出紧凑 JSON，提取/校验失败记录 warning 并降级原文。
  - 所有成功返回值增加 `messages` 键，供后续续聊任务消费。
- `backend/orchestration/chat_dispatcher.py`
  - `ChatTaskState` 新增 `output_schema: Optional[Dict[str, Any]] = None`。
  - `dispatch()` 三条 task 路由统一读取 object 类型 `output_schema`，非 dict 降级为 None。
  - `_run_subagent()` 在 schema 非空时写入 `Task.parameters["output_schema"]`。
- `backend/tools/subagent_tool.py`
  - `INPUT_SCHEMA.tasks.items.properties` 新增可选 object 类型 `output_schema` 及描述。
  - 工具描述同步标注可选 schema。
- `backend/tests/unit/test_subagent_runner.py`
  - 新增 JSON 提取五项测试、schema 成功紧凑输出、schema 违规原文降级、无 schema 回归测试。
  - 存量返回值断言改为键级断言，兼容新增 `messages`。
- `backend/tests/unit/test_subagent_tool.py`
  - 新增 `output_schema` object schema 断言。
- `backend/tests/unit/test_chat_dispatcher.py`
  - 新增 tool-passed schema 进入 `ChatTaskState` 的透传测试。

## TDD 步骤与结果

1. **Step 1 写失败测试**
   - 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_runner.py::TestExtractJsonPayload -q`
   - 结果：5 failed；失败为预期 `ImportError: cannot import name 'extract_json_payload'`。
2. **Step 3/4 实现并验证 JSON 提取**
   - 命令同上。
   - 结果：5 passed（5 warnings，均为既有 Pydantic deprecation warning）。
3. **Step 5 写 runner schema 测试并确认 RED**
   - 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_runner.py -q`
   - 结果：先得到 4 failed/11 passed；失败集中在预期的 `messages` 缺失及 schema 逻辑未实现。修正测试 helper 名称后仍为 4 个实现相关失败。
4. **Step 6/7 实现 runner 并验证**
   - 命令同上。
   - 结果：15 passed（5 warnings）。
5. **Step 8 写工具/dispatcher 测试并确认 RED**
   - 工具 schema 测试：1 failed，预期 `KeyError: 'output_schema'`。
   - dispatcher 透传测试：1 failed，预期 `KeyError: 'schema'`。
6. **Step 9 实现工具与 dispatcher 透传**
   - 定向命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_tool.py::TestSchema::test_schema_tasks_cardinality tests/unit/test_chat_dispatcher.py::test_dispatch_passes_output_schema_to_subagent tests/unit/test_subagent_runner.py -q`
   - 结果：在工具字段实现前为 1 failed/16 passed；补齐字段后全部通过。

## 最终自检

- 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_runner.py tests/unit/test_subagent_tool.py tests/unit/test_chat_dispatcher.py -q`
  - 结果：`33 passed, 5 warnings`。
- 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check .`
  - 结果：`All checks passed!`
- `git diff --check`
  - 结果：通过，无空白错误。

## 遗留疑虑

- 测试环境使用 Python 3.10 的 `sage-backend` 环境；本次新增生产代码未引入 PEP 604 union、`zip(strict=)` 或 `match`。
- Pydantic 既有 deprecation warning 仍存在，但不属于本 Task 变更。
- `output_schema` 不落库，符合本任务接口范围；任务状态持久化字段保持兼容。

## Review 修复轮次 1

- `backend/tools/web_tool.py`
  - 将 `_literal_ip`、`_all_public`、`_validate_subagent_url`、`_validate_subagent_redirect` 的 Python 3.10 union/set 注解改为 Python 3.8 可运行的 `Optional`、`Union`、`Set` 注解；运行逻辑不变。
- `backend/orchestration/subagent_runner.py`
  - 捕获 `validate_against_schema()` 异常，记录 warning 并降级返回原文；抽出 `_warn_structured_failure()` 保持函数职责和长度约束。
- `backend/tests/unit/test_subagent_runner.py`
  - 新增 `test_output_schema_validator_exception_falls_back_to_raw`，覆盖 validator 抛异常时任务仍 succeeded、output 保留原文和 warning 记录。

### 修复 TDD 与验证

1. **validator 异常 RED**
   - 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_runner.py::test_output_schema_validator_exception_falls_back_to_raw -q`
   - 结果：1 failed，`RuntimeError: validator boom` 按预期穿出。
2. **validator 异常 GREEN**
   - 同一命令。
   - 结果：`1 passed, 5 warnings`。
3. **Python 3.8 定向 pytest**
   - 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest tests/unit/test_subagent_runner.py tests/unit/test_subagent_tool.py tests/unit/test_chat_dispatcher.py -q`
   - 结果：Python `3.8.20` 收集阶段被分支既有 `office_create_tool` 的 Pydantic v1 字段约束错误阻塞：`ValueError: On field "slides" ... max_length, min_length`；未进入本 Task 测试执行。
4. **Python 3.8 语法验证**
   - 命令：`/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m py_compile backend/tools/web_tool.py backend/orchestration/subagent_runner.py`，并用同一解释器执行 `ast.parse`。
   - 结果：编译和 AST parse 均通过，确认修复文件可被 Python 3.8 解析。
5. **Python 3.10 最终定向验证**
   - 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_runner.py tests/unit/test_subagent_tool.py tests/unit/test_chat_dispatcher.py -q`
   - 结果：`34 passed, 5 warnings`。
6. **Ruff**
   - 命令：`cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check .`
   - 结果：`All checks passed!`

### 修复遗留疑虑

- `sage-backend-py38` 的完整定向 pytest 仍受既有 Pydantic v1/OfficeCreate collection 错误阻塞；本轮已用 Python 3.8 编译和 AST parse 验证本轮涉及模块。
- Pydantic deprecation warnings（Python 3.10）仍为既有 warning。
