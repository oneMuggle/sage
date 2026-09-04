# Agent Profile 迁移恢复（2026-09-03）

> **状态：实施中**
>
> **已完成（本次分支）：**
> - **Task 1** §3 coder 硬编码修正（`profiles.py:113` 改为 `["read_file", "write_file", "bash", "calculator"]` + 既有测试加断言）
> - **Task 1+** §6 primary 直接 fetch/download（用户可见 LLM 取页 / 便于分步指导）—— 工具白名单加入 `web_fetch` / `http_download`，系统提示升级到 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`；存量 DB 走 `BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT` 链式升级
>
> **未交付（按优先级）：**
> 1. **HIGH** §2：subset 迁移（`_append_missing_tools` + `_PRIMARY_CURRENT_DEFAULT_TOOLS`）—— PR-3 时期 DB（primary 5 工具）不属于任何 `_BEFORE_*` 旧种子，4 段"集合相等"判定全哑炮；新增兜底段补齐。`primary` 列表应包含 12 个工具（含 `web_fetch` / `http_download`）。
> 2. **MEDIUM** §1：`LEGACY_TOOL_NAME_RENAMES` 全表 + 测试 `test_profiles_legacy_tool_rename.py` —— 与 §3 强绑定（硬编码改完 + 旧 DB 重命名 = 完整修复）。
>
> 本文件保留作为 backlog，下次 session 接续时直接读。

## 背景与目标

PR #381（commit `81a20b0b`，2026-08-29）把 `TerminalTool` 重写为 `BashTool`，
新工具 `name = "bash"`；PR #396（commit `d6185b76`）又给 primary 加了一组
`grep_search / glob_search / file_summary / agent / todo_write`，并把
researcher 的白名单追加 `http_download`。两份 commit 都遵守"用硬编码旧种子
集合 + 集合相等判定"的方式在 `ensure_default_agents()` 里做存量 DB 升级。

但用户的 DB（`~/.config/sage/sage.db`）**没吃到这两次迁移**：

| agent | DB 实际 | profiles.py 当前默认 | 差集 |
|---|---|---|---|
| coder | `file_read, file_write, terminal, calculator` | `read_file, write_file, bash, calculator` | 全部 4 个名字错位 |
| primary | `calculator, memory_search, memory_save, list_dir, read_file` | 12 个工具（含 §5 的 web_fetch / http_download） | 缺 7 个 |
| researcher | `web_search, web_fetch, memory_search` | `… + http_download` | 缺 http_download |

**直接后果**：
1. UI 选 coder 后，LLM 看到的 schema 集合是 `calculator`（4 个白名单里只有
   1 个能命中当前 registry）→ 报"没有 bash 工具"；
2. UI 选 primary，LLM 看不到 grep_search / glob_search / file_summary / agent
   / todo_write → 失去代码探索 + 子代理委派 + 任务清单三件套；
3. UI 选 researcher，LLM 看不到 http_download → 内网取页下载失效（PR #396
   主功能）。

**根因**：现有 `_PRIMARY_TOOLS_BEFORE_AGENT` / `_PRIMARY_TOOLS_BEFORE_TODO`
/ `_RESEARCHER_TOOLS_BEFORE_HTTP_DOWNLOAD` 用 **`set(tools) == X` 严格相等**
判定。用户 DB 的形状是 PR-3 时期的 5 个工具种子，**不属于任何一段"旧种子"**
→ 4 段迁移全部哑炮。叠加 PR #381 的 `terminal → bash` 重命名没有任何迁移兜底，
coder 永远卡在旧名字。

**目标**：
1. 让 DB 旧形状能吃到所有累计的工具增补 + system_prompt 升级；
2. 让 coder 的 `terminal / file_read / file_write` 在启动时被一次性重命名到
   当前名字；
3. coder / primary / researcher 的白名单终态与 `profiles.create_default_agents()`
   当前默认一致；
4. 用户**手动编辑过**的白名单一律不动（与既有 `_BEFORE_*` 集合相等判定
   同等尊重）。

**非目标**：
- 不为 primary 加 `bash`（维持 PR #396 的"coordinator + 委派"边界）。
- 不改 ToolRegistry / SageAgent 的接口。
- 不引入新依赖、不改 release 流程。

---

## 1. 工具名重命名迁移（coder 专属）

PR #381 的硬切断（删除 `TerminalTool`）没有任何 migration。本节补这一段。

### 1.1 触发条件

对**每个** agent profile（不限 id），若其 `tools` 列表含以下任意旧名，按
映射重命名；不在映射里的名字保持原样。重命名是**逐元素 in-place 替换**，不
重排序（保留 DB 现状的顺序，便于人肉 diff）。

```python
LEGACY_TOOL_NAME_RENAMES: Dict[str, str] = {
    "terminal":   "bash",       # TerminalTool → BashTool (PR #381)
    "file_read":  "read_file",  # 旧 read_file → read_file
    "file_write": "write_file", # 旧 write_file → write_file
}
```

### 1.2 边界

- **不区分 agent id**：理论上一个 agent 可能自定义过 `terminal`（用户拼写错
  或私有别名），但概率极低，且按映射改名后行为更接近用户意图（"想调 bash
  → 拿到 bash"）。若真误伤，用户可手动从 UI 改回。
- **不区分 enabled**：被禁用的 agent 也执行重命名（避免将来启用时再错）。
- **不动空 list**：若 `tools == []` 或 `None`，跳过。

### 1.3 幂等性

第二次跑 `ensure_default_agents()` 时，旧名已不存在 → 映射是 no-op →
`tools` 列表与上次完全一致 → 不触发 `upsert`（参考 §3.3）。

---

## 2. 启动时差集迁移（primary / researcher）

把现有的"集合相等"判定放宽为"**当前默认 ⊆ DB**"——如果 DB 白名单是当前
默认的超集，**只追加缺的**，不删用户额外项。

### 2.1 新增迁移段（在 `ensure_default_agents()` 内）

```python
# 2026-09-03 (PR #396 后置修复): 集合相等判定太严，PR-3 时期 DB 形状
# 不命中任何 _BEFORE_* 段，导致 4 段累计迁移全哑炮。改为 "当前默认 ⊆
# DB" 判定: 只要 DB 白名单是当前默认的超集, 把缺的工具按当前默认顺序
# 追加到尾部; 用户额外项保留在原位置。
def _append_missing_tools(agent: dict, current_default_tools: List[str]) -> bool:
    db_tools = agent.get("tools") or []
    missing = [t for t in current_default_tools if t not in db_tools]
    if not missing:
        return False
    agent["tools"] = db_tools + missing
    return True
