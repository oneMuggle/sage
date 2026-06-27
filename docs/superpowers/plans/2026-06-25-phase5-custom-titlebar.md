# Phase 5 — 自定义标题栏 + 反馈入口 — 实施计划

**日期：** 2026-06-25
**作者：** Claude (writing-plans skill)
**状态：** 待用户审阅
**所属项目：** sage (Electron 21.4.4 + React 18 + FastAPI)
**所属方案：** AionUi 借鉴方案（详见 `docs/superpowers/specs/2026-06-25-aionui-inspired-ui-design.md` §4.Phase 5）

---

## Goal

为 sage 桌面端实现**平台感知的自定义标题栏**与**反馈入口**。在 macOS 上保留原生交通灯按钮的视觉一致性，在 Windows / Linux 上提供完全自定义的最小化 / 最大化 / 关闭按钮，并集成"反馈"按钮（一键截屏 + 反馈表单模态）。WebUI（纯浏览器）模式下显示**简化版**标题栏（无窗口控件），保证三端体验一致但不破布局。

**成功标准：**
1. macOS / Windows / Linux / WebUI 四个渲染分支**均**得到组件测试覆盖
2. `windowControlsClient` 覆盖率 ≥ **90%**；整体（仅 src 范围）≥ **83%**
3. 所有现有测试（Layout / Sidebar / TitlebarActions 假定的占位 Phase 1 占位）**继续通过**
4. 不引入任何新的 npm 依赖
5. `webContents.capturePage` 在 Electron 21.4.4 上的**可用性**有显式实验记录（README 内联 + plan task）
6. TDD 严格：所有 widget / client / hook **先写测试再写实现**

---

## Architecture

### 模块拓扑（FSD 视角）

```
src/
├── shared/
│   └── api/
│       └── windowControlsClient.ts          [NEW] IPC 客户端 + 平台检测
├── widgets/
│   └── layout/
│       ├── Titlebar.tsx                     [NEW] 总组装
│       ├── WindowControls.tsx               [NEW] Win/Linux 按钮
│       ├── FeedbackButton.tsx               [NEW] 反馈按钮 + FeedbackModal
│       ├── Layout.tsx                       [MOD] 插入 <Titlebar>
│       └── __tests__/                       [NEW] 组件测试目录
│           ├── Titlebar.test.tsx
│           ├── WindowControls.test.tsx
│           └── FeedbackButton.test.tsx
└── shared/
    └── api/
        └── __tests__/
            └── windowControlsClient.test.ts [NEW] 单元测试
```

### 渲染分支决策表

| 平台            | titleBarStyle       | WindowControls | FeedbackButton | 标题栏高度 |
| --------------- | ------------------- | -------------- | -------------- | ---------- |
| macOS           | `hiddenInset`       | 不渲染         | 渲染           | 28px       |
| Windows / Linux | `hidden` + frame=false | 渲染         | 渲染           | 32px       |
| WebUI（浏览器） | N/A                 | 不渲染         | 渲染           | 32px       |

### IPC 协议（preload 侧扩展）

主进程（`electron/main.ts`）注册 `ipcMain.handle`：
- `sage:window-controls:minimize`
- `sage:window-controls:toggle-maximize`
- `sage:window-controls:close`
- `sage:window-controls:capture-page` → 返回 base64 PNG
- `sage:window-controls:is-maximized` → 返回 boolean

preload（`electron/preload.ts`）在 `window.electronAPI` 上暴露 `windowControls` 子对象，签名与 `WindowControlsBridge` 一致。

### Electron BrowserWindow 配置

`createMainWindow()` 中追加 `titleBarStyle` 字段（按平台分支），并把 `frame` 设为 `false`（Win / Linux）。`webContents.setWindowOpenHandler` 已有，无需修改。

### 反馈提交

Phase 5 范围内**仅占位**：FeedbackModal 收集描述 + 截图 + 联系邮箱，提交时 `console.log` 完整 payload 并 toast 提示"已收到（演示模式）"。**不**做真实上报接口（Phase 6+ 再补）。

---

## Tech Stack

| 层级       | 技术                                     | 备注                         |
| ---------- | ---------------------------------------- | ---------------------------- |
| 渲染       | React 18 + TypeScript + Tailwind         | 沿用项目栈                   |
| IPC        | Electron 21.4.4 `ipcRenderer.invoke`     | 沿用 Phase 1 的 `electronAPI` 桥 |
| 状态       | React useState / useEffect               | Titlebar 无复杂状态          |
| 国际化     | `useI18n()` from `@/shared/lib/i18n`     | 复用 i18n 基础设施           |
| 模态       | `<dialog>` 原生 + Tailwind               | 不引入 Radix Dialog          |
| 截图       | `webContents.capturePage().toPNG()`      | Electron 主进程，IPC 转发    |
| 测试       | Vitest + @testing-library/react          | 沿用项目栈                   |
| 平台检测   | `navigator.userAgent` 字符串匹配         | 不引入 `ua-parser-js`        |

---

## Global Constraints

