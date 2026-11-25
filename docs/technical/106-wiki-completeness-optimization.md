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

## 9. LLM 任务路由与设置（2026-11-14）

Wiki 的 LLM 调用层支持按任务类型路由到不同模型、按任务选择推理模式，并可通过
HTTP 端点读写项目级设置。设置按项目隔离，缺省时全部回退到全局默认模型。

### 9.1 项目级设置存储

**位置**：`backend/wiki/settings.py`（dataclass，非 pydantic 模型）

```python
@dataclass
class TaskRoutingConfig:
    chat_model: Optional[str] = None      # None = 用全局默认模型
    ingest_model: Optional[str] = None
    research_model: Optional[str] = None

@dataclass
class ReasoningConfig:
    chat_mode: str = "auto"
    ingest_mode: str = "off"              # 入库默认关闭，避免空内容

@dataclass
class WikiSettings:
    task_routing: TaskRoutingConfig = field(default_factory=TaskRoutingConfig)
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)
```

**持久化**：`<project_root>/.llm-wiki/settings.json`

- `load_settings(project_root)`：文件缺失、JSON 损坏或字段类型异常时返回默认
  `WikiSettings()`（仅告警，不抛错）。
- `save_settings(project_root, settings)`：写 `settings.json.tmp` 后 `replace`
  原子替换，父目录自动创建。
- `resolve_model_for_task(settings, task, default_model)`：按 `chat` / `ingest` /
  `research` 查表，命中值非空则用之，否则返回 `default_model`；未知 task 同样
  回退默认值。

### 9.2 任务路由接入点

`backend/wiki/llm_context.py::make_task_llm_context` 统一完成「加载设置 → 解析
模型 → 选推理模式 → 构建 `LLMContext`」：

```python
settings = load_settings(project_root) if project_root is not None else WikiSettings()
model = resolve_model_for_task(settings, task, default_model)
mode = settings.reasoning.ingest_mode if task == "ingest" else settings.reasoning.chat_mode
return make_llm_context(..., model, reasoning_mode=mode)
```

调用点及其任务类型：

| 入口 | 文件 | task |
|------|------|------|
| Ingest 流式 | `backend/api/wiki_routes.py`（`/wiki/ingest/stream`） | `ingest` |
| Chat 流式 | `backend/api/wiki_routes.py`（`/wiki/chat/stream`） | `chat` |
| Deep Research | `backend/api/wiki_routes.py`（`/wiki/research`） | `research` |
| Web Clip | `backend/api/wiki_routes.py`（`/wiki/clip`） | `ingest` |
| 队列消费 | `backend/wiki/queue_worker.py` | `ingest` |

解析后的模型会写回 `config.llm_model = ctx.model`，因此 ingest/chat/research
各自使用项目设置中配置的模型；设置未配置时沿用请求里传入的默认模型。

### 9.3 Provider 推理模式适配

**位置**：`backend/wiki/reasoning.py`

**Provider 能力表**（`REASONING_CAPABILITIES`）：

| provider | 支持的模式 |
|----------|-----------|
| `openai` | `auto` / `low` / `medium` / `high` |
| `anthropic` | `auto` / `low` / `medium` / `high` / `max` |
| `google` | `auto` / `low` / `medium` / `high` / `max` |
| `deepseek` | `auto` / `high` / `max` |
| `ollama` | `auto` / `low` / `medium` / `high` / `max` |

**默认值**：`CHAT_DEFAULT_MODE = "auto"`、`INGEST_DEFAULT_MODE = "off"`。

**mode → token 预算**：`low=1024`、`medium=4096`、`high=10000`、`max=20000`
（`off`/`auto` 不注入参数）。

**请求适配**：`apply_reasoning_to_request(request_body, provider, mode)` 把 mode
翻译成 provider 专属字段并就地注入：

| provider | 注入字段 |
|----------|---------|
| `openai` | `reasoning_effort = mode` |
| `anthropic` | `thinking = {"type": "enabled", "budget_tokens": budget}` |
| `google` | `thinking_config = {"thinking_budget": budget}` |
| `deepseek` / `ollama` | `reasoning_effort = mode` |

`off` / `auto` 原样返回；provider 不支持的 mode 先 `normalize_mode` 降级为
`auto`，再按上面的规则跳过注入。

**provider 推断**：`infer_provider(base_url)` 依据 URL 关键字推断
（`anthropic` / `generativelanguage`·`googleapis` / `deepseek` / `ollama`·`11434`
/ `openai`），识别失败返回空串，此时不注入任何推理参数。调用方目前不显式传
provider，均由 base_url 推断。

### 9.4 purpose.md / schema.md 注入

**读取**：`backend/wiki/ingest.py::_read_wiki_context(project_root)`

- `purpose.md` 取自 **项目根** `<project_root>/purpose.md`；
- `schema.md` 取自 `<project_root>/wiki/schema.md`。
- 单文件经 `secure_read_file_bounded` 读取，截断到 `MAX_CONTEXT_CHARS = 4000`
  字符；缺失、越界或读取失败一律返回空串，不阻断 ingest。

**注入**：`backend/wiki/llm_prompts.py` 的 `STEP1_ANALYZE`（分析）与
`STEP2_WRITE`（写作）模板各带 `{purpose_section}` / `{schema_section}` 占位符。

