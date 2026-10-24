# B4b — `backend/tests` 的 `real` 差异归因

> **本文的数字有两个时点，不要混用。**
> §1–§5 的归因是在 `origin/main` `7634de8fc` ↔ `release/win7` `82ff6bdc0`（+B4）上做的，
> 当时 `real` = 96。§6.1 记录的**实施**发生在两次基线前进之后
> （`a181f29e4` → `13cb21f48`，其间 #2410/#2414/#2416/#2420/#2425/#2428 落地），
> 届时 `real` = 97、`PURE-LAG` = 17。**以 §6.1 的数字为准做实施决策**；
> §1–§5 的价值在方法与分类结构，具体计数会随基线漂移。
> 本轮内 `release/win7` 共移动 **11 次**，`origin/main` 也在移动 ——
> 任何清单在开工前都必须重跑 parity 刷新。


**日期**：2026-10-23　**性质**：只分析，不改任何代码
**口径**：`origin/main` `7634de8fc` ↔ B4 分支 `e7bf8b99a`（`release/win7` 基线 `82ff6bdc0` + B4 的 88 个纯新增测试文件）
**数据源**：`parity_report.py --base origin/main --head HEAD --json`

> ⚠️ **写作过程中两侧基线都移动了**，本文结论已按最新状态复核：
> - `origin/main`：勘察期 `1508168e0` → 本文 `7634de8fc`（real 计数两版都是 96）
> - `release/win7`：B4 开工基线 `82ff6bdc0` → **`67c257773`**（前进 5 个提交）
>
> **新基线的 5 个提交里有一个直接影响本文**：
> `65d7907a4 sync(win7): 批次 3e — plugin routes + frontend + R92 allowlist helpers (#2410)`
> 已把**整个插件 REST 子系统**带入 win7（`api/plugin_routes.py`、`ports/plugin.py`、
> `plugins/{manifest,registry,tool_bridge}.py`，并在 `main.py:115` import、`:1512`
> `include_router`），同时带入了 B4 曾排除的 `tests/api/test_plugin_routes.py`
> —— 在新基线上实跑 **11 passed**，说明子系统完整可用。
> 另 `67c257773 (#2414)` 修改了 `tests/unit/test_tool_names.py`，新基线上 **25 passed**。
>
> **与 B4（PR #2411）的文件交集 = 0**，故 #2411 不受这 5 个提交影响。
>
> 本文 §5.1 / §5.2 / §5.4 的三处源码缺口**在新基线上经 `git diff --numstat` 复核依然成立**：
> `office_create_tool.py` **+2 −285**、`office_lint_tool.py` **+0 −18**、
> `model_catalog/schemas.py` **+172 −27**（win7 侧多 172 行，印证它是刻意的 py3.8 重写）。
> 只有 §5.3（插件 REST）已被 #2410 解决。

---

## 0. 结论速览

```
96 real
 ├─ 1  假差异（path move）      → 无需动作
 └─ 95 genuine
      ├─ 15 PURE-LAG            → 可安全整替对齐（合计落后 514 行，win7 零独有内容）
      ├─ 11 WIN7-TEST           → 不该动（main 完全没有这些内容）
      ├─  9 COMMENT/MARKER-ONLY → 无害（仅注释或 pytest 标记差异）
      ├─  6 LAYOUT-ONLY         → 无害（同一批语句换行方式不同）
      ├─  3 ADAPT-ONLY(py38/typing) → 须保留（v1 typing 写法）
      ├─  3 ADAPT-ONLY(mixed)   → 须保留
      ├─  1 ADAPT-ONLY(net/win) → 须保留
      └─ 47 NEEDS-REVIEW        → 规则无法判定，已抽查 8 个（见 §4）
```

**规则可解释 48/95 = 51%**。剩下 47 个抽查后的主导模式是：
**「win7 独有安全/平台测试」+「同时落后 main 数十行」的双向分叉** ⇒
**对齐必须做行级合并，绝不能整替**（整替会删掉 win7 的独有加固测试）。

这与本项目已付出代价确立的原则一致：#2274 / #2275 / #2292 三个 PR 都因未先归因而白做。

---

## 1. 方法

四个只读脚本，逐步收紧（每一步都由抽查驱动修正，不是一次写成）：

1. **启发式分类**（按 win7 独有行的关键词）→ 得到初步 5 类，但抽查发现误判。
2. **假差异检测**：
   - *path move* — win7 内容（EOL 归一化后）与 main 某**不同路径**的文件逐字节相同；
   - *layout-only* — 同路径，去空白后的行多重集相同。
   第一版用 **blob hash** 比对，**必然失败**：main 存 LF、win7 存 CRLF，字节级 hash 恒不同；
   且对「main 上该路径不存在」的情况 `git show` 返回空，被静默当成「138 行 win7 独有内容」。
   改为 EOL 归一化内容比对 + 按 basename 在 main 全树找对应文件后，才正确识别出那 1 个假差异。
3. **win7 独有行聚合**：对所有 genuine 文件取「去空白行多重集」的差集（win7 − main），
   按出现频次找共同模式 ⇒ 815 行 / 610 distinct，重复模式覆盖 21%。
4. **逐行 kind 分类 + 文件级归桶**：只有当文件仍含**无法解释的 CODE 行**时才判 NEEDS-REVIEW。

### 1.1 规则演进中修掉的四个 bug（都是「看起来跑通了」的假绿）

| # | bug | 后果 | 修法 |
|---|---|---|---|
| 1 | 用 blob hash 判 path move | main=LF / win7=CRLF ⇒ hash 恒不同，**0 命中**（实际有 1 个） | 比对 EOL 归一化后的内容 |
| 2 | 行归一化去掉所有空白，但模式写成 `^fromtyping import`（含空格） | 该模式**永不匹配**，`from typing import List, Optional` 全落到 CODE | 模式改为 `^fromtypingimport` |
| 3 | `RE_COMMENT` 写成 `^#\|^"""\|^'''`，最后一个 alternative 退化成裸 `^` | 裸 `^` 匹配任意行的空位置 ⇒ **所有行都被判成 COMMENT** | 显式写三种注释前缀，并用探针逐条验证 |
| 4 | 用 `W=$(git rev-parse <rev>:<path> 2>/dev/null \|\| echo ABSENT)` 判文件是否存在 | `git rev-parse` 对**不存在**的路径会把**参数本身**打到 stdout 再返回非零，于是 `W` 变成两行（参数 + `ABSENT`），`[ "$W" = "ABSENT" ]` 判 false ⇒ **把 3 个不存在的文件误报成 PRESENT** | 一律用 `git ls-tree --name-only <rev> -- <path>` 判存在性（空输出 = 不存在） |

