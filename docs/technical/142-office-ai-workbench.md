# 142 AI 文档工作台（文档库 / 规范书库 / AI 审校与修订）

> 面向开发者。覆盖 `/office` 工作台 Phase 1 的三块能力：文档库搜索与重复清理、格式规范书库、AI 审校与「应用到文档」。AI 起草（Phase 2）尚未实现，不在本文范围。

## 1. 能力边界

| 能力 | 状态 | 入口 |
|------|------|------|
| 文档库搜索 / 类型筛选 / 排序 | ✅ | `GET /api/v1/office/documents` |
| 重复检测 / 重复组清理 | ✅ | `POST /api/v1/office/documents/duplicates`、`GET /api/v1/office/documents/duplicate-groups` |
| 格式规范书库（提取 / 激活 / 绑定） | ✅ | `/api/v1/office/specs*`、`/api/v1/office/doc/{doc_id}/spec` |
| AI 合并审校（规范书规则 + LLM） | ✅ | `POST /api/v1/office/ai/review` |
| 审校历史 | ✅ | `GET /api/v1/office/doc/{doc_id}/ai-reviews` |
| 将选中的问题应用为 Word 修订 | ✅ | `POST /api/v1/office/ai/revise` |

所有端点挂在 `/api/v1/office` 下（`office_routes.router` 的 prefix），子路由通过 `router.include_router(...)` 合并，因此子模块自身不重复写 prefix。

## 2. 文档库：搜索、筛选、排序

### 2.1 列表端点

