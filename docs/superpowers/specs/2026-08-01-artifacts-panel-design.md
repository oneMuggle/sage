# Artifacts Panel 设计文档

> 日期: 2026-08-01  
> 状态: 设计完成,待实现

## 1. 背景与目标

Sage 当前的 Chat 页面是单列布局,没有右侧面板来展示 AI 生成的产物和工具调用进度。用户需要:
1. **产物列表**:查看 AI 在对话中生成的文件(代码、文档、图片等)
2. **Progress 面板**:实时查看工具调用进度和状态

参考 OpenWorker 的 RightRail 实现,但采用全栈追踪方案(后端记录工具调用的写操作),确保产物列表精确反映 AI 的实际输出。

## 2. 架构概览

```
┌─────────────────────────────────────────────────────────┐
│ Chat Page                                                │
│  ┌──────────────────────────┐  ┌─────────────────────┐ │
│  │ MessageList              │  │ RightPanel (抽屉)   │ │
│  │                          │  │  ┌─Progress───────┐ │ │
│  │  (消息列表 + 流式输出)   │  │  │ iteration      │ │ │
│  │                          │  │  │ tool calls     │ │ │
│  │                          │  │  │ status         │ │ │
│  │                          │  │  └────────────────┘ │ │
│  │                          │  │  ┌─Artifacts──────┐ │ │
│  │                          │  │  │ file list      │ │ │
│  │                          │  │  │ preview        │ │ │
│  │                          │  │  └────────────────┘ │ │
│  └──────────────────────────┘  └─────────────────────┘ │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ChatInput                                         │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 3. 数据模型

### 3.1 artifacts 表

```sql
CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  tool_call_id TEXT,              -- 关联到消息中的 tool_call
  path TEXT NOT NULL,             -- 文件绝对路径
  name TEXT NOT NULL,             -- 文件名
  kind TEXT NOT NULL,             -- markdown|code|image|csv|json|text
  size INTEGER DEFAULT 0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX idx_artifacts_session ON artifacts(session_id, created_at DESC);
```

### 3.2 产物类型检测

根据文件扩展名映射 `kind`:

| kind | 扩展名 |
|------|--------|
| `markdown` | `.md`, `.markdown` |
| `code` | `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.json`, `.css`, `.html`, `.sh` |
| `image` | `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp` |
| `csv` | `.csv`, `.tsv` |
| `text` | `.txt`, 其他 |

## 4. 后端 API

### 4.1 列出产物

```
GET /api/v1/sessions/{session_id}/artifacts

Response:
{
  "artifacts": [
    {
      "id": "art_xxx",
      "tool_call_id": "call_abc",
      "path": "/absolute/path/file.md",
      "name": "file.md",
      "kind": "markdown",
      "size": 1234,
      "created_at": 1722500000
    }
  ]
}
```

### 4.2 读取产物内容

```
GET /api/v1/sessions/{session_id}/artifacts/read?path=/absolute/path/file.md

Response (文本文件):
{
  "ok": true,
  "path": "...",
  "kind": "markdown",
  "content": "# Title\n\nContent...",
  "truncated": false
}

Response (图片):
{
  "ok": true,
  "path": "...",
  "kind": "image",
  "data_url": "data:image/png;base64,..."
}

Response (错误):
{
  "ok": false,
  "error": "File not found"
}
```

**限制**:
- 文本文件最大 500KB(超过截断,`truncated: true`)
- 二进制文件(image)最大 10MB(超过返回错误)
- 路径必须在 session 绑定的 workspace 范围内(安全检查)

### 4.3 在文件管理器中显示

```
POST /api/v1/sessions/{session_id}/artifacts/reveal
Body: { "path": "/absolute/path/file.md" }

Response: { "ok": true }
```

跨平台实现:macOS `open -R`,Windows `explorer /select`,Linux `xdg-open`

### 4.4 拦截逻辑

在 `backend/chat/executors.py` 中拦截工具执行的写操作:

```python
async def execute_write_file(params, session_id, tool_call_id):
    path = params["path"]
    content = params["content"]
    
    # 执行写入
    write_to_file(path, content)
    
    # 记录产物
    await artifact_store.record(
        session_id=session_id,
        tool_call_id=tool_call_id,
        path=path,
        name=Path(path).name,
        kind=detect_kind(path),
        size=len(content.encode()),
    )
```

拦截的工具:`write_file`、`create_file`、`save_file`(具体工具名需查后端实际定义)

## 5. 前端组件

### 5.1 组件结构

```
src/widgets/chat/
├── RightPanel.tsx              # 右侧面板容器(抽屉)
├── RightPanelToggle.tsx        # 右上角切换按钮
├── progress/
│   ├── ProgressSection.tsx     # Progress 面板
│   └── ToolCallList.tsx        # 工具调用列表
└── artifacts/
    ├── ArtifactsSection.tsx    # 产物列表面板
    ├── ArtifactRow.tsx         # 单个产物行
    └── ArtifactViewer.tsx      # 产物预览器(全屏接管)