bug 4 的代价是实质性的：它一度让我以为「B4 排除的 4 个测试文件已被新基线全部带入」，
而真相是只有 `api/test_plugin_routes.py` 被 #2410 带入，其余 3 个
（`test_office_create_schema_contract.py`、`test_model_catalog_snapshots.py`、
`test_tool_policy.py`）**仍然缺失**。若非紧接着在新基线 worktree 里实跑 pytest
（直接报 `file or directory not found`），这个错误结论就会写进交接文档。

⇒ **存在性判断只用 `ls-tree`；任何「文件已存在」的结论都要用实跑或 `ls` 二次确认。**

另有两处边界：括号类模式用 `$` 锚定，会漏掉带尾随 `#noqa: SIM117` 的重排续行
（改为先剥离尾部注释再判）；`monkeypatch.setattr(` 这类裸调用开头未纳入 BRACKET。

**教训**：分类脚本本身必须用**探针表**验证（本文 §1.2），否则会得到一份看起来整齐、
实则全错的归因。这与「静态检查器本身会假绿」是同一类问题。

### 1.2 探针表（round-3 规则，全部通过）

| 输入（归一化后） | 判定 |
|---|---|
| `fromtypingimportList,Optional` | TYPING |
| `withpatch.object(#noqa:SIM117` | BRACKET |
| `monkeypatch.setattr(` | BRACKET |
| `time.sleep(0.02)` | WIN |
| `)` | BRACKET |
| `return_value=service,` | ARG |
| `assertvalidate_profile_tools(repo)==1` | CODE |
| `#py3.8:noPath.is_relative_to` | COMMENT |
| `pytestmark=pytest.mark.unit` | MARKER |
| `"""docstring` | COMMENT |
| `class_Ref:` / `defderive(client_message_id):` | CODE |

---

## 2. 假差异（1 个）：parity 的路径重构盲区

```
win7  backend/tests/unit/test_memory_manager_coordination.py
main  backend/tests/unit/memory/test_memory_manager_coordination.py
      → EOL 归一化后逐字节相同（diff 0 行）
```

main 把 memory 测试收进了 `unit/memory/`，win7 未跟随该目录重构。parity 按路径比较，
于是把这个文件报成 `real`（win7 侧 138 行「独有」+ main 侧 138 行「缺失」），
**实际语义差异为零**。

顺带确认一个反面结论：B4 切片 3 带入 `unit/memory/` 6 个文件时**没有**造成重复测试 ——
`git diff --name-status` 报的是
`R100 unit/memory/test_memory_manager_coordination.py → unit/test_memory_manager_coordination.py`，
正说明 HEAD 上 `unit/memory/` 那份不存在（parity 已把它识别为「内容已存在于别处」而未列入
main-only 清单，切片脚本因此正确地跳过了它）。

**可选动作**：跟随 main 的目录重构（把文件移到 `unit/memory/` 并删根下副本）。
但这会**修改 win7 原有文件**，与 B4「纯新增」的纪律不同，建议单独一个 chore 批次，
或直接登记为可接受差异。

---

## 3. 规则可解释的 48 个

### 3.1 PURE-LAG（15 个，合计落后 514 行）— 可安全整替

win7 侧**零独有内容**（归一化后差集为空），对齐到 main 不可能破坏任何 win7 修复。
这是 B4b 里**最安全、收益最大**的一批，建议作为第一个实施批次。

| 落后行数 | 文件 |
|---:|---|
| 135 | `integration/test_approval_api.py` |
| 114 | `unit/tools/test_office_update_tool.py` |
| 71 | `unit/test_agent_tool_gate.py` |
| 46 | `unit/test_llm_factory.py` |
| 34 | `api/test_search_routes.py` |
| 32 | `integration/test_office_word_inline_tables.py` |
| 26 | `unit/test_tools_registry.py` |
| 15 | `unit/test_agent_loop_guards.py` |
| 13 | `unit/test_profiles_default_tools.py` |
| 8 | `unit/test_permissions_enforcer.py` |
| 7 | `unit/test_allowed_paths_integration.py` |
| 6 | `unit/test_shipped_writing_skills.py` |
| 3 | `unit/office/test_word_template.py` |
| 3 | `unit/test_file_tool_safepath.py` |
| 1 | `unit/test_attachment_context.py` |

> 注：整替前仍须逐个确认「win7 零独有」是由**内容真的落后**造成，而不是由
> 行尾/编码归一化把差异抹平。做法与 B3 一致：`git diff --ignore-all-space` 看 71 行差异里
> 有无 win7 独有论点（B3 的 `test_office_word_lint.py` 就是这样确认为零独有后整替的，
> 15 → 18 passed）。

### 3.2 WIN7-TEST（11 个）— 不该动

`behind == 0`：main 完全没有这些内容，是 win7 独立演进的测试。

| win7 独有行 | 文件 | 备注 |
|---:|---|---|
| 156 | `unit/test_py38_compat_gate.py` | py38 兼容闸门自测（#2288 引入，证明该闸门生效） |
| 109 | `unit/test_mcp_oauth.py` | #2343 的 MCP OAuth（win7 已做 py3.8 适配） |
| 32 | `unit/test_remote_mcp_server.py` | #2343 remote_mcp 子系统 |
| 25 | `unit/test_mcp_oauth_loopback.py` | **安全加固**：`test_callback_prefix_path_404`（`/callback-evil` 前缀扩展必须 404 且不捕获）、`test_second_callback_404_keeps_first`（一次性回调） |
| 15 | `unit/test_replan_tool.py` | autouse fixture |
| 9 | `unit/test_browser_temp_lifecycle.py` | |
| 5 | `conftest.py` | **注意**：conftest 有 5 行 win7 独有，任何对齐都要格外小心（`setup_test_db` 是 autouse，导入期错误会让整套件 collection 崩） |
| 5 | `unit/test_review_stamp.py` | |
| 1 | `integration/test_sources_stream_persist.py` | STEP_DONE 边界注释（R83） |
| 1 | `unit/test_mcp_oauth_store.py` | `assert store.path.stat().st_mode & 0o777 == 0o600`（token 文件权限） |
| 1 | `unit/test_risk.py` | `_online_network_settings` 标记 |

### 3.3 无害差异（19 个）

