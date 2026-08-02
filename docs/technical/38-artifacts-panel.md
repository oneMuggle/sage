# Artifacts Panel（产物面板） (38)

> Chapter 38 覆盖 Chat 页面右侧抽屉面板：AI 工具调用进度展示（Progress）+ AI 生成文件追踪与预览（Artifacts）。全栈链路为 `write_file` 工具成功写入 → `artifact_repo` 落库 `artifacts` 表 → REST API 查询/读取/reveal → 前端 `RightPanel` 列表与多格式预览。PDF/Excel 预览、跳转消息定位、产物搜索过滤不在本期范围。

## 1. 概述

Sage 的 Chat 会话中，LLM 通过工具调用生成文件（代码、文档、图片、数据）。此前用户对"AI 这一轮做了什么、生成了哪些文件"缺乏可见性。Artifacts Panel 在 Chat 页面右缘增加一个抽屉（drawer），提供两个 Tab：

- **Progress**：展示当前流式响应的中间态（streaming state 文案 + 迭代轮次 + 工具调用名称列表）；
- **Artifacts**：列出本 session 内所有被追踪的文件产物，点击任意条目进入多格式预览（image / code / json / csv / markdown / text），并可一键在系统文件管理器中定位源文件。

产物追踪采用**写入侧拦截**：`WriteFileTool.execute()` 成功写盘后静默记录一条 artifact 行；记录失败绝不影响写入本身。前端按 session 拉取列表、按需懒加载内容。

## 2. 架构

```text
LLM tool loop
      │ write_file 成功
      ▼
WriteFileTool.execute()
      │ current_tool_context() 取 session_id (ContextVar)
      │ _record_artifact_safely()  ← 异常静默, 不阻断写入
      ▼
artifact_repo.record_artifact()
      │ INSERT INTO artifacts
      ▼
sqlite: artifacts 表 (+ idx_artifacts_session)
      ▲
      │ SELECT (list / get)
      │
artifact_routes (APIRouter, prefix=/sessions/{session_id}/artifacts)
      │ 挂载于 main.py: app.include_router(..., prefix="/api/v1")
      │
      ├─ GET  ""                    → {artifacts: [...]}
      ├─ GET  "/{artifact_id}/content" → artifact_reader.read_text / read_image
      └─ POST "/{artifact_id}/reveal"  → artifact_reader.reveal_in_file_manager
      ▲
      │ fetch /api/v1/...
      │
artifactApi.ts (非 2xx 即 throw)
      │
      ├─ useArtifacts(sessionId)        → 列表 + refresh
      └─ useArtifactContent(sid, id)    → 内容 (rejection → {ok:false,error})
      ▲
      ▼
RightPanel (Progress / Artifacts 双 Tab)
      ├─ ProgressSection   (streamingState + iteration + toolCalls)
      ├─ ArtifactsSection  → ArtifactRow × N
      └─ ArtifactViewer    (image/code/json/csv/markdown/text 预览)
```

请求生命周期（以预览为例）：

1. 用户在 Artifacts Tab 点击 `ArtifactRow` → `RightPanel` 设置 `selected` artifact；
2. `ArtifactViewer` 挂载 → `useArtifactContent(sessionId, artifactId)` 发起 `GET /api/v1/sessions/{sid}/artifacts/{aid}/content`；
3. 后端 `artifact_routes` 校验 artifact 存在且 `session_id` 匹配（否则 404）→ 按 `kind` 分派 `read_image`（base64 data URL）或 `read_text`（超长截断）；
4. 前端按返回 `kind` 渲染对应视图；非 2xx 被 API client 转为 reject，hook 的 `.catch` 再转为 `{ok:false, error}` 供错误态渲染。

约束：

- 后端全同步（sqlite3 + FastAPI sync endpoint），遵循既有 `*_repo.py` 仓储约定；
- 产物记录是写入的**旁路副作用**，任何失败（缺 context、DB 异常）都静默降级，`write_file` 结果不受影响；
- API 以 `session_id` 为 scope：`content`/`reveal` 端点校验 `artifact.session_id == session_id`，防跨会话访问。

## 3. 后端模块

### 3.1 数据表（`backend/data/database.py`）

`init_db()` 内联建表（无独立迁移文件）：

