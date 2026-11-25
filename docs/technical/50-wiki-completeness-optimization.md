# Wiki 完整性优化：队列 / Web Clipper / Lint / Review

> **创建日期**: 2026-09-06
> **分支**: `feat/wiki-completeness-optimization`
> **状态**: ✅ 已交付（Phase 1-4 实现完毕，Phase 5 文档收尾）

---

## 1. 背景

Sage Wiki 子系统参考 Andrej Karpathy 的 `llm_wiki` 设计模式。经过对比分析：

| 功能层 | 状态 | 说明 |
|--------|------|------|
| 核心功能（6 步 CoT 摄入 / 混合搜索 / 知识图谱 / RAG 聊天 / Deep Research / MCP Server） | ✅ 90% | 已在 PR-8 / PR-12 落地 |
| 高级功能（持久化队列 / Chrome Clipper / Lint / Review） | ⚠️ → ✅ 本次补齐 | 见下 |
| Rust Agent 运行时 | ❌ 不做 | Sage 有自己的 orchestration 架构（PR-42） |

目标：使 Wiki 达到参考实现 **95%+ 功能完整度**。

---

## 2. 四大新增功能

### 2.1 持久化摄入队列

**位置**：
- 后端：`backend/wiki/ingest_queue.py`（`IngestQueue` 类）
- API：`/api/v1/wiki/ingest/queue/*`（7 个端点）
- 前端：`src/entities/wiki/queue-store.ts` + `WikiQueuePanel.tsx`

**数据模型**：

```python
class QueueStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class IngestTask:
    task_id: str
    source_path: str
    project_root: str
    status: QueueStatus
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[dict] = None
```

**持久化**：`.llm-wiki/ingest-queue.json`（JSON，原子写）

**API 端点**：

| Method | Path | 用途 |
|--------|------|------|
| POST | `/ingest/queue/add` | 添加入任务 |
| GET | `/ingest/queue/status` | 5 状态计数摘要 |
| GET | `/ingest/queue/tasks` | 按状态过滤列出 |
| POST | `/ingest/queue/cancel/{task_id}` | 取消 |
| POST | `/ingest/queue/retry/{task_id}` | 重试失败任务 |
| POST | `/ingest/queue/next` | 取下一个 pending |
| POST | `/ingest/queue/clear` | 清空 completed（或全部） |

**测试**：unit 29 + integration 18 = 47 用例

### 2.2 Chrome Web Clipper

**位置**：`extension/wiki-clipper/`

- Manifest V3
- Readability.js 提取正文 + Turndown.js 转 Markdown
- Popup 选择项目 → Clip 按钮 → POST `/api/v1/wiki/clip`
- 已存在 `/api/v1/wiki/clip` 端点（直接对接）
- 详细使用：[`extension/wiki-clipper/README.md`](../../extension/wiki-clipper/README.md)

### 2.3 Lint 系统

**位置**：
- 后端：`backend/wiki/lint.py`（`WikiLint` 类）
- API：`GET /api/v1/wiki/lint`
- 前端：`src/widgets/wiki/WikiLintView.tsx` + `src/entities/wiki/lint-store.ts`（`runLint` 异步 action）

**6 类检查项**（按 severity 分级）：

| rule | severity | 触发条件 |
|------|----------|----------|
| `required_dir` | error | 缺 `wiki/entities` / `wiki/concepts` / `wiki/sources` |
| `required_file` | error | 缺 `wiki/index.md` / `wiki/overview.md` / `wiki/schema.md` |
| `frontmatter_missing` | warning | 页面无 YAML frontmatter 或字段缺失 |
| `frontmatter_title` | warning | title 与文件名不一致 |
| `wikilink_broken` | warning | `[[target]]` 指向不存在的页 |
| `orphan` | info | 页面无入链（零 incoming） |

**返回形状**：

