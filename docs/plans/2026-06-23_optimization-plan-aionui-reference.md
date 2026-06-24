# 2026-06-23 Sage 优化方案（参考 AionUi）

## 背景与目标

[AionUi](file:///home/fz/project/AionUi) 是一个成熟的开源 Electron + React 桌面 AI 助手平台（Apache-2.0），采用 Bun + electron-vite + Arco Design + UnoCSS，支持桌面/Web/Mobile 多端部署。它在错误监控、IPC 抽象、主题系统、构建优化等方面有明显优势。

本方案基于 AionUi 的成熟模式，针对 sage 项目当前短板提出 **10 项优化**，按优先级分为 3 个阶段。

### 当前状态

| 维度 | Sage 现状 | AionUi 对标 |
|------|-----------|-------------|
| 错误监控 | 无 | Sentry（main + preload + renderer 三端） |
| IPC 抽象 | 散乱调用，无统一层 | 1900 行 typed ipcBridge.ts |
| 主进程 | 346 行单体文件 | 30+ 模块，职责分离 |
| 后端故障 | `app.quit()` | 恢复对话框 + 诊断信息 |
| 状态管理 | 单一 Zustand store | 7 个 React Context + SWR |
| 消息列表 | 全量渲染 | react-virtuoso 虚拟滚动 |
| 主题系统 | 仅 light/dark | 任意主题 ID + 字体缩放 |
| 构建配置 | 48 行基础 Vite | 340 行 electron-vite + Sentry + 自定义插件 |
| 国际化 | 无 | i18next + 10 语言 + 类型生成 |
| 单实例 | 无 | `requestSingleInstanceLock()` + deep link |

---

## 阶段 1：关键基础设施（P0，预计 2 周）

### 1.1 Sentry 错误监控

**问题**：sage 没有任何错误追踪，生产环境崩溃无法诊断。

**方案**：

```
electron/
├── sentry.ts          # 新建：main 进程 Sentry 初始化
├── preload.ts         # 修改：加入 '@sentry/electron/preload'
src/
├── main.tsx           # 修改：renderer Sentry 初始化 + beforeSend 过滤
```

**关键实现**：
- 三端初始化（main → preload → renderer）
- `beforeSend` 过滤后端 fetch 噪声（健康检查轮询等）
- `define` 注入 `SENTRY_DSN` 和 `__APP_VERSION__`
- 生产环境 hidden source maps + Sentry upload

**依赖**：`@sentry/electron`

**验收**：
- [ ] main 进程 uncaughtException 上报 Sentry
- [ ] renderer 未捕获异常上报 Sentry
- [ ] 后端健康检查错误被过滤
- [ ] source maps 上传成功

---

### 1.2 IPC 抽象层

**问题**：IPC 调用散落在各文件中，无类型安全，无统一错误处理。

**方案**：新建 `src/shared/lib/ipcBridge.ts`

```typescript
// 设计思路（参考 AionUi 的 ipcBridge.ts）
interface IpcBridge {
  // 同步调用
  invoke<T, P = void>(command: string, params?: P): Promise<T>
  // 事件订阅
  subscribe<T>(event: string, handler: (data: T) => void): () => void
  // 流式事件
  subscribeStream(streamId: string): AsyncIterable<StreamEvent>
}

// 按领域组织
export const bridge = {
  session: { list, get, create, delete },
  settings: { get, set, getAll },
  agents: { list, get, create, update, delete },
  skills: { list, install, uninstall },
  knowledge: { list, add, remove, search },
  chat: { send, createStream, cancelStream },
}
```

**关键设计**：
- 类型安全：每个方法有完整泛型
- 响应映射：raw API → frontend type 转换
- 错误处理：统一 try/catch + 错误分类
- Stub 模式：Web 模式下 native 功能优雅降级

**验收**：
- [ ] 所有现有 IPC 调用迁移到 bridge
- [ ] TypeScript 类型覆盖 100%
- [ ] 错误处理统一

---

### 1.3 主进程模块化

**问题**：`electron/main.ts` 346 行单体文件，职责混杂。

**方案**：拆分为独立模块

```
electron/
├── main.ts                    # 精简为 ~100 行：仅编排启动流程
├── sentry.ts                  # Sentry 初始化
├── chromium.ts                # configureChromium() — GPU/沙箱/V8 参数
├── backend.ts                 # spawnBackend() + waitForBackend() + killBackend()
├── window.ts                  # createWindow() + bounds 持久化
├── ipc.ts                     # registerIpcHandlers()
├── tray.ts                    # 系统托盘管理（可选，Phase 2）
├── deepLink.ts                # deep link 协议处理（可选，Phase 2）
├── lifecycle.ts               # 单实例锁 + app ready/before-quit
└── logger.ts                  # 已有，保持
```

**关键设计**：
- `main.ts` 只负责编排：`initSentry() → configureChromium() → acquireSingleInstanceLock() → startBackend() → createWindow() → registerIpc()`
- 每个模块导出一个纯函数，接收依赖、返回清理函数
- 后端生命周期封装为 `BackendManager` 类（spawn/health/kill）

**验收**：
- [ ] `main.ts` < 100 行
- [ ] 每个模块可独立测试
- [ ] 功能无回归

---

### 1.4 后端故障恢复 UI

**问题**：后端启动失败时直接 `app.quit()`，用户无法诊断。

**方案**：

```typescript
// main.ts
const backendResult = await startBackend()
if (!backendResult.success) {
  // 不再 app.quit()，而是发送事件给 renderer
  mainWindow.loadFile('backend-error.html')
  // 或通过 IPC 传递错误详情
}
```

```tsx
// src/pages/BackendError.tsx
// 显示：
// 1. 错误原因（端口占用 / Python 未安装 / conda 环境缺失）
// 2. 诊断信息（backend.log 最后 20 行）
// 3. 操作按钮：重试 / 打开日志 / 复制错误信息
```

**验收**：
- [ ] 后端失败不直接退出
- [ ] 显示可读的错误信息
- [ ] 提供重试按钮

---

## 阶段 2：用户体验提升（P1，预计 3 周）

### 2.1 虚拟滚动消息列表

**问题**：长对话全量渲染，性能随消息数线性下降。

**方案**：引入 `react-virtuoso`

```tsx
// src/widgets/chat/MessageList.tsx
import { Virtuoso } from 'react-virtuoso'

export function MessageList({ messages }: Props) {
  return (
    <Virtuoso
      data={messages}
      itemContent={(index, message) => <Message message={message} />}
      followOutput="smooth"
      firstItemIndex={0}
      increaseViewportBy={{ top: 600, bottom: 600 }}
    />
  )
}
```

**关键考虑**：
- `followOutput="smooth"` 自动跟随最新消息
- `increaseViewportBy` 预渲染上下各 600px
- 动态高度消息（代码块、图片）需要 `defaultItemHeight` 或让 Virtuoso 自动测量
- 流式消息更新需要触发 Virtuoso 重新测量

**依赖**：`react-virtuoso`

**验收**：
- [ ] 1000 条消息滚动流畅（60fps）
- [ ] 自动滚动到底部
- [ ] 流式消息正常渲染

---

### 2.2 状态管理重构

**问题**：单一 Zustand store 混合了所有状态，手动 Map 缓存。

**方案**：

```
src/
├── entities/
│   ├── session/
│   │   ├── SessionContext.tsx     # 会话上下文
│   │   ├── useSession.ts          # 会话 hooks
│   │   └── sessionApi.ts          # 会话 API（SWR）
│   ├── settings/
│   │   ├── SettingsContext.tsx
│   │   └── useSettings.ts
│   └── theme/
│       ├── ThemeContext.tsx
│       └── useTheme.ts
├── features/
│   └── send-message/
│       └── useChat.ts             # 保留，但改用 SWR 缓存
```

**关键变化**：
- Zustand → React Context（UI 状态）+ SWR（服务端状态）
- 手动 `messageCache` Map → SWR 自动缓存/重验证
- `useSession()`、`useSettings()`、`useTheme()` 各自独立
- 保留 Zustand 做最小全局状态（当前活跃 sessionId）

**验收**：
- [ ] 状态按领域分离
- [ ] SWR 替代手动缓存
- [ ] 功能无回归

---

### 2.3 主题系统增强

**问题**：仅支持 light/dark，无字体缩放，无自定义主题。

**方案**（参考 AionUi 的 ThemeContext）：

```typescript
// src/entities/theme/ThemeContext.tsx
interface ThemeState {
  appearance: 'light' | 'dark' | 'auto'
  themeId: string           // 支持任意主题 ID
  fontScale: number         // 全局字体缩放 0.8 ~ 1.4
  accentColor: string       // 强调色
}

// 预设主题
const THEMES = {
  default: { name: '默认', appearance: 'light' | 'dark' },
  ocean: { name: '海洋', appearance: 'light' | 'dark' },
  forest: { name: '森林', appearance: 'light' | 'dark' },
}
```

**CSS 变量扩展**：
```css
/* 每个主题独立文件 */
[data-theme='ocean'][data-appearance='dark'] {
  --color-primary: 200 80% 60%;
  --color-bg: 220 20% 10%;
  /* ... */
}
```

**验收**：
- [ ] 至少 3 个预设主题
- [ ] 字体缩放 0.8 ~ 1.4
- [ ] 主题选择持久化

---

### 2.4 单实例锁 + Deep Link

**问题**：可启动多个实例，无协议注册。

**方案**：

```typescript
// electron/lifecycle.ts
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
  return
}
app.on('second-instance', (_, commandLine) => {
  // 聚焦已有窗口
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  }
  // 处理 deep link
  const url = commandLine.pop()
  if (url) handleDeepLink(url)
})

// 注册协议
app.setAsDefaultProtocolClient('sage')
```

**验收**：
- [ ] 第二次启动聚焦已有窗口
- [ ] `sage://` 协议可打开应用

---

## 阶段 3：工程化增强（P2，预计 2 周）

### 3.1 构建配置升级

**问题**：48 行基础配置，缺少 source maps、`define`、`optimizeDeps`。

**方案**：

```typescript
// vite.config.ts 增强
export default defineConfig({
  base: './',
  build: {
    target: 'es2022',           // 从 es2020 升级
    sourcemap: 'hidden',        // 生产 source maps（Sentry 用）
    reportCompressedSize: false, // 加速构建
    cssCodeSplit: true,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: { /* 保持现有 */ },
      },
    },
  },
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BUILD_DATE__: JSON.stringify(new Date().toISOString()),
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'zustand'],
    exclude: ['@sentry/electron'],
  },
  plugins: [
    react(),
    sentryVitePlugin({ /* ... */ }),
  ],
})
```

**验收**：
- [ ] `__APP_VERSION__` 在代码中可用
- [ ] 生产 source maps 生成
- [ ] 构建速度提升 ≥ 10%

---

### 3.2 国际化基础

**问题**：无任何国际化支持。

**方案**（参考 AionUi 的 i18n 架构）：

```
src/
├── shared/
│   └── i18n/
│       ├── index.ts           # i18next 初始化
│       ├── locales/
│       │   ├── zh-CN/
│       │   │   ├── common.json
│       │   │   ├── chat.json
│       │   │   └── settings.json
│       │   └── en-US/
│       │       ├── common.json
│       │       ├── chat.json
│       │       └── settings.json
│       └── types.d.ts         # 自动生成的 key 类型
```

**关键设计**：
- 按领域分 JSON 文件（common/chat/settings/agents/skills/memory）
- 自动生成 TypeScript 类型（防拼写错误）
- 系统语言检测 + 手动切换
- 设置页加语言选择器

**依赖**：`i18next`、`react-i18next`

**验收**：
- [ ] 中英文切换正常
- [ ] 所有 UI 文本国际化
- [ ] 类型安全

---

### 3.3 基础组件库

**问题**：使用 Headless UI 但无封装，各处重复实现 modal/select/scroll。

**方案**：

```
src/shared/ui/
├── BaseModal.tsx          # 统一模态框（参考 AionUi 的 AionModal）
├── BaseSelect.tsx         # 统一下拉选择
├── BaseScrollArea.tsx     # 统一滚动区域
├── BaseCollapse.tsx       # 统一折叠面板
├── LoadingSkeleton.tsx    # 加载骨架屏
├── ErrorBoundary.tsx      # 错误边界
├── EmptyState.tsx         # 空状态组件
└── index.ts               # 统一导出
```

**验收**：
- [ ] 至少 5 个基础组件
- [ ] 现有页面使用基础组件
- [ ] 统一视觉风格

---

## 实施优先级矩阵

```
         高影响
           │
  1.1 Sentry ──┐
  1.2 IPC 抽象 ─┤
  1.3 主进程拆分┤
  2.1 虚拟滚动 ─┤
           │    │
 ──────────┼────┼────────── 低 effort → 高 effort
           │    │
  1.4 后端故障UI┤
  2.4 单实例锁 ─┤
  3.1 构建升级 ─┤
  2.3 主题增强 ─┤
  2.2 状态重构 ─┤
  3.3 基础组件 ─┤
  3.2 国际化   ─┘
           │
         低影响
```

**推荐执行顺序**：

| 优先级 | 优化项 | 预计时间 | 风险 |
|--------|--------|----------|------|
| P0-1 | 1.1 Sentry 错误监控 | 2 天 | 低 |
| P0-2 | 1.4 后端故障恢复 UI | 1 天 | 低 |
| P0-3 | 1.3 主进程模块化 | 3 天 | 中（重构风险） |
| P0-4 | 2.4 单实例锁 + Deep Link | 1 天 | 低 |
| P1-1 | 2.1 虚拟滚动 | 2 天 | 中（流式消息兼容） |
| P1-2 | 3.1 构建配置升级 | 2 天 | 低 |
| P1-3 | 1.2 IPC 抽象层 | 5 天 | 高（大范围迁移） |
| P1-4 | 2.3 主题系统增强 | 3 天 | 低 |
| P2-1 | 2.2 状态管理重构 | 5 天 | 高（大范围重构） |
| P2-2 | 3.3 基础组件库 | 3 天 | 低 |
| P2-3 | 3.2 国际化基础 | 5 天 | 中 |

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| IPC 抽象层迁移范围大 | 可能引入回归 | 分模块迁移，每个模块独立 PR |
| 状态管理重构 | 全局影响 | 先写 E2E 测试保底，再重构 |
| 虚拟滚动 + 流式消息 | 兼容性问题 | 先在 develop 分支验证 |
| Sentry 误报太多 | 噪声淹没真实问题 | `beforeSend` 精细过滤 |
| Win7 兼容性 | Electron 21 + Sentry 可能不兼容 | 测试 Sentry SDK 版本兼容性 |

---

## 依赖清单

| 包 | 用途 | 阶段 |
|----|------|------|
| `@sentry/electron` | 错误监控 | P0 |
| `react-virtuoso` | 虚拟滚动 | P1 |
| `i18next` | 国际化 | P2 |
| `react-i18next` | React 国际化绑定 | P2 |

---

## 涉及的文件与模块

### 新建文件
- `electron/sentry.ts`
- `electron/chromium.ts`
- `electron/backend.ts`
- `electron/window.ts`
- `electron/ipc.ts`
- `electron/lifecycle.ts`
- `src/shared/lib/ipcBridge.ts`
- `src/shared/i18n/`
- `src/shared/ui/`（多个基础组件）
- `src/entities/theme/ThemeContext.tsx`
- `src/pages/BackendError.tsx`

### 修改文件
- `electron/main.ts`（大幅精简）
- `electron/preload.ts`（加 Sentry）
- `src/main.tsx`（加 Sentry、i18n、后端故障检测）
- `src/App.tsx`（lazy loading、readiness gate）
- `src/shared/lib/store.ts`（拆分）
- `src/widgets/chat/MessageList.tsx`（虚拟滚动）
- `vite.config.ts`（全面升级）
- `src/index.css`（主题扩展）

---

## 与现有计划的关系

- 本方案与 `2026-06-23_real-time-streaming-ui.md` 不冲突，虚拟滚动需在流式 UI 稳定后实施
- IPC 抽象层需在 MCP 生命周期计划（`docs/technical/`）之后实施，避免重复设计
- Sentry 可与任何计划并行实施
