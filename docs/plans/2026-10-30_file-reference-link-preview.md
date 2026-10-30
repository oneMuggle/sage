# 会话内文件引用超链接 + 侧边栏预览

> 状态：实施中
> 分支：`feat/file-reference-preview`
> 日期：2026-10-30

## 1. 背景与目标

当前 Sage 的会话消息里，模型提到或生成的文件只有两种呈现：

- 助手正文中的路径是纯文本（markdown `a` 一律按外链 `target="_blank"` 处理）；
- 用户 `@文件` 引用 chip、工具卡（write_file/edit_file）中的文件名不可点击。

用户希望**对齐主流 AI 应用**（Claude artifact 面板、ChatGPT Canvas、Copilot side pane、VS Code Copilot）的交互：消息中的文件引用渲染为可点击 chip/链接，点击后在**会话内右侧栏**打开预览，不跳出对话、不新开窗口。

### 目标

1. 消息内（助手正文、用户引用、工具卡）出现的文件都可点击 → 打开右栏预览。
2. 右栏预览统一支持文本/代码/markdown/CSV/图片/PDF/docx/xlsx/pptx/HTML。
3. 文件不存在时给出明确失效态，不静默失败。
4. 所有路径访问经会话绑定工作区 + realpath 边界校验，不新增任意路径读取通道。

### 非目标

- 不实现代码块 filename header 点击（可作为后续增强）。
- 不实现工作区外任意文件预览（工作区外文件只允许通过已登记 artifact 打开）。
- 不改消息数据库结构（不做 file_refs 持久化）。

## 2. 现状盘点

| 能力 | 现状 | 位置 |
| --- | --- | --- |
| 右栏容器 / Tab | progress、outline、changes、artifacts 四个 Tab | `src/widgets/chat/RightPanel.tsx:56-63` |
| 右栏全局状态 | `selectArtifact / selectChange / selectPreview` | `src/features/right-panel/rightPanelStore.ts:170-190` |
| 产物预览 | 文本/代码/图片/PDF/Office/HTML/Markdown/CSV 全类型 | `src/widgets/chat/artifacts/ArtifactViewer.tsx:343-405` |
| 产物内容 API | `/sessions/{id}/artifacts/{aid}/content` | `backend/api/artifact_routes.py:32-60` |
| 工作区文本预览 | `/sessions/{id}/workspace/changes/file?path=`（2MiB 上限、NUL 嗅探、512KiB 截断、realpath 校验） | `backend/api/workspace_routes.py:415-453` |
| 文档级预览组件 | `DocumentPreview` 支持 docx/pdf/xlsx/pptx，但**未接入生产 UI** | `src/widgets/chat/preview/DocumentPreview.tsx` |
| 消息 markdown | react-markdown v9，`a` 组件无文件识别 | `src/widgets/chat/MessageMarkdownParts.tsx:186-198` |
| 用户 @文件 chip | 纯 `<span>`，不可点击 | `src/widgets/chat/MessageClientMeta.tsx:65-75` |
| 工具卡文件名 | 纯文本 | `src/widgets/chat/toolRenderers/FileWriteToolRenderer.tsx:21-52` |
| IPC 命令注册 | `electron/commandRoutes/sessions.ts` 声明式 route，`invoke` 通用转发 | `electron/commands.ts` |
| 编辑器打开 | `file:open-in-editor`（URL 写错 + 无包含校验） | `electron/main.ts:2093-2127` |
| 提示词 | 无文件路径输出约定 | `backend/agents/profiles.py` |

## 3. 技术方案

### 3.1 后端：工作区文件预览与批量解析

新增两个端点（router 挂在 `/api/v1/sessions/{session_id}/workspace`）：

1. `GET /preview?path=` — 返回与 artifact content 同形状的内容：
   - 文本类：`{ok, kind, content, truncated}`（2MiB 读取上限、NUL → 二进制错误、512KiB 截断）
   - 图片：`{ok, kind:"image", data_url}`（10MB 上限）
   - PDF：`{ok, kind:"pdf", data_url}`（20MB 上限）
   - docx/xlsx/pptx：`{ok, kind, html, structured?}`（20MB 上限）
   - HTML/HTM：`{ok, kind:"html", content}`
2. `POST /resolve` — body `{paths: string[]}`（≤50），返回 `{results: [{path, exists, kind}]}`，用于消息完成后批量判定文本候选路径是否真实存在。

路径规则：

- 相对路径 → 与**会话绑定工作区根**拼接；绝对路径 → 直接使用；
- `_path_within_workspace`（realpath + `startswith(root + os.sep)`）校验，越界 → 403；
- 文件不存在 → 404；不信任调用方传入的 workspace 根。

实现方式：在 `backend/data/artifact_reader.py` 增加 path 版读取函数
（`read_text_path / read_image_path / read_pdf_path / read_office_path`），
现有 artifact 版函数改为「查 artifact → 调 path 版」，避免重复逻辑；新端点直接复用 path 版。

### 3.2 IPC / 前端 API

- `electron/commandRoutes/sessions.ts` 增加：
  - `workspace_preview_file`（GET `/workspace/preview`）
  - `workspace_resolve_files`（POST `/workspace/resolve`）
- `src/shared/api/workspaceApi.ts` 增加 `previewFile(sessionId, path)` / `resolveFiles(sessionId, paths)` 及 wire 类型。

### 3.3 右栏统一文件预览

