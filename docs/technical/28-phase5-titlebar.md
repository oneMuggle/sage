# 28 — Phase 5 Titlebar (M9)

## Overview

`Sage` 的桌面端标题栏 (`Titlebar.tsx`) 是一层**平台特定的 wrapper**,
在 macOS / Windows / Linux / Web 四种运行环境下分别给出合适的渲染:

- **macOS**: 隐藏 native traffic lights,自定义内容从 `y=28px` 开始(`pt-7`)
- **Windows / Linux**: 自绘标题栏,左半放 `TitlebarActions`(back/forward
  导航按钮),右半放 `WindowControls`(minimize / toggleMaximize / close)
- **Web**: 仅 `TitlebarActions` + FeedbackButton(无 window controls)

> 本文档是 M9 (Phase 5 Titlebar) 模块的"事后归档"——原始 spec 在
> `docs/superpowers/specs/2026-06-29-win7-m7-nav-history-design.md` §3.1。
> 实施以 main 侧 `4ab851c..9607af0` 4 个 commit 为蓝本 byte-for-byte port 到
> `release/win7`(本分支 `feat/win7-m7-nav-history` `7a8c17f..e30c563`)。
> drag region CSS 由 main 侧 `e35c590` 同步追加(本分支 `cfc559a`)。

## Architecture

### 文件清单(本分支新增/重构)

```
electron/main.ts                                       # +51 行: 5 个 IPC handlers + titleBarStyle
electron/preload.ts                                    # +12 行: windowControls bridge expose
src/shared/api/windowControlsClient.ts                 # 新增: Platform/WindowControlsBridge + detectPlatform
src/shared/api/__tests__/windowControlsClient.test.ts  # 新增: 9 tests (mock + bridge + 各场景)
src/widgets/layout/Titlebar.tsx                        # 新增: 平台分支 + drag/no-drag class
src/widgets/layout/__tests__/Titlebar.test.tsx         # 新增: 8 tests (web/mac/win/linux × 渲染 + 子组件)
src/widgets/layout/WindowControls.tsx                  # 新增: 3 按钮 + IPC 调用
src/widgets/layout/__tests__/WindowControls.test.tsx   # 新增: 6 tests (平台分支 + 按钮调用)
src/widgets/layout/Layout.tsx                          # +13 行: <Sidebar /> 后加 <Titlebar />
src/widgets/layout/index.ts                            # +1 行: 导出 Titlebar
src/index.css                                          # +9 行: .drag / .no-drag CSS
src/shared/lib/i18n/{zh,en}.ts                         # +3 keys: titlebar.minimize/maximize/close
```

### 三层架构

```
┌────────────────────────────────────────────────────────────────┐
│ Renderer (React + TSX)                                         │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ Titlebar.tsx (顶部 wrapper, 平台分支)                       ││
│ │  ├─ Web      → <TitlebarActions />  + FeedbackButton        ││
│ │  ├─ macOS    → pt-7 偏移 + Traffic lights 区 + Actions      ││
│ │  └─ Win/Linux → drag class + Actions + WindowControls       ││
│ │                                                              ││
│ │ WindowControls.tsx (Win/Linux 3 按钮)                       ││
│ │  └─ minimize / toggleMaximize / close → windowControls.*    ││
│ │                                                              ││
│ │ TitlebarActions.tsx (back/forward 按钮)                     ││
│ │  └─ no-drag class + useNavigationHistory().back()/forward() ││
│ └──────────────────────────────────────────────────────────────┘│
└─────────────────────┬──────────────────────────────────────────┘
                      │ IPC: window.electronAPI.windowControls.*
                      ▼
┌────────────────────────────────────────────────────────────────┐
│ Preload (electron/preload.ts)                                  │
│  windowControls: {                                             │
│    minimize: () => invoke('sage:window-controls:minimize'),    │
│    toggleMaximize: () => invoke('sage:window-controls:toggle-maximize'),│
│    close: () => invoke('sage:window-controls:close'),          │
│    capturePage: () => invoke('sage:window-controls:capture-page'),│
│    isMaximized: () => invoke('sage:window-controls:is-maximized'),│
│  }                                                             │
└─────────────────────┬──────────────────────────────────────────┘
                      │ ipcRenderer.invoke(channel)
                      ▼
┌────────────────────────────────────────────────────────────────┐
│ Main (electron/main.ts)                                        │
│  BrowserWindow(titleBarStyle='hidden' | frame=false, ...)      │
│  ipcMain.handle('sage:window-controls:*', evt => {            │
│    const win = BrowserWindow.fromWebContents(evt.sender);     │
│    win?.minimize() / unmaximize() / close() / etc.            │
│  })                                                             │
└────────────────────────────────────────────────────────────────┘
```

