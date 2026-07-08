# Sage LLM Wiki — 流式聊天/摄取接入设计

> 日期：2026-07-08
> 状态：草案 → 待用户审阅
> 上游参考：`/home/fz/project/llm_wiki`（对比分析见对话历史）
> 关联现有 PR：PR-6（orchestration chat 流式，模式复用）

## 0. 背景

sage 后端 `/api/v1/wiki/chat` 和 `/api/v1/wiki/ingest` 当前是**非流式**端点（`httpx.post` 阻塞等 LLM 完整回答），但前端 hooks `useWikiChatStream` 和 `useWikiIngest` 已按流式事件协议设计好，组件 `WikiIngestProgress` 已写完。后端**从未**发送这些事件，导致：
- WikiChat.tsx 实际是 `await wikiChat()` 一次性返回后丢弃 streamId
- WikiIngestProgress 组件存在但 0 处被渲染
- LintView / ReviewView 全部 mock（独立问题，不在本文档范围）

本文档定义接通流式的 3-PR 实施方案。

## 1. 架构全景

**流式数据流（chat 为例，ingest 同构）**：

```
┌──────────┐  POST /chat/stream  ┌──────────────────┐  async generator  ┌──────────┐
│ Renderer │ ─────────────────► │ Electron main    │ ────────────────► │ Python   │
│ (React)  │                    │ commands.ts      │  NDJSON body      │ FastAPI  │
│          │  {streamId}        │                  │  ←──────────────  │ wiki/    │
│          │ ◄───────────────── │ wiki_chat_stream │   NDJSON lines    │ chat.py  │
│          │                    │   invoke handler │                   └──────────┘
│          │  listen(sage:event │
│          │  :wiki-chat-stream │   ↓              │
│          │  -{id}-chunk/done) │ relay.ts         │
│          │ ◄───────────────── │ parseNdjsonStream│
│          │  via webContents   │ (复用, 加 event  │
│          │  .send             │  分发函数)        │
└──────────┘                    └──────────────────┘
```

## 2. NDJSON 行格式

| 端点 | 事件 | NDJSON 行 payload | 转发到 Electron channel | 渲染端 hook 反应 |
|------|------|-------------------|------------------------|------------------|
| `/chat/stream` | `chunk` | `{"event":"chunk","data":"text"}` | `sage:event:wiki-chat-stream-{id}-chunk`（payload = `"text"`） | `useWikiChatStream` 累积到 `answer` |
| `/chat/stream` | `done` | `{"event":"done","data":{"citations":[...]}}` | `sage:event:wiki-chat-stream-{id}-done`（payload = `{citations:[...]}`） | `useWikiChatStream` 设置 `streaming=false`, `citations=[...]` |
| `/chat/stream` | `error` | `{"event":"error","data":"msg"}` | `sage:event:wiki-chat-stream-{id}-error`（payload = `{error:"msg"}`） | `useWikiChatStream` 设置 `streaming=false`, `error=msg`（**新 channel，hook 需扩 1 个 listen**） |
| `/ingest/stream` | `progress` | `{"event":"progress","data":{"stage":"...","percent":N,"message":"..."}}` | `sage:event:wiki-ingest-{id}-progress`（payload = 原 data） | `useWikiIngest` 更新 progress，stage=completed 时 done=true |
| `/ingest/stream` | `done` | `{"event":"done","data":{"files_written":[...],"stats":{...}}}` | `sage:event:wiki-ingest-{id}-progress`（payload = `{stage:"completed",percent:100,message:"..."}`，relay 内部转换） | 同上 |
| `/ingest/stream` | `error` | `{"event":"error","data":"msg"}` | `sage:event:wiki-ingest-{id}-progress`（payload = `{stage:"failed",percent:0,message:msg}`，relay 内部转换） | hook catch 现有 error state |

**STAGE 字符串**（与 `WikiIngestProgress.tsx::STAGE_LABELS` 严格对齐）：
`started` | `copy_source` | `step1_analyze` | `step2_write` | `embedding` | `completed` | `failed` | `unknown`

