# Sage UI 优化实施方案（2026-09-12）

- **状态**：草稿，待评审
- **范围**：main 分支 → 验证后按需 cherry-pick 到 `release/win7`
- **工作分支**：`feat/ui-optimization-plan`（worktree: `.worktrees/feat-ui-optimization-plan`）
- **背景**：2026-09-12 对 Sage 桌面端 UI 与主流 AI 工具（ChatGPT / Claude.ai / Cursor / Windsurf / Perplexity / v0.dev）的横向对比，识别出 **18 项差距**，按价值/成本分 P0/P1/P2/P3 四级。本计划为**实施方案**，不承诺全部落地，建议按迭代分批选做。

## 1. 现状总结

### 1.1 当前布局架构

```
┌─────────────────────────────────────────────────────────────┐
│ [Sidebar 左]      │ [Titlebar 顶栏]                          │
│  品牌 + 7导航     │ [          <Outlet /> 当前路由页         ] │
│  会话分组列表     │   (Chat / Memory / Knowledge / ...)       │
│  定时任务         │                                          │
│  项目/团队占位    │   Chat页: + fixed 右抽屉 RightPanel       │
│  连接状态+版本    │      (Progress/Changes/Artifacts, w-80)   │
└─────────────────────────────────────────────────────────────┘
```

**技术栈**：Tailwind + Radix UI + FSD 架构 + Zustand + React Router v6 + Electron。

**关键文件**：
- 外壳：`src/widgets/layout/Layout.tsx` / `Sidebar.tsx` / `Titlebar.tsx`
- Chat 三栏：`src/pages/Chat.tsx` / `src/widgets/chat/RightPanel.tsx`
- 其他页面各自定义内部布局（Knowledge / Settings / Office 等）

### 1.2 已有能力（不需重复建设）

- ✅ 左 Sidebar 折叠 + Hover Peek + `Ctrl/Cmd+B`
- ✅ 会话列表搜索 + 拖拽排序 + 重命名 + 删除
- ✅ AttnBadge（待审批+待回答数）
- ✅ 渐进式功能披露（U10）
- ✅ ⌘K 命令面板（cmdk）
- ✅ RightPanel 三 Tab（Progress / Changes / Artifacts）
- ✅ ArchivesModal（归档查看）
- ✅ ErrorBoundary 隔离
- ✅ 响应式（< 768px 覆盖层）

---

## 2. 差距矩阵（18 项）

### 2.1 左栏 Sidebar（对标 ChatGPT / Claude / Cursor / Windsurf）

| # | 维度 | 主流做法 | Sage 现状 | 差距级别 |
|---|---|---|---|---|
| 1 | 会话项元信息 | 最后消息预览 + 相对时间 + 消息数 | 仅标题 + 模型徽章 | ⚠️ 中 |
| 2 | 折叠态 icon rail | Claude 极窄 icon rail（~56px）| `translate-x-full` 全隐藏 | ⚠️ 中 |
| 3 | Workspace 切换 | Cursor/Windsurf 顶部 workspace 下拉 | 无 | ❌ 缺失 |
| 4 | Fuzzy 搜索 | Cmd+K 全局 + 会话内 fuzzy | Cmd+K 仅命令 | ⚠️ 割裂 |
| 5 | 收藏夹/Pin | Claude "Star conversations" | 无 | ❌ 缺失 |
| 6 | 会话分享 | Claude/ChatGPT 一键分享链接 | 无 | ❌ 缺失 |
| 7 | 会话导出 | 原生导出 markdown/PDF | 仅 Memory 页 | ⚠️ 缺失 |
| 8 | Hover 操作 | ChatGPT 悬停三按钮 | 两步删除 + 重命名 | ⚠️ 路径长 |

### 2.2 右栏 RightPanel（对标 Claude Artifacts / Cursor Panel / v0.dev）

