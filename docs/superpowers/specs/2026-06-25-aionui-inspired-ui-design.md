# Sage AionUi 借鉴方案 — 设计文档

**日期：** 2026-06-25
**作者：** Claude (brainstorming 流程产出)
**状态：** 待用户审阅

## 1. 背景与目标

参考 `/home/fz/project/AionUi` 的桌面 AI 应用设计实践，针对 sage 项目（Electron + React + FastAPI）提出 UI/UX 借鉴方案。

调研发现 sage 与 AionUi 架构高度相似（均为 FSD：app/entities/features/pages/shared/widgets），因此借鉴成本低。sage 已有 6 套主题预设、slash 命令、命令面板、虚拟列表、Shiki 高亮、i18n 基础设施，但缺少：

1. 自定义 CSS 主题编辑器（AionUi 差异化亮点）
2. 可拖拽侧边栏（AionUi 高频交互）
3. 导航历史栈（AionUi 浏览器化体验）
4. 自定义标题栏 + 反馈入口
5. /btw 补充消息面板、@文件提及

目标：在不破坏 sage 现有 FSD 架构的前提下，分 6 个 Phase 引入上述特性。

## 2. 范围

**包含：**
- 4 大主题域全面借鉴：主题与个性化、侧边栏与会话组织、交互与微交互、导航与应用框架
- 借鉴深度：先分析设计理念 + 选择性适配（保留 sage 现有技术栈：Tailwind + 自建组件 + Zustand）

**不包含：**
- 不引入 Arco Design 组件库（sage 用自建 + Radix UI）
- 不切换 UnoCSS（sage 用 Tailwind）
- 不引入 MCP / ACP 协议（sage 自有 agent 系统）
- 不重写现有 6 套主题预设

## 3. 总体架构

```
App 层（providers/）
├── ThemeProvider（现有，扩展支持 CSS 主题）
├── LayoutProvider（Phase 2 新建）
├── NavHistoryProvider（Phase 1 新建）
└── TitlebarProvider（Phase 5 新建）

Widgets 层
├── Titlebar（Phase 5 新建）
├── Sidebar（Phase 2 增强拖拽）
├── ThemeEditor（Phase 3 新建）
└── ChatInput（Phase 6 增强 @/btw）

Entities 层
├── theme/（扩展：storage 增加 css 字段）
├── layout/（Phase 2 新建）
├── nav-history/（Phase 1 新建）
└── chat/btwState/（Phase 6 新建）

Shared 层
├── lib/i18n/（现有）
├── lib/dnd/（Phase 2 新建：dnd-kit 封装）
└── lib/codemirror-config/（Phase 3 新建）

Backend（Python）
└── api/theme_router.py（Phase 3 新增：CSS 主题 CRUD）
```

### 核心架构原则

| 原则 | 落地方式 |
|---|---|
| 隔离性 | 每个 Phase 引入独立 Provider/Context，互不耦合 |
| 复用 sage 模式 | Phase 1 沿用 useTheme Context；Phase 2 沿用 useResizableSidebar Hook |
| 可测试性 | 每个 Provider/Context 都有单元测试；关键组件有 Vitest 组件测试 |
| 类型安全 | 所有 Context 用 TypeScript 显式类型，禁用 `any` |

### 引入的依赖

| 依赖 | Phase | 体积 |
|---|---|---|
| `@dnd-kit/core` + `@dnd-kit/sortable` + `@dnd-kit/utilities` | Phase 2 | ~30 KB gzip |
| `@uiw/react-codemirror` + `@codemirror/lang-css` | Phase 3 | ~150 KB gzip |

## 4. 实施阶段

### Phase 1 — 导航历史栈（成本最低，先建立架构基础）

**新增文件：**
- `src/app/providers/NavHistoryProvider.tsx` — Context + Provider
- `src/shared/lib/useNavigationHistory.ts` — Hook 封装
- `src/widgets/layout/TitlebarActions.tsx` — 标题栏前进/后退按钮