## 3. 取消语义

- 渲染端组件 unmount → `useWikiChatStream.reset()` → preload.unlisten → Electron main `sage:unlisten` → AbortController.abort() → 后端 httpx 流被 `signal` 切断 → async generator 收到 `GeneratorExit` 自动结束
- 不引入"取消 LLM 调用"语义（已发出的 LLM 请求无法回收）
- Electron main 维护 `Map<streamId, AbortController>`，unlisten 时清理

## 4. 后端改动

### 4.1 `LLMContext` 依赖（PR-1）

**新增** `backend/wiki/llm_context.py`：

```python
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict, List
import httpx

LlmCall = Callable[[List[Dict], float], Awaitable[str]]
LlmStreamCall = Callable[[List[Dict], float], AsyncIterator[str]]
HttpPost = Callable[[str, Dict[str, str], dict], Awaitable[str]]

@dataclass
class LLMContext:
    llm_call: LlmCall
    llm_stream_call: LlmStreamCall
    http_post: HttpPost

def make_llm_context(llm_base_url: str, llm_api_key: str, llm_model: str) -> LLMContext:
    async def llm_call(messages, temperature):
        async with httpx.AsyncClient(timeout=1800) as client:
            r = await client.post(f"{llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {llm_api_key}", "Content-Type": "application/json"},
                json={"model": llm_model, "messages": messages, "temperature": temperature, "stream": False})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    async def llm_stream_call(messages, temperature):
        async with httpx.AsyncClient(timeout=1800) as client:
            async with client.stream("POST", f"{llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {llm_api_key}", "Content-Type": "application/json"},
                json={"model": llm_model, "messages": messages, "temperature": temperature, "stream": True}) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data: "): continue
                    payload = line[6:]
                    if payload == "[DONE]": break
                    delta = json.loads(payload)["choices"][0].get("delta", {}).get("content", "")
                    if delta: yield delta
    async def http_post(url, headers, body):
        async with httpx.AsyncClient(timeout=1800) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.text
    return LLMContext(llm_call, llm_stream_call, http_post)
```

**改造** `backend/api/wiki_routes.py`：4 处重复的 `llm_call`/`http_post` 内联定义改为 `Depends(get_wiki_llm_context)` 注入。`get_wiki_llm_context` 是工厂函数（不是类 Depends），签名 `get_wiki_llm_context(req: ChatRequest|IngestRequest|ResearchRequest|ClipRequest) -> LLMContext`，从 request 抽出 `llm_base_url/api_key/model` 后调 `make_llm_context(...)` 返回。**PR-1 只重构不改变语义**；PR-2/3 把对应端点切到 `llm_stream_call`。

### 4.2 `chat.py` 流式化（PR-2）

```python
async def chat_with_wiki_stream(
    config: ChatConfig, project_root: Path, query: str, ctx: LLMContext,
) -> AsyncIterator[bytes]:
    try:
        retrieval = retrieve(query, project_root, ...)  # 现有非流式逻辑
        citations = [p.path for p in retrieval.pages]
        messages = build_rag_prompt(query, retrieval.pages, ...)
        async for delta in ctx.llm_stream_call(messages, temperature=0.3):
            yield (json.dumps({"event": "chunk", "data": delta}, ensure_ascii=False) + "\n").encode()
        yield (json.dumps({"event": "done", "data": {"citations": citations}}, ensure_ascii=False) + "\n").encode()
    except Exception as e:
        logger.exception("chat_with_wiki_stream 失败")
        yield (json.dumps({"event": "error", "data": str(e)}, ensure_ascii=False) + "\n").encode()
        raise
```

### 4.3 `ingest.py` 流式化（PR-3）

