# Wiki LLM 交互层优化方案

> 对标 `/home/fz/project/llm_wiki` 项目最新实现，将 LLM 交互层成熟特性移植到 sage wiki 子系统

**创建日期**: 2026-11-14
**分支**: `feat/wiki-llm-optimization`

---

## 背景与目标

sage 的 wiki 子系统（`backend/wiki/`）已具备完整的 ingest → RAG chat → 知识图谱 → MCP 暴露链路。
2026-09 的完整性优化（#wiki-completeness-optimization）已补齐队列/Clipper/Lint/Review。

本次对标 `llm_wiki` 最新代码，发现 LLM 交互层仍有以下高价值特性缺失：

| # | 特性 | llm_wiki 现状 | sage 现状 | 影响 |
|---|------|--------------|----------|------|
| 1 | LLM 任务路由 | chat/ingest 可配不同模型 | 统一模型 | 成本 + 质量 |
| 2 | purpose/schema 注入 | 每次 ingest 注入 wiki 定位文件 | 无 | 生成质量 |
| 3 | 推理模式适配 | 完整 provider 适配表 | 基础 effort 参数 | 多 provider 兼容 |
| 4 | Source 目录自动监听 | watchdog 自动触发 ingest | 手动触发 | 用户体验 |
| 5 | 操作日志 log.md | 确定性格式可解析 | 无 | 可追溯性 |

**目标**：实施 #1–#5，提升 wiki 的 LLM 交互质量和可观测性。

---

## 涉及的文件与模块

### 后端

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/wiki/models.py` | 修改 | 新增 `TaskRoutingConfig`、`ReasoningConfig` |
| `backend/wiki/settings.py` | **新增** | settings.json 读写 + 持久化 |
| `backend/wiki/llm_context.py` | 修改 | 支持任务路由：按 task 选模型 |
| `backend/wiki/reasoning.py` | **新增** | Provider 推理模式适配 |
| `backend/wiki/ingest.py` | 修改 | 读取 purpose/schema 注入 prompt + 写 log |
| `backend/wiki/llm_prompts.py` | 修改 | Step3/Step4 prompt 增加 purpose/schema 占位符 |
| `backend/wiki/source_watcher.py` | **新增** | watchdog 监听 raw/sources/ |
| `backend/wiki/operation_log.py` | **新增** | log.md 读写 |
| `backend/wiki/lifecycle.py` | 修改 | delete/rename 写 log |
| `backend/wiki/queue_daemon.py` | 修改 | 启动 source_watcher |
| `backend/api/wiki_routes.py` | 修改 | 新增 `GET/PUT /wiki/settings` |

### 前端

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/shared/types/wiki.ts` | 修改 | 新增 `WikiSettings`、`TaskRouting` 类型 |
| `src/shared/api-client/wiki.ts` | 修改 | 新增 `getSettings`/`updateSettings` |
| `src/entities/wiki/store.ts` | 修改 | 新增 `settings` state + actions |

---

## 技术方案

### 1. LLM 任务路由

**数据模型**（`backend/wiki/models.py`）：

```python
class TaskRoutingConfig(BaseModel):
    chat_model: str | None = None
    ingest_model: str | None = None
    research_model: str | None = None
```

**路由逻辑**（`backend/wiki/llm_context.py`）：

```python
def resolve_model(task: str, settings: TaskRoutingConfig, default: str) -> str:
    mapping = {"chat": settings.chat_model, "ingest": settings.ingest_model, "research": settings.research_model}
    return mapping.get(task) or default
```

**存储**：`.llm-wiki/settings.json`，每个项目独立配置。

### 2. purpose.md / schema.md 注入

**文件约定**：

```
my-wiki/
  purpose.md   # wiki 定位：目标、关键问题、研究范围
  schema.md    # 结构规则：页面类型、命名规范、必须字段
```

**注入时机**：`ingest.py` Step 3（LLM 分析）和 Step 4（LLM 生成）的 prompt。

```python
def _load_wiki_context(project_path: Path) -> dict[str, str]:
    ctx = {}
    for name in ("purpose.md", "schema.md"):
        f = project_path / name
        if f.exists():
            ctx[name] = f.read_text(encoding="utf-8")
    return ctx
```

**Prompt 模板**（`backend/wiki/llm_prompts.py`）增加 `{purpose_section}` 和 `{schema_section}` 占位符。

### 3. 推理模式适配

**Provider 能力表**（`backend/wiki/reasoning.py`）：

```python
REASONING_CAPABILITIES = {
    "openai": ["auto", "low", "medium", "high"],
    "anthropic": ["auto", "low", "medium", "high", "max"],
    "google": ["auto", "low", "medium", "high", "max"],
    "deepseek": ["auto", "high", "max"],
    "ollama": ["auto", "low", "medium", "high", "max"],
}
INGEST_DEFAULT = "off"
CHAT_DEFAULT = "auto"
```

**请求适配**：按 provider 将 reasoning mode 转为对应 API 参数（`reasoning_effort` / `thinking` / `thinking_config`）。

### 4. Source 目录自动监听

**实现**：`watchdog` 库监听 `raw/sources/`。

- 新增文件 → 自动加入 ingest 队列
- 删除文件 → 触发 `lifecycle.py` 级联删除
- SHA256 缓存保证幂等

**集成**：`queue_daemon.py` 启动时创建 `SourceWatcher`，停止时 `observer.stop()`。

### 5. 操作日志 log.md

**格式**：

```markdown
- [2026-11-14T10:30:00Z] ingest: raw/sources/paper.pdf -> wiki/sources/paper.md
- [2026-11-14T10:35:12Z] delete: wiki/sources/old.md (source: paper.pdf)
- [2026-11-14T11:00:00Z] rename: wiki/sources/a.md -> wiki/sources/b.md
```

**调用点**：
- `ingest.py` Step 4 完成 → `append_log(project, "ingest", detail)`
- `lifecycle.py` cascade delete → `append_log(project, "delete", detail)`
- `files.py` rename → `append_log(project, "rename", detail)`

---

## 实施步骤

- [x] M1: 新增 `settings.py` + `TaskRoutingConfig`/`ReasoningConfig` 模型 + settings.json 持久化
- [x] M2: `llm_context.py` 支持任务路由（`resolve_model`）
- [x] M3: 新增 `reasoning.py` provider 推理模式适配
- [x] M4: `ingest.py` + `llm_prompts.py` 加载 purpose/schema 注入 prompt
- [x] M5: 新增 `source_watcher.py` + 集成到 `queue_daemon.py`
- [x] M6: 新增 `operation_log.py` + 集成到 ingest/lifecycle/files
- [x] M7: 前端类型 + API client + store 适配
- [x] M8: 后端测试 + 集成验证

---

## 风险评估

| 风险 | 缓解措施 |
|------|---------|
| `watchdog` 新依赖 | 加入 `requirements.txt`，检查 CI + win7 兼容 |
| settings.json 并发写入 | 复用 `files.py` 的安全写入（O_EXCL） |
| source_watcher 与手动 ingest 冲突 | SHA256 缓存保证幂等 |
| win7 py38 兼容 | `str | None` → `Optional[str]`，`dict[str, str]` → `Dict[str, str]` |

---

## 依赖

- `watchdog` — 需加入 `backend/requirements.txt`
- 其余均为标准库或已有依赖