```json
{
  "total": 12,
  "by_severity": {"error": 2, "warning": 8, "info": 2},
  "issues": [
    {
      "type": "wikilink_broken",
      "severity": "warning",
      "page": "wiki/entities/agent.md",
      "detail": "断链: [[nonexistent]]",
      "broken_target": "nonexistent",
      "suggested_target": null,
      "suggested_source": null,
      "affected_pages": ["wiki/entities/agent.md"]
    }
  ]
}
```

**前端**：`LintIssueRaw`（snake_case）→ `LintItem`（camelCase）通过 `mapBackendIssue` 映射；severity filter tabs + 计数 + 自动跑。

**测试**：unit 29 + integration 6 = 35 用例

### 2.4 Review 系统

**位置**：
- 后端：`backend/wiki/review.py`（`WikiReview` 类）
- API：`GET /api/v1/wiki/review`
- 前端：`src/widgets/wiki/WikiReviewView.tsx` + `src/entities/wiki/review-store.ts`（`runReview` 异步 action）

**与 Lint 的区别**：Lint 是**结构合规性**检查；Review 是**内容质量**检查（需人工/LLM 复核）。

**5 类审核器**（全部**确定性**，无 LLM 调用）：

| type | 触发条件 | confidence |
|------|----------|------------|
| `missing-page` | `[[wikilink]]` 目标不存在 | 1.0 |
| `duplicate` | 标题 token 集合 Jaccard ≥ 0.6（最少 2 token） | 0.5-1.0 |
| `contradiction` | frontmatter `created > updated`（ISO 字符串比较） | 1.0 |
| `suggestion` | 内容 < 150 字符（`short_page`）或无 title（`no_title`） | 0.6 |
| `confirm` | 孤儿页（零 incoming 链接，豁免 `wiki/schema.md`、`wiki/overview.md`） | 0.5 |

**稳定 ID**：blake2b 64-bit 哈希 `rv-<16hex>`（同输入 → 同 ID，跨次运行结果可对比）。

**Jaccard 相似度**（重复检测）：

```python
def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b: return 0.0
    return len(a & b) / len(a | b)
```

例：`"Deep Transformer Model Architecture"` vs `"Deep Transformer Model Implementation"` → 3/5 = 0.6（命中阈值）。

**返回形状**：

```json
{
  "total": 5,
  "by_type": {"duplicate": 1, "contradiction": 0, "missing-page": 2, "confirm": 1, "suggestion": 1},
  "items": [
    {
      "id": "rv-3a7f1b2c4d5e6f8a",
      "type": "missing-page",
      "title": "断链指向不存在的页: [[nonexistent]]",
      "description": "页面 wiki/entities/agent.md 引用了不存在的页",
      "affected_pages": ["wiki/entities/agent.md"],
      "confidence": 1.0,
      "detail": "broken_link",
      "suggestion": "创建页面 wiki/nonexistent.md 或删除链接"
    }
  ]
}
```

**测试**：unit 51 + integration 8 = 59 用例

---

## 3. 前后端集成模式

### 3.1 API 客户端层

`src/shared/api-client/wiki.ts` 新增：

```typescript
export async function wikiLintRun(projectPath: string): Promise<LintResponse>
export async function wikiReviewRun(projectPath: string): Promise<ReviewResponse>
```

都走 `httpGet<T>(endpoint, params)` 封装（自动加 `?project_path=...`）。

### 3.2 Zustand Store 模式

`lint-store.ts` 和 `review-store.ts` 采用一致的 async-action 模式：

```typescript
interface ReviewStoreState {
  items: ReviewItem[];
  isLoading: boolean;
  lastRunAt: number | null;
  error: string | null;
  runReview: (projectPath: string) => Promise<void>;  // 异步 action
  dismissItem: (id: string) => void;                  // 本地控制
  // ... 向后兼容 mock 数据 action
}

function mapBackendItem(raw: ReviewItemRaw): ReviewItem {
  return {
    id: raw.id,
    type: raw.type,
    title: raw.title,
    description: raw.description,
    affectedPages: raw.affected_pages ?? [],
    resolved: false,
    actions: [],
    confidence: raw.confidence,
    detail: raw.detail,
    suggestion: raw.suggestion,
  };
}
```