```

调用点（插入位置：`ensure_default_agents()` 函数体，原 4 段之前**或**之后皆
可；放最后便于一次跑完所有"集合相等"判定后再做兜底）：

```python
# 2026-09-03 兜底: 当前默认 ⊆ DB → 追加缺的; 真超集 / 集合相等 / 不
# 相交都跳过。用户任意增删都不影响。
# primary 默认值见 §4 架构决定, 不含 bash (协调/委派边界)。
for agent_id, default_tools in (
    ("primary",    _PRIMARY_CURRENT_DEFAULT_TOOLS),
    ("researcher", _RESEARCHER_CURRENT_DEFAULT_TOOLS),
):
    row = repo.get(agent_id)
    if row is None:
        continue
    if _append_missing_tools(row, default_tools):
        repo.upsert(row)
```

### 2.2 边界

- **真超集**（用户额外加了工具）：`missing == []` → 不动。
- **集合相等**：同上，不动。
- **真子集**（DB 是当前默认的子集）：追加缺的，DB 多出来的（用户删过的）也
  不还原。
- **完全不相交**（用户整个白名单换掉了）：不动。这通常意味着用户彻底重写
  了白名单，强行追加会污染意图。
- **空 list / None**：按"完全不相交"处理（用户显式清空），不动。

### 2.3 幂等性

第二次跑时 `missing == []` → 不动 → 不触发 `upsert`。测试断言同 §1.3。

### 2.4 与现有 4 段"集合相等"迁移的关系

保留现有 4 段不动。原因：现有 4 段的精确语义是"白名单**恰好等于**旧种子
时升级"，是更窄的判定；与新增的兜底段不互相影响。即使未来再加第 5 段
"集合相等"迁移，两者并存：精确段优先触发特定升级（如 system_prompt 文字
替换），兜底段负责 tools 白名单的最终一致性。

**新引入的常量**（2026-09-03 更新：primary 列表扩到 12 个，含 §5 的直接 fetch/download）：

```python
# 2026-09-03: 当前 primary 默认工具列表(去掉 bash,见 §4 架构决定)。
# §5 起新增 web_fetch/http_download (用户可见 LLM 行为, 便于分步指导)。
_PRIMARY_CURRENT_DEFAULT_TOOLS = [
    "calculator", "memory_search", "memory_save",
    "list_dir",   "read_file",
    "grep_search","glob_search","file_summary",
    "agent",      "todo_write",
    "web_fetch",  "http_download",
]

