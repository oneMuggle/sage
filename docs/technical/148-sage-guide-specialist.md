# Sage 向导专家（`sage-guide`）

> 内置不可删除的官方向导：解答 Sage 用法、引导排障、按需修改 Sage 配置。
> 相关章节：[133 专家系统](./133-specialist-persona.md)、[41 sage doctor](./41-sage-doctor.md)、[47 Git Worktree](./47-git-worktree-workflow.md)。

## 1. 目标与边界

向导解决一类具体问题：**通用助手答不准 Sage 自身的项目特定问题**。重试默认次数、端口约定、权限档位、Win7 分支差异、配置键白名单……这些都是训练数据里没有的，需要让 LLM 直接读仓库文档 + 实时状态。

| 能力 | 说明 |
|---|---|
| 解答 | 基于内置文档（用户手册 + 精选技术章节）回答"怎么用 / 为什么这样" |
| 指导 | 结合实时状态工具 `sage_self_status` / `sage_doctor` / `sage_usage` 引导排障 |
| 改参数 | `read_sage_config` → 说明影响 → 用户确认 → `update_sage_config` → 回读校验 |

非目标：

- ❌ 通用编程 / 写作 / 调研（那是其他 5 套模板的职责）
- ❌ 写工作区文件、跑 shell、装依赖、改数据库
- ❌ 新增第三方依赖（jieba + sqlite3 FTS5 已存在）

---

## 2. Profile 定义

| 字段 | 值 |
|---|---|
| `id` | `sage-guide` |
| `name` | `Sage 向导` |
| `role` | `specialist` |
| `source` | `builtin` |
| `description` | 解答 Sage 使用问题、引导排障、按需修改 Sage 配置 |
| `tools` | `read_sage_config` / `update_sage_config` / `diagnose_sage_config` / `sage_self_status` / `sage_doctor` / `sage_usage` / `ask_user_question` |
| `skills` | `[]`（fail-closed，无技能） |
| `knowledge_bindings` | 单绑定 `sage_docs`（见 §3） |
| `memory_access` | `[]`（禁止读任何记忆层，避免误引用隐私） |
| `memory_policy` | `{read_scopes: [], write_scope: "project", auto_extract: false}` |
| `permission_mode` | `workspace_write`（配置写入仍需逐次批准） |
| `model_config` | `temperature=0.3`（事实性回答低随机性） |
| `max_iterations` | `12` |
| `persona_ui` | `{avatar: "🧭", tagline: "Sage 用法与配置向导"}` |

`tools` 用 `*CONFIG_TOOLS + *SELF_STATUS_TOOLS + ("ask_user_question",)`
（从 `backend/domain/tool_names.py` 导入常量，避免字面量漂移）。

---

## 3. 知识源 `sage_docs`

### 3.1 路径解析（`backend/services/sage_docs/paths.py`）

按优先级解析文档根目录：

```
1. 显式覆盖：env SAGE_DOCS_DIR（测试 / 高级排障）
2. 打包态：Electron spawnBackend() 注入 SAGE_DOCS_DIR = <resourcesPath>/docs
3. 启发式（后端被独立启动时）：
   - <backend_root>/../docs              （仓库布局 / 打包后 backend 同级）
   - <sys._MEIPASS>/docs                 （PyInstaller onedir/onefile）
4. 全部不存在 → 返回 None，检索层 fail-open 返回空结果
```

### 3.2 文档白名单

白名单抽成单一常量，**三处共用同一份列表**：

- `electron-builder.yml` `extraResources` filter
- `scripts/backend.spec` PyInstaller `datas` filter
- `backend/services/sage_docs/paths.py::TECHNICAL_WHITELIST`

```
docs/user-manual/**/*.md              （全部，40+ 篇）
docs/technical/README.md
docs/technical/15-state-ownership.md
docs/technical/18-hexagonal.md
docs/technical/20-electron.md
docs/technical/22-agents-crud.md
docs/technical/24-skills-system.md
docs/technical/32-settings-canonicalization.md
docs/technical/41-sage-doctor.md
docs/technical/47-git-worktree-workflow.md
docs/technical/133-specialist-persona.md
docs/technical/135-specialist-asset-hub.md
docs/technical/139-specialist-dm-group-chat.md
docs/technical/148-sage-guide-specialist.md    （本节自身）
```