| # | 维度 | 主流做法 | Sage 现状 | 差距级别 |
|---|---|---|---|---|
| 9 | 出现范围 | Cursor 全局可切 Chat/Terminal/Problems | 仅 Chat 页 | ❌ 缺失 |
| 10 | 宽度可调 | 所有主流工具拖拽分割条 | 固定 w-80 | ❌ 缺失 |
| 11 | 独立窗口 | Cursor "Move to secondary sidebar" | 无 | ❌ 缺失 |
| 12 | Artifacts 实时预览 | Claude 可运行 HTML/SVG/React | 仅文本展示 | ❌ 缺失（重大）|
| 13 | Diff 视图 | Cursor side-by-side diff | ChangesSection 仅列表 | ⚠️ 无对比 |
| 14 | 运行时日志 | Cursor Terminal + Output + Debug Console | ProgressSection 仅任务步骤 | ⚠️ 缺失 |
| 15 | Console/Network | Chrome DevTools 式面板 | 无 | ❌ 缺失 |
| 16 | 键盘切换 | Cursor `Cmd+J` toggle panel | 仅鼠标点击 Toggle | ⚠️ 缺失 |

### 2.3 中间 Chat 区（对标 Claude / ChatGPT / Cursor Chat）

| # | 维度 | 主流做法 | Sage 现状 | 差距级别 |
|---|---|---|---|---|
| 17 | 消息级操作 | Claude "Copy/Regenerate/Insert" | 仅代码块复制 | ❌ 缺失 |
| 18 | 编辑已发消息 | Claude/ChatGPT 点击气泡可改写 | 无 | ❌ 缺失（重大）|

### 2.4 整体体验（对标 Claude / Notion AI / Linear）

| # | 维度 | 主流做法 | Sage 现状 | 差距级别 |
|---|---|---|---|---|
| 19 | 对话目录/大纲 | ChatGPT 长对话自动生成章节标题 | 无 | ⚠️ 缺失 |
| 20 | 多模态输入统一 | Claude 输入框内图标切换 | 附件+图片+知识 chip 分散 | ⚠️ 不统一 |
| 21 | @mention 引用 | Cursor `@file / @symbol / @web` | 仅 KnowledgeChip | ⚠️ 不够丰富 |
| 22 | Token 用量可视化 | ChatGPT 每消息显示 token 数 | 仅顶部 UsageBadge 汇总 | ⚠️ 缺失 |
| 23 | 运行回放 | Cursor "Show reasoning" | ActiveAgentIndicator 仅当前 | ⚠️ 历史丢失 |
| 24 | 语音输入 | ChatGPT/Claude 原生语音模式 | 无 | ❌ 缺失 |

---

## 3. 优先级分级与实施计划

### 🔴 P0 — 高价值低成本（第 1 周，4 项）

**目标**：补齐核心交互，对齐 Claude/ChatGPT 基线体验。

#### 3.1 消息级操作菜单（#17）

**范围**：每条 Message 悬停显示操作菜单（复制 / 重新生成 / 引用到对话 / 插入代码库）

**涉及文件**：
- `src/widgets/chat/Message.tsx` — 增加 `MessageActions` DropdownMenu
- `src/entities/chat/types.ts` — 增加 `MessageAction` 类型
- `src/features/chat/useMessageActions.ts` — 新增 hook

**技术方案**：
```tsx
// Message.tsx 改造
<div className="group relative">
  {/* 现有消息内容 */}
  <MessageContent message={message} />
  
  {/* 悬停操作菜单（仅 assistant 消息显示） */}
  {message.role === 'assistant' && (
    <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon"><MoreHorizontal /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={handleCopy}>
            <Copy className="mr-2" /> 复制
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleRegenerate}>
            <RefreshCw className="mr-2" /> 重新生成
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleQuoteToChat}>
            <MessageSquareQuote className="mr-2" /> 引用到对话
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleInsertToCodebase}>
            <Code className="mr-2" /> 插入代码库
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )}
</div>
```

