# Win7 收敛 · backend 批次 16–18 复盘与决议台账（2026-10-26）

> 上游：`docs/mcp-win7-convergence-plan-20261025.md`（§11 批次 6–15、§12 总账 714→382）。
> 本文记录 backend 域三个批次的执行结果、41 个 `both` 冲突的裁决台账，以及本轮新发现的两个闸门缺口。

## 1. 批次 16 — backend 非 tests

| 桶 | 数量 | 处置 |
|---|---:|---|
| `safe` | 20 | 直接取 main blob（reuse） |
| `both` | 77 | 三方合并，排除 5 个依赖钉版文件后 72 |
| `nobase` | 55 | 延后（见 §6） |
| `allowed` | 18 | 已登记意图差异，不动 |
| `win7del` | 1 | `backend/ports/plugin.py`（main 有、win7 无） |

- 合并结果：**clean 31 / conflict 41 / err 0**；最终 PR 侧 20 文件 339 行删除（reuse 14 + clean 37 = 51 条目）。
- PR **#2541** merged `5575fa10`。
- 修红 3 轮，核心是 **py38 兼容闸**：共修 PEP 604 **49 处**（clean 桶 7 文件 28 处 + reuse 桶 6 文件 21 处）。
- 关键教训：**reuse 桶必须同样扫描**。直接复用 main blob sha 会把 main 的 `X | None` 原样带进 PR。

## 2. 批次 17 — backend/tests

| 桶 | 数量 | 处置 |
|---|---:|---|
| `both` | 29 | 三方合并 → **clean 9 / conflict 20** |
| `nobase` | 41 | 不动（win7 侧多为 py38/Windows 适配） |
| `allowed` | 13 | 不动 |
| `win7del` | 11 | 待确认是否刻意删除 |

- clean 9：`conftest.py`、`integration/test_chat_orchestration_stream.py`、`integration/test_chat_stream.py`、
  `integration/test_settings_route_legacy.py`、`unit/office/test_session_workspace.py`、`unit/test_agent_tool.py`、
  `unit/test_chat_dispatcher_topology.py`、`unit/test_risk.py`、`unit/test_skill_auto_activation.py`。
- PR **#2542**（`chore/win7-converge-backend-tests-20261026`）。
- 闸门：`compile()` 全通过、`ruff check --select F,E9`（仓库配置）All checks passed、PEP 604 残留 0。

## 3. 批次 18 — backend 冲突第 1 组（10 文件）

对批次 16 遗留的 41 个 `both` 冲突做逐 hunk 裁决，本组取「main 侧更新/更正确」的机械组。

| 文件 | +/- | 裁决依据 |
|---|---|---|
| `tools/permissions.py` | +99/-2 | main 的 R105 会话规则（`current_tool_context` + 会话 allow 叠加） |
| `memory/vector_store.py` | +21/-16 | main 的日志/注释与 backfill 说明更完整，语义一致 |
| `orchestration/snapshot_store.py` | +3/-1 | main 修 `task.` 前缀无条件切片（补 `startswith` 守卫） |
| `application/services/file_mutation_queue.py` | +4/-2 | 统一走 `py_compat.TIMEOUT_ERRORS` |
| `tools/registry.py` | +4/-0 | 按 hunk 取：h1/h2 保留 win7 的 `List`，h3 取 main 新增逻辑 |
| `api/mcp_routes.py` | +1/-1 | docstring 口径（切片 1-3b 组合） |
| `services/llm_trace/exporter.py` | +2/-2 | 补 `noqa: UP038` 注释 |
| `services/llm_trace/redactor.py` | +1/-1 | 同上 |
| `tools/file_summary_tool.py` | +2/-2 | 补 `noqa: UP038` |
| `utils/logging.py` | +1/-1 | zoneinfo 回退说明口径 |

- 合计 **+138 / −26**，PR **#2543**（`chore/win7-converge-backend-conflicts-18`）。
- **CI 驱动的回退**：首轮 `skills/skill_md/script_runner.py`、`skills/skill_md/validation.py` 取 main 后 py38 闸红
  （`Path.is_relative_to is Py3.9+`）——闸的豁免标记是**字面量** `py38: guarded`，win7 侧注释含该标记、main 侧只有
  `py38-ok` 字样，取 main 等于丢豁免。两文件回退为 win7 原样（`W`）。
- 决议机制：`git merge-file -p --diff3` 产出冲突区，再按 hunk 指定 `W`/`M` 侧**按偏移切片重建**（不再手工 join 行）。