**COMMENT/MARKER-ONLY（9）** — 仅注释或 pytest 标记：
`unit/test_browser_tool.py`(+1 −28)、`unit/test_hooks_builtin.py`(+1 −5)、
`unit/test_hooks_feedback.py`(+1 −5)、`unit/test_hooks_lifecycle.py`(+1 −4)、
`unit/test_env_memory.py`(+2 −2)、`integration/test_web_access_journey.py`(+1 −1)、
`unit/data_repo/test_session_and_settings_repo_r188.py`(+1 −1)、
`unit/test_schema_migrations.py`(+1 −1)、`unit/test_wiki_insights.py`(+1 −1)

**LAYOUT-ONLY（6）** — 同一批语句换行方式不同（win7 把 `with patch(...)` 拆成多行）：
`unit/test_skill_save_tool.py`(+40 −10，BRACKET 20 + ARG 20)、
`unit/test_project_knowledge_extractor.py`(+8 −19)、
`unit/test_project_task_decomposer.py`(+6 −14)、`unit/test_adapter_tag_graph.py`(+4 −10)、
`unit/test_project_advisor.py`(+2 −6)、`unit/wiki/test_ingest_queue.py`(+1 −2)

> LAYOUT-ONLY 虽无语义差异，但会让 parity 永久报 `real`。若想让计数收敛，
> 需要统一换行风格 —— 但那会与「逐字节对齐 main」冲突，且 `ruff format` 在本仓
> **不是闸门**（CI 只跑 `ruff check backend/`），win7 原有测试 831/846 都不符合
> `ruff format`。**建议不动**，改为在 parity 侧考虑「layout-only 降级」（未实现）。

**ADAPT-ONLY（7）** — 必须保留的 win7 适配：
- py38/typing（3）：`unit/test_memory_storage_adapter.py`(TYPING 6)、
  `api/test_runtime_routes.py`(TYPING 6)、`unit/office/test_session_workspace.py`(TYPING 2)
  —— 都是 `from typing import List, Optional` 这类 v1 写法
- net/win（1）：`unit/test_worktree.py`（WIN 2 + MARKER 3）
- mixed（3）：`unit/test_web_tool.py`(+3 −23)、
  `contract/test_settings_schema_parity.py`(+8 −1)、
  `unit/tools/test_office_journal_tool.py`(+2 −2)

### 3.4 行类型统计（815 个 win7 独有行）

| kind | 行数 | 含义 |
|---|---:|---|
| CODE | 341 | 无法用规则解释，需人工 |
| ARG | 162 | 续行参数（字符串字面量 / `kw=value,`） |
| BRACKET | 102 | 括号、`with patch(` 开头等重排碎片 |
| COMMENT | 67 | 注释 / docstring |
| PY38 | 58 | py3.8 双版本习语 |
| NET | 32 | 网络模式 fixture / offline 断言 / proxy |
| TYPING | 21 | v1 typing 写法 |
| MARKER | 21 | `pytestmark` / `@pytest.mark.*` |
| WIN | 11 | Windows 平台适配（时钟粒度、`newline=`、`os.name`） |

---

## 4. NEEDS-REVIEW 47 个：抽查 8 个的结论

按「win7 独有行数」与「落后行数」挑信息量最大的 8 个逐行读。

| 文件 | +/− | win7 独有内容（实读） | 判定 |
|---|---|---|---|
| `unit/test_local_auth.py` | +55 −1 | `LocalAuthMiddleware` / `initialize_local_auth_token` / `require_local_auth`；`def _app_with_routes(*paths: str) -> FastAPI: """Build an app whose routes are guarded by the real middleware."""` | **win7 独有安全加固**（真中间件而非 mock），behind 仅 1 行 ⇒ 基本不该动 |
| `unit/test_network_config.py` | +37 −18 | `配置异常必须 fail-closed 到 OFFLINE；合法显式 ONLINE 保留`，多条 `assert policy.mode is NetworkMode.OFFLINE`，`def test_missing_key_returns_offline_default()` | **双向分叉**：win7 的 fail-closed 语义必须保留，同时补 main 的 18 行 |
| `unit/api/test_search_routes.py` | +21 −22 | `test_global_search_knowledge_project_single_root`、`test_search_knowledge_explicit_scope_passthrough`、`assert out["knowledge"][0]["scope"] == "/p/alpha"`、`assert str(project_root) == "/w/a"` | **双向分叉**：win7 独有 knowledge scope 测试 + 落后 22 行 |
| `unit/test_todo_service.py` | +17 −22 | `time.sleep(0.02)  # 见 test_update_todo：Windows 时钟粒度`、`assert completed.updated_at != created.updated_at`、`test_get_startup_summary_buckets`（Overdue / Today 分桶） | **Windows 时钟粒度适配 + win7 独有测试**，同时落后 22 行 |
| `unit/test_chat_attachment_text.py` | +25 −34 | 手写 `class _Ref:` stub（`ref.id = mid`、`ref.mime_type = "text/plain" if kind.value == "document" else "audio/mpeg"`、`ref.file_path = f"fake/{mid}"`） | 疑似 **pydantic v1 适配**（用 stub 替代真实模型），需进一步确认是否可换成 main 的写法 |
| `unit/test_tool_names.py` | +1 −100 | 仅 `assert validate_profile_tools(repo) == 1` | **1 行断言差异 vs 落后 100 行**：需比对 main 侧同一断言的期望值（可能是 profile 工具数量口径不同） |
| `unit/tools/test_office_create_tool.py` | +1 −102 | `assert set(props.keys()) == {"doc_type","output_dir","filename","content","font_family"}` | **与 B4 排除的契约测试同源**：win7 的 office_create schema 只有 5 个属性，main 已扩到含 `toc`/`section_breaks`/`first_page_*`/`even_page_footer` 等 ⇒ 见 §5.1 |
| `unit/test_plugin_tool_bridge.py` | +2 −97 | `def test_profile_whitelist_requires_exact_plugin_tool_name() -> None:`、`assert registry.get_schemas_for_llm(allowed_tools=["plugin__demo__*"]) == []` | **win7 独有安全测试**（插件白名单要求精确名、拒绝通配）+ 与 plugin REST 子系统缺失同源 ⇒ 见 §5.3 |

### 4.1 从抽查外推的主导模式