**修改文件：**
- `src/App.tsx` — 插入 NavHistoryProvider
- `src/widgets/layout/Layout.tsx` — 增加前进/后退按钮插槽

**数据流：**
```
React Router location 变化
    ↓
NavHistoryProvider useEffect
    ├─ skipNextRef 检查（避免循环）
    ├─ 跳过 navigate({replace:true})
    ├─ 裁剪 forward 栈（浏览器语义）
    ├─ 压入新 entry { path }
    └─ 超过 MAX_HISTORY=50 时裁剪最早

用户点击 back/forward
    ↓
back() / forward()
    ├─ 移动 cursor
    ├─ skipNextRef = true
    └─ navigate(target.path, { replace: true })
```

**核心类型：**
```typescript
type HistoryEntry = { path: string };
interface NavHistoryContextValue {
  canBack: boolean;
  canForward: boolean;
  back: () => void;
  forward: () => void;
}
```

**存储：** 仅内存（不持久化）。

---

### Phase 2 — 拖拽侧边栏

**新增文件：**
- `src/shared/lib/dnd/sortableItem.ts` — `<SortableSessionItem>` 封装
- `src/shared/lib/dnd/useStoredSiderOrder.ts` — 排序状态读取/写入/调和
- `src/widgets/session/SortableSessionList.tsx` — DnD 包装层

**修改文件：**
- `src/widgets/session/SessionItem.tsx` — 拖拽手柄 + useSortable
- `src/widgets/session/VirtualSessionList.tsx` — 与虚拟列表协同
- `package.json` — 新增 `@dnd-kit/*` 依赖

**数据流：**
```
初始化:
  readStoredSiderOrder(storageKey) → localStorage
  reconcileStoredSiderOrder(prev, items)
    ├─ 保留 prev 中仍存在的 id
    ├─ 追加新增的 id 到末尾
    └─ 移除已删除的 id

拖拽过程:
  PointerSensor (8px 阈值) → useSortable → DragOverlay → 释放
  handleDragEnd → arrayMove → setStoredOrder → writeStoredSiderOrder
```

**存储键：** `sage:sider:order:v1`

**依赖：** `@dnd-kit/core`、`@dnd-kit/sortable`、`@dnd-kit/utilities`

---

### Phase 3 — 自定义 CSS 主题编辑器（核心差异化）

**新增文件：**
- `src/features/theme/CodeMirrorThemeEditor.tsx` — CodeMirror 6 + CSS 语言
- `src/features/theme/CssThemeModal.tsx` — 编辑器 + 名称 + 封面 + 保存
- `src/features/theme/backgroundInjector.ts` — 封面图注入工具
- `src/features/theme/themeCssValidator.ts` — 白名单校验
- `src/shared/api/themeCssClient.ts` — IPC 客户端
- `backend/api/theme_router.py` — `/api/theme/save|list|delete|get`

**修改文件：**
- `src/entities/theme/storage.ts` — `ThemePreset` 增加 `css?: string`、`cover?: string`
- `src/entities/theme/presets.ts` — 内置主题增加 `cover` 字段
- `src/pages/settings/ThemeSelector.tsx` — 增加"新建自定义"按钮
- `package.json` — 新增 `@uiw/react-codemirror`、`@codemirror/lang-css`

**数据流：**
```
编辑时:
  CodeMirror onChange → themeCssValidator(css) → 白名单检查
  通过 → 解析 CSS → setProperty(--name, value) → 预览即时生效

保存时:
  handleSave → themeCssClient.save(payload) → IPC → backend
  → 写入 data/themes/<id>.json → registerCssTheme

启动加载:
  ThemeProvider 初始化 → themeCssClient.list() → 注入 <style id="theme-{id}">
```

**核心 IPC 接口：**
```typescript
interface ThemeCssBridge {
  save(payload: ThemeCssPayload): Promise<{ id: string }>;
  list(): Promise<ThemeCssPayload[]>;
  delete(id: string): Promise<void>;
  get(id: string): Promise<ThemeCssPayload | null>;
}

interface ThemeCssPayload {
  id: string;
  name: string;
  cover?: string;
  css: string;
  appearance: 'light' | 'dark';
  created_at: number;
  updated_at: number;
}
```