```
GET /api/v1/office/documents?workspace_path=...&include_archived=false&q=...&doc_type=word&sort=-updated_at
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `workspace_path` | string（必填） | 工作区路径；服务端先 `Path.resolve()` 规范化，再查库 |
| `include_archived` | bool，默认 `false` | `true` 时包含软删除行（`archived_at` 非 NULL） |
| `q` | string，可选 | 文件名子串匹配，命中 `original_filename` 或 `generated_filename` |
| `doc_type` | enum，可选 | `word` / `excel` / `ppt` / `pdf`；非法值由 FastAPI 返回 422 |
| `sort` | string，可选 | 见下方排序契约 |

### 2.2 排序契约

后端 `storage.list_documents(sort=...)` 接受 `created_at` / `updated_at` / `name` / `size`，前缀 `-` 表示降序：

| `sort` | 含义 |
|--------|------|
| `created_at` / `-created_at` | 创建时间升 / 降序 |
| `updated_at` / `-updated_at` | 更新时间升 / 降序 |
| `name` / `-name` | 文件名（`original_filename`，缺失时用 `generated_filename`）A→Z / Z→A |
| `size` / `-size` | `metadata.file_size_bytes` 升 / 降序 |

实现要点：

- SQL 恒为 `ORDER BY created_at DESC`，随后在 Python 侧对已取回的行做**稳定排序**（`_SORT_KEYS`）。这样用户输入永远不会进入 `ORDER BY`，也不依赖部分 SQLite 构建缺失的 `json_extract`。
- 未识别的 `sort` 值静默回落到默认顺序，不报错。
- 前端 `useOfficeDocuments` 的初始 `sort` 为 `-updated_at`（对应下拉「最近更新」）；搜索 / 类型 / 排序任一状态变化都会触发重新拉取。

> 历史坑：前端下拉曾使用 `updated_asc` / `name_asc` 等值，与后端契约不匹配，导致选择排序被静默忽略。现下拉 `option value` 与上表严格一致。

### 2.3 重复检测

- 文档行带 `content_hash`（`sha256:<hex>`，流式 1 MiB 分块计算，见 `office/revision.py:compute_file_revision`）。
- 未计算过 hash 的历史行不参与判重。
- `POST /api/v1/office/documents/duplicates` 的响应是**位置对应**的：`files[i]` 回答 `file_paths[i]`；不存在的文件返回 `content_hash=null` 且不报错（错误留给后续读取步骤）。单次最多 `MAX_DUPLICATE_CHECK_FILES = 50` 个文件；越界路径按工作区沙箱拒绝。
- `GET /api/v1/office/documents/duplicate-groups` 只返回 **live 文档中 ≥2 个成员**的分组：

```json
{
  "groups": [
    {
      "content_hash": "sha256:…",
      "documents": [ { "id": "…", "generated_filename": "draft.docx", "created_at": 1762300000000 } ]
    }
  ],
  "total": 1
}
```

### 2.4 清理动作

前端「清理重复（保留最新）」= 对每组保留 `created_at` 最新的一条，其余逐条走归档（软删除），可随时从「已归档」视图恢复。归档失败会中止整批并提示，不做静默跳过。

同源关系（「作为新版本导入」）通过 `POST /api/v1/office/documents/{doc_id}/lineage` 写 `derived_from`，与重复清理是两条独立路径。

## 3. 格式规范书库（M2.5）

一份规范书 = 说明文件（Word / PDF / Markdown）+ 提取出的规则包 + 出处/版本/绑定范围。

### 3.1 数据模型

```sql
CREATE TABLE office_spec_documents (
  id TEXT PRIMARY KEY,
  workspace_path TEXT NOT NULL,
  name TEXT NOT NULL,
  source_file_path TEXT,
  source_content_hash TEXT,
  rulepack_id TEXT NOT NULL,      -- 关联 word_rulepacks（文件系统 JSON）
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,    -- epoch 毫秒
  updated_at INTEGER NOT NULL
);
```

文档级绑定复用 `office_documents.active_spec_id`（可空；NULL = 跟随工作区默认）。迁移均为 `CREATE TABLE IF NOT EXISTS` / `PRAGMA table_info` 幂等模式。

### 3.2 生效规范书解析

`spec_library.resolve_effective_spec()` 的优先级：

```
显式 spec_id > 文档 active_spec_id > 工作区 is_default 规范书
```

三层都限定在同一个 `workspace_path` 内；跨工作区的 `spec_id` / `doc_id` 一律解析不到，避免元数据泄漏。

### 3.3 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/office/specs` | 列出工作区规范书 |
| GET | `/office/specs/{spec_id}` | 规范书详情（含规则包） |
| POST | `/office/specs` | 从已有规则包保存为新规范书 |
| PATCH | `/office/specs/{spec_id}` | 修改名称 / 规则包 / 默认标记 |
| DELETE | `/office/specs/{spec_id}` | 删除（默认规范书走下面的专用端点解除） |
| DELETE | `/office/specs/default` | 清除工作区默认绑定 |
| POST | `/office/specs/extract` | 从说明文件提取规则包（`use_llm` 可选，复用 `extract_word_rules`） |
| POST | `/office/specs/{spec_id}/activate` | 设为工作区默认 |
| GET / POST | `/office/doc/{doc_id}/spec` | 查询 / 设置文档级绑定（`spec_id=null` 解绑） |

提取失败时仍可「从已有规则包创建」，保证 LLM 不可用时不阻断流程。

## 4. AI 合并审校（M3）

### 4.1 请求 / 响应

```
POST /api/v1/office/ai/review
{
  "workspace_path": "/ws",
  "file_path": "/ws/docs/draft.docx",
  "doc_id": "doc-1",          // 可选；提供时写历史
  "spec_id": "spec-a",        // 可选；不传走绑定解析
  "scope": "full",            // 非 full 会回落并告警
  "use_llm": true,
  "max_issues": 100,          // 1..300
  "max_size_bytes": 52428800  // 1 KiB..200 MiB
}
```

响应 `AiReviewResult`：`ok`、`doc_id`、`file_path`、`scope`、`spec_id`、`spec_name`、`summary`、`issues[]`、`warnings[]`。

问题模型 `AiReviewIssue`：