```

### 5.2 RightPanel 组件

```typescript
interface RightPanelProps {
  open: boolean;
  onToggle: () => void;
  // Progress 数据(从 useChat 传入)
  iteration: number;
  streamingState: AgentEvent['state'] | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  // 产物数据
  sessionId: string | null;
}

// 内部状态
const [activeTab, setActiveTab] = useState<'progress' | 'artifacts'>('progress');
const [artifacts, setArtifacts] = useState<Artifact[]>([]);
const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
```

**布局**:
- 宽度固定 320px,右侧固定定位
- `open=true` 时 `transform: translateX(0)`,`open=false` 时 `translateX(100%)`
- 过渡动画 200ms ease-in-out
- 顶部 Tab 切换:Progress / Artifacts
- 选中产物时,整个面板切换为 `ArtifactViewer`(面包屑导航返回)

### 5.3 ProgressSection 组件

显示内容:
- **流式状态**:映射 `streamingState` 到中文(如 "思考中" / "调用工具" / "生成回复")
- **迭代轮次**:`iteration > 0` 时显示 "第 N 轮"
- **工具调用列表**:遍历 `toolCalls`,显示工具名 + 状态(pending/running/completed)
- **空状态**:无活动时显示 "等待输入..."

### 5.4 ArtifactsSection 组件

显示内容:
- **产物列表**:每个 `ArtifactRow` 显示图标(kind)+ 文件名 + 大小 + 时间
- **操作按钮**:刷新(重新拉取列表)、在文件管理器中显示(第一个产物的路径)
- **空状态**:"暂无产物"
- **点击产物行**:设置 `selectedArtifact`,面板切换为 `ArtifactViewer`

### 5.5 ArtifactViewer 组件

根据 `kind` 渲染不同预览器:

| kind | 渲染方式 |
|------|----------|
| `markdown` | `<Markdown content={...} />`(复用现有组件) |
| `code` | `<ShikiCodeBlock code={...} />`(复用现有组件) |
| `csv` | 解析为表格(`<table>`,最多 500 行) |
| `json` | `<ShikiCodeBlock language="json" />` |
| `image` | `<img src={data_url} />` |
| `text` | `<pre>{content}</pre>` |

**头部操作栏**:
- 返回按钮(回到列表)
- 面包屑:"产物 / filename"
- 复制路径按钮
- 在文件管理器中显示按钮

## 6. 数据流

```
用户发送消息
    ↓
ChatInput → sendMessage()
    ↓
后端处理 → 工具执行(executors.py)
    ↓
write_file 执行成功 → artifact_store.record()
    ↓
前端 SSE 事件流 → useChat 更新 toolCalls/streamingState
    ↓
RightPanel 订阅 useChat 数据 → ProgressSection 实时更新
    ↓
用户切换到 Artifacts Tab → fetchArtifacts(sessionId)
    ↓
点击产物行 → fetchArtifactContent(path) → ArtifactViewer 渲染
```

### 6.1 与现有组件的集成

**Chat.tsx 修改**:
```typescript
// 新增状态
const [rightPanelOpen, setRightPanelOpen] = useState(false);

// 在 Chat 组件顶层添加 RightPanel
return (
  <div className="flex-1 flex flex-col min-h-0 relative">
    {/* 右上角切换按钮 */}
    <RightPanelToggle 
      open={rightPanelOpen} 
      onClick={() => setRightPanelOpen(!rightPanelOpen)} 
    />
    
    {/* 原有内容 */}
    <div className="h-12 ...">...</div>
    <div ref={scrollRef} className="flex-1 ...">
      <MessageList ... />
    </div>
    <ActiveAgentIndicator ... />
    <ChatInput ... />
    
    {/* 右侧面板(抽屉) */}
    <RightPanel
      open={rightPanelOpen}
      onToggle={() => setRightPanelOpen(!rightPanelOpen)}
      iteration={iteration}
      streamingState={streamingState}
      toolCalls={streamingToolCalls}
      isLoading={isLoading}
      sessionId={currentSessionId}
    />
  </div>
);
```

**useChat Hook 扩展**:
```typescript
// 新增暴露 streamingToolCalls
return {
  messages,
  isLoading,
  error,
  // ... 现有字段
  streamingToolCalls,  // 新增:当前流式工具调用
};
```

**新增 API Hook**:
```typescript
// src/features/artifacts/useArtifacts.ts
export function useArtifacts(sessionId: string | null) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  
  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    const res = await fetch(`/api/v1/sessions/${sessionId}/artifacts`);
    const data = await res.json();
    setArtifacts(data.artifacts);
    setLoading(false);
  }, [sessionId]);
  
  useEffect(() => { refresh(); }, [refresh]);
  
  return { artifacts, loading, refresh };
}