**存储：** 后端 `data/themes/<id>.json`，单文件 1-10 KB。

**安全约束（关键）：** 仅允许 16 个白名单变量，禁止 `@import`、`expression()`、`url()` 外链。

---

### Phase 4 — 装饰性主题扩展

**新增文件：**
- `src/entities/theme/decorative-presets.ts` — 5 套主题
- `assets/themes/covers/*.svg` — 5 张封面图
- `src/features/theme/ThemeGallery.tsx` — 网格画廊视图

**修改文件：**
- `src/pages/settings/ThemeSelector.tsx` — 列表 → Gallery 升级
- `src/shared/lib/i18n/zh.ts`、`en.ts` — 主题名翻译

**主题集合：**
1. 薄荷蓝（Mint Blue）
2. 樱花粉（Sakura）
3. Cyber Neon
4. 深夜琥珀（Midnight Amber）
5. 羊皮纸（Parchment）

---

### Phase 5 — 自定义标题栏

**新增文件：**
- `src/widgets/layout/Titlebar.tsx` — 完整自定义标题栏
- `src/widgets/layout/WindowControls.tsx` — Windows/Linux 窗口按钮
- `src/widgets/layout/FeedbackButton.tsx` — 反馈按钮 + 自动截图
- `src/shared/api/windowControlsClient.ts` — IPC 客户端

**修改文件：**
- `src/App.tsx` — 移除默认 OS 标题栏
- `src/widgets/layout/Layout.tsx` — 用新 Titlebar 替换
- `electron/` 配置 — `titleBarStyle: 'hidden'`

**数据流：**
```
macOS: titleBarStyle='hiddenInset' → 保留原生交通灯 + 自定义区域
Windows/Linux: titleBarStyle='hidden', frame=false → 完全自定义

WindowControls:
  minimize → IPC → Electron main
  maximize → IPC → toggleMaximize
  close → IPC → close

FeedbackButton:
  capturePage → base64 PNG → FeedbackModal → 用户输入 → 提交
```

**核心 IPC 接口：**
```typescript
interface WindowControlsBridge {
  minimize(): void;
  toggleMaximize(): void;
  close(): void;
  capturePage(): Promise<string>;
  isMaximized(): Promise<boolean>;
}
```

---

### Phase 6 — @文件提及 + /btw 面板（Stretch）

**新增文件：**
- `src/features/chat/AtFileMenu.tsx` — @ 触发文件选择器
- `src/features/chat/useAtFileQuery.ts` — 提取 @xxx 模式
- `src/features/chat/BtwOverlay.tsx` — btw 浮层面板
- `src/features/chat/useBtwCommand.ts` — /btw 状态机
- `src/shared/api/fileSearchClient.ts` — 文件搜索 IPC
- `src/entities/chat/btwState.ts` — Zustand store

**修改文件：**
- `src/widgets/chat/ChatInput.tsx` — 监听 @ + /btw 前缀
- `src/widgets/chat/MessageList.tsx` — 挂载 BtwOverlay
- `src/features/send-message/index.ts` — 增加 btw 字段

**BtwOverlay 状态机：**
```
idle ──open()──▶ loading ──success──▶ answered
                    │                    │
                    ├──error──▶ error    │
                    │                    │
                    └──任何状态────Esc──▶ idle
```

**核心状态（Zustand）：**
```typescript
interface BtwState {
  isOpen: boolean;
  question: string;
  answer: string;
  isLoading: boolean;
  parentTaskRunning: boolean;
  open: (question: string) => void;
  close: () => void;
  appendDelta: (delta: string) => void;
  setLoading: (v: boolean) => void;
}
```

## 5. 错误处理