1. **不新增 npm 包**。Electron 21.4.4 + React 18 + Tailwind + Vitest + Testing Library 即足。
2. **TDD 严格**：每个 widget / client 的提交必须是"先写失败测试 → 再写实现 → 再重构"。本计划 Task 顺序就是 TDD 顺序。
3. **不破坏现有架构**：
   - Layout.tsx 的 `<Outlet />` 与 `useResizableSidebar` 流程**不能改**
   - Sidebar.tsx 不动
   - Phase 1 文档假定的 `TitlebarActions`（前进/后退）若**未来**实现，要能**无侵入**地插入到 Titlebar 中（计划在 Titlebar.tsx 中保留 `<Slot name="left-actions" />`，但不实现 TitlebarActions）
4. **错误处理**：
   - IPC 失败 → 按钮 disable + `console.warn` + **不抛错到 UI**
   - `capturePage` 失败 → FeedbackModal 切到"无截图"模式，仍可提交
   - 平台检测失败 → 退化到 `titleBarStyle: 'hidden'`
5. **类型安全**：禁用 `any`；preload / client / component 之间用**显式 interface**，不依赖推断
6. **可测试性**：所有 widget 必须把 IPC 调用 prop 化（接收 `bridge: WindowControlsBridge`），便于 `vi.fn()` 桩化
7. **Electron 21.4.4 兼容性**：`webContents.capturePage()` 在 21.x 可用，但**只能**在 main 进程调用（preload 不能直接拿 webContents）。本计划在 main 进程用 `mainWindow.webContents.capturePage()` 实现，preload 通过 IPC invoke 转发。
8. **覆盖率门槛**：windowControlsClient ≥ 90%；整体（src 范围）≥ 83%（`vitest run --coverage` 校验）
9. **FSD 边界**：不跨层引用 — `widgets/` 不直接 `import` 业务实体；`shared/api/` 不感知 React
10. **a11y**：WindowControls 按钮有 `aria-label`（i18n）；FeedbackModal 是 `<dialog>` + `aria-modal`

---

## File Inventory

### Create（5 个源 + 4 个测试 + 1 个 docs = 10 个）

| 文件 | 用途 |
| --- | --- |
| `src/shared/api/windowControlsClient.ts` | IPC 客户端 + 平台检测工具 |
| `src/shared/api/__tests__/windowControlsClient.test.ts` | 单元测试 |
| `src/widgets/layout/Titlebar.tsx` | 标题栏主组件（含 Slot） |
| `src/widgets/layout/WindowControls.tsx` | Win/Linux 窗口按钮 |
| `src/widgets/layout/FeedbackButton.tsx` | 反馈按钮 + FeedbackModal |
| `src/widgets/layout/__tests__/Titlebar.test.tsx` | 平台分支测试 |
| `src/widgets/layout/__tests__/WindowControls.test.tsx` | 按钮交互测试 |
| `src/widgets/layout/__tests__/FeedbackButton.test.tsx` | 反馈流程测试 |
| `docs/superpowers/notes/2026-06-25-phase5-electron21-capturepage.md` | Electron 21 capturePage 可用性实验记录 |
| `docs/superpowers/plans/2026-06-25-phase5-custom-titlebar.md` | 本文件 |

### Modify（4 个）

| 文件 | 改动 |
| --- | --- |
| `src/widgets/layout/Layout.tsx` | 在 `<main>` 之上插入 `<Titlebar />`；Layout 不增加 `border-b` |
| `electron/main.ts` | `createMainWindow()` 追加 `titleBarStyle` 分支；注册 5 个 `ipcMain.handle` |
| `electron/preload.ts` | 暴露 `window.electronAPI.windowControls` |
| `src/shared/types/electron-api.d.ts` | `ElectronAPI` interface 增加 `windowControls` 字段 |

### 暂不改

- `package.json`（无新依赖）
- `vite.config.ts`、`tsconfig.json`（不需路径别名变更）

---

## Milestone Overview

| Milestone | 包含 Task | 验证手段 |
| --- | --- | --- |
| **M1** 平台检测与 IPC 契约 | 1, 2 | `npm test -- windowControlsClient` |
| **M2** 窗口控件按钮 | 3, 4 | `npm test -- WindowControls` |
| **M3** 反馈入口 | 5, 6 | `npm test -- FeedbackButton` |
| **M4** 标题栏组装 | 7, 8 | `npm test -- Titlebar` |
| **M5** Electron 集成 | 9, 10, 11 | `npm run electron:dev` 手测 + Playwright E2E |
| **M6** 覆盖率与回归 | 12, 13 | `npm run test:coverage` ≥ 83% |

---

## Task Breakdown

每个 Task 都包含 **Files / Interfaces / Steps / Commit**。Steps 是 2-5 分钟粒度可执行单元。

---

### Task 1 — 创建 WindowControlsBridge interface 与平台检测工具

**Files**

- Create: `/home/fz/project/sage/src/shared/api/windowControlsClient.ts`
- Create: `/home/fz/project/sage/src/shared/api/__tests__/windowControlsClient.test.ts`

**Interfaces**