# 2026-09-03: 当前 researcher 默认工具列表。
_RESEARCHER_CURRENT_DEFAULT_TOOLS = [
    "web_search", "web_fetch", "http_download", "memory_search",
]
```

---

## 3. `profiles.py` 硬编码修正

`create_default_agents()` 第 111 行（coder profile）改：

```diff
- tools=["file_read", "file_write", "terminal", "calculator"],
+ tools=["read_file", "write_file", "bash", "calculator"],
```

**注释同步**：在变更处补一行注释，指明这是 `BashTool` 重命名后的结果，避免
后续再出现"profiles.py 与 `bash_tool.py` 工具名错位"。

---

## 4. primary 仍不加 bash（架构边界）

PR #396 的设计原则是 primary 是 coordinator / 出网委派，**本次不动**。

| 决定 | 取舍 |
|---|---|
| 不为 primary 加 bash | 维持 coordinator / executor 角色分离；shell 执行仍走 `agent` 委派给子代理 |
| （未来若用户要破例） | 单独走一个 PR，加 `bash` 到 `_PRIMARY_CURRENT_DEFAULT_TOOLS` 即可，本设计的兜底段会自动覆盖到 DB |

`PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`（见 §5）保留委派提示段不变；`_PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION`
判定不变。

---

## 5. primary 直接 fetch/download（用户可见 / 分步指导）

### 5.1 背景与目标

PR #396 的"primary 全委派"设计在两类场景下用户体验欠佳：

1. **简单任务**（"帮我取一下这个 URL 的内容"）：委派给子代理 → 子代理把结果回灌给 primary → primary 再说一遍 → 用户看不到中间过程
2. **分步指导**（"先打开 A 页面，再点 X 按钮，再..."）：用户需要看到 LLM 访问了哪个 URL / 下载了什么文件，才能给出下一步指令

解决方案：**给 primary 也开放 `web_fetch` + `http_download` 两个只读工具**（`web_search` 不开，仍走委派，因为搜索是高频调用会污染 LLM 直觉）。这两个工具的特性：

- **只读 / 落地**：无副作用（取页是 read-only；下载会写工作区但用户可见 + 可审批）
- **可见性**：ToolRegistry 已在 `backend/tools/__init__.py` 注册，每次调用都有 UI 流（用户能看到 URL / 文件名）
- **网络门禁**：仍受 `NetworkPolicy` 控制；OFFLINE 模式下不注册，primary 即使白名单里有也调不到

### 5.2 改动

| 项 | 旧 | 新 |
|---|---|---|
| `create_default_agents()["primary"].tools` | 10 个（含 `agent` + `todo_write`）| 12 个（+ `web_fetch` + `http_download`） |
| `create_default_agents()["primary"].system_prompt` | `PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION` | `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` |
| `_PRIMARY_CURRENT_DEFAULT_TOOLS` | 10 元素 | 12 元素 |
| `ensure_default_agents()` system_prompt 升级 | 单段 `BEFORE_DELEGATION → WITH_DELEGATION` | 链式 `BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT`（合并为单次 upsert） |

### 5.3 新增常量

```python
# 2026-09-03 (post-§2 subset 迁移): primary 也可直接 fetch/download。
# 保留委派段 (复杂研究仍走子代理); 加一段明确指引 simple fetch/download
# 可由 primary 直调 —— 用户可见 LLM 行为, 便于分步指导。
PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT = (
    "你是 Sage，一个智能 AI 助手。负责理解用户需求并协调其他 Agent 完成任务。\n\n"
    "你可以直接调用 web_fetch（取网页内容）和 http_download（下载文件到工作区）"
    "进行简单的网页访问/文件下载，让用户能实时看到你访问的 URL 和下载的文件，"
    "便于分步指导和交互。\n"
    "对于复杂的多步研究任务，使用 agent 工具委派给只读子代理执行"
    "（子代理具备 web_search / web_fetch / http_download / memory_search 等只读工具）。"
    "直接回答时不要假装调用了这些工具。"
)
```

### 5.4 升级链（链式合并为单次 upsert）

```python
# 2026-09-03 (post-§2): system_prompt 二段升级链。
# BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT
# 顺序敏感; 任何一段命中就一气呵成, 避免两次 upsert。
prompt = primary.get("system_prompt")
if prompt == _PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION:
    prompt = PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION
if prompt == PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION:
    prompt = PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
if prompt != primary.get("system_prompt"):
    primary["system_prompt"] = prompt
    repo.upsert(primary)
```

边界：用户自定义 system_prompt（不等于任一旧字符串）→ 全段跳过 → 不动。

### 5.5 幂等性

第二次跑 `ensure_default_agents()` 时：
- tools 子集兜底（Task 3）已是 12 元素 → 不追加 → 不 upsert
- system_prompt 已是 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` → 三段 if 全跳过 → 不 upsert