### Phase 1 — 导航历史栈
- cursor 越界：早返回
- React Router 外部 PUSH：比较 `stack[cursor].path` 去重
- 组件卸载期间调用：React 18 自动清理；函数本身不抛错
- 统一用 optional chaining `navigationHistory?.back()`

### Phase 2 — 拖拽侧边栏
- localStorage 不可用：`try/catch` 返回 `[]`，内存模式运行
- localStorage 数据损坏：返回 `[]`，**不抛出**到 UI
- 排序状态包含已删除 session id：`reconcileStoredSiderOrder` 自动过滤
- PointerSensor 不支持：退化到 MouseSensor

### Phase 3 — CSS 主题（关键）
- CSS 不含 `:root`：红字提示
- CSS 含未允许变量：白名单检查 + 红波浪线
- CSS 语法错误：CodeMirror 实时诊断
- IPC 超时（> 5s）：Toast 提示重试
- 后端 500：Toast 显示错误信息（不暴露堆栈）
- 主题文件被外部删除：启动时检测并从注册表移除
- JSON 损坏：跳过该文件，console.warn
- 封面图 > 2MB：Modal 内提示
- 封面图非图片格式：Modal 内提示

**安全约束：** 仅允许 16 个白名单变量；禁止 `@import`、`expression()`、`url()` 外链。

### Phase 4 — 装饰性主题
- 封面图加载失败：渐变背景占位
- 主题名重复：红字提示
- 主题数据不完整：使用 Indigo 默认

### Phase 5 — 自定义标题栏
- 平台检测失败：退化到 hidden
- IPC 失败：按钮 disable，console.warn，**不抛错**
- `capturePage` 失败：手动描述问题
- maximize 状态查询失败：假设未最大化

### Phase 6 — @文件 + /btw
- 文件搜索超时（> 3s）：AbortController + 重试按钮
- 工作区未选择：AtFileMenu 灰态
- /btw 发送失败：BtwOverlay 显示错误 + 重试
- 流式中断：自动重连 1 次，仍失败则标记 error
- 多个 /btw 同时打开：第二次自动关闭前一个
- btw 加载中 Esc：关闭 overlay，不取消主请求

### 通用原则
1. 永不 throw 到 UI
2. 优雅降级
3. 用户友好提示（Sonner）
4. 开发者可见（console.warn）
5. 状态可恢复

## 6. 测试策略

### 覆盖率目标

| 类型 | 目标 | 工具 |
|---|---|---|
| Unit (hooks/utils) | ≥ 90% | Vitest |
| Component | ≥ 80% | Vitest + Testing Library |
| Integration (IPC) | 关键路径 100% | Vitest + MSW |
| E2E | 6 个核心流程 | Playwright |

### Phase 1 — 导航历史栈
**Unit Tests（10 个）：** 入栈/去重/MAX_HISTORY/back/forward/越界/replace/skipNextRef/search+hash/forward 裁剪
**Component Tests（4 个）：** 按钮 disabled 状态、点击触发回调

### Phase 2 — 拖拽侧边栏
**Unit Tests（8 个）：** localStorage 读取/损坏/隐私模式/reconcile/write/arrayMove
**Component Tests（3 个）：** 渲染顺序、拖拽手柄、dragEnd 更新

### Phase 3 — CSS 主题（重点）
**Unit Tests（6 个）：** 白名单通过、@import 拒绝、expression() 拒绝、无 :root 拒绝、非白名单拒绝、嵌套选择器
**Unit Tests（3 个）：** backgroundInjector 注入位置/替换/转义
**Integration Tests（5 个）：** save/list/delete/get/timeout
**Component Tests（7 个）：** 保存按钮 disabled/enabled、封面大小/类型、cancel、delete 可见、错误行内
**E2E（3 个）：** 创建主题、删除主题、无效 CSS 被拒绝

### Phase 4 — 装饰性主题
**Component Tests（4 个）：** 渲染所有主题、cover 加载失败渐变、active 高亮、点击触发
**Visual Regression（可选）：** 主题截图对比