```sql
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,          -- 'art_' + uuid4 hex 前 12 位
    session_id TEXT NOT NULL,
    tool_call_id TEXT,            -- 预留: 未来跳转定位到产生该产物的工具调用
    path TEXT NOT NULL,           -- 文件绝对路径
    name TEXT NOT NULL,           -- 文件名 (basename)
    kind TEXT NOT NULL,           -- markdown/code/image/csv/text
    size INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL   -- epoch millis
);
CREATE INDEX IF NOT EXISTS idx_artifacts_session
    ON artifacts(session_id, created_at DESC);
```

### 3.2 仓储层（`backend/data/artifact_repo.py`）

- `@dataclass Artifact` + `from_row` / `to_dict`（`to_dict` 输出 snake_case，直接作为 API payload）；
- `record_artifact(session_id, path, name, kind, size, tool_call_id=None) -> str`：生成 `art_*` id + `created_at = int(time.time()*1000)`，INSERT 后 commit，返回 id；
- `list_artifacts(session_id) -> List[Artifact]`：`ORDER BY created_at DESC`（命中 `idx_artifacts_session`）；
- `get_artifact(artifact_id) -> Optional[Artifact]`：不存在返回 `None`。

### 3.3 读取层（`backend/data/artifact_reader.py`）

| 函数 | 行为 |
| --- | --- |
| `read_text(artifact_id, max_bytes=500_000)` | UTF-8 读取；`UnicodeDecodeError` → `{ok:false, error:"binary file cannot be previewed"}`；超过 500KB 按字节截断并置 `truncated:true`（`errors="ignore"` 容忍半字符） |
| `read_image(artifact_id, max_bytes=10_000_000)` | 超过 10MB → `{ok:false, error:"file too large"}`；否则按扩展名映射 MIME，返回 `{ok:true, kind:"image", data_url:"data:<mime>;base64,..."}` |
| `reveal_in_file_manager(artifact_id)` | macOS `open -R <path>` / Windows `explorer /select,<path>` / Linux `xdg-open <parent>`；`CalledProcessError`/`FileNotFoundError` → `{ok:false, error}` |

三者统一返回 `dict`，artifact 不存在或文件已删除时返回 `{ok:false, error:"artifact not found" | "file not found"}`。

### 3.4 路由层（`backend/api/artifact_routes.py`）

`APIRouter(prefix="/sessions/{session_id}/artifacts", tags=["artifacts"])`，在 `main.py` 以 `prefix="/api/v1"` 挂载，最终路径：

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| `GET` | `/api/v1/sessions/{session_id}/artifacts` | `{artifacts: [Artifact.to_dict(), ...]}` |
| `GET` | `/api/v1/sessions/{session_id}/artifacts/{artifact_id}/content` | 文本：`{ok, kind, content, truncated}`；图片：`{ok, kind:"image", data_url}`；不存在/跨会话：404 |
| `POST` | `/api/v1/sessions/{session_id}/artifacts/{artifact_id}/reveal` | `{ok}` 或 `{ok:false, error}` |

`content`/`reveal` 先 `get_artifact` 并校验 `artifact.session_id == session_id`，不匹配视同 404（不泄漏其他会话产物存在性）。

### 3.5 写入侧拦截（`backend/tools/file_tool.py`）

- `detect_artifact_kind(path) -> str`：扩展名 → kind 映射（见 §5）；
- `_record_artifact_safely(resolved_path, size)`：从 `current_tool_context()`（ContextVar）取 `session_id`；ctx 缺失或无 session_id 直接返回；`except Exception` 全兜底，仅 `logger.debug` 记录——**记录产物失败绝不阻断写入**；
- `WriteFileTool.execute()` 在写盘成功、构造 `ToolResult(success=True)` 之前调用 `_record_artifact_safely(result["path"], content_bytes)`。

## 4. 前端模块

### 4.1 API 客户端（`src/features/artifacts/artifactApi.ts`）

- 类型：`ArtifactKind = 'markdown' | 'code' | 'image' | 'csv' | 'json' | 'text'`、`Artifact`（snake_case 镜像后端）、`ArtifactContent`；
- `listArtifacts(sessionId)` / `readArtifactContent(sessionId, artifactId)` / `revealArtifact(sessionId, artifactId)`；
- 统一 `httpError(fn, res)` helper：**任何非 2xx 都 throw Error**（`"<fn> failed: <status>"`），由上层 hook 决定降级策略。

