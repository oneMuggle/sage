# 工具系统

## 概述

Sage Agent 通过 OpenAI 兼容的 `function_calling` 协议扩展 LLM 能力。
内置工具通过 `ToolRegistry` 注册，`agent.run_loop` 实现 ReAct 循环。

## 架构

- `backend/core/agent_state.py` — 状态机与事件流
- `backend/core/agent.py::run_loop` — ReAct 主循环
- `backend/tools/registry.py` — 工具注册表
- `backend/tools/*.py` — 内置工具实现

## 当前内置工具

- `calculator` — 数学计算（AST 白名单）
- `read_file` / `write_file` / `list_dir` — 文件操作
- `web_search` / `web_fetch` — 网络访问
- `memory_search` / `memory_save` — 记忆系统
- `terminal` — 终端命令

## 添加新工具

1. 继承 `BaseTool`，实现 `_build_schema()` 与 `execute()`
2. 在 `backend/tools/__init__.py::register_all_tools()` 中注册
3. 写单元测试

## ReAct 循环

```
THINKING → ACTING → OBSERVING → THINKING → ... → DONE/FAILED
```

最大迭代默认 10 次（`DEFAULT_MAX_ITERATIONS=10`，由 `agent.run_loop` 兜底；每个 agent profile 可单独覆盖），由 `agent.run_loop` 强制。子代理（agent tool）的委派预算独立配置：默认 6，落在 `OrchSettings.max_subagent_iterations`（设置 → 通用 → "子代理迭代上限"），后台常量 `SUBAGENT_MAX_ITERATIONS` 仅在配置读失败时兜底。