```python
async def ingest_source_stream(
    config: IngestConfig, project_root: Path, source_file: Path, ctx: LLMContext,
) -> AsyncIterator[bytes]:
    def emit(stage: str, percent: int, message: Optional[str] = None) -> bytes:
        return (json.dumps({"event":"progress","data":{"stage":stage,"percent":percent,"message":message}},
                          ensure_ascii=False) + "\n").encode()
    try:
        yield emit("started", 0, "开始导入")
        # 1. copy_source (从现有 ingest_source.py 抽出 copy_to_raw 函数)
        target = await copy_to_raw(project_root, source_file)
        yield emit("copy_source", 10, f"复制到 {target.name}")
        # 2. cache check (从现有 ingest_source.py 抽出 cache_get 函数)
        cached = cache_get(target)
        if cached:
            yield emit("completed", 100, f"缓存命中: {len(cached)} 文件")
            return
        # 3. step1 analyze (从现有 ingest_source.py 抽出 analyze_source 函数, 用 ctx.llm_call)
        yield emit("step1_analyze", 20, "LLM 分析中...")
        analysis = await analyze_source(target, ctx.llm_call)
        # 4. step2 write (从现有 ingest_source.py 抽出 generate_pages 函数, 用 ctx.llm_call)
        yield emit("step2_write", 50, "LLM 写作中...")
        files_written = await generate_pages(analysis, ctx.llm_call)
        # 5. embedding (从现有 ingest_source.py 抽出 embed_pages 函数, 用 ctx.http_post)
        yield emit("embedding", 80, f"嵌入 {len(files_written)} 文件")
        await embed_pages(files_written, ctx.http_post)
        # 6. cache save (从现有 ingest_source.py 抽出 cache_put 函数)
        cache_put(target, files_written)
        yield emit("completed", 100, f"导入完成: {len(files_written)} 文件")
    except Exception as e:
        logger.exception("ingest_source_stream 失败")
        yield emit("failed", 0, str(e))
        raise
```

### 4.4 `/chat/stream` 端点（PR-2，**替换** `/chat`）

```python
@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    ctx: LLMContext = Depends(get_wiki_llm_context),
):
    project_root = Path(req.project_path)
    # req_to_chat_config 从现有 /chat route 里的内联 ChatConfig 构造抽出 (PR-1 重构时一起做)
    config = req_to_chat_config(req)
    return StreamingResponse(
        chat_with_wiki_stream(config, project_root, req.query, ctx),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`/chat` 同步端点整段删除（PR-2 一并删）。

### 4.5 `/ingest/stream` 端点（PR-3，**替换** `/ingest`）

同 §4.4 结构。`/ingest` 同步端点整段删除（PR-3 一并删）。

### 4.6 `graph.py` mtime 缓存（PR-1）

```python
def get_graph_cached(project_root: Path, query: Optional[str] = None) -> GraphData:
    cache_path = project_root / ".llm-wiki" / "graph-cache.json"
    wiki_dir = project_root / "wiki"
    latest_mtime = max(
        (p.stat().st_mtime for p in wiki_dir.rglob("*.md") if p.is_file()),
        default=0.0,
    )
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
        if cache.get("latest_mtime") == latest_mtime and cache.get("query") == query:
            return GraphData.from_dict(cache["data"])
    graph = build_graph(project_root, query)
    cache_path.write_text(json.dumps({
        "latest_mtime": latest_mtime, "query": query, "data": graph.to_dict(),
    }, ensure_ascii=False))
    return graph
```

### 4.7 `list_directory` 递归（PR-1）

```python
@router.get("/list")
async def list_directory(path: str, project_path: str, depth: int = 10) -> List[Dict]:
    base = Path(project_path) / path
    if not base.exists():
        raise HTTPException(404, "path not found")
    def walk(p: Path, d: int) -> Dict:
        node = {"name": p.name, "path": str(p.relative_to(Path(project_path))), "is_dir": p.is_dir()}
        if p.is_dir() and d > 0:
            node["children"] = [
                walk(child, d - 1)
                for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                if not child.name.startswith(".")
            ]
        else:
            node["children"] = []
        return node
    return [walk(base, depth)]