## 平台检测 (windowControlsClient.ts)

```typescript
export type Platform = 'macos' | 'windows' | 'linux' | 'web';

export function detectPlatform(): Platform {
  if (typeof window === 'undefined') return 'web';
  const ua = (window.navigator?.userAgent ?? '').toLowerCase();
  if (ua.includes('mac')) return 'macos';
  if (ua.includes('win')) return 'windows';
  if (ua.includes('linux')) return 'linux';
  return 'web';
}
```

`isElectronDesktop(platform)` 返回 `platform === 'windows' || platform === 'linux'`。

## Electron IPC Channels

| Channel                              | Renderer 调用             | Main handler                                       |
| ------------------------------------ | ------------------------- | -------------------------------------------------- |
| `sage:window-controls:minimize`      | `windowControls.minimize()` | `mainWindow.minimize()`                            |
| `sage:window-controls:toggle-maximize` | `windowControls.toggleMaximize()` | `win.isMaximized ? unmaximize() : maximize()` |
| `sage:window-controls:close`         | `windowControls.close()`   | `mainWindow.close()`                               |
| `sage:window-controls:capture-page`  | `windowControls.capturePage()` | `win.webContents.capturePage()` → base64 PNG |
| `sage:window-controls:is-maximized`   | `windowControls.isMaximized()` | `return win.isMaximized()`                       |

## Drag Region CSS

`src/index.css` 新增:

```css
.drag {
  -webkit-app-region: drag;
}

.no-drag {
  -webkit-app-region: no-drag;
}
```

`Titlebar.tsx`:
- Web 分支外层: 无 drag(无 native frame)
- macOS 分支外层: 无 drag(native traffic lights 处理)
- Win/Linux 分支外层: `className="drag flex ..."` 启用可拖动
  + WindowControls 包裹 div: `className="no-drag ..."` 确保按钮可点击

`TitlebarActions.tsx`: 最外层 `<div className="no-drag flex ...">`。

`WindowControls.tsx`: `<div className="flex no-drag">`。

## 测试策略

| 文件 | 测试数 | 覆盖 |
|---|---|---|
| `windowControlsClient.test.ts` | 9 | SSR no window / no electronAPI / partial mock / Linux UA / 客户端捕获异常 |
| `WindowControls.test.tsx` | 6 | 平台分支(win/linux/mac/web) × 3 按钮存在性 + onClick 调 IPC |
| `Titlebar.test.tsx` | 8 | 三分支渲染 + 子组件 mount + pt-7 / h-9 / h-10 class |

## win7 适配差异

- **Layout.tsx 简化版**: win7 不需要 main 上 `useResizableSidebar` / `ResizeDivider` 等。M9 port 时保留 win7 简化 `Layout`,仅新增 `<Titlebar />` 一行。
- **FeedbackButton 缺失**: win7 没 port M4 阶段的 FeedbackButton/FeedbackModal 模块。Titlebar.tsx 的 macOS 分支与 main 相比没有 `<FeedbackButton />` 元素。
- **WindowControls `no-drag` inline class**: main 4ab851c 引入 WindowControls 时已在 `<div className="flex no-drag" ...>` 添加,win7 cherry-pick 后保留。
- **drag region fix**: win7 cherry-pick 顺序为 M9 4 commit → e35c590 drag fix → M7 9 commit。e35c590 中 TitlebarActions.tsx 部分被推迟到 M7 T13 (aa235a2) commit 时手工 amend 加 `no-drag`,确保 TitlebarActions 一创建就含正确类。

## 与 M7 Nav-history 的关系

- M7 (Nav-history) 的 `TitlebarActions.tsx` 强依赖 M9 (Phase5 Titlebar) 提供的 `<Titlebar>` 渲染容器。
- 因此本分支**(M7+M9 联合 port)** 是必须的,不能拆开。
- 详见 `29-m7-nav-history.md`。

## 参考

- **父 spec**: `docs/superpowers/specs/2026-06-29-win7-m7-nav-history-design.md` §3.1 + §4
- **本模块 plan**: `docs/superpowers/plans/2026-06-29-win7-m7-nav-history-impl.md` Phase 2-3
- **main M9 source commits**: `4ab851c..9607af0` (4 commits)
- **main drag fix**: `e35c590`
- **兄弟模块**: `docs/technical/29-m7-nav-history.md` (TitlebarActions 的消费方)