- Consumes: 无（顶层工具）
- Produces:
  ```typescript
  export type Platform = 'macos' | 'windows' | 'linux' | 'web';
  export function detectPlatform(ua?: string): Platform;
  export function isElectronDesktop(platform: Platform): boolean;
  export interface WindowControlsBridge {
    minimize(): Promise<void>;
    toggleMaximize(): Promise<void>;
    close(): Promise<void>;
    capturePage(): Promise<string>; // base64 PNG, 不含 "data:image/png;base64," 前缀
    isMaximized(): Promise<boolean>;
  }
  export function createWebControlsBridge(): WindowControlsBridge;
  ```

**Steps**

1. **测试先行** — 在 `windowControlsClient.test.ts` 写 4 个 `describe`：
   - `detectPlatform`: macOS UA / Windows UA / Linux UA / 浏览器 fallback → 期望 `'macos' | 'windows' | 'linux' | 'web'`
   - `isElectronDesktop`: 4 个 platform 各自期望 true/false
   - `createWebControlsBridge`: 调用 `capturePage` 应 `reject(new Error('Not in desktop'))`；其他方法 `resolve()` / `resolve(false)`
   - **类型契约**: `WindowControlsBridge` 字段存在（用 `expectTypeOf` 或运行时 key 检查）
2. 运行 `npm test -- windowControlsClient` — 期望 RED
3. 实现 `windowControlsClient.ts`：
   - `detectPlatform(ua = typeof navigator !== 'undefined' ? navigator.userAgent : '')`
     - `/Macintosh|Mac OS X/i` → `'macos'`
     - `/Windows NT/i` → `'windows'`
     - `/Linux/i` → `'linux'`
     - else → `'web'`
   - `isElectronDesktop(p)` → `p === 'macos' || p === 'windows' || p === 'linux'`
   - `createWebControlsBridge()` 返回 5 个方法，`capturePage` reject
4. 运行 `npm test -- windowControlsClient` — 期望 GREEN
5. 重构：提取 `UA_PATTERNS` 常量；`detectPlatform` 切换为 `for...of` 表驱动

**Commit**

```bash
git add src/shared/api/windowControlsClient.ts src/shared/api/__tests__/windowControlsClient.test.ts
git commit -m "feat(phase5): add WindowControlsBridge interface and platform detection"
```

---

### Task 2 — 实现 Electron preload 桥接（ipcRenderer.invoke 委托）

**Files**

- Modify: `/home/fz/project/sage/electron/preload.ts`
- Modify: `/home/fz/project/sage/src/shared/types/electron-api.d.ts`

**Interfaces**

- Consumes: `WindowControlsBridge` from `shared/api/windowControlsClient`
- Produces: `window.electronAPI.windowControls: WindowControlsBridge`（在 renderer 端）

**Steps**

1. 在 `electron-api.d.ts` 给 `ElectronAPI` 加 `windowControls: WindowControlsBridge` 字段；import 类型用 `import('../api/windowControlsClient').WindowControlsBridge`（`type` 关键字）
2. 在 `preload.ts` 的 `electronAPI` 对象上增加 `windowControls`：
   - `minimize`: `ipcRenderer.invoke('sage:window-controls:minimize')`
   - `toggleMaximize`: `ipcRenderer.invoke('sage:window-controls:toggle-maximize')`
   - `close`: `ipcRenderer.invoke('sage:window-controls:close')`
   - `capturePage`: `ipcRenderer.invoke('sage:window-controls:capture-page') as Promise<string>`
   - `isMaximized`: `ipcRenderer.invoke('sage:window-controls:is-maximized') as Promise<boolean>`
3. 类型同步：preload 文件尾部 `export type ElectronAPI = typeof electronAPI` 自动继承新字段
4. 写最小 typecheck 验证：`npx tsc --noEmit`（不需要新测试 — 类型已覆盖）

**Commit**

```bash
git add electron/preload.ts src/shared/types/electron-api.d.ts
git commit -m "feat(phase5): expose windowControls bridge in preload"
```

---

### Task 3 — windowControlsClient 桥接函数（调用 window.electronAPI.windowControls）

**Files**

- Modify: `/home/fz/project/sage/src/shared/api/windowControlsClient.ts`
- Modify: `/home/fz/project/sage/src/shared/api/__tests__/windowControlsClient.test.ts`

**Interfaces**

- Consumes: `window.electronAPI.windowControls: WindowControlsBridge`
- Produces:
  ```typescript
  export function getWindowControlsBridge(): WindowControlsBridge | null;  // null 表示 WebUI
  export const windowControls: WindowControlsBridge;  // 单例（WebUI 模式是 stub）
  ```

**Steps**

1. **测试先行** — 在 `windowControlsClient.test.ts` 新增 `describe('getWindowControlsBridge')`：
   - 桩 `window.electronAPI.windowControls = mockBridge` → 返回该对象
   - 桩 `window.electronAPI = undefined` → 返回 `null`
   - 桩 `window.electronAPI.windowControls = undefined` → 返回 `null`
   - 桩 `navigator.userAgent = '...Linux...'` → `getWindowControlsBridge()` 在 `window.electronAPI` 存在时**仍**返回对象（renderer 不应该基于 UA 过滤，由调用方决定）