## 4. 验证闸门（本轮更新）

1. `compile()` 全量 + 冲突标记**按行首**扫描（`=======` 会命中注释分隔线，不可用子串判定）。
2. `ruff check --select F,E9`，`cwd` 必须是 worktree（否则不走仓库配置）。
3. **PEP 604 深层扫描**：AST 遍历**注解子树**（不是只看顶层 annotation），覆盖 `Tuple[Any, str | None]` 这类嵌套。
4. **依赖闸**：取 main 实现前，先比对该文件在 main 侧的全部 `backend.*` import 是否都存在于 win7 树；符号级（如 `py_compat.TIMEOUT_ERRORS`）单独确认。

## 5. 41 个 `both` 冲突裁决台账

`W` = 保留 win7 原样（已在 win7 侧完成的适配/基线，本批不动）；`M` = 采 main；`C` = 自定义按 hunk 合并；`D` = 延后。

| # | 文件 | 裁决 | 依据摘要 |
|---:|---|---|---|
| 1 | `adapters/out/storage/memory_adapter.py` | W | 仅 PEP 604 ↔ `Optional` |
| 2 | `adapters/out/tool/inproc_adapter.py` | W | win7 侧含 alpha.36 `validate_required_args` 前置校验（超集） |
| 3 | `api/chat_attachment_routes.py` | W | `_constrained_list(float, ...)` 双版本安全范式（pydantic v1/v2） |
| 4 | `api/diagnostic_routes.py` | W | win7 侧多 `/browser-check`（Phase D 浏览器诊断） |
| 5 | `api/llm_proxy_routes.py` | W | 仅 PEP 604 ↔ `Optional` |
| 6 | `api/mcp_routes.py` | M | docstring 口径 |
| 7 | `api/office_routes.py` | W | `Optional` 仍在用 |
| 8 | `api/permission_routes.py` | D | main 的 R99 内容寻址删除改契约（`index` → `tool_pattern`+`decision`），须与前端成对 |
| 9 | `api/prompt_routes.py` | W | 已登记基线：无 reorder 端点，保持 `updated_at` 排序 |
| 10 | `api/wiki_routes.py` | W | 仅 PEP 604 |
| 11 | `application/services/file_mutation_queue.py` | M | `TIMEOUT_ERRORS` 收口 |
| 12 | `cli/doctor.py` | W | 仅 PEP 604 |
| 13 | `core/legacy/agent.py` | C | 22 hunk：win7 的 alpha.36 校验 × main 的 R92/R98 匹配器重构，需手工并 |
| 14 | `data/agent_repo.py` | W | win7 侧保留 typing 导入 |
| 15 | `data/session_repo.py` | W | win7 的 `save()` 为无条件解析段变体（已注明 R23 教训） |
| 16 | `data/settings_canonicalizer.py` | W | win7 专属 `max*Iterations` 白名单键 |
| 17 | `memory/async_extractor.py` | W | win7 惰性建队列（避免 py38 队列绑错 loop） |
| 18 | `memory/vector_store.py` | M | 注释/日志更完整 |
| 19 | `office/models.py` | W | pydantic 1.10.13 通道：`WordIndexSpec`/`WordSectionBreakSpec` 必须前置定义 + `pydantic_compat` 垫片 |
| 20 | `orchestration/orch_settings.py` | W | win7 专属 camelCase 别名 + `max_iterations=0` 语义 |
| 21 | `orchestration/snapshot_store.py` | M | `startswith` 守卫修复 |
| 22 | `services/backup_service.py` | W | `Optional` 仍在用 |
| 23 | `services/llm_trace/exporter.py` | M | `noqa: UP038` |
| 24 | `services/llm_trace/redactor.py` | M | `noqa: UP038` |
| 25 | `services/permission_gate.py` | W | PEP 604 ↔ `Optional` |
| 26 | `services/usage_tracker.py` | W | PEP 604 ↔ `Optional` |
| 27 | `skills/skill_md/script_runner.py` | W | 注释含 py38 闸豁免标记 `py38: guarded`（main 侧无） |
| 28 | `skills/skill_md/validation.py` | W | 同上 |
| 29 | `tools/agent_tool.py` | W | `Optional` + win7 的 `TimeoutError` 字面量分组 |
| 30 | `tools/browser_cdp.py` | C | 13 hunk：win7 的打包浏览器选择 × main 的 `_kill_process_tree`/`DevToolsActivePort` |
| 31 | `tools/credential_vault.py` | W | Firefox CDP `sameSite` 缺省补 `Lax` |
| 32 | `tools/executor.py` | W | win7 侧 `validate_required_args` 相关导入（超集） |
| 33 | `tools/file_summary_tool.py` | M | `noqa: UP038` |
| 34 | `tools/permissions.py` | M | R105 会话规则 |
| 35 | `tools/registry.py` | C | h1/h2 → W，h3 → M |
| 36 | `tools/shell_resolver.py` | W | win7 打包路径 `resources/tools/git-bash/usr/bin/bash.exe` |
| 37 | `tools/web_render.py` | W | win7 注入 cookie 前做 `normalize_cookie_for_cdp` |
| 38 | `tools/web_tool.py` | D | main 的 R19-W1 `block_reason` 拦截分类依赖 main 侧 `credential_vault.find_credential_for_host`；win7 侧该文件是自研 `normalize_cookie_for_cdp`，二者须成对合并 |
| 39 | `utils/logging.py` | M | zoneinfo 回退说明 |
| 40 | `wiki/chat.py` | W | 仅 PEP 604 |
| 41 | `wiki/review.py` | W | 仅 PEP 604 |