| 字段 | 说明 |
|------|------|
| `id` | 稳定标识（用于前端勾选与去重） |
| `severity` | `error` / `warning` / `info` |
| `category` | 例如 `layout` / `content` / `wording` |
| `message` / `suggestion` / `rationale` | 展示文案与依据 |
| `expected` / `actual` | **可应用修订的锚点**：`actual` 为文中现有文本，`expected` 为目标文本 |
| `fixable` | 是否可自动修复 |
| `location` | Word 段落索引 + 段落文本 |
| `source` | `{kind: "spec"|"llm"|"builtin", spec_id?, spec_name?, rule_id?, rule_pack_id?}` |

### 4.2 审校流水线

1. 校验工作区、路径围栏、文件存在、大小上限。
2. `doc_id` 若提供，必须属于同一工作区（否则 `OfficeParseError`，且不写历史）。
3. 解析生效规范书，先跑**确定性规则**（免费、高优先级）。
4. `use_llm=true` 时再跑 LLM 语义审校：
   - 最多 `MAX_LLM_PARAGRAPHS=80` 段、每段 `800` 字、总计 `16000` 字、产出 `MAX_LLM_ISSUES=40` 条；
   - LLM 客户端统一走 `build_llm_client_from_settings()`；
   - 文档正文被视为不可信输入，系统提示明确忽略其中指令。
5. 合并去重，按 `max_issues` 截断（硬上限 `MAX_ISSUES_CAP=300`）。
6. `doc_id` 存在时写 `office_ai_reviews`（best-effort，失败不打断响应）。

常见 `warnings[].code`：`spec_rulepack_missing`、`llm_unavailable`、`llm_unsupported_format`、`llm_no_content`、`llm_failed`、`llm_parse_failed`、`llm_issue_rejected`、`scope_fallback`。

### 4.3 历史

```
GET /api/v1/office/doc/{doc_id}/ai-reviews?workspace_path=/ws&limit=50
```

最新在前，`limit` 收敛到 `[1, 200]`。传入 `workspace_path` 时，非本工作区文档返回**空列表**（不暴露文档是否存在）。每次记录包含 `spec_id`、`model`、`scope`、`issue_count`、`summary`、`duration_ms`、`prompt_tokens`、`completion_tokens`、`created_at`（epoch 毫秒）。

## 5. 应用到文档（修订痕迹 + 快照）

```
POST /api/v1/office/ai/revise
{
  "workspace_path": "/ws",
  "file_path": "/ws/docs/draft.docx",
  "doc_id": "doc-1",            // 可选
  "issues": [ /* AiReviewIssue，1..200 条 */ ],
  "output_filename": null,      // null = 覆盖原文件
  "author": "Sage",
  "add_comments": true
}
```

处理流程（`office_ai_review_routes.ai_revise_endpoint`）：

1. 路径围栏 + 文件存在校验；`doc_id` 必须是本工作区文档。
2. `snapshot_pre_edit(summary)` 做 pre-edit 快照：
   - 位置：`<managed_dir>/.snapshots/<epoch_ms>-<generated_filename>`；
   - `copy2` 保留 mtime/atime，毫秒时间戳避免同秒冲突；
   - 失败返回 `None`，**绝不阻断**修订。
3. 逐条把 issue 映射为 `{find, replace, comment, reason}`：
   - `actual` → `find`；`expected`（为空时退化到 `suggestion`）→ `replace`；
   - 任一为空或两者相同 → 跳过；
   - 全部跳光 → `OfficeParseError("所选问题没有可应用的修订")`。
4. `apply_word_revisions(...)` 写入真正的 Word 修订痕迹（`w:del` + `w:ins`），`output_filename` 为空时覆盖原文件。
5. 返回 `AiReviseResult`：`ok`、`doc_id`、`snapshot_path`、`source_path`、`output_path`、`overwritten`、`planned`/`applied`/`skipped`、`changes[]`、`warnings[]`。

评论正文由 `_build_comment(issue)` 生成：`message — rationale [AI]` 或 `message — rationale [spec:<rule_id>]`，截断至 1000 字符。

安全边界：