**后端依赖**：
- 重新生成 → 需调用 `/api/v1/chat/regenerate`（已有 `/api/v1/chat` POST，增加 `regenerate_message_id` 参数）
- 插入代码库 → 需调用 `/api/v1/knowledge/insert`（新增 API）

**验收**：
- 单测：`Message.test.tsx` 断言悬停显示 4 个操作项
- E2E：点击"重新生成"触发 API 调用，消息列表更新

**工作量**：~1 天

#### 3.2 编辑已发送消息（#18）

**范围**：用户点击自己的消息气泡可改写，提交后清空后续 AI 回复

**涉及文件**：
- `src/widgets/chat/Message.tsx` — 用户消息增加"编辑"按钮
- `src/widgets/chat/EditableMessage.tsx` — 新增（CodeMirror 编辑态）
- `src/features/chat/useEditMessage.ts` — 新增 hook
- `src/entities/session/store.ts` — 增加 `truncateAfterMessage(sessionId, messageId)` action
- `backend/api/chat_routes.py` — 增加 `truncate` 参数

**技术方案**：
```tsx
// EditableMessage.tsx
const [editing, setEditing] = useState(false);
const [editValue, setEditValue] = useState(message.content);

if (editing) {
  return (
    <div className="space-y-2">
      <CodeMirror
        value={editValue}
        onChange={setEditValue}
        className="border rounded"
      />
      <div className="flex gap-2">
        <Button onClick={handleSave}>保存并重新生成</Button>
        <Button variant="ghost" onClick={() => setEditing(false)}>取消</Button>
      </div>
    </div>
  );
}

return (
  <div className="group relative">
    <MessageContent message={message} />
    <Button
      className="absolute right-2 top-2 opacity-0 group-hover:opacity-100"
      variant="ghost"
      size="icon"
      onClick={() => setEditing(true)}
    >
      <Edit2 />
    </Button>
  </div>
);
```

**后端改造**：
```python
# chat_routes.py
@router.post("/api/v1/chat")
async def chat(request: ChatRequest):
    # 新增参数
    if request.truncate_after_message_id:
        await session_store.truncate_after(
            request.session_id,
            request.truncate_after_message_id
        )
    # 继续原有逻辑...
```

**验收**：
- 单测：`EditableMessage.test.tsx` 断言编辑态切换
- 集成测试：`test_chat_routes.py` 断言 truncate 后消息列表截断
- E2E：编辑消息 → 提交 → 后续 AI 回复被清空 → 新回复生成

**工作量**：~1.5 天

#### 3.3 RightPanel 宽度可调（#10）

**范围**：用现有 `ResizeDivider` 组件支持左边界拖拽

**涉及文件**：
- `src/widgets/chat/RightPanel.tsx` — 增加 `width` state + `ResizeDivider`
- `src/shared/ui/ResizeDivider.tsx` — 复用（已存在）

**技术方案**：
```tsx
// RightPanel.tsx
const [width, setWidth] = useLocalStorage('right-panel-width', 320);

return (
  <div
    className="fixed top-12 right-0 h-[calc(100vh-3rem)] bg-background border-l"
    style={{ width: `${width}px` }}
  >
    <ResizeDivider
      onResize={setWidth}
      min={280}
      max={600}
      position="left" // 左边界拖拽
    />
    {/* 现有 Tab 内容 */}
  </div>
);
```

**验收**：
- 单测：`RightPanel.test.tsx` 断言拖拽改变宽度
- 宽度持久化到 localStorage

**工作量**：~0.5 天

#### 3.4 会话项元信息增强（#1）

**范围**：显示最后消息预览（截断 40 字）+ 相对时间 + 消息数

**涉及文件**：
- `src/widgets/session/SessionItem.tsx` — 增加元信息行
- `src/entities/session/types.ts` — 增加 `lastMessagePreview` / `messageCount` 字段
- `src/features/session/useSessionMetadata.ts` — 新增 hook（查询最后一条消息）