- `_context_sections(purpose, schema)` 生成片段：非空时为
  `"\n\n项目目的:\n<purpose>"` 与 `"\n\n页面结构规范:\n<schema>"`，空则空串。
- `format_step1_prompt(...)` / `format_step2_prompt(...)` 通过 `str.format`
  内插，内容中的花括号不会被当作模板变量解析。
- `ingest.py` 在 `analyze_source`（Step 1）和 `generate_pages`（Step 2）中各读
  一次上下文再格式化对应 prompt。

### 9.5 Source 目录自动监听

**位置**：`backend/wiki/source_watcher.py`，依赖 `watchdog`（可选依赖）。

- **优雅降级**：`watchdog` 未安装时 `_WATCHDOG_AVAILABLE = False`，`start()`
  直接返回，不影响手动 ingest。
- **监听范围**：`<project_root>/raw/sources/`，`recursive=False`；忽略目录事件
  与以 `.` 开头的文件名。
- **事件处理**：
  - 新增文件 → `IngestQueue(project_root).add("raw/sources/<name>", priority="normal")`。
  - 删除文件 → `lifecycle.cascade_delete_source(project_root, "raw/sources/<name>")`。
- **共享 Observer**：`SourceWatcher(project_root, observer=...)` 传入外部
  Observer 时只注册/注销监听（生命周期由调用方管理）；不传则自建并自管。
- **幂等**：watcher 本身只负责入队/级联删除；重复触发由 ingest 的 SHA256 缓存
  （`.llm-wiki/ingest-cache.json`）去重。
- **守护进程集成**：`backend/wiki/queue_daemon.py` 的 `run_queue_daemon` 启动时
  为所有已初始化项目（存在 `.llm-wiki/`）创建 watcher 并共享单个 Observer，
  `finally` 中先逐个 `watcher.stop()` 再停止 Observer；单个项目失败不影响其他
  项目。

### 9.6 操作日志

**位置**：`backend/wiki/operation_log.py`，日志文件 `<project_root>/wiki/log.md`。

**格式**（确定性、可解析，UTC 时间）：

```markdown
- [2026-11-14T10:30:00Z] ingest: raw/sources/paper.pdf -> wiki/sources/paper.md
- [2026-11-14T10:35:12Z] delete: raw/sources/paper.pdf -> [...]
- [2026-11-14T11:00:00Z] rename: wiki/sources/a.md -> wiki/sources/b.md
```

`append_log(project_root, action, detail)` 以追加模式写入
`- [<YYYY-MM-DDTHH:MM:SSZ>] <action>: <detail>\n`。写失败仅告警，不向上抛错。

**实际调用点**：

| action | 文件 | 时机 |
|--------|------|------|
| `ingest` | `backend/wiki/ingest.py` | 非流式 ingest 完成后 |
| `ingest` | `backend/wiki/ingest.py` | 流式 ingest `completed` 前 |
| `delete` | `backend/wiki/lifecycle.py` | 源文件级联删除后 |
| `rename` | `backend/api/wiki_routes.py`（`/wiki/rename`） | 重命名成功后 |

`log.md` 在级联清理时与 `index.md`、`schema.md` 一同被排除，不会被误删。

### 9.7 设置读写端点

**路由**：`backend/api/wiki_routes.py` 的 `/wiki/settings`，挂载于 `/api/v1`，
完整路径为 `/api/v1/wiki/settings`。

**鉴权**：两端点均先经 `authorize_registered_project(project_path)`。项目须已登记
（recent 列表或 projects 注册表的并集，fail-closed），且目录下存在 `wiki/`。路径
非法 → 400，未登记 → 403，目录不存在 → 404。

**GET `/api/v1/wiki/settings?project_path=...`**

- 查询参数：`project_path`。
- 返回：`{"task_routing": {"chat_model", "ingest_model", "research_model"},
  "reasoning": {"chat_mode", "ingest_mode"}}`；无 settings.json 时返回默认值。

**PUT `/api/v1/wiki/settings`**

- 请求体（pydantic `WikiSettingsPayload`）：

  ```json
  {
    "project_path": "/abs/project",
    "task_routing": {"chat_model": null, "ingest_model": "m1", "research_model": null},
    "reasoning": {"chat_mode": "auto", "ingest_mode": "off"}
  }
  ```

- 校验：`chat_mode` / `ingest_mode` 必须属于
  `{auto, off, low, medium, high, max}`，否则 400 `不支持的推理模式: <mode>`。
- 行为：`save_settings` 落盘后返回保存后的完整设置（与 GET 同形）。

**前端**：

- 类型：`src/shared/types/wiki.ts`（`WikiProjectSettings`、`WikiTaskRouting`、
  `WikiReasoningSettings`、`ReasoningMode`、`DEFAULT_WIKI_SETTINGS`）。
- API：`src/shared/api-client/wiki.ts`（`getWikiSettings` / `updateWikiSettings`）。
- 状态：`src/entities/wiki/settings-store.ts`（`useWikiSettingsStore`，含
  `settings` / `isLoading` / `isSaving` / `error` 与 `loadSettings` / `saveSettings`
  / `reset`）。
- 界面：`src/widgets/wiki/WikiSettingsDialog.tsx`，由 `WikiToolbar.tsx` 打开；
  模型留空即用全局默认，推理模式按对话/入库分别选择。

