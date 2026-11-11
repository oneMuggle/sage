# 项目工作台 AI 分析优化

> **状态**: 进行中  
> **分支**: `fix/project-workbench-ai-optimization`  
> **Worktree**: `.worktrees/fix-project-workbench-ai-optimization`  
> **创建日期**: 2026-11-11

---

## 背景与目标

### 问题

1. **后端事件循环阻塞**: `profile_project()` 是同步函数，在大项目（数千文件）上会阻塞 FastAPI 事件循环 2-5 秒，影响其他 API 请求
2. **无前端超时/取消**: 用户无法中止长时间分析，只能等待或跳过
3. **无后端整体超时**: 仅依赖 LLM Provider 级别 120-300s 超时
4. **无进度反馈**: 只有 spinner，用户不知道分析进展

### 目标

1. **P0**: 将 `profile_project()` 放入线程池，避免阻塞事件循环
2. **P1**: 添加前端超时与取消机制（AbortController + 60s 超时）
3. **P2**: 添加流式进度反馈（SSE/NDJSON 或轮询）
4. **P3**: 添加后端缓存（相同路径 + 相同 git commit = 直接返回）

---

## 涉及的文件与模块

### 后端

| 文件 | 改动 |
|------|------|
| `backend/api/project_routes.py` | `analyze_project` 用 `run_in_executor` 包裹 `profile_project` |
| `backend/api/project_routes.py` | 添加整体 `asyncio.timeout()` |
| `backend/services/project_profiler.py` | 可选：添加缓存层 |

### 前端

| 文件 | 改动 |
|------|------|
| `src/features/project-type/ProjectAnalysisWizard.tsx` | 添加 AbortController + 超时 + 取消按钮 |
| `src/shared/api/projectApi.ts` | `analyze()` 接受 `signal` 参数 |
| `src/shared/api/desktopInvoke.ts` | `invoke()` 传递 `signal` |
| `electron/invoke.ts` | `invokeBackend()` 使用 `AbortSignal` |
| `electron/commandRoutes/projects.ts` | 路由支持 signal 传递 |

---

## 技术方案

### P0: 事件循环解耦

```python
# backend/api/project_routes.py
@router.post("/analyze", response_model=ProjectAnalyzeResponse)
async def analyze_project(request: ProjectAnalyzeRequest) -> ProjectAnalyzeResponse:
    loop = asyncio.get_event_loop()
    
    # 将同步的 profile_project 放入线程池
    profile = await loop.run_in_executor(
        None, 
        lambda: profile_project(request.path)
    )
    
    # LLM 分析本身是异步的
    agent = ProjectAnalysisAgent()
    async with asyncio.timeout(180):  # 整体 3 分钟超时
        report = await agent.analyze(profile)
    
    return ProjectAnalyzeResponse(...)
```

### P1: 前端超时与取消

```typescript
// ProjectAnalysisWizard.tsx
const [abortController, setAbortController] = useState<AbortController | null>(null);

const runAnalysis = useCallback(async () => {
  const controller = new AbortController();
  setAbortController(controller);
  
  try {
    const result = await Promise.race([
      projectApi.analyze(path, { signal: controller.signal }),
      new Promise((_, reject) => 
        setTimeout(() => reject(new Error('ANALYSIS_TIMEOUT')), 60000)
      )
    ]);
  } catch (err) {
    if (err.name === 'AbortError') {
      // 用户取消
    } else if (err.message === 'ANALYSIS_TIMEOUT') {
      setAnalysisError('分析超时，请重试或跳过');
    }
  } finally {
    setAbortController(null);
  }
}, [path]);

const cancelAnalysis = () => {
  abortController?.abort();
};
```

### P2: 流式进度（可选，复杂度较高）

参考 Chat 的 NDJSON 模式，改造为 SSE 流式推送：

```
POST /api/v1/projects/analyze/stream
-> yield {"stage": "profiling", "progress": 20}
-> yield {"stage": "analyzing", "progress": 60}  
-> yield {"stage": "generating", "progress": 90}
-> yield {"stage": "complete", "result": {...}}
```

**注意**: 此步骤需要 Electron IPC 支持流式，改动较大，可考虑降级为轮询。

### P3: 后端缓存

```python
# backend/services/project_profiler.py
import hashlib

_analysis_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 3600  # 1 小时

async def analyze_project_cached(path: str) -> AnalysisReport:
    # 计算 cache key: path + git sha
    git_sha = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], 
        cwd=path
    ).decode().strip()
    
    cache_key = f"{path}:{git_sha}"
    
    if cached := _analysis_cache.get(cache_key):
        ts, result = cached
        if time.time() - ts < CACHE_TTL:
            return result
    
    # 执行分析
    result = await analyze(path)
    _analysis_cache[cache_key] = (time.time(), result)
    return result
```

---

## 实施步骤

### M1: P0 - 事件循环解耦 [x]

- [x] 修改 `backend/api/project_routes.py`
  - [x] `profile_project()` 用 `run_in_executor` 包裹
  - [x] 添加 `asyncio.timeout(180)` 包裹整体分析流程
- [ ] 添加单元测试（可选，后续补充）
- [x] 验证：TypeScript 类型检查通过 + Python 语法检查通过

### M2: P1 - 前端超时与取消 [x]

- [x] ~~修改 `src/shared/api/desktopInvoke.ts` 支持 signal~~ — 采用软取消方案，无需修改
- [x] ~~修改 `src/shared/api/projectApi.ts` 接受 signal~~ — 采用软取消方案，无需修改
- [x] ~~修改 `electron/invoke.ts` 使用 AbortSignal~~ — 采用软取消方案，无需修改
- [x] 修改 `ProjectAnalysisWizard.tsx` 添加取消按钮 + 60s 超时
- [x] 验证：TypeScript 类型检查通过

**方案说明**：Electron IPC 原生不支持 AbortSignal 穿透，采用**软取消**方案：
- 前端用 `Promise.race` 实现 60s 超时
- 取消按钮让前端不再等待结果（后端继续执行但丢弃结果）
- 比"硬取消"简单，对分析任务可接受

### M3: P2 - 流式进度（可选）[ ]

- [ ] 评估 Electron IPC 流式支持
- [ ] 设计进度事件协议
- [ ] 实现后端 SSE/NDJSON 流
- [ ] 实现前端进度条

### M4: P3 - 后端缓存 [x]

- [x] 实现 cache key 计算（path + git sha）
- [x] 实现内存缓存（TTL = 1 小时，上限 50 条）
- [x] 验证：Python 语法检查通过

---

## 风险评估

| 风险 | 缓解 |
|------|------|
| `run_in_executor` 增加线程开销 | 仅用于 profile_project（IO 密集），可接受 |
| AbortController 穿透 IPC 层复杂 | Electron IPC 原生支持 abort，但需要测试 |
| 缓存占用内存 | 限制 cache 大小（LRU），设置 TTL |
| 流式进度改动大 | P2 标记为可选，优先 P0+P1 |

---

## 参考

- [Chat 流式实现](src/shared/api/chatApi.ts) -- NDJSON 模式参考
- [M4 index_material](backend/api/project_ai_routes.py:625) -- `run_in_executor` 参考
- [Electron IPC abort](https://www.electronjs.org/docs/latest/api/ipc-main) -- 官方文档