**技术方案**：
```tsx
// SessionItem.tsx
<div className="flex flex-col gap-1">
  <div className="flex items-center justify-between">
    <span className="font-medium truncate">{session.title}</span>
    <span className="text-xs text-muted-foreground">
      {formatRelativeTime(session.updated_at)}
    </span>
  </div>
  <div className="flex items-center justify-between text-xs text-muted-foreground">
    <span className="truncate">{session.last_message_preview}</span>
    <span>{session.message_count} 条</span>
  </div>
</div>
```

**后端改造**：
- `/api/v1/session/list` 返回增加 `last_message_preview` / `message_count` 字段
- 查询优化：`SELECT ... (SELECT content FROM messages WHERE session_id = s.id ORDER BY created_at DESC LIMIT 1) as last_message_preview`

**验收**：
- 单测：`SessionItem.test.tsx` 断言元信息渲染
- 性能：列表加载时间 < 200ms（100 个会话）

**工作量**：~0.5 天

---

### 🟠 P1 — 中等价值（第 2-3 周，4 项）

**目标**：增强桌面端独特能力，对齐 Cursor/Claude 高级体验。

#### 3.5 Artifacts 实时预览（#12）⭐ 重大特性

**范围**：HTML → iframe 沙盒，SVG → inline 渲染，React → 转译

**涉及文件**：
- `src/widgets/chat/ArtifactsSection.tsx` — 增加预览渲染器
- `src/widgets/chat/ArtifactPreview.tsx` — 新增（沙盒 iframe）
- `src/widgets/chat/SvgPreview.tsx` — 新增（inline SVG）
- `src/features/artifacts/useArtifactPreview.ts` — 新增 hook
- `electron/main.ts` — 增加沙盒 BrowserWindow 创建（独立窗口版）

**技术方案**：
```tsx
// ArtifactPreview.tsx
const ArtifactPreview = ({ artifact }: { artifact: Artifact }) => {
  if (artifact.type === 'html') {
    return (
      <iframe
        srcDoc={artifact.content}
        sandbox="allow-scripts" // 沙盒化
        className="w-full h-full border-0"
        title="Artifact Preview"
      />
    );
  }
  
  if (artifact.type === 'svg') {
    return (
      <div
        className="w-full h-full"
        dangerouslySetInnerHTML={{ __html: artifact.content }}
      />
    );
  }
  
  if (artifact.type === 'react') {
    // 转译为可执行代码（需要 babel-standalone 或 sucrase）
    const transpiled = transpileReact(artifact.content);
    return <TranspiledReactComponent code={transpiled} />;
  }
  
  return <div>不支持的 artifact 类型</div>;
};
```

**安全考虑**：
- iframe `sandbox="allow-scripts"` 阻止跨域请求
- SVG 内联前用 `DOMPurify` 清理
- React 转译在 Web Worker 中执行

**验收**：
- 单测：`ArtifactPreview.test.tsx` 断言三种类型渲染
- 安全测试：注入 `<script>alert(1)</script>` 不执行
- E2E：生成 HTML artifact → 预览可交互

**工作量**：~3 天

#### 3.6 折叠态 icon rail（#2）

**范围**：折叠后保留 ~56px 宽度，显示图标（💬 🧠 📖 ⚙️）

**涉及文件**：
- `src/widgets/layout/Sidebar.tsx` — 改造折叠逻辑
- `src/widgets/layout/SidebarRail.tsx` — 新增（icon rail 态）

**技术方案**：
```tsx
// Sidebar.tsx
const [collapsed, setCollapsed] = useLocalStorage('sidebar-collapsed', false);

return (
  <aside
    className={cn(
      'transition-all duration-200',
      collapsed ? 'w-14' : 'w-64'
    )}
  >
    {collapsed ? (
      <SidebarRail /> // 仅图标
    ) : (
      <SidebarFull /> // 完整内容
    )}
  </aside>
);

// SidebarRail.tsx
const SidebarRail = () => (
  <div className="flex flex-col items-center gap-4 py-4">
    <BrandLogo size={32} />
    <NavIconButton icon={<MessageSquare />} tooltip="对话" href="/chat" />
    <NavIconButton icon={<Brain />} tooltip="记忆" href="/memory" />
    <NavIconButton icon={<Book />} tooltip="知识库" href="/knowledge" />
    <NavIconButton icon={<Settings />} tooltip="设置" href="/settings" />
  </div>
);
```