- 跨工作区 `doc_id` → 拒绝（不落快照、不写文件）；
- `file_path` 越出工作区 → `OfficePathError`；
- 无 `doc_id` 时仍允许应用修订，但**不产生快照**（调用方需自行承担回退成本）；
- 所有写操作都发生在用户显式点击确认之后，前端有二次确认对话框。

## 6. 前端组件

| 组件 | 职责 |
|------|------|
| `OfficeDocumentList` | 搜索框 / 类型下拉 / 排序下拉 / 重复徽标 / 重复组横幅 + 一键清理 |
| `useOfficeDocuments` | 持有 `q` / `docType` / `sort` 状态，驱动列表与重复组刷新 |
| `OfficeSpecLibrary` | 规范书列表、提取、从规则包创建、设为默认、文档级绑定 |
| `OfficeAiAssistantPanel` | 审校执行、来源徽章与过滤、历史、逐项勾选、「应用到文档」确认与结果展示 |

`OfficeAiAssistantPanel` 的可勾选条件与后端应用条件保持一致：`fixable && actual && (expected || suggestion)`。全选只选可修复项；应用成功后清空选择并展示快照路径。

### IPC 命令（Electron 层）

| 命令 | 方法 + 路径 |
|------|-------------|
| `office_list_documents` | `GET /api/v1/office/documents` |
| `office_list_duplicate_groups` | `GET /api/v1/office/documents/duplicate-groups` |
| `office_check_duplicates` | `POST /api/v1/office/documents/duplicates` |
| `office_set_document_lineage` | `POST /api/v1/office/documents/{docId}/lineage` |
| `office_specs_list` / `_get` / `_create` / `_update` / `_delete` | `/api/v1/office/specs*` |
| `office_specs_extract` / `_activate` / `_clear_default` | `/api/v1/office/specs*` |
| `office_doc_spec_get` / `office_doc_spec_bind` | `/api/v1/office/doc/{docId}/spec` |
| `office_ai_review` | `POST /api/v1/office/ai/review` |
| `office_ai_revise` | `POST /api/v1/office/ai/revise` |
| `office_doc_ai_reviews` | `GET /api/v1/office/doc/{docId}/ai-reviews` |

新增命令后必须重跑 `npm run ipc:manifest` 更新 `electron/ipc-manifest.json`。

## 7. 测试

| 层 | 文件 | 覆盖点 |
|----|------|--------|
| 后端集成 | `backend/tests/integration/test_office_ai_review_routes.py` | 规则审校 + 历史、规范书来源、路径/大小/跨工作区拒绝、修订 + 快照、无 doc_id 不落快照、无可应用修订报错 |
| 后端单元 | `backend/tests/unit/test_office_storage*.py` | 搜索/筛选/排序、重复组 |
| 前端 | `src/features/office/__tests__/OfficeAiAssistantPanel.test.tsx` | 勾选、全选、确认对话框、请求参数、结果与错误展示 |
| 前端 | `src/features/office/__tests__/useOfficeDocuments.test.ts` | 默认 `sort=-updated_at`、归档视图、重复组刷新 |
| 前端 | `src/features/office/__tests__/OfficeDocumentList.test.tsx` | 搜索/筛选/排序控件、重复横幅、批量清理 |

归档验收：office 全量前端套件 56 文件 / 287 测试通过；`tsc --noEmit` 无错误。

## 8. 分支同步注意（release/win7）

- Python 文件保留 `# ruff: noqa: UP006, UP007, UP035`，使用 `typing.List/Optional/Dict`，不写 `list[...]` / `X | None`（Python 3.8）。
- 所有 pydantic 模型同时满足 v1 / v2（项目内 `pydantic_compat` 垫片）。
- 前端功能不依赖 main 独有的能力；`OfficeAiAssistantPanel` 的 props 未改动，`Office.tsx` 无需同步修改。
- 同步后重跑 `npm run ipc:manifest`，并核对 `backend/tests` 中的工作区路径断言。