### 4.2 Hooks（`src/features/artifacts/`）

| Hook | 职责 | 失败策略 |
| --- | --- | --- |
| `useArtifacts(sessionId \| null)` | 列表 + `loading` + 手动 `refresh()`；`sessionId` 变化自动重拉 | try/catch/finally：瞬时失败保留上一次列表，不抛给调用方 |
| `useArtifactContent(sessionId, artifactId \| null)` | 按选中项懒加载内容；`cancelled` 标志防竞态 | `.catch` 将 rejection 转为 `{ok:false, error}`，复用 viewer 既有错误态（避免 unhandled rejection） |

### 4.3 组件（`src/widgets/chat/`）

- `RightPanelToggle.tsx`：头部图标按钮（lucide `PanelRight`），`aria-label="切换右侧面板"`；
- `RightPanel.tsx`：抽屉容器，`fixed top-12 right-0 w-80`，`translate-x-full ⇄ translate-x-0` 过渡；双 Tab（`progress`/`artifacts`），选中 artifact 时整面板切换为 `ArtifactViewer`（隐藏 Tab 栏）；持有 `useArtifacts`，并把 `revealArtifact` 接给行内操作；
- `progress/ProgressSection.tsx`：渲染 `streamingState`（经 `STATE_LABELS` 映射文案）+ `第 N 轮` 迭代计数 + 工具调用名称列表；
- `artifacts/ArtifactsSection.tsx`：空态 / loading / `ArtifactRow` 列表；
- `artifacts/ArtifactRow.tsx`：单条产物（名称、kind 标识、大小）+ 选中回调；
- `artifacts/ArtifactViewer.tsx`：多格式预览——`image` 渲染 `data_url`；`code`/`json` 代码块；`csv` 经 `parseCsv`（处理 CRLF）渲染表格（上限前 500 行，超出提示）；`markdown`/`text` 文本展示；`truncated` 显示截断提示；`ok:false` 显示错误信息。

### 4.4 页面集成（`src/pages/Chat.tsx`）

- 头部挂载 `RightPanelToggle`，`rightPanelOpen` state 控制开合；
- `ChatInput` 之后挂载 `RightPanel`，透传 `iteration` / `streamingState` / `streamingToolCalls ?? []`（防御性默认）/ `isLoading` / `currentSessionId`。

## 5. Kind 检测规则与限制

### 5.1 扩展名 → kind（`detect_artifact_kind`）

| kind | 扩展名 |
| --- | --- |
| `markdown` | `.md` `.markdown` |
| `code` | `.py` `.js` `.ts` `.tsx` `.jsx` `.json` `.css` `.html` `.sh` |
| `image` | `.png` `.jpg` `.jpeg` `.gif` `.svg` `.webp` |
| `csv` | `.csv` `.tsv` |
| `text` | 其余全部（fallback） |

前端 `ArtifactKind` 额外保留 `json` 取值，viewer 将 `code`/`json` 同等按代码块渲染。

### 5.2 预览限制

| 类型 | 上限 | 超限行为 |
| --- | --- | --- |
| 文本预览 | 500 KB（`MAX_TEXT_BYTES = 500_000`） | 按字节截断，响应置 `truncated: true` |
| 图片预览 | 10 MB（`MAX_IMAGE_BYTES = 10_000_000`） | `{ok:false, error:"file too large"}` |
| CSV 表格渲染 | 前 500 行（前端） | 提示"仅显示前 500 行" |

## 6. 错误处理约定

| 层 | 约定 |
| --- | --- |
| 工具层 | 产物记录全异常兜底，写入永远优先；无 tool context 时静默跳过（如非 Chat 场景调用 `write_file`） |
| 读取层 | 统一 `{ok, error}` 信封，不抛异常；区分 `artifact not found` / `file not found` / `binary file cannot be previewed` / `file too large` |
| 路由层 | artifact 不存在或 `session_id` 不匹配 → `HTTPException(404)`；读取/reveal 的业务失败以 200 + `{ok:false}` 返回 |
| API 客户端 | 非 2xx → throw（`httpError`）；成功体原样透传（含业务级 `{ok:false}`） |
| Hooks | `useArtifacts` 失败保留旧列表；`useArtifactContent` 把 rejection 收敛为 `{ok:false, error}`，viewer 错误态统一渲染 |

## 7. 测试覆盖

