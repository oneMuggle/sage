# 桌宠窗口生命周期优化计划

> **创建日期**: 2026-11-03  
> **状态**: 计划中  
> **优先级**: P1

## 背景与目标

用户反馈两个桌宠相关问题：
1. **进程残留**：开发模式下关闭 Electron 窗口后，桌宠依然存在
2. **点击无响应**：桌宠有时不可点击，需要重启应用

本计划旨在修复这两个问题，提升桌宠窗口的生命周期管理可靠性。

## 问题分析

### 问题1：窗口关闭后进程残留

**根因**：
- `disposePet()` 仅在 `before-quit` 事件中被调用（`main.ts:3145`）
- 主窗口 `closed` 事件（`main.ts:1203-1208`）只清理 `agentBrowserHandle`，未调用 `disposePet()`
- 桌宠窗口作为独立 BrowserWindow（`focusable: false`、`skipTaskbar: true`）阻止 `window-all-closed` 事件触发
- 应用无法退出，进程残留

**代码路径**：
```
用户关闭窗口 → win.on('closed') → 只清理 agentBrowserHandle
                                 → 未调用 disposePet()
                                 → 桌宠窗口仍存在
                                 → window-all-closed 不触发
                                 → 应用无法退出
```

### 问题2：桌宠有时不可点击

**根因**：
- 点击穿透依赖 `pollPointer()` 60ms 轮询鼠标位置（`windows.ts:528-545`）
- `setIgnoreMouseEvents(true, { forward: true })` 在某些环境不稳定（Win7/VM）
- `ignoring` 状态字段可能和实际窗口状态不同步
- `pointerFallbackBroken` 一旦触发（第539行），无法恢复轮询

**关键代码**（windows.ts:528-577）：
```typescript
private pollPointer(): void {
  // 60ms 轮询鼠标位置
  const inside = isPointInRect(cursor, petHitBox(bounds));
  this.setIgnoreMouse(!inside);
}

private setIgnoreMouse(ignore: boolean): void {
  if (ignore) {
    this.win.setIgnoreMouseEvents(true, { forward: true });
  } else {
    this.win.setIgnoreMouseEvents(false);
  }
  this.ignoring = ignore;
}
```

## 涉及的文件与模块

| 文件 | 模块 | 变更类型 |
|------|------|----------|
| `electron/main.ts` | 主进程入口 | 修改窗口关闭事件处理 |
| `electron/pet/index.ts` | 桌宠单例 | 确保 disposePet() 幂等 |
| `electron/pet/windows.ts` | 桌宠窗口 | 修复点击状态同步 |

## 技术方案

### 方案1：主窗口关闭时清理桌宠（问题1）

**修改点**：`electron/main.ts` 主窗口 `closed` 事件（第1203行附近）

```typescript
// 修改前：
win.on('closed', () => {
  if (agentBrowserHandle) {
    void agentBrowserHandle.close();
    agentBrowserHandle = null;
  }
});

// 修改后：
win.on('closed', () => {
  if (agentBrowserHandle) {
    void agentBrowserHandle.close();
    agentBrowserHandle = null;
  }
  // 清理桌宠窗口，避免阻止 window-all-closed
  disposePet();
});
```

**补充修改**：`electron/pet/index.ts` 确保 `disposePet()` 幂等

```typescript
// 修改前：
export function disposePet(): void {
  controller?.dispose();
  controller = null;
  unregisterPetIpc();
}

// 修改后：
export function disposePet(): void {
  if (!controller) return; // 幂等保护
  controller.dispose();
  controller = null;
  unregisterPetIpc();
}
```

**注意**：macOS `activate` 事件恢复窗口时，`createMainWindow()` 会重新调用 `ensurePetInitialized()`（`main.ts:1199`），桌宠会重新初始化。

### 方案2：修复点击状态同步（问题2）

**修改点1**：`electron/pet/windows.ts` 增加状态同步保护方法