统计：**W 27 / M 10 / C 3 / D 2**（#35 `tools/registry.py` 记为 `C`：h1/h2 取 W、h3 取 M）。

## 6. 本轮新增的两个闸门缺口

**缺口 A：`F821 builtins`。** `tools/registry.py` 的合并结果语法合法、`compile()` 通过，但 `import builtins` 的删除落在**无冲突区**（win7 侧删了它），
而 `builtins.List` 的新增落在**冲突区**（取 main 侧）——两边各自成立，合并后运行时 `NameError`。只有 `ruff --select F` 能抓到。
**规则**：三方合并后，凡「一侧删除 import、另一侧在冲突区新增对该符号的用法」，必须复核 import 是否还在。

**缺口 C：py38 闸的豁免标记是字面量。** `scripts/check_py38_compat.py` 只认 `PY38_GUARD_MARKER = "py38: guarded"`。
main 侧同义注释（`py38-ok ...`）**不算豁免**，取 main 会直接触红。凡 `Path.is_relative_to` / `str.removeprefix` 一类调用点，
一律保留 win7 侧注释形态。

**缺口 D：同包跨文件「符号级」依赖。** 模块级依赖闸（`backend.*` 模块是否存在）不够：main 的 `tools/web_tool.py` 从
`tools/credential_vault.py` 导入 `find_credential_for_host`，而 win7 的 `credential_vault.py` 是自研版本（含
`normalize_cookie_for_cdp`），没有该符号 → 单取 web_tool 会让 `backend/tests/unit/test_web_tool.py` 全线 ImportError。
**规则**：取 main 实现时，逐条核对被 import 的**符号**是否在同一 PR 内一并到位。

**缺口 B：PEP 604 嵌套。** `Tuple[Any, str | None]` 是 `Subscript` 里的 `BinOp`，只扫顶层 annotation 会漏。已改为 AST 注解子树遍历。

## 7. 下一批次入口

1. **批次 19 — 自定义合并**：`core/legacy/agent.py`（22 hunk，win7 alpha.36 校验 × main B2 分组调度）、`tools/browser_cdp.py`（13 hunk）。
   两者都需要 hunk 级 union（同一区域内两侧各有新增），现有 `W`/`M` 二选一不足，需要「M 侧 + 补 W 独有行」的第三种决策。
2. **批次 20 — `tools/credential_vault.py` + `tools/web_tool.py` 成对合并**（保留 win7 的 `normalize_cookie_for_cdp`，
   同时并入 main 的 `find_credential_for_host` 与 R19-W1）。
3. **批次 21 — `api/permission_routes.py`**：与前端 `permissions` 面板成对落地（R99 内容寻址 + R101/R102/R104 插件归属 + R105 存续范围）。
4. **nobase 55**：FMT-ONLY 2、伪 DIFF 28、真差异 25（大者 `api/legacy_memory_list_routes.py` w81、`model_catalog/schemas.py` w70/m1、`services/arena_accounts.py` w68/m3；唯一 m 侧重者 `data/session_event_backfill.py` m14）。
5. `requirements*.txt` + `environment.yml` 5 个因版本钉版策略仍**故意跳过**。
6. `win7del 1`：`backend/ports/plugin.py` 需确认 win7 是否刻意删除该端口插件桥。