### 7.1 Backend（21 tests）

| 套件 | 测试数 | 覆盖范围 |
| --- | --- | --- |
| `backend/tests/unit/test_artifacts_schema.py` | 2 | 建表 DDL / 索引存在性 |
| `backend/tests/unit/test_artifact_repo.py` | 5 | record/list/get、降序、id 前缀、不存在返回 None |
| `backend/tests/unit/test_artifact_reader.py` | 6 | 文本截断、二进制拒绝、图片超限、data URL、reveal 平台分派 |
| `backend/tests/unit/test_artifact_interception.py` | 3 | `write_file` 成功落库、记录失败不阻断写入、无 context 跳过 |
| `backend/tests/api/test_artifact_routes.py` | 5 | 3 条 API 路径、404（不存在/跨会话）、content kind 分派 |

### 7.2 Frontend

| 套件 | 测试数 |
| --- | --- |
| `src/features/artifacts/__tests__/artifactApi.test.ts` | 6 |
| `src/features/artifacts/__tests__/useArtifacts.test.ts` | 3 |
| `src/features/artifacts/__tests__/useArtifacts.rejection.test.ts` | 1 |
| `src/features/artifacts/__tests__/useArtifactContent.test.ts` | 2 |
| `src/features/artifacts/__tests__/useArtifactContent.rejection.test.ts` | 1 |
| `src/widgets/chat/__tests__/ProgressSection.test.tsx` | 5 |
| `src/widgets/chat/__tests__/ArtifactRow.test.tsx` | 2 |
| `src/widgets/chat/__tests__/ArtifactsSection.test.tsx` | 4 |
| `src/widgets/chat/__tests__/ArtifactViewer.test.tsx` | 6 |
| `src/widgets/chat/__tests__/RightPanel.test.tsx` | 2 |

完整仓库 suite：`npx vitest run` → 1173 passed / 2 skipped，0 failed；`npx tsc --noEmit` 0 type error。

## 8. 未来迭代

- **PDF / Excel 预览**：当前 PDF 落入 `text` fallback 会因二进制被拒，Excel 同理；需新增 kind 与专用渲染器；
- **跳转消息定位**：`tool_call_id` 列已预留，可在 Artifacts 行增加"定位到消息"，按 `tool_call_id` 滚动至产生该产物的工具调用消息；
- **产物搜索 / 过滤**：按名称、kind 过滤与关键词搜索；
- **实时刷新**：当前列表依赖面板打开/session 切换时拉取，未来可由流式事件（工具调用完成）主动 `refresh()`；
- **win7 LTS 同步**：本特性尚未 cherry-pick 至 `release/win7`（py3.8 兼容性需单独验证）。

## 9. 文件清单

### Backend
- `backend/data/database.py`（MODIFY：`artifacts` 表 + `idx_artifacts_session` 索引）
- `backend/data/artifact_repo.py`（NEW）
- `backend/data/artifact_reader.py`（NEW）
- `backend/api/artifact_routes.py`（NEW）
- `backend/main.py`（MODIFY：挂载 artifact router，`prefix="/api/v1"`）
- `backend/tools/file_tool.py`（MODIFY：`detect_artifact_kind` + `_record_artifact_safely` + 写入后拦截）

### Frontend
- `src/features/artifacts/artifactApi.ts`（NEW）
- `src/features/artifacts/useArtifacts.ts`（NEW）
- `src/features/artifacts/useArtifactContent.ts`（NEW）
- `src/widgets/chat/progress/ProgressSection.tsx`（NEW）
- `src/widgets/chat/artifacts/ArtifactRow.tsx`（NEW）
- `src/widgets/chat/artifacts/ArtifactsSection.tsx`（NEW）
- `src/widgets/chat/artifacts/ArtifactViewer.tsx`（NEW）
- `src/widgets/chat/RightPanel.tsx`（NEW）
- `src/widgets/chat/RightPanelToggle.tsx`（NEW）
- `src/pages/Chat.tsx`（MODIFY：头部 Toggle + ChatInput 后挂载 RightPanel）

### Docs
- `docs/technical/38-artifacts-panel.md`（NEW，本章节）

## 10. 引用

- 计划：`docs/superpowers/plans/2026-08-01-artifacts-panel.md`
- 任务简报/报告：`.superpowers/sdd/2026-08-01-artifacts-panel/`