47 个 NEEDS-REVIEW 里，`win7_only` ≤ 2 而 `behind` ≥ 20 的有 4 个
（`test_office_create_tool` +1 −102、`test_tool_names` +1 −100、
`test_plugin_tool_bridge` +2 −97、`test_credential_vault` +5 −45），
这类**接近纯落后**，只需判定那 1–5 行是什么；
其余多为 `+N −M` 两侧都有实质内容 ⇒ **必须行级合并**。

**因此 B4b 的实施纪律应当是**：
1. 先做 15 个 PURE-LAG（整替，逐个复核零独有）；
2. 再做「win7 独有 ≤ 2 行」的近似纯落后项（判定那几行后整替或行级补）；
3. 最后做真正的双向分叉（行级合并，保留 win7 独有测试）；
4. 全程**不整替** WIN7-TEST / ADAPT-ONLY / conftest.py。

---

## 5. B4 排除项指向的 4 处源码缺口

B4（PR #2411）刻意排除了 4 个测试文件，它们精确指出了 win7 落后于 main 的源码位置。
本节把「测试的失败」翻译成「源码要改什么」。

### 5.1 `backend/tools/office_create_tool.py` — 落后 285 行（+285 / −2）

- **缺失能力**：交叉引用占位符（`{{fig:caption}}` / `{{tbl:caption}}` 写成 Word `REF` 域，
  以及 `{{fn:}}` / `{{en:}}` 行内脚注尾注）与 `do_refresh` TOC 刷新路径
  （`_attach_toc_refresh_local` / `_attach_toc_refresh_managed`）。
- **归因**：win7 独有的那 2 行经查都是 main 重写前的旧形态（一处是缺新占位符文档的
  schema 描述字符串，一处是 main 加 `do_refresh` 分支之前的裸
  `return self._generate_document(...)`）⇒ **零 win7 独有修复，纯落后**。
- **牵连**：B3 已把 `WordFormatSpec` 对齐 main，于是 model 现在声明了手写 JSON schema
  从未获得的字段 ⇒ `unit/tools/test_office_create_schema_contract.py` 的
  `set(schema_props) == set(WordFormatSpec.model_fields)` 断言失败，
  缺 `toc` / `section_breaks` / `first_page_header` / `first_page_footer` /
  `first_page_different` / `even_page_footer` 等 11 项；
  同时 `unit/tools/test_office_create_tool.py`(+1 −102) 的
  `assert set(props.keys()) == {5 项}` 也是同一根因。
- **属功能级改动**：牵连 tool schema、tool 注册、前端 `src/shared` 的 `types.ts` 与文档，
  因此不属 tests-only 批次。

### 5.2 `backend/tools/office_lint_tool.py` — 落后 18 行（+18 / −0）

checkable 白名单缺 `figure_index` / `table_index` / `toc`。
**win7 独有行为零**（该文件无任何 win7 独有行）⇒ 最安全的一处，可与 5.1 同批。

### 5.3 插件 REST 子系统 — ~~win7 完全缺失~~ **已由 #2410 解决**

**B4 归因时的状态**（基线 `82ff6bdc0`）：

- `backend/api/plugin_routes.py` = main-only，win7 无
- `backend/ports/plugin.py` = main-only，win7 无
- win7 的 `backend/main.py` **既没 import 也没 include_router**；
  main 在 `:110` import、`:1143` `app.include_router(plugin_router, prefix="/api/v1")`
  （注释「R82 插件生命周期记录 REST」）
- 直接后果：`api/test_plugin_routes.py` 的 11 个测试全部 404

**现状**（基线 `67c257773`，经 `65d7907a4` / #2410「批次 3e — plugin routes + frontend +
R92 allowlist helpers」带入）：

| 文件 | 状态 |
|---|---|
| `backend/api/plugin_routes.py` | 已存在（与 main 仍有差异） |
| `backend/ports/plugin.py` | 已存在（与 main 仍有差异） |
| `backend/plugins/{manifest,registry,tool_bridge}.py` | 已存在（与 main 仍有差异） |
| `backend/main.py` | `:115` import + `:1512` `app.include_router(plugin_router, prefix="/api/v1")` |
| `backend/tests/api/test_plugin_routes.py` | 已存在，**实跑 11 passed** |

⇒ **本项从 B4b 移除**。B4 当时排除该测试文件的判断在当时的基线上是正确的
（子系统确实完全不存在，带入测试只会得到 11 个 404），只是这个缺口后来被
他人的并行批次填上了。这也再次印证「**每阶段开工前必须重跑 parity，不可假设基线不动**」：
本轮内 `release/win7` 已移动 7 次。

**仍需注意**：`unit/test_plugin_tool_bridge.py`(+2 −97) 依然落后 97 行，
其 win7 独有的 2 行是安全测试
（`test_profile_whitelist_requires_exact_plugin_tool_name`、
`assert registry.get_schemas_for_llm(allowed_tools=["plugin__demo__*"]) == []`
—— 插件白名单要求精确名、拒绝通配）。现在 `plugins/registry.py` 已在 win7 存在，
这个文件转入 §4.1 的「近似纯落后」处理路径：判定那 2 行后做行级合并，
**保留 win7 的白名单精确匹配断言**。

### 5.4 `backend/model_catalog/schemas.py` — v2 侧 immutability 缺口

- **现象**：`unit/api/test_model_catalog_snapshots.py` 的 18 个测试里 17 个通过，
  唯一失败的 `test_merge_output_is_frozen_value` 断言 `merged.native = 1` 应抛
  `ValidationError`，实得 `DID NOT RAISE`。
- **根因**：win7 的 `CatalogValue` **只用 pydantic v1 的方式声明不可变性**
  （`class Config: allow_mutation = False`），而 v2 忽略该键。其自带注释已承认
  `v2 honors only extra`，且显式的 `__hash__` / `__eq__` 覆盖的是 v2 的 **hashability**
  ⇒ **immutability 从未被覆盖**，测试所说的「快照审计完整性前提」在 v2 下不成立。
- **修法**：补 v2 形式（`frozen=True`）。
- **约束**：该文件是 win7 **刻意的 172 行 py3.8 重写**（用 plain types +
  `@field_validator` 取代 main 的 `Annotated[..., AfterValidator(...)]`，
  因为 v1 下 `Annotated` 不在 `typing`、`AfterValidator` 不存在），
  **绝不能整替**；且任何改动的 v1 那一半**本地无法验证**
  （两个 conda 环境都是 pydantic 2.5.0，只有 CI 装 1.10.13）
  ⇒ 必须作为独立的、由 CI 验证的小改动。

---

## 6. 建议的 B4b 批次划分