2. 运行测试 — 期望 RED
3. 实现 `getWindowControlsBridge()`：
   ```typescript
   export function getWindowControlsBridge(): WindowControlsBridge | null {
     if (typeof window === 'undefined') return null;
     return window.electronAPI?.windowControls ?? null;
   }
   ```
4. 导出单例 `windowControls`：
   ```typescript
   export const windowControls: WindowControlsBridge =
     typeof window !== 'undefined' && window.electronAPI?.windowControls
       ? window.electronAPI.windowControls
       : createWebControlsBridge();
   ```
5. 运行测试 — 期望 GREEN
6. **新加测试**: 验证 `windowControls` 在 mock electronAPI 下调用 `minimize` 会触发 mockBridge.minimize
7. **覆盖率确认**: `npm test -- windowControlsClient --coverage` — 期望 ≥ 90%

**Commit**

```bash
git add src/shared/api/windowControlsClient.ts src/shared/api/__tests__/windowControlsClient.test.ts
git commit -m "feat(phase5): wire windowControlsClient to electronAPI bridge"
```

---

### Task 4 — WindowControls 组件（Win/Linux 按钮）

**Files**

- Create: `/home/fz/project/sage/src/widgets/layout/WindowControls.tsx`
- Create: `/home/fz/project/sage/src/widgets/layout/__tests__/WindowControls.test.tsx`

**Interfaces**

- Consumes: `WindowControlsBridge` from `shared/api/windowControlsClient`；`useI18n()` from `shared/lib/i18n`
- Produces:
  ```typescript
  interface WindowControlsProps {
    bridge?: WindowControlsBridge;  // 注入便于测试；默认 windowControls 单例
  }
  export function WindowControls(props: WindowControlsProps): JSX.Element;
  ```

**Steps**

1. **测试先行** — 在 `WindowControls.test.tsx` 写 5 个 test：
   - 渲染 3 个按钮（minimize / maximize / close），各带 `aria-label`
   - 点击 minimize → 调用 `bridge.minimize`
   - 点击 maximize → 调用 `bridge.toggleMaximize`（**注意是 toggle，不是 maximize**）
   - 点击 close → 调用 `bridge.close`
   - IPC 失败（bridge.minimize 抛错）→ 按钮恢复可点击，**不抛错**到 UI（spy on `console.warn`）
2. 运行测试 — 期望 RED
3. 实现 `WindowControls.tsx`：
   - 从 `useI18n()` 拿 `t`
   - 从 i18n `zh.ts` / `en.ts` 加 3 个 key：`titlebar.minimize`、`titlebar.maximize`、`titlebar.close`
   - 用 `bridge = props.bridge ?? windowControls`
   - 每个按钮 onClick 包 try-catch（`bridge.minimize().catch((e) => console.warn(...))`）
   - 按钮样式：`flex gap-0` 容器；close 按钮 hover 红色背景（参考 AionUi 视觉）
4. 运行测试 — 期望 GREEN
5. 视觉：Tailwind 类 `hover:bg-bg-hover`、`hover:bg-red-600/90`（close）
6. a11y：`<button aria-label={t('titlebar.minimize')}>` 全部有

**Commit**

```bash
git add src/widgets/layout/WindowControls.tsx \
        src/widgets/layout/__tests__/WindowControls.test.tsx \
        src/shared/lib/i18n/zh.ts \
        src/shared/lib/i18n/en.ts
git commit -m "feat(phase5): add WindowControls component with i18n"
```

---

### Task 5 — FeedbackButton 组件（按钮 + FeedbackModal）

**Files**

- Create: `/home/fz/project/sage/src/widgets/layout/FeedbackButton.tsx`
- Create: `/home/fz/project/sage/src/widgets/layout/__tests__/FeedbackButton.test.tsx`

**Interfaces**

- Consumes: `WindowControlsBridge`；`useI18n()`
- Produces:
  ```typescript
  interface FeedbackButtonProps {
    bridge?: WindowControlsBridge;
  }
  interface FeedbackPayload {
    description: string;
    contact: string;
    screenshot: string;  // base64 PNG, 含 "data:image/png;base64," 前缀
    platform: Platform;
    userAgent: string;
    createdAt: number;
  }
  export function FeedbackButton(props: FeedbackButtonProps): JSX.Element;
  export function FeedbackModal(props: {  // 内部组件，单独 export 便于测试
    open: boolean;
    onClose: () => void;
    initialScreenshot: string | null;
    platform: Platform;
  }): JSX.Element;
  ```

**Steps**

1. **测试先行** — 在 `FeedbackButton.test.tsx` 写 6 个 test：
   - 渲染 1 个 `<button aria-label>`，文本 = `t('titlebar.feedback')`
   - 点击按钮 → FeedbackModal 打开（`<dialog open>` 出现）
   - FeedbackModal 中点击"截屏" → 调用 `bridge.capturePage` 一次；成功后 `<img src="data:image/png;base64,...">` 出现
   - FeedbackModal 中点击"截屏"但 `bridge.capturePage` 抛错 → 显示"截屏失败"红字提示，**不**关闭 modal
   - FeedbackModal 填写 description + 提交 → 触发 `console.log` 含 payload（spy on console.log），关闭 modal
   - FeedbackModal Esc 键 / 点击"取消" → 关闭 modal 且不提交