要点：
- `isLoading` / `error` / `lastRunAt` 三字段追踪请求状态
- `mapBackendItem` 负责 snake_case → camelCase 翻译
- 保留 mock-action（`setItems`、`addItem`、`updateItem`、`resolveItem`、`removeItem`、`clearResolved`、`setLoading`）向后兼容历史 UI 测试

### 3.3 视图模式

`WikiLintView.tsx` 和 `WikiReviewView.tsx` 采用一致的 UI 结构：

- 顶部 toolbar：运行按钮 + 过滤开关 + 计数统计 + 上次运行时间
- 二级 filter tabs：按 type/severity 过滤
- 主内容区：grid 卡片布局（`xl:grid-cols-2` 响应式）
- 自动运行：`useEffect(() => { runXxx(projectPath) }, [projectPath])`
- 错误 banner / 加载中 spinner / 空状态（CheckCircle2）
- `WikiReviewView` 每张卡片右上角额外叠加 dismiss 按钮（X 图标）

---

## 4. 关键设计决策

### 4.1 为什么 Review 不用 LLM？

原计划用 LLM 评估质量，但实际采用**确定性检测**：

| 维度 | 确定性方案 ✅ | LLM 方案 ❌ |
|------|--------------|-------------|
| 速度 | 毫秒级（纯字符串/集合操作） | 秒级（LLM 调用） |
| 成本 | 0 | 每页 ≈ $0.01 |
| 稳定性 | 同输入 → 同结果 | 概率性输出 |
| 覆盖 | 5 类规则（可扩展） | 泛化但不可控 |

权衡：确定性方案**不能**评估"内容准确性"、"写作质量"等语义层面；但能覆盖 80% 的真实需求（断链、重复、矛盾、短页、孤儿）。

### 4.2 为什么用 blake2b 而不是 uuid？

- **稳定性**：同输入产生同 ID → 跨次运行结果可对比（"上次没报，这次报了 = 新引入问题"）
- **快速**：blake2b 是 sha256 的 3-5× 加速
- **短**：64-bit digest（16 hex chars）足够避免 10^5 级碰撞

### 4.3 为什么 Jaccard 阈值 0.6？

经验值：
- 0.5 → 误报（"Transformer Model" vs "Transformer Architecture" 只有 1/3 重叠）
- 0.6 → 合理（"Deep Transformer Model Architecture" vs "Deep Transformer Model Implementation" = 3/5 = 0.6）
- 0.7 → 漏报（"Deep Transformer Model Architecture" vs "Deep Transformer Model Variants" = 4/6 = 0.67）

### 4.4 为什么 Review 豁免 `wiki/schema.md` 和 `wiki/overview.md`？

这两个文件是元数据页（定义 schema、总览），天然不会被业务页引用。不豁免会永久报 `confirm`（孤儿）。

---

## 5. 测试覆盖

| 模块 | Unit | Integration | 合计 |
|------|------|-------------|------|
| 队列 | 29 | 18 | 47 |
| Lint | 29 | 6 | 35 |
| Review | 51 | 8 | 59 |
| **合计** | **109** | **32** | **141** |

全部测试通过（pytest + python 3.10 + pydantic 2.x）。

---

## 6. 性能预期

| 操作 | 目标 | 实测 |
|------|------|------|
| 队列 add/cancel/retry | < 100ms | ~5ms |
| Lint 1000 页 | < 10s | ~2s |
| Review 100 页 | < 5s | ~0.5s（确定性） |
| Chrome Clipper 加载 | < 2s | ~0.3s |

---

## 7. 后续优化