| 批次 | 内容 | 风险 | 前置 |
|---|---|---|---|
| **B4b-1** | 15 个 PURE-LAG 整替（514 行） | 低（win7 零独有内容） | 逐个复核零独有 |
| **B4b-2** | `office_lint_tool.py` +18 行白名单（`figure_index`/`table_index`/`toc`） | 低（`git diff --numstat` 复核为 **+0 −18**，零 win7 独有行） | — |
| **B4b-3** | `model_catalog/schemas.py` 补 v2 `frozen=True` | 中（双版本，v1 侧只能靠 CI） | 独立 PR，便于 CI 单独验证 |
| **B4b-4** | `office_create_tool.py` +285 行（占位符 + TOC 刷新）+ `types.ts` | **高**（功能级，牵连注册/前端/文档） | 需要产品侧确认；`types.ts` 属 B5 |
| **B4b-5** | 47 个 NEEDS-REVIEW 里「win7 独有 ≤ 2 行」的近似纯落后项（含 `test_tool_names.py` +1 −100、`test_office_create_tool.py` +1 −124、`test_plugin_tool_bridge.py` +2 −97、`test_credential_vault.py` +5 −45） | 中 | 逐个判定那几行 |
| **B4b-6** | 真正的双向分叉（行级合并，保留 win7 独有测试） | **高** | 每个文件单独 review |
| ~~B4b-7~~ | ~~插件 REST 子系统~~ | — | **已由 #2410 (`65d7907a4`) 解决，从 B4b 移除**；新基线上 `test_plugin_routes.py` 实跑 11 passed |
| （可选） | `test_memory_manager_coordination.py` 跟随 main 目录重构 | 低但会改 win7 原有文件 | 建议单独 chore 或登记为可接受差异 |

**开工前必做**：重跑 parity。本文写作期间 `release/win7` 就从 `82ff6bdc0` 前进到
`67c257773`（5 个提交，其中 #2410 直接消掉了本表一整行），本轮内该基线共移动 7 次。

**不该动的**：11 个 WIN7-TEST、7 个 ADAPT-ONLY、9 个 COMMENT/MARKER-ONLY、
以及 `backend/tests/conftest.py`（5 行 win7 独有 + autouse fixture 的脆弱性）。

---

## 6.1 B4b-1 实施结果（2026-10-23，PR #2433）：PURE-LAG ≠ 可执行

B4b-1 经历**两次尝试**，因为 `release/win7` 在中间又前进了。两次合起来才是完整的结论。

### 6.1.1 第一次尝试（基线 `a181f29e4`）：19 个 PURE-LAG → 只留 10 个

整替前逐个复核通过（`git diff --ignore-all-space -U0` 的 `+` 行全为 0、两侧 blob 严格
UTF-8 可解码、无 U+FFFD）⇒「需人工确认的：0」，合计落后 770 行。

```
整替 19 个 → py38 collect 报 1 error
             ImportError: cannot import name 'plugin_tool_belongs_to_plugin'
                          from 'backend.domain.tool_names'
  ↓ 顺带对齐 backend/domain/tool_names.py（numstat 0 added / 29 deleted，纯落后）
重跑 → 19 failed, 311 passed, 2 skipped
  ↓ 回退 9 个受阻文件
重跑 → 148 passed, 2 skipped（10 个文件 + tool_names.py），ruff clean
```

### 6.1.2 基线前进到 `13cb21f48`：2 个改动变成冗余，6 个受阻项被解锁一半

`a181f29e4..13cb21f48` 的 6 个提交里有两个正中要害：

```
13cb21f48 fix(win7): R95 plugin_name 传播到 enforcer.check — 与 main 对齐 (#2428)
78a8f1237 feat(win7): sync R94 plugin runtime tool picker + R95 remember approvals (#2425)
```

后果：

- `backend/domain/tool_names.py` 与 `backend/tests/unit/test_tool_names.py`
  **numstat 变为空（已与 main 完全一致）** ⇒ 我第一次尝试里那 +29 行源码改动
  和 +23 行测试改动**全部冗余，作为冗余丢弃**。
- `test_permission_gate.py`、`api/test_plugin_routes.py` **变为 IDENTICAL** ⇒ 从清单消失。
- `test_agent_tool_gate.py` 落后从 −124 缩到 −41、`test_tools_registry.py` −30 ⇒
  **这两个在第二次尝试中通过了**，是 R95 落地的直接收益。

重跑 parity + 归因（`13cb21f48` ↔ main `2099292ef`）：
`backend/tests` 的 `real` 从 101 降到 **97**，`PURE-LAG` 从 19 变为 **17**（合计落后 652 行）。

### 6.1.3 第二次尝试（基线 `13cb21f48`）：17 个 → 留 11 个，回退 6 个

```
整替 17 个 → py38 collect 306 tests / 0 errors（import 问题已消失）
           → v2 pytest 18 failed, 286 passed, 2 skipped
  ↓ 回退 6 个受阻文件
重跑 → 148 passed, 2 skipped（11 个文件），ruff clean，CRLF i/lf w/crlf
```

**本批次最终不含任何源码改动**（tests-only），提交 `edcef646d`，
经 Git Data API 推送为远程 `ec764a91c`（**tree 字节级一致** `3464ce8ca…`，
stats +373 −2 / 11 files 两侧相同）⇒ **PR #2433**。

留下的 11 个：

| 文件 | 行数变化 |
|---|---|
| `unit/tools/test_office_update_tool.py` | 279 → 420（+141） |
| `unit/test_llm_factory.py` | 199 → 247（+48） |
| `api/test_search_routes.py` | +42 |
| `unit/test_agent_tool_gate.py` | 215 → 256（+41）**← R95 解锁** |
| `integration/test_office_word_inline_tables.py` | +38 |
| `unit/test_tools_registry.py` | 239 → 269（+30）**← R95 解锁** |
| `unit/test_agent_loop_guards.py` | +17 |
| `unit/test_allowed_paths_integration.py` | +7 |
| `unit/office/test_word_template.py` | +4 −1 |
| `unit/test_file_tool_safepath.py` | +4 −1 |
| `unit/test_attachment_context.py` | +1 |

### 6.1.4 方法论盲区（本文 §3.1 的判定不完整）

§3.1 说 PURE-LAG「可安全整替」，这个结论**只对了一半**：

- ✅ **成立的部分**：win7 零独有内容 ⇒ 整替不会摧毁任何 win7 修复。复核是充分的。
- ❌ **不成立的部分**：它**不保证 main 的新测试能在 win7 上跑起来**。测试文件本身没有
  win7 独有内容，不等于它依赖的**被测源码**在 win7 已就位。