测试断言：连续两次调用，第二次 0 upsert。

### 5.6 与 §2 兜底段的关系

`_PRIMARY_CURRENT_DEFAULT_TOOLS` 扩到 12 元素后，§2 的 `_append_missing_tools` 兜底段自动覆盖：

| 用户 DB 状态 | 现有 tools 迁移 | system_prompt 迁移 |
|---|---|---|
| 8 工具 (PR-3 早期) | `_PRIMARY_TOOLS_BEFORE_AGENT` 段 → 9 工具 → `_PRIMARY_TOOLS_BEFORE_TODO` 段 → 10 工具 → §2 兜底 → 12 工具 | `_PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION` → `WITH_DELEGATION` → `WITH_FETCH_DIRECT` (单次 upsert) |
| 10 工具 (PR-3) | §2 兜底 → 12 工具 | 同上 |
| 12 工具 (current) | 不动 | 同上 |
| ≥12 工具 (含用户额外项) | 不动 | 不动 |

升级链中任一段命中，整个链都吃到；用户已升级到 `WITH_FETCH_DIRECT` 时全段跳过。

---

## 6. 测试

### 6.1 新增文件

`backend/tests/unit/test_profiles_legacy_tool_rename.py`：

- `test_coder_terminal_renames_to_bash`：DB 存 `["terminal"]` → 跑后变成 `["bash"]`。
- `test_coder_file_read_write_renames`：DB 存 `["file_read","file_write"]` → 变成 `["read_file","write_file"]`。
- `test_renames_preserve_user_extras`：DB 存 `["terminal","my_custom"]` → 变成 `["bash","my_custom"]`，用户项不动。
- `test_renames_idempotent`：`tools` 已经全是新名 → 第二次跑 `upsert` 0 次。
- `test_renames_only_affects_three_legacy_names`：DB 存 `["foo","bar"]` → 完全不动。

### 6.2 新增文件

`backend/tests/unit/test_profiles_subset_migration.py`：

- `test_primary_subset_gets_missing_appended`：DB 存 `["calculator", …, "read_file"]`（5 工具）→ 跑后追加缺的 7 个工具（到 12 个当前默认），原顺序保留。
- `test_primary_superset_untouched`：DB 存 `["calculator", …, "read_file", "user_extra"]` → 完全不动。
- `test_primary_disjoint_untouched`：DB 存 `["my_a","my_b"]`（完全不相交）→ 完全不动。
- `test_researcher_subset_gets_http_download_appended`：DB 存 `["web_fetch","http_download","memory_search"]`（**刻意缺 web_search, 不命中既有 _RESEARCHER_TOOLS_BEFORE_HTTP_DOWNLOAD 段**）→ 走子集段追加 `web_search`；断言第 2 次 `upsert` 0 次。
- `test_researcher_already_current_no_upsert`：DB 已是 4 工具当前默认 → 不触发 `upsert`。
- `test_subset_migration_idempotent`：连续跑两次，第二次 `upsert` 0 次。

### 6.3 既有文件更新

`backend/tests/unit/test_profiles_intranet_web_access_migration.py`：

- 加 1 个断言（**Task 1，已完成**）：`test_default_seed_coder_uses_current_tool_names` 验证
  `create_default_agents()["coder"].tools` 是 `["read_file", "write_file", "bash", "calculator"]`
  （顺序敏感）。
- **§5 fetch_direct 实现后**加 4 个断言：
  - `test_default_seed_primary_includes_fetch_download`：验证 `create_default_agents()["primary"].tools` 含 `web_fetch` + `http_download`。
  - `test_default_seed_primary_uses_fetch_direct_prompt`：验证 `create_default_agents()["primary"].system_prompt` 是 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`。
  - `test_primary_system_prompt_legacy_two_step_chain_migration`：DB system_prompt 是 `_PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION` → 升级到 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`（合并为单次 upsert）。
  - `test_primary_system_prompt_with_delegation_one_step_migration`：DB system_prompt 是 `PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION` → 升级到 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`。
  - `test_primary_system_prompt_already_fetch_direct_no_upsert`：DB system_prompt 已是 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` → 0 upsert。

### 6.4 覆盖率目标

`profiles.py` 行覆盖 ≥ 80%（既有 `_BEFORE_*` 常量都已覆盖；本 PR 新增的
段需在 6.1 / 6.2 测试里覆盖到 `if row is None`、`missing == []`、`tools
is None` 三条分支）。

### 6.5 不在范围内

