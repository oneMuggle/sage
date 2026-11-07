# TaskCenter 后台任务聚合 · Phase 5

> 日期：2026-11-07
> 分支：`feat/background-task-phase5`（main）；win7 同步另起分支
> 状态：实施中

## 背景

Phase 0–4 已把后台 shell 能力铺齐：列表 / 流式输出 / 通知 / 持久化 / 强校验。
但后台 shell 的可见性仍局限在**聊天右栏「进度」Tab** 的 `BackgroundShellsSection`
里 —— 用户离开 chat 页就看不到、无法取消。

Phase 5 目标：把后台 shell 聚合进**全局 TaskCenter 胶囊**，与 registry tasks /
chat streams / orchestration lanes 并列显示。用户在任意页面都能看到运行中的
后台任务，点击打开输出面板，可终止。

## 涉及的文件与模块

### 后端
- `backend/api/shell_routes.py`：新增 `DELETE /api/v1/shells/{shell_id}`（调用
  `registry.terminate`），返回最后输出片段。

### Electron
- `electron/commandRoutes/settings.ts`：新增 `shell_kill`（`DELETE /api/v1/shells/{id}`）。
- `electron/ipc-manifest.json`：`npm run ipc:manifest` 重生成。

### 前端
- `src/features/task-center/taskCenterStore.ts`：新增 `registerShell` /
  `removeShell`，shell 条目标记 source='shell'。
- `src/widgets/task-center/TaskCenterWidget.tsx`：
  - 轮询 `listShells()`（3s），diff 更新 taskCenterStore。
  - Entry 渲染分支增加 source='shell'（command 截断、状态图标、age）。
  - 点击 entry → 打开 `ShellStreamDrawer`（新组件）。
- `src/widgets/task-center/ShellStreamDrawer.tsx`（新）：
  - 全屏抽屉（类似 DeliveryDrawerHost），承载 ShellStreamPanel 内容。
  - 顶部：command、status、退出码（若已退出）。
  - 底部：终止按钮（running 时）/ 关闭按钮。

### 测试
- `backend/tests/unit/test_shell_routes.py`：kill 端点单测。
- `src/widgets/task-center/__tests__/TaskCenterWidget.shells.test.tsx`：轮询、entry
  渲染、点击开抽屉。
- `src/widgets/task-center/__tests__/ShellStreamDrawer.test.tsx`：抽屉渲染、按钮。

## 技术方案

### T1: kill 端点
```python
@router.delete("/shells/{shell_id}")
def kill_shell(shell_id: str) -> Dict[str, Any]:
    registry = get_registry()
    payload = registry.terminate(shell_id, cap=64 * 1024)
    if payload is None:
        raise HTTPException(404, detail="unknown shell_id")
    return payload
```

### T2: Electron command route
```ts
shell_kill: {
  method: 'DELETE',
  path: (a) => `/api/v1/shells/${encodeURIComponent(String(a.id))}`,
}
```

### T3: taskCenterStore 扩展
新增 `registerShell` / `removeShell` / `removeShellsNotIn`；shell 条目 status 映射：
`running` → `running`；`exited` → `succeeded`（exit_code=0）或 `failed`（非 0）。

### T4: TaskCenterWidget 轮询 + 渲染
`useEffect` 3s 轮询 `listShells()`；diff 更新 store。新增 `source==='shell'` 渲染
分支。

### T5: ShellStreamDrawer
- 全屏抽屉（framer-motion 动画）。
- 内部复用 `ShellStreamPanel`。
- 顶部：command + 状态徽标 + 关闭按钮。
- 底部：终止按钮（running 时）→ `invoke('shell_kill', {id})`。

## 实施步骤

- [x] M1: 本 plan 文档
- [x] M2: kill 端点 + 测试
- [x] M3: Electron shell_kill 路由
- [x] M4: taskCenterStore shell 支持
- [x] M5: TaskCenterWidget 轮询 + 渲染
- [x] M6: ShellStreamDrawer 组件 + 测试
- [x] M7: ruff / py38 / typecheck / 架构检查
- [ ] M8: main PR → CI → 合并
- [ ] M9: win7 同步 PR

## 风险

| 风险 | 缓解 |
|---|---|
| 抽屉动画性能 | 仅打开时渲染；关闭 unmount |
| 3s 轮询频率 | 仅 TaskCenterWidget 挂载时 |
| kill 端点权限 | 沿用 LocalAuthMiddleware |
| 输出过大卡顿 | ShellStreamPanel 200k 字符上限 |
| 抽屉互斥 | 打开一个关闭另一个 |

## 不在范围

- shell 历史归档
- 多窗口并行查看
- 输出搜索/过滤
- 移动端响应式