2. 运行测试 — 期望 RED
3. 实现 `FeedbackButton.tsx`：
   - 主组件：`<button onClick={open}>` + `<FeedbackModal>`
   - 状态：`open: boolean`、`screenshot: string | null`、`description: string`、`contact: string`
   - "截屏"按钮 → `bridge.capturePage().then(b64 => setScreenshot(\`data:image/png;base64,${b64}\`)).catch(...)`
   - 提交按钮 → `console.log({ description, contact, screenshot, platform: detectPlatform(), userAgent: navigator.userAgent, createdAt: Date.now() })` + close
   - 用原生 `<dialog>` + `dialog.showModal()` / `dialog.close()` 切换 open 状态
4. i18n keys: `titlebar.feedback`、`titlebar.feedback.title`、`titlebar.feedback.description`、`titlebar.feedback.contact`、`titlebar.feedback.screenshot`、`titlebar.feedback.capture`、`titlebar.feedback.submit`、`titlebar.feedback.cancel`、`titlebar.feedback.captureFailed`、`titlebar.feedback.submittedToast`
5. 运行测试 — 期望 GREEN
6. 视觉：modal 居中、遮罩、半透明、提交按钮 primary 色

**Commit**

```bash
git add src/widgets/layout/FeedbackButton.tsx \
        src/widgets/layout/__tests__/FeedbackButton.test.tsx \
        src/shared/lib/i18n/zh.ts \
        src/shared/lib/i18n/en.ts
git commit -m "feat(phase5): add FeedbackButton with screenshot capture"
```

---

### Task 6 — Titlebar 组件（总组装 + 平台分支）

**Files**

- Create: `/home/fz/project/sage/src/widgets/layout/Titlebar.tsx`
- Create: `/home/fz/project/sage/src/widgets/layout/__tests__/Titlebar.test.tsx`

**Interfaces**

- Consumes: `detectPlatform`、`isElectronDesktop`、`useI18n()`；`WindowControls`、`FeedbackButton`（同级 widgets）
- Produces:
  ```typescript
  interface TitlebarProps {
    title?: string;                    // 默认 "Sage"
    platform?: Platform;               // 注入便于测试；默认 detectPlatform()
    bridge?: WindowControlsBridge;     // 透传给子组件
  }
  export function Titlebar(props: TitlebarProps): JSX.Element;
  ```

**Steps**

1. **测试先行** — 在 `Titlebar.test.tsx` 写 6 个 test：
   - platform=`'macos'` → 渲染 1 个区域 + FeedbackButton，**不**渲染 WindowControls；高度类含 `h-7`
   - platform=`'windows'` → 渲染 3 个 WindowControls 按钮 + FeedbackButton；高度类含 `h-8`
   - platform=`'linux'` → 同 windows
   - platform=`'web'` → 渲染 FeedbackButton，**不**渲染 WindowControls；高度类含 `h-8`
   - 自定义 `title` → 渲染该文本
   - macOS 下点击标题栏**不**触发任何 IPC
2. 运行测试 — 期望 RED
3. 实现 `Titlebar.tsx`：
   - `const platform = props.platform ?? detectPlatform()`
   - 容器 `<header>` Tailwind: `drag-region flex items-center justify-between select-none border-b border-border bg-surface px-3`
     - 注意：`drag-region` 是 CSS class（在后续 Task 9 配合 `titleBarStyle: 'hidden'` 需要 `-webkit-app-region: drag`）
   - 左侧：`<div>{title}</div>` + 预留 `<Slot name="left-actions" />`（**注释说明** — 不实现 TitlebarActions）
   - 中间：空（占位）
   - 右侧：`<FeedbackButton bridge={bridge} />`
   - 右侧 macOS: 在 FeedbackButton 之前**不**插入 WindowControls；Win/Linux: 插入 `<WindowControls bridge={bridge} />`
   - 高度分支：`platform === 'macos' ? 'h-7' : 'h-8'`
4. 运行测试 — 期望 GREEN
5. macOS hiddenInset 兼容：左侧留 80px padding（`pl-[80px]`）预留原生交通灯位置

**Commit**

```bash
git add src/widgets/layout/Titlebar.tsx \
        src/widgets/layout/__tests__/Titlebar.test.tsx
git commit -m "feat(phase5): add Titlebar with platform-aware layout"
```

---

### Task 7 — Layout.tsx 插入 Titlebar

**Files**

- Modify: `/home/fz/project/sage/src/widgets/layout/Layout.tsx`

**Interfaces**

- Consumes: `<Titlebar />` from `./Titlebar`
- Produces: Layout 顶部出现 32px（或 28px mac）高的标题栏

**Steps**