```

## 5. Electron main 改动

### 5.1 `commands.ts` 新增 IPC handler（PR-2/3）

```ts
// 模块级 Map: streamId → AbortController (用于 unlisten 时 abort 后端流)
const streamControllers = new Map<string, AbortController>();

ipcMain.handle('sage:invoke', async (_e, { cmd, args }) => {
  if (cmd === 'wiki_chat_stream') {
    const streamId = `wiki-chat-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
    const controller = new AbortController();
    streamControllers.set(streamId, controller);
    const wc = BrowserWindow.fromWebContents(_e.sender);
    // 异步触发后端流 + relay
    (async () => {
      try {
        const res = await fetch(`${backendUrl}/api/v1/wiki/chat/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(args),
          signal: controller.signal,
        });
        if (!res.ok) {
          wc.webContents.send(`sage:event:wiki-chat-stream-${streamId}-error`, {
            error: `HTTP ${res.status}`,
          });
          return;
        }
        await relayNdjsonToEvent(res.body, `wiki-chat-stream-${streamId}`, wc, controller.signal);
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          wc.webContents.send(`sage:event:wiki-chat-stream-${streamId}-error`, {
            error: String(e),
          });
        }
      } finally {
        streamControllers.delete(streamId);
      }
    })();
    return { streamId };
  }
  if (cmd === 'wiki_ingest_stream') {
    // 同结构, eventPrefix = "wiki-ingest-{id}", splitMap = {done: '-progress'}
    // (见 §5.2 的 done → progress 终态转换)
  }
});
```

### 5.2 `relay.ts` 通用化（PR-2）

复用现有 `parseNdjsonStream`。**新增** `relayNdjsonToEvent`：

```ts
type NdjsonEvent = 'chunk' | 'done' | 'error' | 'progress';

export async function relayNdjsonToEvent(
  body: NodeJS.ReadableStream | null,
  eventPrefix: string,
  webContents: WebContentsLike,
  signal: AbortSignal,
  splitMap?: Partial<Record<NdjsonEvent, string>>,
): Promise<void> {
  const defaultSplit: Record<NdjsonEvent, string> = {
    chunk: '-chunk', done: '-done', error: '-error', progress: '-progress',
  };
  const map = { ...defaultSplit, ...splitMap };
  await parseNdjsonStream(body, (rawEvent: any) => {
    if (typeof rawEvent !== 'object' || !rawEvent.event) {
      webContents.send(`sage:event:${eventPrefix}-error`, { error: 'invalid NDJSON' });
      return;
    }
    const suffix = map[rawEvent.event as NdjsonEvent];
    if (!suffix) return;
    if (rawEvent.event === 'done' && eventPrefix.startsWith('wiki-ingest-')) {
      // ingest done → 转为 progress 终态
      webContents.send(`sage:event:${eventPrefix}-progress`, {
        stage: 'completed', percent: 100, message: JSON.stringify(rawEvent.data),
      });
    } else {
      webContents.send(`sage:event:${eventPrefix}${suffix}`, rawEvent.data);
    }
  }, signal);
}
```

### 5.3 abort/cleanup（PR-2）

`ipcMain.handle('sage:unlisten', ...)` 扩参（payload 加 `streamId` 字段），按 `streamId` 查 `streamControllers` 调 `controller.abort()`：

```ts
ipcMain.handle('sage:unlisten', async (_e, { event, streamId }) => {
  if (streamId) {
    const controller = streamControllers.get(streamId);
    if (controller) {
      controller.abort();
      streamControllers.delete(streamId);
    }
  }
  // 原有 unlisten 逻辑保持...
});
```

`preload.ts::listen` 返回的 unlisten 闭包需在调用 `sage:unlisten` 时把 `streamId` 一并传入（renderer 端 `wikiChatStream`/`wikiIngestStream` 返回的 streamId）。

## 6. 前端改动

### 6.1 `api-client/wiki.ts` 新增流式函数（PR-2/3）

```ts
export async function wikiChatStream(
  query: string,
  projectPath: string,
  llmConfig: { baseUrl: string; apiKey: string; model: string;
               embedBaseUrl: string; embedApiKey: string; embedModel: string },
  handlers: {
    onChunk: (chunk: string) => void;
    onDone: (data: { citations: string[] }) => void;
    onError: (err: Error) => void;
  },
): Promise<{ streamId: string; cancel: () => void }> {
  const { streamId } = await invoke<{ streamId: string }>('wiki_chat_stream', {
    query, projectPath, ...llmConfig,
  });
  const prefix = `wiki-chat-stream-${streamId}`;
  const unlistenChunk = await listen<string>(`${prefix}-chunk`,
    (e) => handlers.onChunk(e.payload));
  const unlistenDone = await listen<{ citations: string[] }>(`${prefix}-done`,
    (e) => handlers.onDone(e.payload));
  const unlistenError = await listen<{ error: string }>(`${prefix}-error`,
    (e) => handlers.onError(new Error(e.payload.error)));
  return { streamId, cancel: () => { unlistenChunk(); unlistenDone(); unlistenError(); } };
}