正确的判定需要两个独立维度（B4 勘察时只做了第一个的一部分）：

| 维度 | 判据 | 结果 |
|---|---|---|
| **安全性**：整替会不会丢 win7 的东西 | win7-only 行数 = 0（忽略空白 + 编码校验） | ✅ 17/17 通过 |
| **可执行性**：main 的新测试能否在 win7 跑通 | 被测模块**存在** + 所需**符号/行为就位** | ❌ 6/17 不满足，只能靠实跑发现 |

B4 勘察时的「可执行性分级」只检查了**模块存在性**
（`git ls-tree origin/release/win7 -- backend/<mod>/__init__.py`），
而这里缺的是**模块内部的符号与语义**：模块存在，但少了 main 后来加的
`plugin_name` 形参、缺失的 REST 路由、缺失的 profile 工具项、SKILL.md 里缺失的工具名。

⇒ **后续任何「可安全整替」的判定，都必须同时给出安全性与可执行性两个证据。**

### 6.1.5 受阻的 6 个文件与 5 处源码缺口（建议编为 B4b-0）

18 个失败全部指向源码缺口，且**5 处缺口全是双向分叉**（win7 持有独有行）
⇒ 需要行级合并而非整替，属源码级批次：

| 测试文件 | 失败数 | 根因（实读断言/异常） | 源码缺口 |
|---|---|---|---|
| `api/test_permission_routes.py` | 6 | `assert 404 == 200`，路由不存在（list/delete rules、`test_delete_rule_with_evil_origin_returns_403`） | `backend/api/permission_routes.py` **+1 −66** |
| `unit/test_permissions_enforcer.py` | 6 | `TypeError: PermissionRule.matches() got an unexpected keyword argument 'plugin_name'`；`PermissionEnforcer.check()` 同 | `backend/tools/permissions.py` **+6 −46**；main 签名 `matches(self, tool_name, plugin_name: Optional[str] = None)`，docstring「受限插件通配只按权威插件身份匹配」 |
| `integration/test_approval_api.py` | 3 | `TestHarnessProposalDraftApproval`：approve adopts without skill writer / reject marks proposal without mutation / stale approve returns 409 | harness proposal draft 审批链 |
| `unit/test_trust_escalation.py` | 1 | `TypeError: TrustEscalationEnforcer.check() got an unexpected keyword argument 'plugin_name'` | `backend/services/trust_escalation.py` **+9 −12** |
| `unit/test_profiles_default_tools.py` | 1 | `assert 'browser_login' in _PRIMARY_SEED_TOOLS` 失败 | `backend/agents/profiles.py` **+9 −18** |
| `unit/test_shipped_writing_skills.py` | 1 | `assert 'office_refresh_toc' in report.body` 失败 | `backend/skills/skill_md/shipped/report-writing/SKILL.md` **+7 −36**（main 含 `office_refresh_toc` **3 次**，win7 **0 次**）—— 与 §5.1 `office_create_tool.py` 落后 285 行**同源** |

**注意 #2428 的标题是「R95 plugin_name 传播到 enforcer.check — 与 main 对齐」，
但 `PermissionEnforcer.check()` / `PermissionRule.matches()` /
`TrustEscalationEnforcer.check()` 仍不接受 `plugin_name=`** ⇒ R95 只落地了一部分
（足以解锁 `test_agent_tool_gate.py` 与 `test_tools_registry.py`，不足以解锁 enforcer 组）。

### 6.1.6 对 §6 批次表的修正

- **B4b-1 已实施**（PR #2433）：实际收益 **11 个文件 / +373 −2**，不是 19 个。
- **新增 B4b-0（应排在最前）**：对齐 R95 enforcer 的 `plugin_name` 形参链
  （`tools/permissions.py`、`services/trust_escalation.py`）+ `api/permission_routes.py`
  的路由 + `agents/profiles.py` 的 `browser_login`。全部双向分叉 ⇒ **行级合并，源码级，
  风险高于本表其他各项**；完成后上表 6 个测试文件可一并带入（`test_approval_api.py` 的
  3 个 harness proposal 失败需单独看）。
- `report-writing/SKILL.md` 的 `office_refresh_toc` 与 §5.1 的 `office_create_tool.py`
  （B4b-4）**必须同批**，否则技能文档会引导用户调用一个 win7 尚不具备的能力。

---

## 6.2 B4b-0 实施结果（2026-10-24，PR #2454）与 R98 新发现

### 6.2.1 起因：一个可达的、未捕获的运行时 TypeError

`#2428`（`13cb21f48`，标题「R95 plugin_name 传播到 enforcer.check — 与 main 对齐」）
**只改了调用方，没改被调用方**：

```python
# backend/core/legacy/agent.py::_check_permission（2 个真实调用点：:1058、:2661）
plugin_name = self._authoritative_plugin_name(tool_name)
if plugin_name is None:
    return enforcer.check(tool_name, args)
return enforcer.check(tool_name, args, plugin_name=plugin_name)   # ← TypeError
```

而当时 win7 侧三个 callable 都不接受该形参：

| | win7（修复前） | main |
|---|---|---|
| `PermissionEnforcer.check` | `(self, tool_name, args=None)` | 含 `plugin_name` |
| `PermissionRule.matches` | `(self, tool_name)` | `(self, tool_name, plugin_name=None)` |
| `TrustEscalationEnforcer.check` | `(self, tool_name, args=None)`，文件内 `plugin_name` **0 次** | `plugin_name=None` + 传递 |

⇒ 调用**任何已发布的插件工具**（`plugin__<name>__<tool>`，`_authoritative_plugin_name`
返回非 None）都抛未捕获的 `TypeError`。

**CI 全绿也发现不了**：`check(...plugin_name=)` 在 `backend/tests` 里出现 **0 次**，
修复前 `test_permissions_enforcer.py` 是 **51 passed**。最小复现：

```python
e = PermissionEnforcer(mode=PermissionMode.WORKSPACE_WRITE, rules=[])
e.check("bash", {})                                   # 两版都 OK
e.check("plugin__demo__run", {}, plugin_name="demo")
#   修复前: TypeError: ... unexpected keyword argument 'plugin_name'
#   修复后: PermissionDecision(allowed=False, needs_approval=True,
#           reason='workspace_write 模式下 execute 类工具 plugin__demo__run 需要用户审批确认')
```