```typescript
// 在 PetWindow 类中添加：
private syncIgnoreState(): void {
  if (!this.win || this.win.isDestroyed()) return;
  if (!this.clickThroughActive()) {
    // 非 click-through 模式，确保不忽略鼠标
    if (this.ignoring) {
      this.setIgnoreMouse(false);
    }
    return;
  }
  // click-through 模式，根据鼠标位置决定
  try {
    const cursor = screen.getCursorScreenPoint();
    const bounds = this.win.getBounds();
    const inside = isPointInRect(cursor, petHitBox(bounds));
    this.setIgnoreMouse(!inside);
  } catch {
    // 轮询失败，保持可交互
    this.setIgnoreMouse(false);
  }
}
```

**修改点2**：关键生命周期节点调用 `syncIgnoreState()`

```typescript
show(): void {
  if (!this.win || this.win.isDestroyed()) return;
  // ... existing code ...
  this.syncIgnoreState(); // 显示后同步状态
}

endDrag(): void {
  if (!this.dragging) return;
  this.dragging = false;
  // ... existing code ...
  this.syncIgnoreState(); // 拖拽结束同步状态
}
```

**修改点3**：`pollPointer()` 允许重试，不永久设置 `pointerFallbackBroken`

```typescript
private pollPointer(): void {
  if (this.compatibility || this.dragging) return; // 移除 pointerFallbackBroken 检查
  if (!this.win || this.win.isDestroyed() || !this.win.isVisible()) return;
  try {
    const cursor = screen.getCursorScreenPoint();
    const bounds = this.win.getBounds();
    const inside = isPointInRect(cursor, petHitBox(bounds));
    this.setIgnoreMouse(!inside);
    // 成功后重置 fallback 标志
    this.pointerFallbackBroken = false;
  } catch (err) {
    // 失败时不永久设置 pointerFallbackBroken，保持可交互
    logger.warn('pet: cursor polling failed, will retry', {
      err: err instanceof Error ? err.message : String(err),
    });
    this.setIgnoreMouse(false);
  }
}
```

## 实施步骤

### 里程碑1：修复进程残留（P0）

- [x] 修改 `electron/main.ts` 主窗口 `closed` 事件，调用 `disposePet()`
- [x] 确保 `disposePet()` 幂等（`electron/pet/index.ts`）
- [x] 验证 `window-all-closed` 正常触发
- [x] 测试 macOS `activate` 事件恢复窗口的场景

### 里程碑2：修复点击状态同步（P1）

- [x] 添加 `syncIgnoreState()` 方法（`electron/pet/windows.ts`）
- [x] 在 `show()` / `endDrag()` 调用同步
- [x] 修改 `pollPointer()` 允许重试
- [x] 测试 Win7 / Wayland 环境的点击穿透

### 里程碑3：回归测试

- [ ] 开发模式：关闭窗口 → 验证进程完全退出
- [ ] 生产模式：关闭窗口 → 验证进程完全退出
- [ ] Close-to-tray 开启：关闭窗口 → 验证桌宠隐藏但进程存活
- [ ] 拖拽桌宠 → 验证拖拽后点击正常
- [ ] 隐藏/显示桌宠 → 验证点击正常

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| macOS activate 恢复窗口时桌宠丢失 | 中 | `initPet()` 检查已有 controller，避免重复初始化 |
| `syncIgnoreState()` 频繁调用影响性能 | 低 | 仅在关键生命周期节点调用，不在轮询中调用 |
| `pointerFallbackBroken` 可恢复导致轮询频繁失败 | 低 | 失败后 fallback 到完全可交互，不影响功能 |

## 依赖

- 无外部依赖
- 需要双分支（main + release/win7）同步

## 参考资料

- Electron BrowserWindow 生命周期：https://www.electronjs.org/docs/api/browser-window
- `setIgnoreMouseEvents` 文档：https://www.electronjs.org/docs/api/browser-window#winsetignoremouseeventignore-options
- 桌宠功能设计文档：`docs/plans/2026-10-30_desktop-pet.md`
- 技术文档：`docs/technical/117-desktop-pet.md`
