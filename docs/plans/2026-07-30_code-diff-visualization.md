# A17 — Code Diff Visualization

> **状态:** 已完成
> **日期:** 2026-07-30
> **目标分支:** `main`(feature 分支 `feat/code-diff-visualization`)
> **来源:** `docs/plans/2026-07-30_sage-optimization-final.md` A17(Phase 2,来自 LLM_Simple + pi)
> **参考实现:**
> - `/home/fz/project/LLM_Simple/main.py:206-234`(write/edit 前后捕获内容 → emit diff)
> - `/home/fz/project/pi/packages/coding-agent/src/core/tools/edit-diff.ts`(unified patch 生成)

---

## 1. 背景与目标

LLM 调用 `write_file` 修改文件后,用户在 chat UI 中只能看到工具结果 JSON
(`{"path": ..., "bytes_written": ...}`),**看不到具体改了什么**。
LLM_Simple 与 pi 都在工具执行前后捕获文件内容并渲染 diff,体感差距明显。

**目标:** `write_file` 执行成功后,chat 工具卡片内渲染 inline diff 视图
(新增行绿色、删除行红色、可折叠)。

**非目标(后续迭代):**

- `edit_file` 工具(Sage 目前不存在,仅有 write_file + append 模式)
- diff 持久化到消息历史(仅 live SSE 渲染;历史回放显示普通工具卡片)
- Office 文档 diff(已有独立实现,不重复)

## 2. 涉及的文件与模块

### 后端(Python 3.11,conda env `sage-backend`)

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/application/services/code_diff.py` | **新建** | 纯函数:unified diff 生成 + metadata 构建 + 大小护栏 |
| `backend/tools/base.py` | 修改 | `ToolResult` 增加 `metadata` 字段(对齐 sage_core 域模型) |
| `backend/tools/file_tool.py` | 修改 | `WriteFileTool.execute` 写前捕获旧内容、写后生成 diff |
| `backend/core/legacy/agent.py` | 修改 | OBSERVING 事件展示层注入 `metadata`(LLM 上下文不带,省 token) |
| `backend/adapters/out/tool/inproc_adapter.py` | 修改 | 工具层 metadata 透传到域 `ToolResult.metadata` |

### 前端(React 18 + Vite)

| 文件 | 变更 | 说明 |
|---|---|---|
| `package.json` | 修改 | 新增 `react-diff-viewer-continued`(react-diff-viewer 的维护版 fork,React 18 兼容) |
| `src/shared/lib/store.ts` | 修改 | `ToolCall.metadata` 增加 `code_diff` 类型 |
| `src/widgets/chat/CodeDiffViewer.tsx` | **新建** | diff 渲染组件(可折叠卡片 + react-diff-viewer + unified 降级渲染) |
| `src/widgets/chat/Message.tsx` | 修改 | 工具卡片检测 `tc.metadata.code_diff` → 渲染 CodeDiffViewer |

### 测试

| 文件 | 变更 |
|---|---|
| `backend/tests/unit/test_code_diff.py` | **新建**:纯函数 + WriteFileTool 集成 + adapter 透传 + agent 展示序列化 |
| `src/widgets/chat/__tests__/CodeDiffViewer.test.tsx` | **新建** |
| `src/widgets/chat/__tests__/Message.test.tsx` | 修改:增加 code_diff 渲染用例 |

## 3. 技术方案

### 3.1 数据流

```
WriteFileTool.execute
  ├─ 写前: 读旧内容(存在且可读; 超 MAX_DIFF_CONTENT_BYTES 仅读探测)
  ├─ 写后: 新内容 = content (append 模式 = old + content)
  ├─ code_diff.build_code_diff_metadata() → dict | None
  └─ ToolResult(success, content={path, bytes_written, mode},
                metadata={"code_diff": {...}})
        │
        ├─ [legacy agent / chat SSE 路径]
        │   agent.py: OBSERVING 事件 content = json(content + metadata)
        │             LLM messages 历史仍用裸 content(省 token)
        │   → 前端 useChat observing 分支已有 parsed.metadata 提取逻辑
        │     (HIGH-2 imageData 同款机制,零新增管线)
        │   → tc.metadata.code_diff
        │   → Message.tsx 工具卡片 → <CodeDiffViewer />
        │
        └─ [ChatService / ToolPort 路径]
            InprocToolAdapter 合并 raw.metadata → 域 ToolResult.metadata
            (满足 "result.metadata['code_diff']" 契约)