### Phase 5 — 自定义标题栏
**Unit Tests（4 个）：** minimize/maximize/capturePage/IPC failure
**Component Tests（5 个）：** Windows 显示、macOS 隐藏、WebUI 隐藏、feedback 打开、截图预览
**E2E（3 个）：** 最小化、最大化切换、反馈模态

### Phase 6 — @文件 + /btw
**Unit Tests（useAtFileQuery 4 个）：** 提取 @query、无 @ 时、多字节、尾空格
**Unit Tests（useBtwCommand 4 个）：** open/close/appendDelta/Esc 行为
**Component Tests（AtFileMenu 4 个）：** 搜索结果、点击插入、超时、空状态
**Component Tests（BtwOverlay 5 个）：** 渲染 question、loading spinner、answer 流式、Esc、error 态
**E2E（2 个）：** @文件插入、/btw 完整流程

### Mock 策略

| 类型 | Mock 方式 |
|---|---|
| Electron IPC | `vi.mock('electron', () => ({ ipcRenderer: { invoke: vi.fn() } }))` |
| React Router | `MemoryRouter` + 手动 `history.push` |
| localStorage | `vi.spyOn(Storage.prototype, 'getItem')` |
| CodeMirror | 仅测试 validator，编辑器用 fireEvent.change |
| 时序/计时器 | `vi.useFakeTimers()` |

### 覆盖率门槛（per Phase）

| Phase | 关键模块 | 整体 |
|---|---|---|
| Phase 1 | NavHistory: 95% | ≥ 80% |
| Phase 2 | useStoredSiderOrder: 95% | ≥ 80% |
| Phase 3 | themeCssValidator: 100%, themeCssClient: 90% | ≥ 82% |
| Phase 4 | ThemeGallery: 85% | ≥ 82% |
| Phase 5 | windowControlsClient: 90% | ≥ 83% |
| Phase 6 | useAtFileQuery/useBtwCommand: 95% | ≥ 85% |

## 7. 风险与依赖

### 技术风险

| 风险 | 影响 | 缓解策略 |
|---|---|---|
| 自定义 CSS 的 XSS 风险 | 高 | 严格白名单 + 禁止 @import/expression/url() |
| CodeMirror 包体积 | 中 | 150 KB gzip 可接受；懒加载（dynamic import） |
| @dnd-kit 与虚拟列表协同 | 中 | 参考 AionUi 实现，先 mock 测试 |
| 流式 btw 中断 | 低 | AbortController + 自动重连 |
| 平台差异（macOS vs Windows 标题栏） | 低 | 平台检测 + 分支渲染 |
| Electron 版本约束（sage 用 21.4.4） | 中 | Phase 5 需确认 webContents.capturePage 在 21.x 可用 |

### 依赖

- sage-backend conda 环境（Python 后端）
- Tailwind + 自建组件库
- Zustand（已有）
- i18next（已有）
- Vitest + Testing Library（已有）
- Playwright（已有）

### 兼容性

- 不破坏现有 6 套主题
- 不破坏现有 slash 命令
- 不破坏虚拟列表
- 不破坏 i18n 基础设施

## 8. 实施顺序（推荐）

按价值/成本比排序：

1. **Phase 1**（导航历史栈） — 1 周，架构基础，零风险
2. **Phase 2**（拖拽侧边栏） — 1.5 周，复用 Phase 1 Context 模式
3. **Phase 3**（CSS 主题编辑器） — 2-3 周，核心差异化，安全重点
4. **Phase 4**（装饰性主题） — 1 周，复用 Phase 3 存储
5. **Phase 5**（自定义标题栏） — 1.5 周，平台适配工作量大
6. **Phase 6**（@文件 + /btw） — 2-3 周，Stretch 阶段，可拆分

**总预估：** 9-11 周（6 个 Phase，含测试与文档）

每个 Phase 独立可发布，回滚成本低。

## 9. 后续行动

设计获批后，移交 writing-plans skill 创建每个 Phase 的详细实施计划。