// src/features/artifacts/useArtifactContent.ts
export function useArtifactContent(sessionId: string, path: string | null) {
  const [content, setContent] = useState<ArtifactContent | null>(null);
  const [loading, setLoading] = useState(false);
  
  useEffect(() => {
    if (!path) { setContent(null); return; }
    setLoading(true);
    fetch(`/api/v1/sessions/${sessionId}/artifacts/read?path=${encodeURIComponent(path)}`)
      .then(r => r.json())
      .then(setContent)
      .finally(() => setLoading(false));
  }, [sessionId, path]);
  
  return { content, loading };
}
```

### 6.2 状态管理

- **RightPanel 开关状态**:本地 `useState`(不持久化,刷新后默认关闭)
- **ActiveTab**:`useState<'progress' | 'artifacts'>('progress')`
- **Artifacts 列表**:`useArtifacts` hook(组件挂载时拉取,切换 session 时重新拉取)
- **SelectedArtifact**:`useState<Artifact | null>(null)`
- **ArtifactContent**:`useArtifactContent` hook(选中产物时拉取)

## 7. 错误处理

### 7.1 后端

| 场景 | 处理 |
|------|------|
| 产物记录失败(数据库错误) | 记录日志,不阻断工具执行(产物列表可以稍后刷新) |
| 文件不存在 | `{"ok": false, "error": "File not found"}` |
| 路径穿越攻击(路径不在 workspace 内) | `{"ok": false, "error": "Path escapes workspace"}` |
| 文件过大(文本 >500KB) | 截断,`truncated: true` |
| 图片过大(>10MB) | `{"ok": false, "error": "File too large"}` |
| 二进制文件无法预览 | `{"ok": false, "error": "Binary file cannot be previewed"}` |

### 7.2 前端

| 场景 | 处理 |
|------|------|
| API 请求失败 | 显示 "加载失败,点击重试" |
| 产物列表为空 | 显示 "暂无产物" |
| 预览内容加载失败 | 显示错误信息 + "在系统应用中打开" 按钮 |
| 未选中 session | RightPanel 显示 "请先选择会话" |

## 8. 测试计划

### 8.1 后端测试(pytest)

1. `test_record_artifact` — 工具执行后 artifacts 表有记录
2. `test_list_artifacts` — API 返回产物列表,按 created_at 降序
3. `test_read_artifact_text` — 读取文本文件,返回 content
4. `test_read_artifact_image` — 读取图片,返回 data_url
5. `test_read_artifact_not_found` — 文件不存在,返回 ok=false
6. `test_read_artifact_path_traversal` — 路径穿越,返回 ok=false
7. `test_reveal_artifact` — 调用系统命令(用 mock 验证)

### 8.2 前端测试(vitest)

1. `RightPanel.test.tsx` — 开关状态、Tab 切换
2. `ProgressSection.test.tsx` — 显示 iteration/toolCalls
3. `ArtifactsSection.test.tsx` — 渲染产物列表、空状态
4. `ArtifactRow.test.tsx` — 点击行触发 onSelect
5. `ArtifactViewer.test.tsx` — 根据 kind 渲染不同预览器
6. `useArtifacts.test.ts` — API 调用、加载状态

### 8.3 集成测试(Playwright)

1. 发送消息 → 工具调用 → 产物列表自动刷新
2. 点击产物 → 预览器显示内容
3. 点击"在文件管理器中显示" → 调用 reveal API

## 9. 实施顺序

1. **后端**:数据库迁移 + artifacts 表
2. **后端**:artifact_store 模块(record/list/read/reveal 方法)
3. **后端**:拦截 executors.py 中的写操作
4. **后端**:API 端点(3 个)
5. **后端**:pytest 测试
6. **前端**:useArtifacts + useArtifactContent hooks
7. **前端**:RightPanel + RightPanelToggle 容器
8. **前端**:ProgressSection + ToolCallList
9. **前端**:ArtifactsSection + ArtifactRow
10. **前端**:ArtifactViewer
11. **前端**:集成到 Chat.tsx
12. **前端**:vitest 测试
13. **前端**:Playwright 集成测试

## 10. 后续迭代(不在本次范围)

- PDF 预览(pdf.js)
- Excel 预览(SheetJS)
- Office 文档"在系统应用中打开"
- 产物跳转到对应消息(通过 tool_call_id)
- 产物搜索/过滤
- 产物批量操作(下载、删除)