1. **更多 Review 规则**：长句检测、被动语态、术语一致性（可接入 LanguageTool）
2. **批量操作**：队列/审核的批量处理 API
3. **Review 持久化**：当前是"每次重算"，可加 `.llm-wiki/review-history.json` 跟踪解决状态
4. **Obsidian 自动同步**：监听 wiki 目录变化，双向同步

---

## 8. 相关文件

**后端**：

- `backend/wiki/ingest_queue.py`
- `backend/wiki/lint.py`
- `backend/wiki/review.py`
- `backend/wiki/__init__.py`（导出）
- `backend/api/wiki_routes.py`（/queue/*、/lint、/review）

**前端**：

- `src/entities/wiki/queue-store.ts`
- `src/entities/wiki/lint-store.ts`
- `src/entities/wiki/review-store.ts`
- `src/widgets/wiki/WikiQueuePanel.tsx`
- `src/widgets/wiki/WikiLintView.tsx`
- `src/widgets/wiki/WikiReviewView.tsx`
- `src/widgets/wiki/LintItemCard.tsx`
- `src/widgets/wiki/ReviewItemCard.tsx`
- `src/shared/api-client/wiki.ts`
- `src/shared/types/wiki.ts`
- `src/pages/Knowledge.tsx`（'queue' / 'lint' / 'review' 三个视图入口）

**Chrome 扩展**：

- `extension/wiki-clipper/`（Manifest V3）

**测试**：

- `backend/tests/unit/wiki/test_ingest_queue.py`
- `backend/tests/unit/wiki/test_lint.py`
- `backend/tests/unit/wiki/test_review.py`
- `backend/tests/integration/test_wiki_queue_routes.py`
- `backend/tests/integration/test_wiki_lint_routes.py`
- `backend/tests/integration/test_wiki_review_routes.py`

## 2026-10-30 补齐：队列执行入口 / 来源管理 / 研究面板

- **队列**：新增 `backend/wiki/queue_worker.py` 与
  `POST /wiki/ingest/queue/process`，按 FIFO 真实执行 ingest；
  `WikiQueuePanel`「处理队列」按钮与 `SourcesTree`「加入队列」入口闭环。
- **来源管理**：`SourcesView` 去 mock，接真实列表/预览/级联删除；
  新增外部文件导入端点与 Electron 单文件选择器。
- **研究面板**：`RightPanel` 挂载 `WikiResearchPanel`（Tavily Key 来自
  `search_config`；缺失时禁用并提示）。
- **已知剩余**：后台守护进程式队列执行、PDF FTS itemID 修正、
  `literature_aggregator` 目录收敛仍未做（P2）。

## 2026-10-30 P2 收尾

- **队列**：`backend/wiki/queue_daemon.py` 每 60s 消费项目 pending 队列，与手动入口共享进程锁；main lifespan 启停。
- **文献聚合**：`literature_aggregator` 接入 `wiki/zotero/items`，同步后生成 `wiki/literature/index.md`，并新增 `POST /wiki/literature/review`。
- **图谱**：新增 Adamic-Adar 第 4 信号，前后端同步。
- **向量库**：`SAGE_WIKI_VECTOR_BACKEND=hnsw` 可选启用 HNSW，缺依赖自动回退 JSON。
- **PDF 全文**：Zotero FTS 改为附件 itemID 优先，父条目 legacy fallback。
- **剩余观察项**：真实 Zotero 库手工验证、Win7 实机 reparse/HNSW 验证。

---

## 9. LLM 任务路由与设置

Wiki 的 LLM 交互层按**任务类型**路由到不同模型、按 provider 适配推理模式，并在生成时注入 `purpose.md` / `schema.md`；同时提供 `raw/sources/` 自动监听与 `wiki/log.md` 操作日志。项目级设置存储在 `.llm-wiki/settings.json`，通过 `GET/PUT /wiki/settings` 读写。

### 9.1 数据模型与持久化

**位置**：`backend/wiki/settings.py`（经 `backend/wiki/__init__.py` 导出）

```python
@dataclass
class TaskRoutingConfig:
    chat_model: Optional[str] = None       # None → 使用全局默认模型
    ingest_model: Optional[str] = None
    research_model: Optional[str] = None

@dataclass
class ReasoningConfig:
    chat_mode: str = "auto"                # chat / research 共用
    ingest_mode: str = "off"               # ingest 默认关闭，避免空内容

@dataclass
class WikiSettings:
    task_routing: TaskRoutingConfig
    reasoning: ReasoningConfig
```

- **存储路径**：`<project_root>/.llm-wiki/settings.json`，每个项目独立。
- **写入**：`save_settings()` 先写 `settings.json.tmp`，再用 `Path.replace()` 原子替换。
- **读取**：`load_settings()` 文件缺失、JSON 损坏或字段类型异常时一律回退到 `WikiSettings()` 默认值（记 warning，不抛错）；`from_dict` 忽略未知字段。

### 9.2 任务路由判定

**位置**：`backend/wiki/settings.py` + `backend/wiki/llm_context.py`

```python
def resolve_model_for_task(settings, task, default_model):
    mapping = {
        "chat": settings.task_routing.chat_model,
        "ingest": settings.task_routing.ingest_model,
        "research": settings.task_routing.research_model,
    }
    return mapping.get(task) or default_model
```

`llm_context.make_task_llm_context(base_url, api_key, default_model, project_root, task, provider="", timeout=1800)` 是路由入口：加载项目设置 → 解析任务模型 → 选择推理模式 → 构建 `LLMContext`。

- 任务名：`chat` / `ingest` / `research`；未识别或未配置模型时落到全局 `default_model`。
- 推理模式：`task == "ingest"` 用 `ingest_mode`，**其余任务（含 `research`）都用 `chat_mode`**。
- 调用点（`backend/api/wiki_routes.py`）：ingest 流式路由用 `task="ingest"`、chat 路由用 `task="chat"`、research 路由用 `task="research"`，research 的自动 ingest 分支再用 `task="ingest"`。
- 路由后模型写入 `ctx.model`，回填到 `IngestConfig.llm_model` / `ChatConfig.llm_model`。

**provider 推断**：调用方不显式传 `provider` 时，`infer_provider(base_url)` 按 URL 关键字推断（顺序敏感）：`anthropic` → `anthropic`，`generativelanguage`/`googleapis` → `google`，`deepseek` → `deepseek`，`ollama`/`11434` → `ollama`，`openai` → `openai`；无法识别返回空串。

### 9.3 Provider 推理模式适配

**位置**：`backend/wiki/reasoning.py`（参考 `llm_wiki` 的 reasoning-capabilities）

| provider | 支持模式 | 注入的请求参数 |
|----------|----------|----------------|
| `openai` | `auto` `low` `medium` `high` | `reasoning_effort = mode` |
| `anthropic` | `auto` `low` `medium` `high` `max` | `thinking = {"type": "enabled", "budget_tokens": budget}` |
| `google` | `auto` `low` `medium` `high` `max` | `thinking_config = {"thinking_budget": budget}` |
| `deepseek` | `auto` `high` `max` | `reasoning_effort = mode` |
| `ollama` | `auto` `low` `medium` `high` `max` | `reasoning_effort = mode` |

- **token 预算**：`low=1024` / `medium=4096` / `high=10000` / `max=20000`，未知模式默认 4096。
- `apply_reasoning_to_request(body, provider, mode)`：`off` / `auto` 直接返回不改请求体；provider 不支持该 mode 时 `normalize_mode` 降级为 `auto`（等价于不注入）后再处理。
- 任务默认值：`INGEST_DEFAULT_MODE = "off"`、`CHAT_DEFAULT_MODE = "auto"`（与 `ReasoningConfig` 默认一致）。
- 接入点：`make_llm_context()` 内 `_chat_body()` 仅在 `reasoning_mode` 非空时调用适配函数，非流式/流式请求共用同一份 body 构造。

### 9.4 purpose.md / schema.md 注入

**文件约定**（由 `backend/wiki/wiki_templates.py` 初始化）：

```
<project_root>/
  purpose.md       # 项目目的：目标 / 关键问题 / 范围
  wiki/schema.md   # 页面结构规范
```

**读取**：`backend/wiki/ingest.py` 的 `_read_wiki_context(project_root)` 返回 `(purpose, schema)`：

- 分别读取根目录 `purpose.md` 与 `wiki/schema.md`；
- 经 `secure_read_file_bounded(project_root, path, MAX_CONTEXT_CHARS * 4)` 读取，UTF-8 `errors="replace"`，截断到 `MAX_CONTEXT_CHARS = 4000` 字符；
- 文件缺失、越界或读取失败时返回空串，不阻断 ingest。

**注入点**：Step 1（分析）与 Step 2（写作）都会注入。

- `analyze_source()` → `format_step1_prompt(content, purpose=..., schema=...)`
- `generate_pages()` → `format_step2_prompt(..., purpose=..., schema=...)`

**Prompt 模板**（`backend/wiki/llm_prompts.py`）：`STEP1_ANALYZE` / `STEP2_WRITE` 首句后带 `{purpose_section}{schema_section}` 占位符；`_context_sections()` 生成：

```
"\n\n项目目的:\n<purpose>"
"\n\n页面结构规范:\n<schema>"
```

空值时该段为空串。文件内容通过 `str.format` 的**参数值**内插（而非再次格式化），因此正文中的花括号不会被当作模板解析。

### 9.5 Source 目录监听

**位置**：`backend/wiki/source_watcher.py`（依赖 `watchdog`，`backend/requirements.txt` 固定 `watchdog==4.0.2`）

- 启动监听 `raw/sources/`（`recursive=False`，目录不存在则创建）；`watchdog` 未安装时 `create_observer()` 返回 `None`，整体降级为 no-op。
- `_SourceHandler`：
  - `on_created`：跳过目录和以 `.` 开头的隐藏文件，调用 `IngestQueue(project_root).add("raw/sources/<name>")` 入队；
  - `on_deleted`：调用 `lifecycle.cascade_delete_source("raw/sources/<name>")`，级联删除引用页、清理向量与死链、更新 `index.md`；
  - 回调内的异常仅记 warning，不中断监听线程。
- **生命周期**：`queue_daemon._start_source_watchers()` 为所有已初始化项目（存在 `.llm-wiki` 目录）创建 `SourceWatcher`，并复用**单个共享 `Observer`**（多项目一个线程）；`_stop_source_watchers()` 先逐个注销监听再停 Observer。
- **集成**：`run_queue_daemon(poll_seconds=60, watch_sources=True)` 在 `backend/main.py` lifespan 中作为 `wiki-queue-daemon` 任务启动；守护进程每轮扫描有 pending 任务的项目，批量上限 `BATCH_LIMIT = 5`，与手动「处理队列」共享 `queue_process_lock`。

### 9.6 操作日志

**位置**：`backend/wiki/operation_log.py` → `<project_root>/wiki/log.md`

格式为确定性、可解析的单行文本：

```markdown
- [2026-11-14T10:30:00Z] ingest: raw/sources/paper.pdf -> wiki/sources/paper.md
- [2026-11-14T10:35:12Z] delete: raw/sources/paper.pdf -> ['wiki/sources/paper.md']
- [2026-11-14T11:00:00Z] rename: wiki/sources/a.md -> wiki/sources/b.md
```

- 追加写，时间戳为 UTC `%Y-%m-%dT%H:%M:%SZ`；写失败只记 warning，不影响主流程。
- **写入点**：
  - `ingest`：`ingest.py` 的非流式 `ingest_source` 与流式 `ingest_source_stream` 完成写盘后各写一条；
  - `delete`：`lifecycle.cascade_delete_source`（含 watcher 触发的级联删除）；
  - `rename`：文件重命名路由 `backend/api/wiki_routes.py`。

### 9.7 设置读写端点

路由前缀 `/wiki`，挂载到 `/api/v1`，即完整路径 `/api/v1/wiki/settings`。

| Method | Path | 请求 / 响应 |
|--------|------|-------------|
| GET | `/wiki/settings?project_path=...` | 返回 `{task_routing: {...}, reasoning: {...}}`；无配置文件时返回默认值 |
| PUT | `/wiki/settings` | body：`project_path` + `task_routing{chat_model,ingest_model,research_model}` + `reasoning{chat_mode,ingest_mode}`；保存后返回同一结构 |

- **请求模型**：`TaskRoutingPayload`（三个 `Optional[str]`）、`ReasoningPayload`（默认 `chat_mode="auto"`、`ingest_mode="off"`）、`WikiSettingsPayload`（含 `project_path`）。
- **校验**：`chat_mode` / `ingest_mode` 必须属于 `{auto, off, low, medium, high, max}`，否则 `400`。
- **鉴权（两层）**：外层 `LocalAuthMiddleware` 要求 `Authorization: Bearer ${SAGE_LOCAL_AUTH_TOKEN}`；路由内 `authorize_registered_project()` 校验项目根：路径无效 `400`，不在 recents ∪ projects 注册表中 `403`（异常一律 fail-closed 视为未登记）。

### 9.8 前端

- **类型**（`src/shared/types/wiki.ts`）：`ReasoningMode`、`WikiTaskRouting`、`WikiReasoningSettings`、`WikiProjectSettings`，以及默认值常量 `DEFAULT_WIKI_SETTINGS`（`chat/ingest/research` 均为 `null`，`chat_mode="auto"`、`ingest_mode="off"`）。
- **API 客户端**（`src/shared/api-client/wiki.ts`）：`getWikiSettings(projectPath)` 走 `GET /wiki/settings`；`updateWikiSettings(projectPath, {task_routing, reasoning})` 走 `PUT /wiki/settings`。
- **Store**（`src/entities/wiki/settings-store.ts`）：`useWikiSettingsStore` 维护 `settings` / `loadedProjectPath` / `isLoading` / `isSaving` / `error`，暴露 `loadSettings` / `saveSettings` / `reset`。
- **UI**（`src/widgets/wiki/WikiSettingsDialog.tsx`）：三行模型输入（对话 / 入库 / 研究）＋ 两个推理模式下拉（选项 `auto/off/low/medium/high/max`），由 `WikiToolbar` 打开；打开时按当前项目拉取设置，保存成功后同步本地草稿。

### 9.9 测试

**后端单元**：

- `backend/tests/unit/wiki/test_settings.py`（默认值 / 往返持久化 / 损坏回退 / 未知字段 / 任务路由解析）
- `backend/tests/unit/wiki/test_reasoning.py`（能力表 / 归一化 / 各 provider 参数注入 / 预算映射）
- `backend/tests/unit/wiki/test_source_watcher.py`（watchdog 降级 / 入队 / 级联删除 / 共享 Observer 生命周期）
- `backend/tests/unit/wiki/test_operation_log.py`（行格式 / 追加 / 不可写路径不抛错）
- `backend/tests/unit/wiki/test_llm_prompts.py`（purpose/schema 注入 / 花括号安全）

**后端路由**：`backend/tests/unit/api/test_wiki_routes.py` 的 Settings 段（默认值、PUT 持久化、非法模式 400、GET-after-PUT 回显）。

**前端**：`src/entities/wiki/__tests__/settings-store.test.ts`。

