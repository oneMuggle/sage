# ZCode 启发的 UI/功能优化方案

> 参考 `/home/fz/project/ZCode`（智谱 AI 编程工作台 v3.14.0）的功能与 UI 设计，
> 对 Sage 进行有针对性的优化。分支：`feat/zcode-inspired-optimizations`。

## 背景

ZCode 相比 Sage 的差异化优势主要集中在：
1. **开发者工作流集成度**：底部终端面板、内嵌 Diff 查看器、文档预览
2. **命令面板覆盖度**：所有页面 + 快速操作 + 最近会话都在 ⌘K 内
3. **信息密度**：底部终端 + 右侧面板 + 代码 Diff 三位一体

本方案从中选取 **4 个高 ROI 功能**，按优先级分批实施。

---

## 实施范围

### Phase 1：命令面板扩展（P0，无新依赖）✅ 已完成

**目标**：让 ⌘K 成为应用内唯一的全局导航入口，覆盖所有页面 + 高频操作。

**缺失的路由（对比 `src/pages/`）**：

| 路由 | 当前在命令面板? | 优先级 |
|---|---|---|
| `/memory` | ✓ 有 | - |
| `/knowledge` | ✓ 有 | - |
| `/todos` | ✅ 已补充 | 高 |
| `/scheduled` | ✅ 已补充 | 高 |
| `/model-catalog` | ✅ 已补充 | 中 |
| `/help` | ✅ 已补充 | 低 |

**缺失的操作命令**：

| 操作 | 说明 |
|---|---|
| `toggle-right-panel` | ✅ 已实现 |

**实施文件**：
- [x] `src/widgets/command/commandItems.ts` — 补充缺失路由 + 新操作命令
- [x] `src/widgets/command/CommandPalette.tsx` — 注册新操作的分派逻辑

---

### Phase 2：文档预览 Tab（P1，复用既有基础设施）✅ 已完成

**目标**：RightPanel 增加 `preview` Tab，渲染 Agent 生成的本地文档（DOCX/PDF/XLSX/PPTX）。

**复用基础设施**：
- `DocxNativePreview`（docx-preview 封装）
- `OfficePreviewPanel`（PDF/XLSX/PPTX 结构化渲染）
- `officeApi.readPdf/readExcel/readPpt`（后端 API 客户端）

**实施内容**：
1. [x] `rightPanelStore.ts` — 增加 `'preview'` 到 `RightPanelTab` 联合类型 + `previewFilePath` + `selectPreview()` / `clearPreview()`
2. [x] 新建 `src/widgets/chat/preview/DocumentPreview.tsx`
   - DOCX：`DocxNativePreview` 高保真渲染
   - PDF/XLSX/PPTX：`OfficePreviewPanel` 结构化渲染
   - 输入：相对工作区根的文件路径
3. [x] `RightPanel.tsx` — Tab 列表加 `preview`，显示 `DocumentPreview` 或占位提示
4. [x] `FileChangeCard.tsx` — 新增 Eye 按钮，点击在预览 Tab 打开 Office 文档

---

### Phase 3：底部终端面板（P1，新增 `@xterm/xterm` + `node-pty`）✅ 已完成

**目标**：底部可折叠终端面板，用户可直接在应用内操作 shell，减少上下文切换。

**参考 ZCode 设计**：
- xterm.js 渲染终端
- node-pty 提供 PTY 进程（shell）
- 底部可拖拽高度
- `` Ctrl+` `` 快捷键切换

**架构选择**：方案 A（node-pty in Electron 主进程），经 IPC 转发到 renderer。

**实施文件**：
1. [x] `electron/main.ts` — 注册 `pty:create` / `pty:write` / `pty:resize` / `pty:destroy` IPC handler（惰性加载 node-pty）
2. [x] `electron/preload.ts` — 添加 `pty` bridge（create/write/resize/destroy/onData/onExit）
3. [x] `src/shared/types/electron-api.d.ts` — 添加 `PtyElectronApiBridge` 接口 + `pty?` 到 `ElectronAPI`
4. [x] 新建 `src/features/terminal-panel/terminalPanelStore.ts` — Zustand store（open/height/ptyId/ptyError）
5. [x] 新建 `src/widgets/chat/TerminalPanel.tsx` — @xterm/xterm 封装 + 拖拽调整高度
6. [x] `src/pages/Chat.tsx` — 集成 TerminalPanel（main column 内 ChatInput 下方）+ `` Ctrl+` `` 快捷键
7. [x] `electron-builder.yml` — asarUnpack node-pty native addon

**依赖**：`@xterm/xterm` `@xterm/addon-fit` `node-pty`

---

### Phase 4：Diff 查看器增强（P2，无新依赖）

**目标**：Agent 修改文件后，在 RightPanel `changes` Tab 提供更清晰的 Diff 视图。

**已有基础**：
- `SplitDiff.tsx` + `diffHunks.ts` + `splitDiffParser.ts` 已存在
- `FileChangeCard.tsx` 已有文件级 Diff 渲染

**增强点**：
1. `FileChangeCard` 增加 **accept / reject** 单文件操作（调用后端 API 回滚）
2. 增加 **side-by-side 视图切换**（inline ↔ split 切换按钮）
3. 增加 "在编辑器打开" 按钮（IPC 调用系统默认编辑器）

> Phase 4 在 Phase 1-3 完成后单独 PR 实施，不阻塞本次。

---

## 实施顺序

```
Phase 1（命令面板扩展）  →  Phase 2（文档预览 Tab）  →  Phase 3（终端面板）
        ↓                         ↓                         ↓
  无新依赖，30 min          新增 pdfjs-dist，1 h        新增 xterm + node-pty，2 h
```

Phase 1-3 完成即提 PR，Phase 4 单独 PR。

---

## 涉及文件清单

### 修改
- `src/widgets/command/commandItems.ts`
- `src/widgets/command/CommandPalette.tsx`
- `src/features/right-panel/rightPanelStore.ts`
- `src/widgets/chat/RightPanel.tsx`
- `electron/main.ts`（Phase 3）
- `electron-builder.yml`（Phase 3 asarUnpack）
- `package.json`（依赖）

### 新建
- `src/widgets/chat/preview/DocumentPreview.tsx`（Phase 2）
- `src/widgets/terminal/TerminalPanel.tsx`（Phase 3）
- `src/widgets/terminal/terminalPanelStore.ts`（Phase 3）

### 测试
- `src/widgets/command/__tests__/commandItems.test.ts`（Phase 1）
- `src/widgets/chat/preview/__tests__/DocumentPreview.test.tsx`（Phase 2）
- `src/widgets/terminal/__tests__/terminalPanelStore.test.ts`（Phase 3）