1. **不写新组件测试** — Task 6 已覆盖 Titlebar。Layout 修改通过现有 E2E（如果有） + 手动 `npm run dev` 验证
2. 修改 `Layout.tsx`：
   - 在 `<main id="main-content">` 之前（外层 `<div className="flex h-screen">` 内）插入 `<Titlebar />` —— 但**注意**：当前 Layout 是 `flex h-screen`（row），Titlebar 应该作为**独立 row** 放在 `<aside>` / `<main>` 之前
   - 调整结构：
     ```tsx
     <div className="flex flex-col h-screen bg-bg">
       <Titlebar />
       <div className="flex flex-1 overflow-hidden">
         {/* 现有 aside + main 内容 */}
       </div>
     </div>
     ```
   - 删除原来 `h-screen` 的外层 div 改 `h-screen flex-col`（保持高度）
3. 验证：`npm test -- Layout` — 现有测试应继续通过（如果有）
4. 验证：`npm run dev` — 浏览器看到顶部出现 32px 高的标题栏（无窗口控件因为是 WebUI 模式）
5. 验证：`npm run electron:dev` — Win 上看到 3 个窗口按钮；mac 上不显示（待 Task 9 配 `titleBarStyle`）

**Commit**

```bash
git add src/widgets/layout/Layout.tsx
git commit -m "feat(phase5): insert Titlebar into Layout"
```

---

### Task 8 — Tailwind `drag-region` 工具类与样式

**Files**

- Modify: 项目的 Tailwind 配置（找到 `tailwind.config.{js,ts}`）
- Modify: 全局 CSS（找到 `src/index.css` 或 `src/app/styles.css`）

**Interfaces**

- Consumes: 无
- Produces: `.drag-region` 应用 `-webkit-app-region: drag`；`.no-drag` 应用 `-webkit-app-region: no-drag`

**Steps**

1. 检查 `tailwind.config.{js,ts}` 位置：`ls /home/fz/project/sage/tailwind.config.*`
2. 在 `tailwind.config.js` 的 `theme.extend` 中（如不存在则新增 `theme`）：
   ```javascript
   plugins: [],
   ```
   不需要新增 utility；直接用 CSS 自定义类
3. 在 `src/index.css`（或对应全局 CSS）追加：
   ```css
   .drag-region {
     -webkit-app-region: drag;
   }
   .no-drag,
   .no-drag * {
     -webkit-app-region: no-drag;
   }
   ```
4. 修改 `Titlebar.tsx` 容器类：把 `drag-region` 加上；同时 FeedbackButton / WindowControls 根容器加 `no-drag`（让按钮可点击）
5. 运行 `npm test -- Titlebar` — 验证测试仍通过（className 字符串变化不影响渲染断言）
6. 手动：在 `npm run electron:dev` 下点击标题栏**空白**区域应能拖动窗口；点击按钮**不会**触发拖动

**Commit**

```bash
git add tailwind.config.js src/index.css src/widgets/layout/Titlebar.tsx \
        src/widgets/layout/WindowControls.tsx src/widgets/layout/FeedbackButton.tsx
git commit -m "feat(phase5): add drag-region CSS for frameless window"
```

---

### Task 9 — Electron BrowserWindow 配 titleBarStyle

**Files**

- Modify: `/home/fz/project/sage/electron/main.ts`

**Interfaces**

- Consumes: `process.platform`
- Produces: `BrowserWindow({ titleBarStyle, frame, ... })` 按平台分支

**Steps**

1. 在 `createMainWindow()` 内修改 `BrowserWindow` 配置：
   ```typescript
   const platform = process.platform;
   mainWindow = new BrowserWindow({
     width: DEFAULT_WINDOW_WIDTH,
     height: DEFAULT_WINDOW_HEIGHT,
     minWidth: MIN_WINDOW_WIDTH,
     minHeight: MIN_WINDOW_HEIGHT,
     title: 'Sage',
     icon: join(__dirname, '..', 'build', 'icon.ico'),
     titleBarStyle: platform === 'darwin' ? 'hiddenInset' : 'hidden',
     frame: platform !== 'darwin' ? false : true,
     trafficLightPosition: platform === 'darwin' ? { x: 12, y: 8 } : undefined,
     webPreferences: {
       preload: join(__dirname, 'preload.js'),
       contextIsolation: true,
       nodeIntegration: false,
       sandbox: false,
     },
   });
   ```
2. 写 Electron 集成测试 — 留待 Task 10
3. **手动验证**：
   - macOS: `npm run electron:dev`（如可在 Mac 上跑） → 看到原生交通灯在左上，标题栏**不**显示
   - Win/Linux: 标题栏区域完全空白，WindowControls 在右侧显示
4. **平台分支已记录** — 在 `electron/main.ts` 顶部加注释解释

**Commit**

```bash
git add electron/main.ts
git commit -m "feat(phase5): configure titleBarStyle per platform"
```

---

### Task 10 — Electron main 进程注册 windowControls IPC handlers

**Files**

- Modify: `/home/fz/project/sage/electron/main.ts`
- Create: `/home/fz/project/sage/electron/__tests__/windowControls.test.ts`

**Interfaces**

- Consumes: `mainWindow: BrowserWindow | null`（模块级变量）
- Produces: 5 个 `ipcMain.handle` 处理器

**Steps**