> 技术手册刻意只带"配置 / 权限 / 排障 / 专家"相关的 13 篇（含本节）+
> 全量用户手册，避免安装包膨胀与噪声召回。

### 3.3 索引库（`indexer.py`）

- 位置：`~/.sage/sage-docs-index/index.sqlite3`（覆盖：`SAGE_DOCS_INDEX_DIR`）
- 表：`docs_meta`（`rel_path` + `mtime_ns` + `size` + `sha1`）+ `chunks`（按 Markdown 标题切段，单段超 1200 字符按段落二次切分，重叠 100 字符）+ `chunks_fts`（FTS5，`content_tok` 为 jieba 空格分词后的文本）
- 增量：`(mtime_ns, size, sha1)` 指纹未变跳过；文件被删清索引
- 分词：写入 `backend.memory.chinese_tokenizer.tokenize()`（jieba 词间空格）；
  查询 `tokenize_for_search()`（`"用户" OR "喜欢" OR "火锅"` 形式）

> **中文召回必要步骤**：FTS5 `unicode61` tokenizer 不切中文，必须预分词。
> `workspace_index.py` 因直接写原文中文召回弱，本索引不能照抄。

### 3.4 检索（`search.py` + `knowledge_retriever.py`）

```python
def _search_sage_docs(
    binding: KnowledgeBinding,
    query: str,
    query_vector: Optional[List[float]],  # 忽略（纯关键词召回）
    limit: int,
) -> List[SourceHit]:
    ...
```

- 签名与 `wiki_project` / `project_material` / `specialist_private` 完全一致（四参数 + `List[SourceHit]`）
- 每命中构造 `SourceHit(doc_id=f"{rel_path}::{chunk_index}", content=..., loc={"rel_path":..., "heading":..., "start_line":...})`
- 通过既有管道进入 `retrieve_knowledge_context()` → `(knowledge_block, sources, no_hit_hint)` → `dynamic_context_parts`
- 无命中给出 `no_hit_hint`（"内置文档中未找到相关内容，请确认是否属于 Sage 功能"）
- **fail-open**：索引构建失败 / 文档缺失 / sqlite 异常 → 记 `logger.warning`，返回空结果，**绝不**因知识库故障让对话失败

### 3.5 绑定注册

```python
KNOWLEDGE_SOURCE_TYPES = (..., "sage_docs")

# 种子绑定（完整字段，_coerce_binding 要求全字段可解析）
{
    "id": "sage-guide-docs",
    "agent_id": "sage-guide",
    "source_type": "sage_docs",
    "source_id": "bundled",
    "name": "Sage 内置文档库",
    "filters": {}
}
```

---

## 4. 权限加固

两处现存缺陷同步修复，缺一不可。

### 4.1 profile 权限上限（`agent.py`）

`_build_permission_enforcer()` 原本只读全局设置，**从未应用 `profile["permission_mode"]`**。
修复：`load_enforcer_from_settings(...)` 之后，若 `role == "specialist"` 且 profile 声明的 mode 更严格，调用 `PermissionEnforcer.force_mode()`（实例级覆盖，不写回 settings 文件）。

```python
_SPECIALIST_MODE_RANK = {
    "read_only": 0, "prompt": 1, "workspace_write": 2, "full_access": 3,
}

def _apply_specialist_cap(profile, base):
    if not isinstance(profile, dict): return base
    if profile.get("role") != "specialist": return base
    profile_mode = profile.get("permission_mode")
    if profile_mode not in _SPECIALIST_MODE_RANK: return base
    current_value = getattr(base.mode, "value", base.mode)
    if _SPECIALIST_MODE_RANK[profile_mode] < _SPECIALIST_MODE_RANK[str(current_value)]:
        base.force_mode(PermissionMode(profile_mode))
    return base
```

只降不升（`min` 语义）；只作用于 `role == "specialist"`；主助手与子代理行为不变。

### 4.2 自管理工具永不自动放行（`trust_escalation.py`）

