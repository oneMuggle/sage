# Office 文档功能：读取与生成 (PPT/Word/Excel)

- [x] M0 Foundation 完成（commits 6ae9434..0c90be1）

> **状态：** 计划（进行中）
> **日期：** 2026-07-16
> **作者：** planner agent
> **目标分支：** `main`（release/win7 同源兼容，见 §6）

---

## 0. TL;DR

为 Sage 增加 **Office 文档本地读取与生成能力**，使用业界标准的纯 Python 库
（`python-pptx`、`python-docx`、`openpyxl`），不引入 LibreOffice / .NET 等重型外部依赖。

| 维度 | 内容 |
|---|---|
| 涉及模块 | `backend/office/` (新) · `backend/api/office_routes.py` (新) · `src/features/office/` (新) · `src/pages/Office.tsx` (新) · `electron/commands.ts` · `electron/preload.ts` |
| 新增依赖 | `python-pptx==0.6.23` · `python-docx==1.1.2` · `openpyxl==3.1.5` · 全部为**纯 Python**，Win7 LTS (Py 3.8) 兼容 |
| 阶段数 | 3 阶段（每阶段独立可发布） |
| 预估代码量 | ~1500 行后端 + ~1200 行前端 + ~300 行测试 fixtures |
| 与现有架构冲突 | **零**（不修改 Layout/Chat/Wiki/Skills，仅新增路由 + 页面） |

---

## 1. 背景与目标

### 1.1 背景

Sage 当前是"对话型"桌面助手，但用户的实际工作流大量围绕 **Office 文档**：
- 让 LLM 读取 `.docx` 报告并基于内容回答
- 让 LLM 把分析结果输出成 `.pptx` 演示稿
- 让 LLM 把表格数据生成成 `.xlsx`

Sage 目前缺失这三类能力。此前曾有 officecli 集成计划（依赖 .NET OfficeCLI 二进制，**Win7 不兼容**）解决**预览**，
但该计划已于 2026-07-17 清理。本计划解决**读取 + 生成**（纯 Python，**Win7 LTS 兼容**）。

### 1.2 目标（按 MoSCoW 排序）

| 优先级 | 目标 |
|---|---|
| **Must** | 后端能读取 .pptx/.docx/.xlsx → 结构化 JSON（文本/表格/元数据） |
| **Must** | 后端能从 JSON 内容规格生成 .pptx/.docx/.xlsx → 文件落盘 |
| **Must** | 前端 `/office` 页面：上传文件 → 解析预览 → 生成新文件 → 下载 |
| **Must** | 副作用走 IPC 桥（用户授权），文件存到用户选定的本地目录 |
| **Should** | 与 Skills 系统集成：`/office` slash command 触发 LLM 工具调用 |
| **Should** | Round-trip：读 → 改 → 写（保留原格式最大兼容） |
| **Could** | 内置模板库（演示稿、报告、表格模板） |
| **Won't (v1)** | 在线协编辑、版本控制、与云端 Office 集成 |

### 1.3 非目标

- 不引入 LibreOffice / MS Office / OfficeCLI 等外部二进制
- 不做"实时预览"渲染（PPT Morph 等动画），那是 2026-06-26 计划的事
- 不修改 Office 文件的默认打开方式
- 不实现完整 OOXML 规范（仅覆盖 95% 实际使用场景）

---

## 2. 用户确认决策（2026-07-16）

> ✅ 用户已逐条确认，下面是最终决策：

| # | 问题 | 最终决策 | 与原默认差异 |
|---|---|---|---|
| Q1 | **作用对象** | **两者都要**：用户显式 UI + LLM 工具调用 | 默认 ✓ |
| Q2 | **输入来源** | **本地文件选择器 + 拖拽上传** | ⬆️ 在原生 dialog 之外增加 HTML5 drag-and-drop |
| Q3 | **MVP 包含编辑** | **是**——MVP 最终交付包含编辑现有 | ⬆️ 编辑功能进入 Phase 2 实现 |
| Q4 | **存储位置** | **Workspace 目录 + SQLite 元数据** | 默认 ✓ |
| Q5 | **LLM 集成** | **Phase 2 才接 slash command** | 默认 ✓ |
| Q6 | **Excel 库** | **pandas + openpyxl** | ⬆️ 引入 pandas（同时引入 numpy ~30MB bundle 增量可接受） |
| Q7 | **Phase 1 交付** | **Phase 1 = 读取 + 最小生成**（不含编辑） | 默认 ✓ |
| Q8 | **CJK 字体** | **依赖系统字体**，不打包 | 默认 ✓ |

### 2.1 由 Q3 调整带来的阶段重排

用户决定 MVP 包含编辑 → Phase 2 不只是"编辑 + LLM"，而是：

- **Phase 1（独立可发布）：** 读取 + 最小生成（从零生成 PPT/Word/Excel）
- **Phase 2（独立可发布）：** 编辑现有文档（替换文本/修改表格/追加 slide）+ LLM slash 集成
- **Phase 3（独立可发布）：** 模板库 + Excel 图表 + 性能优化