1. **测试先行** — 在 `electron/__tests__/windowControls.test.ts` 写 3 个 test（用 `vi.mock('electron', ...)`）：
   - 桩 `mainWindow.minimize = vi.fn()` → 调用 handler 后 `mainWindow.minimize` 被调用
   - 桩 `mainWindow.isMaximized = vi.fn(() => true)` → handler 返回 `true`
   - 桩 `mainWindow.webContents.capturePage = vi.fn(() => Promise.resolve({ toPNG: () => Buffer.from('abc') }))` → handler 返回 `'abc'`
2. 运行测试 — 期望 RED（handlers 还没注册）
3. 在 `registerIpcHandlers()` 中追加：
   ```typescript
   ipcMain.handle('sage:window-controls:minimize', () => {
     mainWindow?.minimize();
   });
   ipcMain.handle('sage:window-controls:toggle-maximize', () => {
     if (!mainWindow) return;
     if (mainWindow.isMaximized()) mainWindow.unmaximize();
     else mainWindow.maximize();
   });
   ipcMain.handle('sage:window-controls:close', () => {
     mainWindow?.close();
   });
   ipcMain.handle('sage:window-controls:is-maximized', () => {
     return mainWindow?.isMaximized() ?? false;
   });
   ipcMain.handle('sage:window-controls:capture-page', async () => {
     if (!mainWindow) throw new Error('No main window');
     const image = await mainWindow.webContents.capturePage();
     return image.toPNG().toString('base64');
   });
   ```
4. **Electron 21 兼容性验证**（如果上述测试在 mock 环境下无法跑）— 走 **E2E 任务** Task 11
5. 运行测试 — 期望 GREEN
6. 写实验记录到 `docs/superpowers/notes/2026-06-25-phase5-electron21-capturepage.md`：
   - `webContents.capturePage()` 在 Electron 21.4.4 的 API 形态
   - 返回 `NativeImage`，用 `.toPNG()` 转 Buffer 再 `.toString('base64')`
   - 该 API 在 `BrowserWindow` 未 `ready-to-show` 时调用会失败 — 加 try-catch

**Commit**

```bash
git add electron/main.ts electron/__tests__/windowControls.test.ts \
        docs/superpowers/notes/2026-06-25-phase5-electron21-capturepage.md
git commit -m "feat(phase5): register windowControls IPC handlers in main process"
```

---

### Task 11 — E2E 测试（Playwright，Electron 启动）

**Files**

- Create: `/home/fz/project/sage/e2e/titlebar.spec.ts`（或 `tests/e2e/`，按项目现有约定）

**Interfaces**

- Consumes: Playwright `_electron.launch()`
- Produces: 3 个 E2E test

**Steps**

1. 找项目 E2E 目录：`find /home/fz/project/sage -type d -name 'e2e' -not -path '*/node_modules/*'`
2. 如不存在，创建 `e2e/` 目录，约定 Playwright + `_electron`
3. 写 3 个 test：
   - **最小化**: 启动 Electron，断言 WindowControls 3 按钮可见（`platform: 'win32'` 模拟可通过 `userAgent` 注入；Electron 端无法改 UA，**改用** `_electron.launch({ env: { ...process.env, SAGE_TEST_PLATFORM: 'win32' } })` 并在 main.ts 测试分支读取该 env —— **但**这违反"不加 env 测"原则。**替代方案**：用 `await electronApp.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length)` 验证窗口数；**不**测按钮可见性，测 IPC 是否注册（`electronApp.evaluate(({ ipcMain }) => Object.keys(ipcMain._invokeHandlers))`）
   - **IPC 注册**: `ipcMain` 5 个 `window-controls:*` handler 存在
   - **isMaximized**: 默认 `false`（窗口未最大化）
4. **注意**: E2E 不强求通过 CI（Electron 在 Linux CI 启动慢），但**写**出测试，标记 `test.skip` 在 CI 环境（参考 `process.env.CI`）
5. 手动跑一次：`npx playwright test e2e/titlebar.spec.ts`（本地有 Electron 环境）

**Commit**

```bash
git add e2e/titlebar.spec.ts
git commit -m "test(phase5): add E2E for window controls IPC registration"
```

---

### Task 12 — i18n 翻译完整性

**Files**

- Modify: `/home/fz/project/sage/src/shared/lib/i18n/zh.ts`
- Modify: `/home/fz/project/sage/src/shared/lib/i18n/en.ts`
- Modify: `/home/fz/project/sage/src/shared/lib/i18n/index.tsx`（如需新增 TranslationKey）

**Interfaces**

- Consumes: `TranslationKey` 联合类型
- Produces: 13 个新 key × 2 语言 = 26 个翻译条目

**Steps**