**验收**：
- 单测：`Sidebar.test.tsx` 断言折叠态显示 icon rail
- 键盘测试：`Ctrl+B` 切换折叠态

**工作量**：~1 天

#### 3.7 全局搜索合并（#4）

**范围**：当前 cmdk 命令面板 → 加入"会话/记忆/知识/文件"tabs

**涉及文件**：
- `src/widgets/command/CommandPalette.tsx` — 增加 tabs
- `src/features/search/useGlobalSearch.ts` — 新增 hook
- `backend/api/search_routes.py` — 新增 `/api/v1/search/global`

**技术方案**：
```tsx
// CommandPalette.tsx
<CommandDialog>
  <CommandInput placeholder="搜索命令、会话、记忆..." />
  <CommandList>
    <CommandTabs>
      <CommandTab value="commands">命令</CommandTab>
      <CommandTab value="sessions">会话</CommandTab>
      <CommandTab value="memories">记忆</CommandTab>
      <CommandTab value="knowledge">知识</CommandTab>
    </CommandTabs>
    
    <CommandTabPanel value="commands">
      {/* 现有命令列表 */}
    </CommandTabPanel>
    
    <CommandTabPanel value="sessions">
      {sessions.map(s => (
        <CommandItem key={s.id} onSelect={() => navigate(`/chat?session=${s.id}`)}>
          <MessageSquare className="mr-2" />
          {s.title}
        </CommandItem>
      ))}
    </CommandTabPanel>
    
    {/* 其他 tabs */}
  </CommandList>
</CommandDialog>
```

**后端 API**：
```python
# search_routes.py
@router.get("/api/v1/search/global")
async def global_search(q: str, types: str = "session,memory,knowledge"):
    results = {}
    if "session" in types:
        results["sessions"] = await session_store.search(q, limit=10)
    if "memory" in types:
        results["memories"] = await memory_store.search(q, limit=10)
    if "knowledge" in types:
        results["knowledge"] = await knowledge_store.search(q, limit=10)
    return results
```

**验收**：
- 单测：`CommandPalette.test.tsx` 断言 tabs 切换
- 集成测试：`test_search_routes.py` 断言多类型搜索
- E2E：`Cmd+K` → 输入"项目" → 切换到"会话"tab → 点击跳转

**工作量**：~2 天

#### 3.8 Diff 视图（#13）

**范围**：RightPanel Changes tab 显示 side-by-side diff

**涉及文件**：
- `src/widgets/chat/ChangesSection.tsx` — 替换为 diff 视图
- `src/widgets/chat/FileDiff.tsx` — 新增（react-diff-viewer）
- `package.json` — 增加 `react-diff-viewer-continued`

**技术方案**：
```tsx
// FileDiff.tsx
import ReactDiffViewer from 'react-diff-viewer-continued';

const FileDiff = ({ file }: { file: FileChange }) => (
  <ReactDiffViewer
    oldValue={file.original_content}
    newValue={file.new_content}
    splitView={true}
    leftTitle="原始"
    rightTitle="修改后"
    useDarkTheme={isDark}
  />
);

// ChangesSection.tsx
<div className="space-y-4">
  {changes.map(file => (
    <div key={file.path} className="border rounded">
      <div className="px-3 py-2 bg-muted font-mono text-sm">
        {file.path}
      </div>
      <FileDiff file={file} />
    </div>
  ))}
</div>
```

**验收**：
- 单测：`FileDiff.test.tsx` 断言 diff 渲染
- E2E：触发文件变更 → RightPanel Changes 显示 side-by-side diff

**工作量**：~1.5 天

---

### 🟡 P2 — 长期价值（第 4-6 周，选 2-3 项）