### 6.2.2 五处源码缺口的处置各不相同

| 文件 | 行数 | 做法 | 依据 |
|---|---|---|---|
| `tools/permissions.py` | 453 → 493 | **整替** | 先扫描：main 版 **0 PEP604 / 0 PEP585 / 0 `zip(strict=)` / 0 `datetime.UTC` / 0 `match`**，本身 py3.8 干净；win7 那 6 行「独有」只是被取代的旧签名与其调用点 |
| `services/trust_escalation.py` | 209 → 217 | 整替 + **splice 回 win7 的 py38 注释**（main 28–30 行 → win7 28–35 行） | main 的措辞在注释里**字面写出** `` ``zip(strict=)`` ``、`` ``datetime.UTC`` ``，而 win7 自己的 `scripts/check_py38_compat.py` 按字面量扫描、不区分注释与代码 ⇒ 直接用 main 措辞会**把闸门弄红** |
| `api/permission_routes.py` | 389 → 454 | 整替 + **改 1 行** | main 只有 1 处 PEP604（`-> JSONResponse \| None`），而这恰是 win7 在本文件唯一的独有内容（win7 写 `-> Optional[JSONResponse]`）；main 已 import Optional |
| `agents/profiles.py` | 1020 → 1032 | 整替 + **4 处保留** | main **根本没 import Optional**；3 处 PEP604 改写；**保留 win7 的 researcher `memory_save` 及两行理由**（main 版整段删除），写入前对 win7 blob 逐字断言 |
| `api/legacy_skill_draft_routes.py` | 513 → 570 | **整替** | `+0 −57` 纯落后、py38 扫描干净；正是 `TestHarnessProposalDraftApproval` 3 个失败需要的 harness proposal adopt/reject 路径 |

外加棘轮基线**只改一条**（`profiles.py` 1021 → 1033）。

win7 那段被保留的注释原文（它解释了自己为什么必须存在）：

```
注意：这段说明本身会被 ``scripts/check_py38_compat.py`` 的正则文本扫描
命中 —— 该脚本按字面量找禁用写法，不区分代码与注释。所以这里刻意不写出
那些符号本身，改用 PEP 编号与自然语言指代。
```

### 6.2.3 并行工作导致 PR 自动缩小（他人独立修了同一处）

PR 开出后基线继续前进，到 `55e874fb2`（#2469）时**他人已独立完成了同一段对齐**：

| 文件 | 新基线状态 |
|---|---|
| `tools/permissions.py` | **IDENTICAL-to-main**（`plugin_name` 出现 9 次） |
| `tests/unit/test_trust_escalation.py` | **IDENTICAL-to-main** |
| `services/trust_escalation.py` | DIFFERS，但差异**正是同一段 win7 py38 注释** ⇒ 他人与我收敛到同一处理 |
| `api/permission_routes.py` | `plugin_name` 出现 7 次 |

于是 #2454 的 diff 自动从 11 files / +589 −11 缩到 **7 files / +256 −3**，
剩余 7 个文件经 `git rev-parse` 逐个比对确认**仍与新基线不同（仍需要）**。

### 6.2.4 CI 红的归因：与改动无关，是 pillow 新通告

`Backend (Python 3.8, Win7 LTS)` 一度 failure，**pytest 步骤全被 skipped**，
挂在 step 8「Enforce Win7 dependency audit gate」：

```
pip findings=71
##[error]pip pillow GHSA-5x8w-8jj5-q52h package_version=10.4.0
        affected_path=Win7 LTS Python 3.8 production path: not covered by policy
```

判定为 **pre-existing** 的证据链：

1. 我的 11 个改动文件里 **policy 0 个、requirements 0 个**
2. **我的分支基点 `7740c6187` 的同一 job 也是 failure**（在我动手之前就红）
3. 他人提交 `a442c159b` 的同一 job 也是 failure
4. 时间线：较早的 `a243282ac` success → 较晚的 `7740c6187`/`9348fc991` failure
   ⇒ 通告在这两个时间点之间披露

他人随后加了豁免但**加了两次**，闸门改报
`policy exception 107: duplicate ('pip','pillow','10.4.0','GHSA-5x8w-8jj5-q52h',...)`，
由 **#2456（`1359e5923`）** 修掉重复。

### 6.2.5 pillow 豁免记录的三处失真（PR #2458，+3 −3）

豁免条目本身保留，但其内容是**照通用 pillow 模板填的**，与本通告不符。实测事实：

| 字段 | 原记录 | 实测 |
|---|---|---|
| `actual_reachability` | 「reachable via user file uploads; conditional based on input format」 | **不可达**：漏洞在 FlashPix(FPX) JPEG-tile 解码器，代码位于 `PIL.FpxImagePlugin`，该插件 import **可选依赖 `olefile`**；两条依赖轨都没装 ⇒ `from PIL import FpxImagePlugin` 直接 `ModuleNotFoundError`、`'FPX' in Image.OPEN` 为 **False** ⇒ 即使上传按内容（OLE2 magic，不看扩展名）构造的文件也到不了解码器 |
| `controls` | 修复需 `>=11/12 on Python >=3.9` | `first_patched_version = 13.0.0`，其 `pyproject.toml` 声明 **`requires-python = ">=3.11"`** ⇒ 比其余 47 条 pillow 豁免**更够不着** |
| `notes` | 「修复需要 >=12.1.1」 | 同上，应为 13.0.0 / Python 3.11 |

实测数据：

```
pillow (py38 轨) 10.4.0    olefile 可导入: False
pillow (v2  轨)  12.3.0    olefile 可导入: False
from PIL import FpxImagePlugin -> ModuleNotFoundError: No module named 'olefile'
'FPX' in Image.OPEN -> False
pillow 13.0.0 的 pyproject.toml -> requires-python = ">=3.11"
```

并补上真正让本条保持关闭的**硬约束**：`olefile` 不得进入任一 requirements ——
否则将来一次加依赖就会静默把已关闭路径变成可触达 RCE，而记录仍声称「已缓解」。

改法：模板文字被约 **32 条** pillow 豁免共用（实测 `needle` 命中 32 次），
全局文本替换有歧义 ⇒ 先定位条目行区间（1407–1420），**只在区间内整行替换**。
改后重校验：合法 JSON、`exceptions` **108 条不变**、**恰好 1 条变更**（index 103）、
变更字段 == `[actual_reachability, controls, notes]`、五元组 **0 重复**
（不重演 #2456 之前的 `duplicate` 失败）、LF 保持。