> 与原 plan 唯一差别：Phase 2 范围扩大（编辑 + LLM），Phase 3 不变。

### 2.2 由 Q2 调整带来的 UI 增量

`src/features/office/OfficeFilePicker.tsx` 增加 HTML5 drag-and-drop 支持：

```tsx
<div
  onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
  onDragLeave={() => setIsDragging(false)}
  onDrop={(e) => { e.preventDefault(); handleDroppedFiles(e.dataTransfer.files); }}
>
  {/* 既有 file picker UI */}
</div>
```

### 2.3 由 Q6 调整带来的依赖变更

`backend/requirements.txt` 追加：

```python
# DataFrame 处理（聚合、透视、数据校验）
pandas==2.2.3     # ~15MB wheel，依赖 numpy
```

> **bundle size 影响：** main +30MB（pandas + numpy）。release/win7 LTS 需在 `requirements-py38.txt` 中找 Py 3.8 兼容版本。
> **替代方案评估：** 纯 openpyxl 不够灵活，无法做 DataFrame 聚合。用户接受 bundle 增量换取功能完整性。

---

## 3. 技术方案

### 3.1 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│  React Renderer (src/pages/Office.tsx)                       │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │ FilePicker     │  │ ContentPreview  │  │ DownloadBtn  │  │
│  │ (Native dialog)│  │ (read JSON)     │  │ (save dialog)│  │
│  └────────┬───────┘  └────────┬────────┘  └──────┬───────┘  │
│           │                   │                  │          │
│           ▼                   ▼                  ▼          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  src/features/office/useOfficeDocuments.ts           │   │
│  │  src/shared/api/officeApi.ts  (typed wrapper)        │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼  IPC bridge                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  electron/preload.ts  (new: pickOfficeFile, etc.)    │   │
│  │  electron/commands.ts (new: office_* routes)         │   │
│  │  electron/officeIpc.ts (NEW file)                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼  HTTP POST /api/v1/office/*       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  backend/api/office_routes.py  (FastAPI router)      │   │
│  │    POST /ppt/read                                     │   │
│  │    POST /ppt/generate                                 │   │
│  │    POST /word/read  · POST /word/generate             │   │
│  │    POST /excel/read · POST /excel/generate            │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  backend/office/                                      │   │
│  │    ppt.py       (python-pptx wrappers)                │   │
│  │    word.py      (python-docx wrappers)                │   │
│  │    excel.py     (openpyxl wrappers)                   │   │
│  │    models.py    (Pydantic request/response models)   │   │
│  │    storage.py   (workspace directory management)      │   │
│  │    errors.py    (typed exception hierarchy)           │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 模块边界

| 层 | 模块 | 职责 | 不做什么 |
|---|---|---|---|
| 后端服务 | `backend/office/*.py` | 纯函数 + Pydantic 模型，不依赖 FastAPI | 不读写 HTTP / 不做权限 |
| 后端路由 | `backend/api/office_routes.py` | HTTP 边界，调用服务，返回 JSON | 不做业务逻辑 |
| 共享 API | `src/shared/api/officeApi.ts` | 类型化 IPC 客户端 | 不做 UI 状态 |
| Feature hook | `src/features/office/useOfficeDocuments.ts` | 业务逻辑 + 状态管理 | 不直接调 IPC |
| Page | `src/pages/Office.tsx` | UI 容器 | 不做业务逻辑 |
| Electron IPC | `electron/officeIpc.ts` | Native dialog (open/save) + HTTP bridge | 不做业务逻辑 |

### 3.3 文件存储策略

**默认：** 用户在文件选择器中选定"工作区目录"，所有生成文件落到
`<workspace>/office/<doc_id>/<timestamp>_<name>.<ext>`。

**元数据：** 存 SQLite 新表 `office_documents`，与 Sage 现有 DB 同库（不新建 DB）。

```sql
CREATE TABLE office_documents (
  id TEXT PRIMARY KEY,           -- uuid4
  workspace_path TEXT NOT NULL,  -- 用户选定的工作区
  doc_type TEXT NOT NULL,        -- 'ppt' | 'word' | 'excel'
  original_filename TEXT,        -- 用户上传的原始名（解析时记录）
  generated_filename TEXT,       -- 生成的文件名
  status TEXT NOT NULL,          -- 'parsed' | 'generated' | 'edited'
  created_at INTEGER NOT NULL,   -- unix timestamp ms
  updated_at INTEGER NOT NULL,
  metadata JSON                  -- 页数/Sheet 数/作者等
);
CREATE INDEX idx_office_docs_workspace ON office_documents(workspace_path);
```

> **安全：** 解析和生成均在工作区目录内做 path validation，
> 拒绝 `..` / 符号链接逃逸（参考 wiki_routes.py §6 已有的 sandbox 模式）。

### 3.4 IPC 接口契约（TypeScript 类型先行）

```typescript
// src/shared/api/types.ts （追加）
export type OfficeDocType = 'ppt' | 'word' | 'excel';

export interface OfficeDocumentSummary {
  id: string;
  workspace_path: string;
  doc_type: OfficeDocType;
  original_filename: string | null;
  generated_filename: string;
  status: 'parsed' | 'generated' | 'edited';
  created_at: number;
  updated_at: number;
  metadata: {
    page_count?: number;    // PPT/Word
    sheet_count?: number;   // Excel
    paragraph_count?: number;
    table_count?: number;
    file_size_bytes: number;
  };
}

export interface OfficePptReadResult {
  summary: OfficeDocumentSummary;
  slides: Array<{
    index: number;
    title: string | null;
    text_blocks: string[];
    table_count: number;
    image_count: number;
    notes: string | null;
  }>;
}

export interface OfficeWordReadResult {
  summary: OfficeDocumentSummary;
  paragraphs: Array<{ style: string; text: string; level: number }>;
  tables: Array<{ rows: string[][] }>;
  images: number;
}

export interface OfficeExcelReadResult {
  summary: OfficeDocumentSummary;
  sheets: Array<{
    name: string;
    rows: string[][];
    max_row: number;
    max_col: number;
  }>;
}

export interface OfficePptGenerateRequest {
  workspace_path: string;
  filename: string;
  slides: Array<{
    title: string;
    bullets?: string[];
    notes?: string;
  }>;
  template?: 'default' | 'minimal';
}

export interface OfficeWordGenerateRequest {
  workspace_path: string;
  filename: string;
  title: string;
  paragraphs: Array<{ heading?: 'h1' | 'h2' | 'h3'; text: string }>;
  tables?: Array<{ headers: string[]; rows: string[][] }>;
}

export interface OfficeExcelGenerateRequest {
  workspace_path: string;
  filename: string;
  sheets: Array<{
    name: string;
    headers: string[];
    rows: string[][];
  }>;
}
```

### 3.5 Electron IPC 新增

```typescript
// electron/commands.ts （追加）
office_ppt_read: { method: 'POST', path: () => '/api/v1/office/ppt/read' },
office_ppt_generate: { method: 'POST', path: () => '/api/v1/office/ppt/generate' },
office_word_read: { method: 'POST', path: () => '/api/v1/office/word/read' },
office_word_generate: { method: 'POST', path: () => '/api/v1/office/word/generate' },
office_excel_read: { method: 'POST', path: () => '/api/v1/office/excel/read' },
office_excel_generate: { method: 'POST', path: () => '/api/v1/office/excel/generate' },
office_list_documents: { method: 'GET', path: () => '/api/v1/office/documents' },
office_delete_document: {
  method: 'DELETE',
  path: (a) => `/api/v1/office/documents/${encodeURIComponent(String(a.id))}`,
},
```

```typescript
// electron/preload.ts （追加，参照 skills 模式）
office: {
  pickOfficeFile: (docType: 'ppt' | 'word' | 'excel') =>
    ipcRenderer.invoke('office:pick-file', { docType }) as Promise<{
      path: string; name: string; sizeBytes: number
    } | null>,
  pickSavePath: (defaultName: string) =>
    ipcRenderer.invoke('office:save-dialog', { defaultName }) as Promise<string | null>,
} satisfies OfficeElectronApiBridge,
```

```typescript
// electron/officeIpc.ts （新文件）
// 注册 ipcMain.handle('office:pick-file', ...) 和 ipcMain.handle('office:save-dialog', ...)
// 用 dialog.showOpenDialog / dialog.showSaveDialog
// 选完后调用 backend 解析或生成 → 返回结果给 renderer
```

---

## 4. 实施步骤

### 阶段 1：MVP 读取 + 最小生成（独立可发布）

> **目标：** 用户能在 `/office` 页面选一个 .pptx/.docx/.xlsx → 看到解析结果 → 下载。
> 生成功能从最简单的"标题+列表 → .pptx"开始。
> **可独立发布，不依赖后续阶段。**

#### 1.1 后端依赖与骨架（0.5 天）

1. **添加依赖**（File: `backend/requirements.txt`）
   - Action: 追加 `python-pptx==0.6.23`, `python-docx==1.1.2`, `openpyxl==3.1.5`
   - Why: 三个库均为纯 Python，Win7 LTS Python 3.8 wheel 完整，无 numpy/torch 等重依赖
   - 同源文件: `backend/requirements-py38.txt`（release/win7 分支）需同步追加
   - Risk: Low
   - Verify: `pip install -r backend/requirements.txt` 在 sage-backend 环境中成功

2. **创建 Pydantic 模型**（File: `backend/office/models.py`，新文件，~80 行）
   - Action: 定义 `OfficeDocType` 枚举 + 所有 Read/Generate Request/Response Pydantic models
   - 参照 `backend/wiki/models.py` 模式
   - Risk: Low

3. **创建错误层级**（File: `backend/office/errors.py`，新文件，~30 行）
   - Action: `OfficeError` 基类 + `OfficeFileNotFound` / `OfficeParseError` / `OfficePathError` / `OfficeGenerateError`
   - Why: 统一异常 → FastAPI HTTPException 映射（参照 wiki_routes.py §6）
   - Risk: Low

#### 1.2 三个核心 reader（2 天，TDD）

4. **PPT reader**（File: `backend/office/ppt.py`，新文件，~120 行 + 测试 ~150 行）
   - Action: `read_ppt(file_path: Path) -> OfficePptReadResult`
   - 纯函数，不依赖 FastAPI
   - 使用 `python-pptx.Presentation(path)` 遍历 slides
   - 提取 title/text_frame/table_count/image_count/notes
   - Test: `backend/office/__tests__/test_ppt.py`，**fixture: 一个小 .pptx**（人工用 PowerPoint 生成后 commit 进 `backend/office/__tests__/fixtures/sample.pptx`，git-lfs 不需要，单文件 <50KB）
   - 覆盖: 空 PPT、单 slide、多 slide、带表格、带图片

5. **Word reader**（File: `backend/office/word.py`，新文件，~100 行 + 测试 ~150 行）
   - Action: `read_docx(file_path: Path) -> OfficeWordReadResult`
   - 用 `python-docx.Document(path)` 遍历 paragraphs 和 tables
   - Test: fixture `sample.docx`，覆盖标题层级、段落、表格

6. **Excel reader**（File: `backend/office/excel.py`，新文件，~100 行 + 测试 ~150 行）
   - Action: `read_xlsx(file_path: Path) -> OfficeExcelReadResult`
   - 用 `openpyxl.load_workbook(path, data_only=True)`
   - 遍历 sheets → 每个 sheet 提取 headers + rows
   - **必须 `data_only=True`**，否则读取公式而非值
   - Test: fixture `sample.xlsx`，覆盖多 sheet、空 sheet、合并单元格

7. **storage 模块**（File: `backend/office/storage.py`，新文件，~80 行）
   - Action: `validate_workspace(path) -> Path`、`generate_document_dir(workspace, doc_type) -> Path`
   - path traversal 防御：`resolved.is_relative_to(workspace_resolved)`
   - SQLite 持久化：使用现有 `backend/data/database.py` 的 Database，新增 `office_documents` 表
   - Risk: Medium（路径安全）

8. **创建 FastAPI 路由**（File: `backend/api/office_routes.py`，新文件，~150 行）
   - Action: `APIRouter(prefix="/office")`，注册 3 个 read 端点（生成在阶段 1.4）
   - Mount 在 `/api/v1`（与 wiki_routes 同模式）
   - Test: 集成测试用 `httpx.AsyncClient` + FastAPI TestClient

9. **注册路由**（File: `backend/main.py`）
   - Action: `from backend.api.office_routes import router as office_router` + `app.include_router(office_router, prefix="/api/v1")`
   - Risk: Low

10. **SQLite 迁移**（File: `backend/data/migrations/00X_office_documents.sql`，新文件）
    - Action: CREATE TABLE 段（同 §3.3 schema）
    - 调用方：`Database.init_schema()` 自动加载新 migration 文件
    - Risk: Low

#### 1.3 前端基础设施（1 天）

11. **类型定义**（File: `src/shared/api/types.ts`）
    - Action: 追加 §3.4 中所有类型
    - Risk: Low

12. **API 客户端**（File: `src/shared/api/officeApi.ts`，新文件，~80 行）
    - Action: 参照 `skillsApi.ts` 模式：`officeReadPpt/Wordexcel/...`、`officeGenerate...`、`officeListDocuments`、`officeDeleteDocument`
    - 用 `invoke` + `withRetry` + `handleApiError`
    - Test: `src/shared/api/__tests__/officeApi.test.ts`，mock invoke

13. **Electron bridge**（File: `electron/preload.ts` + `electron/officeIpc.ts`）
    - Action: preload 暴露 `window.electronAPI.office.pickOfficeFile/pickSavePath`
    - officeIpc.ts 实现 `ipcMain.handle('office:pick-file', ...)` 用 `dialog.showOpenDialog`
    - Test: `electron/__tests__/officeIpc.test.ts`，mock electron

14. **IPC 路由注册**（File: `electron/commands.ts`）
    - Action: 追加 §3.5 的 COMMAND_ROUTES 条目
    - Risk: Low（参考已有 patterns）

#### 1.4 前端 /office 页面 + 生成（2 天）

15. **Feature hook**（File: `src/features/office/useOfficeDocuments.ts`，新文件，~100 行）
    - Action: `useOfficeDocuments()` 返回 `{ documents, loadDocuments, uploadFile, generatePpt/Word/Excel, deleteDocument }`
    - 状态: `loading`, `error`, `documents[]`
    - Test: vitest + mock officeApi

16. **Feature components**（File: `src/features/office/`，新目录）
    - `OfficeFilePicker.tsx` — 文件选择 UI（调 native dialog）
    - `OfficePreviewPanel.tsx` — 读取结果展示（按 doc_type 切换视图）
    - `OfficeGenerateForm.tsx` — 三种生成的表单（PPT 列表、Word 段落、Excel 表格）
    - `OfficeDocumentList.tsx` — 历史文档列表 + 删除
    - Test: 每个组件 2-3 个 vitest，mock hook

17. **Page**（File: `src/pages/Office.tsx`，新文件，~150 行）
    - Action: 整合所有 feature components + Toast
    - **样式：** 沿用 Skills.tsx 模式（卡片 + 列表 + 操作按钮）
    - Risk: Low

18. **Sidebar 导航**（File: `src/widgets/layout/Sidebar.tsx`）
    - Action: `navItems` 数组追加 `{ path: '/office', label: 'Office', icon: FileText }`
    - 插在 `/skills` 与 `/settings` 之间
    - Risk: Low（参考 PR #88 已有的 skills 入口模式）

19. **App 路由**（File: `src/App.tsx`）
    - Action: `import Office from './pages/Office'` + `<Route path="office" element={<Office />} />`
    - Risk: Low

20. **生成 endpoint**（File: `backend/api/office_routes.py`，追加）
    - Action: 注册 `POST /ppt/generate`, `/word/generate`, `/excel/generate`
    - 调用 `backend/office/{ppt,word,excel}.py::generate_*` 纯函数
    - Test: 集成测试覆盖基本生成

#### 1.5 阶段 1 测试与文档（1 天）

21. **单元测试覆盖率 ≥ 80%**
    - Backend: `backend/office/__tests__/` 覆盖所有 reader/generator 纯函数
    - Frontend: vitest 覆盖所有 hook + 主要组件

22. **用户手册**（File: `docs/user-manual/XX-office-features.md`，新文件）
    - Action: 介绍上传/生成/下载/列表 4 个核心场景，附截图占位

23. **技术文档**（File: `docs/technical/XX-office-features.md`，新文件）
    - Action: 架构图、IPC 契约、库选型理由、Win7 兼容说明

24. **删除本计划文件**（完成 §1.5 后）
    - Action: 按 `docs/feature-development.md` 规范，文档归档到 technical/user-manual 后**删除** `docs/plans/2026-07-16_office-features.md`

**阶段 1 验收标准：**
- [ ] `curl -X POST http://127.0.0.1:8765/api/v1/office/ppt/read -d '{"file_path":"...sample.pptx"}'` 返回 200 + JSON
- [ ] `/office` 页面能上传 + 看到预览 + 生成简单 PPT + 下载
- [ ] CI 5/5 全绿（Frontend TS / Electron build x2 / Electron smoke / Backend pytest）

---

### 阶段 2：编辑现有 + Round-trip + LLM 集成（独立可发布）

> **目标：** 用户能上传 → 编辑（替换文本、修改表格）→ 下载。
> 引入 LLM 工具调用：ChatInput slash menu 加 `/office` 选项。

#### 2.1 编辑现有（2 天）

25. **PPT 编辑器**（File: `backend/office/ppt.py`）
    - Action: `edit_ppt(file_path: Path, edits: List[PptEdit]) -> OfficeDocumentSummary`
    - Edit 类型: `ReplaceText(slide_idx, old, new)`、`AppendSlide(title, bullets)`、`DeleteSlide(idx)`
    - 加载 → 修改 → 保存到 `<workspace>/edited_<timestamp>_<name>.pptx`，**不覆盖原文件**

26. **Word 编辑器**（File: `backend/office/word.py`）
    - Action: 同上模式，`ReplaceText`、`AppendParagraph`、`ReplaceTable`
    - Note: python-docx 修改是 in-place；保存到新文件避免破坏原文件

27. **Excel 编辑器**（File: `backend/office/excel.py`）
    - Action: `ReplaceCell(sheet, row, col, value)`、`AddSheet` 等
    - **保留公式**：`openpyxl` 默认保留公式 cell，但需 `data_only=False` 写入

28. **编辑 endpoint**（File: `backend/api/office_routes.py`）
    - Action: `POST /ppt/edit`, `/word/edit`, `/excel/edit`
    - Pydantic 校验 edit ops

29. **前端编辑 UI**（File: `src/features/office/OfficeEditPanel.tsx`）
    - Action: 选中 slide/段落/单元格 → inline 编辑 → 保存
    - 不做富文本（仅纯文本替换）

#### 2.2 LLM 工具调用（1 天）

30. **Backend tool 注册**（File: `backend/agents/tools/office_tool.py`，新文件）
    - Action: 定义 `OfficeReadTool` 和 `OfficeGenerateTool`，注册到工具系统（参照 skills pattern）
    - 让 LLM agent 能调用这些工具

31. **Slash command**（File: `src/features/chat/`）
    - Action: ChatInput slash menu 加 `/office` 选项
    - 用户输入 `/office read <path>` → LLM 决定调 read tool
    - 参照 PR #86/#87 的 skill slash 集成模式

#### 2.3 阶段 2 文档同步

32. 更新用户手册 §2.4（编辑章节）
33. 更新技术文档 §3（新增 LLM 工具章节）

**阶段 2 验收标准：**
- [ ] 用户能在 UI 编辑现有 PPT/Word/Excel 并下载
- [ ] Chat 中输入 `/office read xxx.pptx` 触发 LLM 调用 read tool
- [ ] CI 全绿

---

### 阶段 3：模板库 + 图表 + 优化（独立可发布）

> **目标：** 模板库、Excel 图表、批量生成、性能优化。

#### 3.1 模板库（2 天）

34. **模板目录**（File: `backend/office/templates/`，新目录）
    - Action: 内置 3 个 PPT 模板（default/minimal/blank）+ 1 个 Word 模板 + 1 个 Excel 模板
    - **不打包 .pptx 二进制**，用代码生成（python-pptx 创建模板内容）
    - 用户也可上传自定义模板

35. **模板选择 UI**（File: `src/features/office/OfficeTemplatePicker.tsx`）

#### 3.2 Excel 图表（1 天）

36. **图表生成**（File: `backend/office/excel.py`）
    - Action: `add_chart(sheet, chart_type, data_range)`
    - 支持 `LineChart`/`BarChart`/`PieChart` 三种

#### 3.3 性能优化

37. **流式读取**：大文件 (>5MB) 改用流式，避免一次性 load 到内存
38. **缓存**：相同文件 sha256 缓存解析结果
39. **压缩上传**：>10MB 文件前端压缩后上传

**阶段 3 验收标准：**
- [ ] 模板选择能生成符合模板样式的文档
- [ ] Excel 图表生成正确
- [ ] 100MB Excel 文件解析 <5s

---

## 5. 测试策略

### 5.1 单元测试（pytest）

| 文件 | 覆盖 |
|---|---|
| `backend/office/__tests__/test_ppt.py` | `read_ppt`、`generate_ppt`、`edit_ppt` |
| `backend/office/__tests__/test_word.py` | 同上 |
| `backend/office/__tests__/test_excel.py` | 同上 |
| `backend/office/__tests__/test_storage.py` | path validation、SQLite 持久化 |
| `backend/office/__tests__/test_errors.py` | 异常 → HTTPException 映射 |
| `backend/api/__tests__/test_office_routes.py` | 端到端 HTTP 集成测试 |

**Fixtures：** `backend/office/__tests__/fixtures/` 包含手工生成的小样本文件
（每个 <50KB，git 直接追踪，无需 lfs）：
- `sample.pptx` — 3 slides，含表格/图片
- `sample.docx` — 标题 + 段落 + 表格
- `sample.xlsx` — 2 sheets
- `empty.pptx`/`empty.docx`/`empty.xlsx` — 边界 case

### 5.2 前端单元测试（vitest）

| 文件 | 覆盖 |
|---|---|
| `src/shared/api/__tests__/officeApi.test.ts` | mock invoke，覆盖正常/错误路径 |
| `src/features/office/__tests__/useOfficeDocuments.test.ts` | hook 行为 |
| `src/features/office/__tests__/OfficeFilePicker.test.tsx` | 渲染 + 交互 |
| `src/features/office/__tests__/OfficePreviewPanel.test.tsx` | 三种 doc_type 切换 |
| `src/features/office/__tests__/OfficeGenerateForm.test.tsx` | 表单提交 |

### 5.3 E2E 测试（Playwright，可选 Phase 2）

- `e2e/office-upload-preview.spec.ts` — 上传 .pptx → 看到预览
- `e2e/office-generate-download.spec.ts` — 生成 PPT → 验证文件下载

### 5.4 测试覆盖率门槛

- 后端：≥ 80%（按测试规范 §testing.md）
- 前端：≥ 75%（UI 组件）
- **关键路径**（read/generate 纯函数）：100%

---

## 6. 风险与缓解

### 6.1 风险矩阵

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| R1 | **大文件 OOM**（100MB+ Excel） | 高 | 阶段 3 引入流式读取；Phase 1 加 50MB 上限 + 友好提示 |
| R2 | **CJK 字体渲染**（用户系统缺中文字体） | 中 | python-pptx/docx 写入不嵌入字体；README 提示装"微软雅黑" |
| R3 | **Win7 LTS wheel 缺失** | 中 | python-pptx/docx/openpyxl 均为纯 Python wheel，Py 3.8 有；CI 在 `release/win7` PR 验证 |
| R4 | **Bundled Python 依赖膨胀** | 中 | 三个库合计 ~2MB（纯 Python，无 C 扩展），bundled size 增量 <5MB |
| R5 | **SQLite 迁移兼容性** | 低 | 新增表，不动旧 schema；与现有 `Database.init_schema()` 模式一致 |
| R6 | **Path traversal 攻击** | 中 | `storage.validate_workspace()` 严格 `is_relative_to` 校验（参照 wiki_routes） |
| R7 | **OOXML 边界格式**（少见宏/嵌入对象） | 中 | MVP 不读/写宏，解析失败返回 `OfficeParseError` + 详细错误 |
| R8 | **LLM 工具误用**（生成超大文档） | 中 | 加 size limit + 用户确认对话框 |
| R9 | **IPC 类型契约漂移** | 低 | 所有类型集中在 `src/shared/api/types.ts`，COMMAND_ROUTES 测试 guard |

### 6.2 与 release/win7 LTS 分支的关系

**好消息：python-pptx、python-docx、openpyxl 三个库都是纯 Python，没有 C 扩展，**
**Python 3.8 wheel 完整。所以 main 上的实现可以 byte-for-byte port 到 release/win7，**
**无需任何修改。**

唯一需要同步的：
- `backend/requirements.txt` → `backend/requirements-py38.txt`
- 三个新增 backend 模块
- 三个新增 frontend feature 文件
- 路由注册 / Sidebar 导航 / App 路由

预计 port 工作量：~半天（cherry-pick + 跑 CI）。

### 6.3 与 2026-06-26 officecli 计划的关系

- officecli 计划：**预览**（外部 .NET 二进制）
- 本计划：**读取 + 生成**（纯 Python）
- **两者独立、可并行、不互相依赖**
- 阶段 1 完成后，前端可在 PreviewPanel.tsx 中根据文件类型路由：
  - `.pptx` → 解析 + 显示文本（本期） → 后续可换成 officecli 预览（待合并）
- 用户不需要 officecli 也能用本计划的功能

### 6.4 与现有架构的兼容性

| 维度 | 影响 |
|---|---|
| FastAPI 启动流程 | 无（只新增 1 个 router） |
| Electron 主进程 | 无（只新增 1 个 IPC 模块 + 8 个 COMMAND_ROUTES 条目） |
| Vite 配置 | 无 |
| 数据库 | **新增** 1 个表（向后兼容） |
| Sidebar | **新增** 1 个导航项（参考 PR #88 模式） |
| Layout.tsx | **零**修改（用户约束已确认） |

---

## 7. 依赖清单

### 7.1 后端（新增）

```python
# backend/requirements.txt 追加
python-pptx==0.6.23   # PPTX 读写，~5MB wheel，纯 Python
python-docx==1.1.2    # DOCX 读写，~2MB wheel，纯 Python
openpyxl==3.1.5       # XLSX 读写，~1MB wheel，纯 Python
```

**版本验证：**
- python-pptx 0.6.23 是 2024-12 最新稳定版，支持 PPTX 格式（PowerPoint 2007+）
- python-docx 1.1.2 是 2024-05 最新稳定版
- openpyxl 3.1.5 是 2024-08 最新稳定版，支持 xlsx 全部特性 + 图表（Phase 3）

**三个库同作者**（Steve Canny），文档规范，API 一致，社区活跃。

### 7.2 前端

无新增 npm 依赖。沿用现有：
- React + TypeScript + react-router-dom
- sonner（Toast）
- lucide-react（图标，FileText / Upload / Download 等）
- clsx（className 工具）

### 7.3 系统依赖

- **无**新系统级依赖（与 officecli 计划不同）
- Linux 用户需 `python3-pip` 已存在（Conda 环境提供）

---

## 8. 文件改动清单

### 8.1 新增文件

**后端（21 个）：**
- `backend/office/__init__.py`
- `backend/office/models.py`
- `backend/office/errors.py`
- `backend/office/ppt.py`
- `backend/office/word.py`
- `backend/office/excel.py`
- `backend/office/storage.py`
- `backend/api/office_routes.py`
- `backend/data/migrations/00X_office_documents.sql`
- `backend/office/__tests__/__init__.py`
- `backend/office/__tests__/test_ppt.py`
- `backend/office/__tests__/test_word.py`
- `backend/office/__tests__/test_excel.py`
- `backend/office/__tests__/test_storage.py`
- `backend/office/__tests__/test_errors.py`
- `backend/office/__tests__/fixtures/sample.pptx`
- `backend/office/__tests__/fixtures/sample.docx`
- `backend/office/__tests__/fixtures/sample.xlsx`
- `backend/office/__tests__/fixtures/empty.pptx`
- `backend/office/__tests__/fixtures/empty.docx`
- `backend/office/__tests__/fixtures/empty.xlsx`

**前端（13 个）：**
- `src/shared/api/officeApi.ts`
- `src/features/office/useOfficeDocuments.ts`
- `src/features/office/OfficeFilePicker.tsx`
- `src/features/office/OfficePreviewPanel.tsx`
- `src/features/office/OfficeGenerateForm.tsx`
- `src/features/office/OfficeDocumentList.tsx`
- `src/features/office/index.ts`
- `src/features/office/__tests__/useOfficeDocuments.test.ts`
- `src/features/office/__tests__/OfficeFilePicker.test.tsx`
- `src/features/office/__tests__/OfficePreviewPanel.test.tsx`
- `src/features/office/__tests__/OfficeGenerateForm.test.tsx`
- `src/shared/api/__tests__/officeApi.test.ts`
- `src/pages/Office.tsx`

**Electron（2 个）：**
- `electron/officeIpc.ts`
- `electron/__tests__/officeIpc.test.ts`

**文档（3 个）：**
- `docs/user-manual/XX-office-features.md`
- `docs/technical/XX-office-features.md`
- 本计划文件（完成后删除）

### 8.2 修改文件

| 文件 | 改动 | 备注 |
|---|---|---|
| `backend/requirements.txt` | +3 行 | 新增三个库 |
| `backend/main.py` | +3 行 | 导入 + include_router |
| `electron/preload.ts` | +10 行 | 暴露 office bridge |
| `electron/commands.ts` | +12 行 | 8 个 IPC 路由 |
| `electron/main.ts` | +3 行 | 调用 registerOfficeIpc |
| `src/App.tsx` | +3 行 | import + Route |
| `src/widgets/layout/Sidebar.tsx` | +2 行 | navItems 加 office |
| `src/shared/api/types.ts` | +60 行 | 新增类型 |
| `src/shared/api/index.ts` | +2 行 | export officeApi |
| `backend/data/database.py` | +5 行 | 自动加载新 migration |

**总计：~10 个修改文件 + ~36 个新文件**

### 8.3 文件行数预估

| 模块 | 行数（不含测试） | 行数（含测试） |
|---|---|---|
| 后端 office/ | ~700 | ~1500 |
| 后端 api/ | ~150 | ~250 |
| 前端 features/office/ | ~600 | ~1000 |
| 前端 pages/Office.tsx | ~150 | ~150 |
| Electron | ~100 | ~200 |
| 文档 | ~400 | ~400 |
| **总计** | **~2100** | **~3500** |

---

## 9. 成功标准

### 9.1 功能标准

- [ ] 用户在 `/office` 页能选本地 .pptx/.docx/.xlsx → 看到解析后的文本和表格
- [ ] 用户能在 `/office` 页生成简单 PPT（标题+列表）/Word（段落）/Excel（表格）并下载
- [ ] Office 文档元数据持久化在 SQLite，可列出/删除历史
- [ ] 编辑现有文件后下载，新文件保留原文件（不覆盖）
- [ ] Phase 2: ChatInput slash menu 加 `/office`，LLM 可调用 read tool
- [ ] Phase 3: 用户可选模板生成，Excel 可生成图表

### 9.2 质量标准

- [ ] 单元测试覆盖率 ≥ 80%（后端），≥ 75%（前端）
- [ ] CI 5/5 全绿（含 Electron smoke）
- [ ] 无 CRITICAL/HIGH lint 问题
- [ ] 无 `console.log` / hardcoded secrets
- [ ] 文件 <800 行 / 函数 <50 行 / 嵌套 ≤4 层

### 9.3 兼容性标准

- [ ] main 分支可正常打包、运行
- [ ] release/win7 分支可 byte-for-byte port，所有 CI 绿
- [ ] Linux/macOS/Windows 三平台均可（bundled Python 包含）
- [ ] 与现有 Layout/Chat/Wiki/Skills 无任何回归

### 9.4 文档标准

- [ ] `docs/user-manual/XX-office-features.md` 完成
- [ ] `docs/technical/XX-office-features.md` 完成
- [ ] README 顶部章节引用更新
- [ ] 本计划文件按规范在归档后删除

---

## 10. 附录

### A. 关键参考

| 来源 | 用途 |
|---|---|
| [python-pptx 官方文档](https://python-pptx.readthedocs.io/) | API 参考 |
| [python-docx 官方文档](https://python-docx.readthedocs.io/) | API 参考 |
| [openpyxl 官方文档](https://openpyxl.readthedocs.io/) | API 参考 |
| `backend/api/wiki_routes.py` | 路由 + sandbox 模式参考 |
| `src/shared/api/skillsApi.ts` | API 客户端模式参考 |
| `electron/skillsIpc.ts` | Electron IPC 模块参考 |

### B. 与已合并的 PR 模式对齐

| 已合并 PR | 借鉴 |
|---|---|
| PR #86 (#87) ChatInput SKILL.md slash 集成 | slash command 集成模式 |
| PR #88 Sidebar 加 Skills 入口 | 侧边栏导航项添加模式 |
| PR #91 Skills 管理（删除+自动刷新） | Feature slice + 乐观更新 + 错误回滚模式 |
| PR #94 Skills 加载新技能（Rescan/Import） | IPC bridge 加新方法模式 |
| PR #98 Electron 桌面日志 | native dialog 集成模式 |

### C. 风险检查清单（实施前）

- [ ] 用户已确认 §2 中 Q1-Q8 全部问题
- [ ] 用户已确认 9.x 成功标准
- [ ] 用户已确认阶段 1 完成后即合 main + 发 alpha（按项目 feature-branch-workflow.md 流程）
- [ ] release/win7 同步计划已约定（预计阶段 1 完成后立即 cherry-pick + 发 LTS）