**目标**：增强桌面端独特能力，形成差异化优势。

#### 3.9 Workspace / Project 切换器（#3）

**范围**：Sidebar 顶部下拉显示最近 10 项目 + 收藏 + 新建

**涉及文件**：
- `src/widgets/sidebar/WorkspaceSwitcher.tsx` — 新增
- `src/widgets/layout/Sidebar.tsx` — 顶部插入切换器
- `src/features/workspace/useWorkspaces.ts` — 新增 hook
- `backend/api/workspace_routes.py` — 增加 `/api/v1/workspace/list`

**工作量**：~2 天

#### 3.10 对话目录/大纲（#19）

**范围**：自动提取 assistant 消息的 h2/h3 生成大纲，集成到 RightPanel

**涉及文件**：
- `src/widgets/chat/ConversationOutline.tsx` — 新增
- `src/widgets/chat/RightPanel.tsx` — 增加第四个 Tab "目录"
- `src/features/chat/useConversationOutline.ts` — 新增 hook

**工作量**：~2 天

#### 3.11 Artifacts 独立窗口（#11）⭐ 桌面端独特能力

**范围**：双击 Artifact → 弹出独立 BrowserWindow

**涉及文件**：
- `electron/main.ts` — 增加 `createArtifactWindow()` IPC handler
- `electron/preload.ts` — 暴露 `openArtifactWindow()` API
- `src/widgets/chat/ArtifactsSection.tsx` — 双击触发 IPC

**工作量**：~2 天

#### 3.12 语音输入（#24）

**范围**：Whisper.cpp 本地 STT + Electron 麦克风权限

**涉及文件**：
- `electron/main.ts` — 增加麦克风权限请求
- `backend/services/stt/whisper.py` — 新增（Whisper.cpp 封装）
- `src/widgets/chat/ChatInput.tsx` — 增加麦克风按钮
- `src/features/stt/useSpeechToText.ts` — 新增 hook

**工作量**：~3 天

---

### 🟢 P3 — 锦上添花（未来版本，按需选做）

| # | 特性 | 工作量 | 备注 |
|---|---|---|---|
| 13 | 会话分享链接 | ~2 天 | 需后端 API + 前端模态 |
| 14 | 多会话并排 | ~4 天 | 复杂布局系统 |
| 15 | @mention 扩展 | ~3 天 | @file / @symbol / @web / @memory |
| 16 | 键盘导航体系 | ~2 天 | vim-style j/k |
| 17 | 拖放文件全区域 | ~1 天 | 发现性优化 |
| 18 | Token 用量按消息可视化 | ~2 天 | 需后端返回 per-message tokens |

---

## 4. 实施步骤（分阶段里程碑）

### 阶段 1（第 1 周）：P0 全部

- [ ] T1.1 消息级操作菜单（#17）
  - [ ] 后端：`/api/v1/chat/regenerate` + `/api/v1/knowledge/insert` API
  - [ ] 前端：`Message.tsx` 增加 `MessageActions`
  - [ ] 测试：单测 + E2E
- [ ] T1.2 编辑已发送消息（#18）
  - [ ] 后端：`ChatRequest` 增加 `truncate_after_message_id`
  - [ ] 前端：`EditableMessage.tsx` + `useEditMessage.ts`
  - [ ] 测试：单测 + 集成测试 + E2E
- [ ] T1.3 RightPanel 宽度可调（#10）
  - [ ] 前端：`RightPanel.tsx` 增加 `ResizeDivider`
  - [ ] 测试：单测
- [ ] T1.4 会话项元信息增强（#1）
  - [ ] 后端：`/api/v1/session/list` 增加字段
  - [ ] 前端：`SessionItem.tsx` 渲染元信息
  - [ ] 测试：单测 + 性能测试

**验收**：
- 所有 P0 特性在 main 分支可用
- CI 全绿
- 提交 PR #X（4 个特性合并到一个 PR 或拆分 4 个 PR，待讨论）

### 阶段 2（第 2-3 周）：P1 选做