### 6.2.6 新发现：R98（main 在 R95 之后又演进了插件通配语义）

合并 #2433 后 `test_agent_tool_gate.py` **又落后 61 行**，新增 2 个失败：

```
test_plugin_wildcard_unpublished_tool_denied_by_profile_r98
test_plugin_wildcard_uses_published_identity_not_prefix_r98
```

R98 的语义（引自 main 的测试注释）：

```python
def test_plugin_wildcard_uses_published_identity_not_prefix_r98(self):
    # 工具名字符串以 plugin__demo__ 开头、但权威身份是 demo__sub
    # 时，demo 的单插件通配不得带飞，demo__sub 的通配才命中。
    bridge = MagicMock()
    bridge.published_tool.return_value = SimpleNamespace(plugin_name="demo__sub")
```

即**通配匹配必须按权威身份而非名称前缀** —— 这是 R95「传播 plugin_name」之后的下一步：
光有权威身份还不够，匹配逻辑本身也要改用它。win7 尚未跟进。

### 6.2.7 B4b-5 已空（重要结论）

按 §6 的定义重跑归因后（基线 `55e874fb2` ↔ main `7c38c4113`，real **87** =
1 假差异 + 86 genuine），**PURE-LAG 只剩 5 个**（从 17 降），
而「NEEDS-REVIEW 里 win7 独有 ≤2 行且落后 ≥10」的 B4b-5 候选**只剩 1 个**：
`unit/tools/test_office_create_tool.py` `+1 −102`，其唯一 win7 独有行是

```python
assert set(props.keys()) == {"doc_type","output_dir","filename","content","font_family"}
```

这正是 §5.1 的同源项（office schema 落后 285 行），**单独带入必然失败**。

而那 5 个 PURE-LAG 经双维度复核后的归属是：

| 文件 | 落后 | 归属 |
|---|---|---|
| `integration/test_approval_api.py` | −135 | **已被 #2454 覆盖** |
| `unit/test_agent_tool_gate.py` | −61 | **需要新的 R98 对齐** |
| `unit/test_profiles_default_tools.py` | −13 | **已被 #2454 覆盖** |
| `unit/test_permissions_enforcer.py` | −8 | **已被 #2454 覆盖** |
| `unit/test_shipped_writing_skills.py` | −6 | **被 B4b-4 阻塞**（需 `office_refresh_toc`） |

实跑印证：整替这 5 个后 py38 compile rc=0、collect **111 tests / 0 errors**，
但 v2 pytest **7 failed / 104 passed**，7 个失败正好落在上表后三类
（3 个 HarnessProposalDraftApproval + 2 个 R98 + 1 个 browser_login + 1 个 office_refresh_toc）。

⇒ **B4b-5 无独立工作可做，应从批次表中移除**；后续只有 R98 与 B4b-4 两条线。

---

## 6.3 通道故障与两个 API 推送陷阱

`github.com:443` 在本轮内多次完全不通（`curl` 返回 000 / 12–21s 超时），
而 `api.github.com:443` 稳定（200 / 0.4s）⇒ 推送改走 **Git Data API**
（blobs → tree → commit → ref），且**在主机侧用 `gh api` 执行，token 不出主机、不进日志**。

途中踩到两个陷阱，都会产生「看起来成功」的错误结果：

1. **上传了工作区字节而非 git 存储字节**。`core.autocrlf=true` 下工作区是 CRLF、
   blob 对象是 LF，直接 `open(path,'rb')` 上传会重写每一处行尾，
   产生的 commit tree 与本地不一致（stats **+2872 −2501** 而不是 **+373 −2**）。
   修法：blob 内容一律取 `git cat-file blob HEAD:<path>`。
   第二次推送后 **TREE IDENTICAL**（`3464ce8ca…`，两侧 stats 一致）。

2. **新分支取不到远程 tip 时回退用了本地陈旧 parent**。第一次推送
   policy 修正时，脚本查「远程分支 HEAD」当 parent，但那是**新建分支**（远程不存在），
   于是回退到本地 `HEAD^` = `7740c6187`（陈旧），产出 `+26 −0`「新增整条豁免」的 diff ——
   若合并到已含该豁免的 `1359e5923`，就会**重演 #2456 刚修掉的 `duplicate` 闸门失败**。
   修法：删除该远程分支，改为显式取 `branches/release/win7` 的 sha 当 parent 与
   `base_tree`，重建后核验 **parent=`1359e5923`、files=1、`+3 −3`、status=modified**。

另两个小陷阱：`git rev-parse <rev>:<path>` 对**不存在**的路径会把参数本身打到 stdout
再返回非零，`W=$(... || echo ABSENT)` 于是得到两行、比较失败 ⇒ **误报 PRESENT**
（一度让我以为 4 个文件已被带入，实际只有 1 个）；`--force-with-lease=<branch>:<sha>`
要求 **40 字符完整 sha**，缩写会报 `cannot parse expected object name`。

force push 前先证明安全：`git merge-base --is-ancestor 1359e5923 origin/release/win7`
为真 ⇒ 被覆盖的 `4f6ed4fdb`（GitHub `update-branch` 造的 merge commit）内容
已被我的 merge 完整包含，不丢任何代码改动。

---

## 7. 复现

```bash
cd <worktree>            # 基于 release/win7，且已含 B4 的 88 个新增测试文件
PY=<conda>/envs/sage-backend/python.exe

# 1) real 清单（JSON）
$PY scripts/win7/parity_report.py --base origin/main --head HEAD --json <out.json>

# 2) 假差异检测（path move / layout-only）
#    关键：比对 EOL 归一化后的内容，不要用 blob hash（main=LF / win7=CRLF）
git show origin/main:<path> | tr -d '\r' > /tmp/a
git show HEAD:<path>        | tr -d '\r' > /tmp/b
cmp /tmp/a /tmp/b
#    path move：在 main 全树找同 basename 的文件再比
git ls-tree -r --name-only origin/main | grep "/$(basename <path>)$"

# 3) win7 独有行（去空白后的多重集差集，避免换行重排虚增计数）
#    win7-only = HEAD 有而 main 无；behind = main 有而 HEAD 无

# 4) 单文件精读
git diff --ignore-all-space -U1 origin/main HEAD -- <path>
```

**注意**：`--ignore-all-space` **不能**识别「同一语句换行方式不同」
（行集合真的变了），所以 LAYOUT-ONLY 必须靠「去空白后按行取多重集差集」来判。