1. 在 `zh.ts` 和 `en.ts` 中追加：
   - `titlebar.minimize`: `'最小化'` / `'Minimize'`
   - `titlebar.maximize`: `'最大化'` / `'Maximize'`
   - `titlebar.close`: `'关闭'` / `'Close'`
   - `titlebar.feedback`: `'反馈'` / `'Feedback'`
   - `titlebar.feedback.title`: `'提交反馈'` / `'Send Feedback'`
   - `titlebar.feedback.description`: `'问题描述'` / `'Describe the issue'`
   - `titlebar.feedback.contact`: `'联系方式（可选）'` / `'Contact (optional)'`
   - `titlebar.feedback.screenshot`: `'附上截图'` / `'Attach screenshot'`
   - `titlebar.feedback.capture`: `'截屏'` / `'Capture'`
   - `titlebar.feedback.submit`: `'提交'` / `'Submit'`
   - `titlebar.feedback.cancel`: `'取消'` / `'Cancel'`
   - `titlebar.feedback.captureFailed`: `'截屏失败'` / `'Screenshot failed'`
   - `titlebar.feedback.submittedToast`: `'已收到（演示模式）'` / `'Received (demo mode)'`
2. 如 `TranslationKey` 是 union，在 `zh.ts` 中用 `as const` + `export type TranslationKey = typeof zh[keyof typeof zh]`，新增 key 后 TS 会自动扩展类型
3. 验证：`npx tsc --noEmit` 0 错

**Commit**

```bash
git add src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts
git commit -m "feat(phase5): add titlebar i18n keys (zh/en)"
```

---

### Task 13 — 全量测试 + 覆盖率 + 回归

**Files**

- Modify: 视结果而定

**Steps**

1. 运行 `npm test -- --run` — 所有测试通过
2. 运行 `npm run test:coverage`（或 `vitest run --coverage`）— 整体 ≥ 83%；`windowControlsClient.ts` ≥ 90%
3. 若覆盖率不达标：定位未覆盖分支，加测试（**不**改实现）
4. **回归测试**：
   - `npm test` 全通过
   - `npm run build` 成功（**警告** Electron preload 改 TS 路径需 build 出 `preload.js`）
   - `npx tsc --noEmit` 0 错
5. **手动冒烟**：
   - `npm run dev`（WebUI 模式）：看到 Titlebar 32px 高，FeedbackButton 可见，**不**显示 WindowControls
   - `npm run electron:dev`（Electron 模式）：Win 上看到 3 个窗口按钮可点击最小化/最大化/关闭；mac 上保持原生外观
6. **修复发现的任何 regression** — 不在此计划范围内实现新功能

**Commit**（若无修改则跳过）

```bash
git add -A  # 仅在修改了文件时
git commit -m "test(phase5): achieve coverage targets and fix regressions"
```

---

## Risk & Mitigation

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| `webContents.capturePage()` 在 Electron 21 实际行为与文档不符 | 高 | Task 10 写实验记录；Task 13 手动验证 |
| `frame: false` + `drag-region` 在 macOS 失效 | 中 | macOS 用 `hiddenInset` 不设 `frame: false`；拖动用 `-webkit-app-region: drag` |
| 反馈提交 console.log 污染生产控制台 | 低 | 在生产构建时用 Vite 的 `import.meta.env.DEV` 包裹（**可选**，Phase 5 范围内接受） |
| 原生 `<dialog>` 浏览器兼容（WebUI） | 低 | 项目用现代浏览器，`<dialog>` 自 2022 年 Chrome / Safari / Firefox 全支持 |
| 现有 Layout 测试可能依赖具体结构 | 中 | Task 7 验证现有测试不破；如破了，重构测试而非实现 |
| Phase 1 TitlebarActions 后续插入位置 | 低 | Task 6 在 Titlebar 中预留 `<Slot name="left-actions" />` 注释 |

---

## Out of Scope

- 真实反馈上报接口（HTTP / GitHub Issues / Sentry） — Phase 6+ 再做
- 标题栏主题色（始终 bg-surface）— Phase 6+ 主题
- 自定义标题栏高度 / 字号 — 暂用 32px / 28px
- 标题栏右键菜单（maximize / minimize 等）— 后续
- 多窗口（Phase 1 注释里提到 `getAllWindows` 但本计划仍单窗口）

---

## Verification Checklist

- [ ] `npm test -- --run` 全通过
- [ ] `npm run test:coverage` 整体 ≥ 83%；`windowControlsClient.ts` ≥ 90%
- [ ] `npx tsc --noEmit` 0 错
- [ ] `npm run build` 成功
- [ ] `npm run dev`（WebUI）下看到简化版 Titlebar
- [ ] `npm run electron:dev`（Electron）下 Win 上 3 按钮可点击
- [ ] macOS 平台 `hiddenInset` 配置已写（实际 mac 测试可在合并前由用户跑）
- [ ] 反馈提交时 `console.log` 打印完整 payload
- [ ] 所有 widget 测试覆盖 4 个 platform 分支
- [ ] 不破坏现有 Layout / Sidebar / 其他 widget 测试
- [ ] docs/superpowers/notes/2026-06-25-phase5-electron21-capturepage.md 已写

---

## 后续 Phase 衔接

- **Phase 6** @文件 / /btw：可复用 `<Slot name="left-actions" />` 注入 ChatInput
- **Phase 7** 欢迎屏：FeedbackButton 在 QuickActionBar 中可复用
- **Phase 1** 导航历史栈：TitlebarActions 后续在 Titlebar 的 left-actions 槽位实现