- [ ] T2.1 Artifacts 实时预览（#12）⭐ 优先
- [ ] T2.2 折叠态 icon rail（#2）
- [ ] T2.3 全局搜索合并（#4）
- [ ] T2.4 Diff 视图（#13）

**验收**：
- 至少完成 2 项
- Artifacts 预览安全测试通过

### 阶段 3（第 4-6 周）：P2 选做

- [ ] T3.1 Workspace / Project 切换器（#3）
- [ ] T3.2 对话目录/大纲（#19）
- [ ] T3.3 Artifacts 独立窗口（#11）⭐ 优先
- [ ] T3.4 语音输入（#24）

**验收**：
- 至少完成 2 项
- 桌面端独特能力演示

### 阶段 4（未来）：P3 按需

- [ ] 根据用户反馈选做

---

## 5. 风险评估与依赖

### 5.1 风险

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| Artifacts 预览 XSS 漏洞 | 中 | 高 | iframe 沙盒 + DOMPurify + 安全审计 |
| 编辑消息后 session store 状态不一致 | 中 | 中 | 集成测试覆盖 + 状态机校验 |
| 全局搜索性能（1000+ 会话）| 低 | 中 | 后端分页 + 前端 debounce |
| 语音输入 Whisper.cpp 跨平台编译 | 高 | 中 | 先做 macOS/Linux，Windows 延后 |

### 5.2 依赖

- **后端 API 改造**：P0 的 #17/#18 需要后端配合，需与后端开发协调
- **Electron IPC**：P2 的 #11/#12 需要 Electron 主进程改造
- **第三方库**：
  - `react-diff-viewer-continued`（Diff 视图）
  - `babel-standalone` 或 `sucrase`（React 转译）
  - `whisper.cpp`（语音输入，需 native 编译）

### 5.3 不在范围内

- ❌ 不重构现有 FSD 架构
- ❌ 不替换 Tailwind / Radix UI
- ❌ 不做移动端适配（Electron 桌面端专属）
- ❌ 不做多语言国际化（i18n）

---

## 6. Sage 独特机会（差异化）

由于 Sage 是 **Electron 桌面端**，有几件事是 ChatGPT/Claude 网页版做不到的，可以形成差异化：

1. **Artifacts 独立窗口**（#11） — 把 HTML/React/SVG 渲染到独立 BrowserWindow，支持 DevTools
2. **本地文件拖放联动** — 拖文件到 Sidebar 自动创建知识 / 拖到 Chat 自动附件
3. **本地代码库 @symbol 引用**（Cursor 核心体验）— 集成 LSP 或 tree-sitter
4. **系统级语音输入** — 全局热键触发 Whisper，任何界面可用
5. **系统通知深度集成** — 长时间任务完成时 OS 通知，点击跳转对应会话
6. **离线 Artifacts 持久化** — 本地保存渲染结果，重开应用仍可访问

**建议优先落地 #11 Artifacts 独立窗口**，这是桌面端的杀手级特性。

---

## 7. 推荐实施顺序

```
第 1 周：P0 全部（消息菜单 / 编辑消息 / 右栏可调 / 会话元信息）
  ↓ PR #X（4 个特性合并或拆分）
第 2 周：P1 的 #12（Artifacts 预览）+ #2（icon rail 折叠）
  ↓ PR #Y
第 3 周：P1 的 #4（全局搜索）+ #13（Diff 视图）
  ↓ PR #Z
第 4-6 周：P2 选 2-3 项启动
  ↓ PR #A / #B / #C
```

---

## 8. 附录：主流工具对比截图参考

- ChatGPT：https://chat.openai.com
- Claude.ai：https://claude.ai
- Cursor：https://cursor.sh
- Windsurf：https://codeium.com/windsurf
- Perplexity：https://perplexity.ai
- v0.dev：https://v0.dev

---

**文档状态**：草稿，待评审  
**下一步**：用户评审本方案 → 确认 P0 范围 → 开 PR 实施