- `rightPanelStore` 新增 `selectedFilePath` + `openFilePreview(path)` / `clearFilePreview()`；
  `openFilePreview` 与 `selectArtifact` 互斥（互相清除对方选中态）。
- 从 `ArtifactViewer` 抽出内容分发（image/pdf/html/office/code/markdown/csv/text）为
  `src/widgets/chat/preview/FileContentRenderer.tsx`，`ArtifactViewer` 与新的
  `FilePreviewPanel` 共用（`MarkdownRendered` / `CsvPreview` 一并迁移）。
- 新增 `FilePreviewPanel`：头部返回、路径面包屑、复制路径、外部编辑器打开；内容走
  `workspaceApi.previewFile`，加载/错误/截断提示齐备。
- `RightPanel` 详情态优先级：`selectedArtifactId` → `ArtifactViewer`；
  `selectedFilePath` → `FilePreviewPanel`；否则按 Tab 渲染。

### 3.4 消息内引用可点击

- 用户 `@文件` chip：`<span>` → `<button>`，点击 `openFilePreview(ref.path)`。
- `FileWriteToolRenderer`：文件名改为按钮，点击 `openFilePreview(filePath)`。
- Markdown `a` 组件：识别本地路径 href（非 `http(s)://` / `mailto:` / `#` / `sage-file://`），
  拦截默认行为 → `openFilePreview(href)`；外链行为不变。
- 系统提示词（`backend/agents/profiles.py`）增加约定：
  「提到工作区内文件时使用 markdown 链接格式 `[文件名](相对路径)`；生成/修改文件后主动给出链接」。

### 3.5 文本兜底识别（M3）

- 消息完成后，对助手正文提取候选路径（含 `/` 或 `\`、带常见扩展名、长度受限），
  调 `workspace_resolve_files` 批量确认；
- 用 remark 插件把**确认存在**的文本路径替换为 link 节点，渲染时经 `a` 组件拦截打开预览；
- 流式期间不做识别，避免链接闪烁与请求风暴。

## 4. 涉及文件与模块

后端：

- `backend/data/artifact_reader.py`（path 版读取函数）
- `backend/api/workspace_routes.py`（`/preview`、`/resolve`）
- `backend/agents/profiles.py`（提示词约定）
- `backend/tests/test_workspace_preview.py`（新增）

Electron / 前端：

- `electron/commandRoutes/sessions.ts`
- `src/shared/api/workspaceApi.ts`
- `src/features/right-panel/rightPanelStore.ts`
- `src/widgets/chat/preview/FileContentRenderer.tsx`（新增，抽取）
- `src/widgets/chat/preview/FilePreviewPanel.tsx`（新增）
- `src/widgets/chat/RightPanel.tsx`
- `src/widgets/chat/MessageMarkdownParts.tsx`
- `src/widgets/chat/MessageClientMeta.tsx`
- `src/widgets/chat/toolRenderers/FileWriteToolRenderer.tsx`
- `src/widgets/chat/artifacts/ArtifactViewer.tsx`（改用抽取后的渲染器）
- 相关 `__tests__`

## 5. 实施步骤

- [x] M1 后端预览端点 + path 版读取函数 + 单测（文本/截断/二进制/越界/不存在/图片/Office/批量解析）——`test_workspace_preview_routes.py` 17 用例全绿
- [x] M2 右栏统一文件预览：rightPanelStore + FileContentRenderer 抽取 + FilePreviewPanel + RightPanel 接线 + 单测
- [x] M3 消息内引用可点击：用户 chip、工具卡、markdown `a` 拦截 + 单测；顺带修复 `file:open-in-editor`（URL 错误 + realpath 包含校验）
- [x] M4 提示词文件链接约定（`_FILE_REFERENCE_LINK_PROMPT` 并入 `build_system_base`）
- [x] M5 文本兜底识别（批量 resolve + remark 插件 + Provider）+ 单测
- [x] M6 全量回归：前端 5558 用例通过（1 个 IPC manifest 陈旧失败 → `npm run ipc:manifest` 重新生成后通过）；后端相关 72 用例、ruff、tsc、eslint 全绿

> 偏差说明：
> - `ToolCallCard` 头部由 `<button>` 改为 `<div role="button">`——文件名需要独立点击打开预览，嵌套 `<button>` 是非法 DOM。
> - 工作区外文件仍不支持直接预览（安全红线），只可通过已登记 artifact 查看。
> - 代码块 filename header 点击与 hover 预览卡片未纳入本期（非目标，留作后续增强）。

## 6. 风险评估与依赖

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 文本兜底误伤（代码片段/不存在路径） | 误渲染链接 | 仅「后端确认存在」才加链接；流式期不识别；样式克制 |
| 大文件/二进制 | 渲染卡顿 | 复用现有 2MiB/10MB/20MB 上限与截断提示 |
| 路径逃逸 | 安全 | 会话绑定根 + realpath 校验；绝对路径也须在工作区内 |
| Windows 路径差异（盘符/反斜杠） | 识别失败 | 后端用 `os.path.isabs`；前端候选提取兼容 `\`；补用例 |
| ArtifactViewer 抽取回归 | 产物预览失效 | 抽取后保留原测试并跑 `ArtifactViewer.test.tsx` |
| 提示词改动影响既有用例 | 测试红 | 先跑 prompts 相关测试，按需更新断言 |

依赖：无新增第三方依赖。OCR/图片识别不在范围内。
