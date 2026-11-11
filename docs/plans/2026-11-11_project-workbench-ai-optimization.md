# 项目工作台 AI 分析优化

**日期**: 2026-11-11
**PR**: 待创建
**状态**: 已实施

## 背景与目标

用户反馈项目工作台 AI 分析时会阻塞 Sage 应用其他模块。根因是 `profile_project()` 同步调用阻塞 FastAPI 事件循环，导致其他 API 请求无法处理。

## 涉及的文件与模块

- `backend/api/project_routes.py`: `analyze_project` 端点
- `src/features/project-type/ProjectAnalysisWizard.tsx`: 前端分析向导

## 技术方案

### 1. 后端：事件循环解耦（run_in_executor）

将 `profile_project()` 放入线程池，避免阻塞异步事件循环。

```python
loop = asyncio.get_event_loop()
profile = await loop.run_in_executor(None, lambda: profile_project(path))
```

### 2. 后端：结果缓存（path + git_sha，TTL 1h）

相同项目 + 相同 git commit 在 1 小时内直接返回缓存，避免重复分析。

```python
_analysis_cache: Dict[str, Tuple[float, dict, dict]] = {}
_ANALYSIS_CACHE_TTL = 3600  # 1 小时
_ANALYSIS_CACHE_MAX_SIZE = 50  # 最多 50 个项目
```

缓存 key = `path:git_sha`，非 git 仓库不缓存。

### 3. 后端：整体超时（asyncio.timeout 180s）

```python
async with asyncio.timeout(180):
    report = await agent.analyze(profile)
```

### 4. 前端：软超时 + 取消（Promise.race，60s）

Electron IPC 不支持 AbortSignal，用 `Promise.race` 实现软超时：

```typescript
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 60_000);

const result = await Promise.race([
  projectApi.analyze(path),
  timeoutPromise,
]);
```

加「取消」按钮，用户可主动中止等待。

## 实施步骤

- [x] 后端：`run_in_executor` 解耦 `profile_project()`
- [x] 后端：`_analysis_cache` + `_get_git_sha()` + `_cleanup_cache()`
- [x] 后端：`asyncio.timeout(180)` 包裹 LLM 分析
- [x] 前端：`cancelled` 状态 + `ANALYSIS_TIMEOUT_MS` + `Promise.race`
- [x] 前端：取消按钮 UI
- [x] Python 语法验证通过
- [x] TypeScript 类型检查通过
- [ ] CI 验证
- [ ] 合并 PR

## 风险评估

- **缓存失效**：git_sha 变化自动失效，非 git 目录不缓存
- **并发安全**：`_analysis_cache` 是进程内 dict，FastAPI 单进程安全
- **超时处理**：前端 60s 软超时 + 后端 180s 硬超时，双层保护