export async function wikiIngestStream(
  sourceFile: string,
  projectPath: string,
  llmConfig: { baseUrl: string; apiKey: string; model: string;
               embedBaseUrl: string; embedApiKey: string; embedModel: string },
  handlers: {
    onProgress: (p: { stage: string; percent: number; message?: string }) => void;
    onDone: (data: { files_written: string[] }) => void;
    onError: (err: Error) => void;
  },
): Promise<{ streamId: string; cancel: () => void }> {
  // 同结构, eventPrefix = "wiki-ingest-{id}"
  // listen 单一 progress 通道 (done/error 都映射到 progress with stage)
}
```

### 6.2 `WikiChat.tsx` 改用流式（PR-2）

替换 `await wikiChat(...)` 为 `wikiChatStream(...).onChunk/.onDone/.onError`。流式累积由 `useWikiChatStream` 内部完成，UI 已有 `stream.answer` 实时渲染。

### 6.3 `useWikiChatStream` 加 error 事件支持（PR-2）

现有只 listen chunk + done。**改 1 处**：增 listen `-error` channel，payload 转 `Error` 设到 `state.error`。

### 6.4 `WikiIngestProgress` 接入 `WikiProjectPicker`（PR-3）

`WikiProjectPicker.tsx` 现有 alert 替换为 `wikiIngestStream` + 渲染 `<WikiIngestProgress progress={...} done={...} error={...} />`。

### 6.5 `useWikiIngest` 不需改

它已 listen 单一 `progress` 通道，relay 把 done/error 都转为 progress payload 兼容。

## 7. 测试策略

### PR-1 测试
- `backend/tests/unit/test_llm_context.py`：3 case（构造 / llm_call / llm_stream_call）
- `backend/tests/unit/test_graph_cache.py`：4 case（cold / mtime 命中 / mtime 失效 / query 变化失效）
- `backend/tests/unit/test_list_directory.py`：扩 2 case（子目录 / 隐藏文件过滤）
- `src/widgets/wiki/__tests__/WikiEditor.test.tsx`：1 case（切文件后 editContent 同步）

### PR-2 测试
- `backend/tests/integration/test_chat_stream.py`：5 case（NDJSON 格式 / 完整 chunk 拼合 / citations / error / 流中断）
- `src/features/wiki/__tests__/useWikiChatStream.test.tsx`：4 case（chunk 累积 / done / error / cancel）
- `e2e/wiki-chat-stream.spec.ts`：1 smoke（stub backend 返 3 chunk + 1 done，UI 看到"思考中→逐字→完成"）

### PR-3 测试
- `backend/tests/integration/test_ingest_stream.py`：5 case（progress 顺序 / completed 终态 / 缓存命中早退 / error / 取消）
- `src/features/wiki/__tests__/useWikiIngest.test.tsx`：3 case（progress / completed / error）
- `src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx`：扩 1 case（导入按钮触发流 + 显示 progress）
- `e2e/wiki-ingest-stream.spec.ts`：1 smoke

### 验收门
- `npx tsc --noEmit` 全绿
- `conda activate sage-backend && pytest backend/tests -q` 全绿
- `npx vitest run src/features/wiki` 全绿
- `npx vitest run --coverage` 对 `src/features/wiki` 覆盖 ≥80%
- `LEFTHOOK=0 git push` 成功 + CI 4/4 绿

## 8. PR 切分

### PR-1: `fix(wiki): bugfix batch + LLMContext refactor`
分支：`fix/wiki-bugfix-batch`
```
1. fix(wiki): correct WikiEditor useState → useEffect
2. fix(wiki): recursive list_directory
3. perf(wiki): mtime-based graph cache
4. refactor(wiki): extract LLMContext dependency
```

### PR-2: `feat(wiki): streaming chat (NDJSON)`
分支：`feat/wiki-chat-stream`
```
1. feat(wiki): chat_with_wiki_stream async generator
2. feat(api): /chat/stream NDJSON endpoint, deprecate /chat
3. feat(electron): wiki_chat_stream IPC + relay
4. feat(wiki-chat): useWikiChatStream error event support
5. refactor(wiki-chat): replace non-streaming call with stream
6. test(wiki-chat): integration + unit + e2e
```

### PR-3: `feat(wiki): streaming ingest (NDJSON)`
分支：`feat/wiki-ingest-stream`
```
1. feat(wiki): ingest_source_stream async generator
2. feat(api): /ingest/stream NDJSON endpoint, deprecate /ingest
3. feat(electron): wiki_ingest_stream IPC + relay
4. feat(wiki-picker): render WikiIngestProgress on import
5. test(wiki-ingest): integration + unit + e2e
```

### 依赖与顺序
- PR-1 → 必先合（LLMContext 是 PR-2/3 前提）
- PR-2 ↔ PR-3 互不依赖，可并行
- 每个 PR 单独 review + 合并

## 9. 范围外（明确不做）

- ❌ 取消后端 LLM 调用（已发不可收）
- ❌ SSE / WebSocket 改造（NDJSON 已选定）
- ❌ 流状态持久化（刷新页面重连）
- ❌ 多模态 chat（独立 issue）
- ❌ Lint / Review / Insights 后端（独立 issue）
- ❌ Chat 多对话持久化（独立 issue）
- ❌ Stage 1 列表里的 LintView mock→real / HNSWVectorStore 删除（移出本次）

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Electron main 串行 relay 慢（多条 ingest 并行） | `Map<streamId, AbortController>` 限流，>5 并行排队 |
| FastAPI StreamingResponse 在客户端断开时不立即停 generator | httpx `signal=` 主动 abort；Python `try/except GeneratorExit` 兜底 |
| NDJSON 行被截断在两个 TCP chunk | 复用 `relay.ts::parseNdjsonStream` 已处理 `buf` 累积 |
| `/api/v1/wiki/ingest` 还有 MCP / scripts 调用方 | grep 确认仅前端调；如 MCP 调用则 PR-3 同步加 `wiki_ingest_source_stream` 包装（5 行 wrapper） |
| release/win7 同步 | PR-1/2/3 全在 main，PR-3 后按项目惯例 cherry-pick + 验证 PEP 604/585 兼容（参考 M2/M3/M4 模式） |

## 11. spec 审阅门

本文档需用户确认后方可进入 writing-plans 阶段。审阅请关注：
- §2 NDJSON 事件命名（chunk / done / error / progress）和 STAGE 字符串是否与现有 hook 兼容
- §4.1 LLMContext 设计是否过度抽象（PR-1 是否要拆得更小）
- §8 PR 切分粒度是否合适
- §9 范围外是否漏列/误列