```

### 3.2 code_diff metadata 结构

```json
{
  "path": "/abs/path/file.py",
  "is_new_file": false,
  "unified_diff": "--- a/...\n+++ b/...\n@@ ...",
  "additions": 3,
  "deletions": 1,
  "old_content": "...",
  "new_content": "..."
}
```

**大小护栏**(防止大文件写穿 SSE / 前端内存):

| 常量 | 值 | 行为 |
|---|---|---|
| `MAX_DIFF_CONTENT_BYTES` | 64 KB | old/new 任一侧超限 → metadata 省略 `old_content`/`new_content`(前端降级渲染 unified_diff) |
| `MAX_UNIFIED_DIFF_BYTES` | 32 KB | unified diff 超限 → 截断并标 `diff_truncated: true` |
| `MAX_CAPTURE_BYTES` | 1 MB | 写前读旧内容的硬上限,超限 → `{"path", "skipped": "file_too_large"}` |

`old == new` 时返回 `None`(不附 metadata,不渲染)。

### 3.3 前端组件

- `CodeDiffViewer` 优先用 `react-diff-viewer-continued` 的
  `ReactDiffViewer(oldValue, newValue, splitView=false)` 渲染
  (old/new 内容可得时,语法级高亮)。
- old/new 缺失但 unified_diff 可得 → 降级为按行着色 `<pre>`
  (`+` 绿 / `-` 红 / `@@` 蓝)。
- 深色模式:`document.documentElement.classList.contains('dark')`
  (ThemeProvider 已在 root 上 toggle `dark` class)。
- 头部:文件路径 + `+N` / `-M` 徽章 + 折叠开关(默认展开)。

### 3.4 LLM 上下文隔离

`backend/core/legacy/agent.py` 中,工具结果同时服务两处:

1. **LLM messages 历史** — 保持裸 `json.dumps(result.content)`,
   **不**注入 metadata(避免 diff/旧内容消耗上下文 token)。
2. **OBSERVING 展示事件** — `ToolCallResult.content` 注入
   `"metadata"` 键(前端 `parsed.metadata` 提取)。

抽取纯函数 `_tool_result_display_content(result_content, metadata)`
便于单测。

## 4. 实施步骤

- [x] 步骤 1:后端 `code_diff.py` 纯函数 + `ToolResult.metadata` 字段
- [x] 步骤 2:`WriteFileTool` + `EditTool` 捕获前后内容、生成 diff metadata(main 分支存在 edit_file 工具,一并接入)
- [x] 步骤 3:legacy agent 展示层注入 + InprocToolAdapter 透传
- [x] 步骤 4:`backend/tests/unit/test_code_diff.py` 24 用例全绿;全量单测 2151 passed / 0 failed
- [x] 步骤 5:前端安装 `react-diff-viewer-continued@^4.4.0` + store `CodeDiff` 类型
- [x] 步骤 6:`CodeDiffViewer.tsx` + `Message.tsx` 集成
- [x] 步骤 7:vitest 984 passed / tsc 零错误 / eslint + ruff 零告警
- [x] 步骤 8:commit + push + PR

## 5. 风险评估与依赖

| 风险 | 缓解 |
|---|---|
| react-diff-viewer(原版 2020 停更)与 React 18 peer 冲突 | 用维护版 fork `react-diff-viewer-continued`(API 兼容,React 18 peer) |
| 大文件写穿 SSE | 三级大小护栏(§3.2) |
| diff 进 LLM 上下文浪费 token | 展示层/上下文层分离(§3.4) |
| 并行会话占用主工作区 | 在独立 worktree `/home/fz/project/sage-a17` 实施 |
| Win7 分支同步 | main 先行;release/win7 按需 cherry-pick(本项纯增量,py3.8 兼容:不使用 match/新语法) |