- 不加 e2e：本次改动纯 DB + 内存，e2e 已在 PR #396 / #381 覆盖 bash 与
  http_download 的运行时；新增 e2e 收益低。
- 不加集成测试：现有 `tests/integration/test_chat_office_tools.py` 等已验
  证 `get_schemas_for_llm` 的过滤行为；本次改动只动 `profiles.py`，
  不动 registry 接口。

---

## 7. 验收清单

- [ ] `pytest backend/tests/unit/test_profiles_legacy_tool_rename.py` 全绿
- [ ] `pytest backend/tests/unit/test_profiles_subset_migration.py` 全绿
- [ ] `pytest backend/tests/unit/test_profiles_intranet_web_access_migration.py` 全绿
- [ ] `pytest backend/tests/unit/ -k "profile or agent_helper"` 全绿
- [ ] 用户 DB `~/.config/sage/sage.db` 启动后端一次后：
  - coder.tools 变为 `["read_file", "write_file", "bash", "calculator"]`
  - primary.tools 变为 12 个当前默认（含 web_fetch + http_download，顺序与 `_PRIMARY_CURRENT_DEFAULT_TOOLS` 一致）
  - researcher.tools 变为 4 个当前默认
  - 若 primary.system_prompt 是 `_PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION` → 升级到 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`（合并为单次 upsert）
  - 若 primary.system_prompt 是 `PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION` → 升级到 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`（单次 upsert）
- [ ] 第二次重启后端：上述三个 agent 的 `updated_at` 不再抖动（无 `upsert` 发生）
- [ ] UI 选 coder profile → LLM schema 列表包含 `bash`（用 `curl /api/v1/chat/...` 抓一下首轮 request 里的 tools 字段）
- [ ] UI 选 primary profile → LLM schema 列表包含 `web_fetch` + `http_download`（OFFLINE 模式下应自动从 schema 中过滤掉）
- [ ] CHANGELOG.md 增加一条 `fix(agents): …`（按既有格式）
- [ ] 不在 release/win7 触发任何变更（PR 不动 `backend/requirements-py38.txt`、不动 win7 独有的测试）

---

## 8. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 差集迁移误把"用户私有别名"加成"默认工具" | 低 | 中 | "完全不相交才不动"的边界（§2.2）+ idempotent 测试 |
| 工具名重命名误伤 `terminal` 作他义工具名的 agent | 极低 | 低 | 映射表小且单一含义；用户可 UI 改回 |
| 现有 4 段"集合相等"段被新兜底段干扰 | 低 | 中 | 不删旧段；新段只追加，不改写 |
| 链式 system_prompt 升级顺序错（WITH_DELEGATION → BEFORE_DELEGATION）| 极低 | 中 | `if prompt == A` 单调链，逻辑反向无意义；测试覆盖两步 / 一步 / 跳过三种路径 |
| primary 直调 web_fetch/http_download 偶发调用 http:// 失败 | 低 | 低 | ToolRegistry 仍受 NetworkPolicy 控制，OFFLINE 不注册 |
| DB schema 未升级，旧 DB 不含 `updated_at` 字段 | 极低 | 高 | `_row_to_dict` 已含 fallback（`agent_repo.py:202`） |

回滚：`git revert` 即可。新增的兜底段是纯追加，没有副作用累积；下次启动
会按当前代码重新判定，行为可预测。

---

## 9. 关联文件

| 文件 | 操作 |
|---|---|
| `backend/agents/profiles.py` | 改 `create_default_agents()["coder"].tools`（§3，Task 1 已完成）；改 `create_default_agents()["primary"].tools` + `.system_prompt`（§5，Task 5）；新增 `_LEGACY_TOOL_NAME_RENAMES` / `_PRIMARY_CURRENT_DEFAULT_TOOLS` / `_RESEARCHER_CURRENT_DEFAULT_TOOLS` 常量；新增 `_append_missing_tools` 助手；新增 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` 常量；扩展 `ensure_default_agents()`（含 §5 的 system_prompt 链式升级）|
| `backend/tests/unit/test_profiles_legacy_tool_rename.py` | 新增 |
| `backend/tests/unit/test_profiles_subset_migration.py` | 新增 |
| `backend/tests/unit/test_profiles_intranet_web_access_migration.py` | 加 1 个断言（Task 1 已完成）+ §5 加 4 个断言（Task 5）|
| `CHANGELOG.md` | 加 `fix(agents): …` 条目 |

`backend/main.py` 的 `lifespan` / `backend/data/agent_repo.py` 的 `upsert` /
`backend/tools/registry.py` 的 `get_schemas_for_llm` **均不动**。