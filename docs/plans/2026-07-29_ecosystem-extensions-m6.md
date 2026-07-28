# M6 生态扩展 (Ecosystem Extensions) — 实施计划

> 日期: 2026-07-29 · 分支: `feat/ecosystem-extensions` (基于 main)
> 设计参考: claw-code (`rust/crates/runtime/src/{hooks,usage,prompt}.rs` + `mock-anthropic-service`)

## 背景与目标

M6 是里程碑收尾，交付 5 个相互独立的生态扩展能力：

1. **Hooks 系统** — claw 风格用户自定义工具钩子（pre/post tool use，allow/deny/modify）
2. **用量/成本面板** — token 用量追踪 + 每模型定价估算 + REST + 设置页面板
3. **项目上下文发现** — SAGE.md/CLAUDE.md 向上发现 + 去重 + 注入 system prompt
4. **i18n 覆盖清扫** — Office / Orchestration 两页硬编码中文提取
5. **Mock LLM 一致性测试台** — 脚本化 OpenAI 兼容 mock 服务器 + 真实 LLMClient 线协议测试

## 涉及的文件与模块

| 交付物 | 新增/修改 |
|--------|-----------|
| D1 Hooks | `backend/hooks/{__init__,config,runner}.py`, `backend/core/legacy/agent.py` (接线块), `backend/data/settings_repo.py` (whitelist), `backend/tests/unit/test_hooks.py`, `backend/tests/integration/test_hooks_integration.py` |
| D2 Usage | `backend/services/usage_tracker.py`, `backend/core/legacy/llm_client.py`, `backend/api/usage_routes.py`, `backend/main.py`, 前端 Settings GeneralTab + i18n, `backend/tests/unit/test_usage_tracker.py`, `backend/tests/api/test_usage_routes.py` |
| D3 Context | `backend/chat/project_context.py`, `backend/api/legacy_routes.py` (注入点), `backend/tests/unit/test_project_context.py`, `backend/tests/integration/test_project_context_injection.py` |
| D4 i18n | `src/pages/Office.tsx`, `src/features/office/**`, `src/pages/Orchestration.tsx`, `src/shared/lib/i18n/{zh,en}.ts`, 相关 vitest |
| D5 Parity | `backend/tests/parity/{__init__,mock_server,test_llm_client_parity}.py` |

## 技术方案要点

- **D1**: `run_hook()` 走 asyncio subprocess，JSON payload 经 STDIN，env `SAGE_HOOK_EVENT`/`SAGE_TOOL_NAME`；超时 `start_new_session` + `killpg`；fail-open（仅显式 deny 生效）。接线位于 `agent.run_loop` 工具执行块（M1 enforcer 尚未落地 main，保持单块标记便于 rebase）。
- **D2**: 内存 ring buffer（1000）+ 按日聚合 dict，无新 DB 表；定价表 USD/1M tokens；未知模型成本 None；`LLMClient.chat` 内部记录（tracker 失败永不影响 chat）。
- **D3**: 从 workspace root 向上遍历至文件系统根，每级先 SAGE.md 后 CLAUDE.md，内容哈希去重，单文件 8000 字符 / 总量 16000 字符上限，截断标注；realpath 防符号链接；失败静默跳过。
- **D5**: `http.server.BaseHTTPRequestHandler` 线程服务器，场景以数据定义（按请求序号取响应脚本），3 场景：plain / tool_call round-trip / SSE stream。

## 实施步骤

- [x] D1 Hooks 系统（`backend/hooks/{config,runner}.py` + agent 接线 + settings whitelist + 30 单测 + 5 集成）
- [x] D2 后端用量追踪（`usage_tracker.py` + LLMClient usage 提取 + `GET /api/v1/usage` + 15 测试）
- [x] D2 前端用量面板（`usage_summary` IPC 路由 + `UsagePanel.tsx` + GeneralTab + 3 vitest + guard 测试）
- [x] D3 项目上下文发现（`project_context.py` + legacy_routes 注入 + 7 单测 + 2 集成）
- [x] D5 Mock LLM 一致性测试台（`tests/parity/` 线程 http.server + 4 parity 测试, 不依赖 respx）
- [x] D4 i18n 清扫（Office 6 文件 + Orchestration 2 文件, zh/en 各 +83 键, 3 测试文件包裹 I18nProvider）
- [x] i18n 键: settings.section.usage + settings.usage.* 8 键 (zh+en, D4 落盘后追加)
- [x] 验证：ruff ✅ + py3.8 py_compile ✅ + pytest unit/api ✅ + integration ✅ (206 passed) + parity ✅ + vitest 456 ✅ + tsc ✅ + typecheck:electron ✅ + eslint ✅

## 风险评估与依赖

- **Hooks 接线 vs M1 enforcer**: M1 会在 agent.py 落 enforcer；本分支接线保持单一标记块 (`# === M6 HOOKS BEGIN/END ===`)，merge 顺序建议 M1 先落、M6 rebase。
- **py3.8 兼容**: 所有新代码使用 `typing.*` 注解 + `from __future__ import annotations`，`sage-backend-py38` py_compile 校验。
- **Hooks 安全性**: 钩子命令是用户配置的可信 shell，fail-open 保证钩子故障永不阻断 agent；仅显式 `deny` 生效。