`TrustEscalationEnforcer.check()` 在 `needs_approval` 时只排除路径边界类原因与危险 bash，
**没有排除 `SELF_MODIFY_TOOLS`**。用户连续 3 次批准 `update_sage_config` 后，第 4 次会被自动放行 —— 与"逐次批准"设计意图冲突。

修复（放在 EXECUTE 检查前，因为 `update_sage_config` 是 CONFIG 类工具而非 EXECUTE，不会被 bash 安全网拦截）：

```python
if tool_name in SELF_MODIFY_TOOLS:
    return decision   # 永不自动放行
```

`SELF_MODIFY_TOOLS = frozenset({"update_sage_config", "schedule_task", "cancel_scheduled_task", "wake_session_at", "wake_on_background"})`。

### 4.3 删除保护

`backend/api/legacy_agent_routes.py`：`PROTECTED_AGENT_IDS = frozenset({"primary", "sage-guide"})`，单删 + 批删共用同一内部函数，删除返回 `{"type":"protected_agent","message":"..."}`。

前端 `Specialists.tsx`：`PROTECTED_AGENT_IDS = new Set(['primary', 'sage-guide'])`，卡片 `selectable=false`、删除入口隐藏、"内置"徽章沿用 `source == "builtin"` 既有逻辑。

### 4.4 模板特判（关键陷阱）

`specialist_importer._sanitize_bindings()` 只保留 `specialist_private` 绑定，其余一律丢弃进 `dropped_bindings`。**因此不能让 `sage-guide` 走通用导入路径**，否则 `sage_docs` 绑定必丢。

方案：`instantiate_template()` 中对 `sage-guide` 特判 —— 固定 id + 幂等实例化，返回 `existed` 标记。重复点"使用模板"不会产生 `sage-guide-xxxx` 副本。

---

## 5. 打包

| 文件 | 改动 |
|---|---|
| `electron-builder.yml` | `extraResources` 增加 `docs` → `docs`（加白名单 filter） |
| `electron/main.ts` | `spawnBackend()` 在 `app.isPackaged` 时注入 `SAGE_DOCS_DIR: join(process.resourcesPath, 'docs')` |
| `scripts/backend.spec` | PyInstaller `datas` 增加同白名单子集 |

三处共用同一份白名单（注释互相指向），避免漂移。

---

## 6. 测试矩阵

| 层 | 文件 | 覆盖 |
|---|---|---|
| 路径单测 | `test_sage_docs_paths.py` | 覆盖 / 打包 / 仓库 / 全缺失 四态 |
| 索引单测 | `test_sage_docs_indexer.py` | 首建 / 增量 / 删除 / sha1 变化 / 中文分词 |
| 检索单测 | `test_sage_docs_search.py` | 中文查询召回 / 无命中 / 索引损坏 fail-open |
| profile 单测 | `test_agent_profile_sage_guide.py` | 字段齐备 / binding 可解析 / persona 字节一致 |
| 权限上限 | `test_apply_specialist_cap.py` | 9 用例：null profile / 非 specialist / 只降不升 / 非法 mode / 不写 settings |
| trust 升级 | `test_trust_escalation.py::test_self_modify_tools_never_auto_released` | 连续 99 次批准后仍 `needs_approval` |
| 模板 | `test_specialist_templates.py` | 6 模板 / sage-guide 首位 / 实例化两次 `existed=True` |
| 路由 | `test_routes_agents.py` | `EXPECTED_DEFAULT_IDS` 8 个 / 单删批删 400 |
| 集成 | `test_sage_guide_flow.py` | 检索注入 → 工具调用 → 配置写入 → 回读校验 |
| 前端 | `Specialists.test.tsx` | 5/5 通过 |

---

## 7. 已知限制

1. **索引惰性构建首次略慢**：首次问答触发索引构建（~52 篇文档，秒级）。后续检索走增量指纹校验（stat 成本可忽略）。
2. **打包后帮助页历史路径未修**：`electron/main.ts:1740` 的"帮助"页读 `__dirname/../docs/user-manual` 在打包态是坏的（历史问题，本次不修，仅确保向导知识源不依赖该路径）。
3. **中文召回依赖 jieba 分词质量**：极少数专有名词（如 `SAGE_LOCAL_AUTH_TOKEN`）可能被分词器切碎，需查询方写完整 token。
