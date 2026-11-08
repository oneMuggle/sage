# /office 文档库复用全局侧栏（方案 A：侧栏内容列路由作用域化）

## 背景与目标

`/office`「文档与审校」页当前同时存在两列历史列表：

1. 全局 `Sidebar` 内容列（300px，项目 / 会话 / Git 分区）；
2. 页面内 `OfficeLayout left` 的文档库（200–260px）。

在 1280–1366px 宽度下，两列加上 `p-6` 内边距与 `gap-4` 会把 `DocumentCanvas` 挤到不足半数宽度。
而使用文档/审校功能时基本不会用到会话列表，主流 AI 应用（Claude / ChatGPT 作品集页、Notion AI 文档页）
也都把「当前工作对象的列表」放在唯一一条左栏，而不是再叠一列。

**目标**

- `/office` 路由下，全局侧栏内容列改为承载文档库（列表 + live/archived 切换 + 搜索/筛选/排序 + 快照入口）；
- 页面内不再渲染左侧文档库列，画布获得整行宽度；
- 其他路由的侧栏行为完全不变；
- 侧栏折叠 / 移动端抽屉 / 无 Layout 的单元测试环境下自动回退到现有的 `OfficeLayout` 两栏，不出现「文档库消失」。

**非目标**

- 不做 `?doc=<id>` 文档深链（YAGNI，避免与预览状态形成双向同步）；
- 不改 `useOfficeDocuments`（789 行）的状态归属，不引入全局 store；
- 不改移动端抽屉的交互模型（仍由 Titlebar 汉堡按钮开关）。

## 涉及的文件与模块

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `src/widgets/layout/SidebarSlotProvider.tsx` | 新增 | `SidebarSlotContext` + `SidebarSlotProvider` + `useSidebarSlot()`，默认值可在无 Provider 时安全使用 |
| `src/widgets/layout/Layout.tsx` | 修改 | 用 `SidebarSlotProvider` 包裹 `Sidebar` 与 `<main>` |
| `src/widgets/layout/Sidebar.tsx` | 修改 | `/office` 路由下内容列渲染 slot 容器，替代 primary actions + nav；状态栏保留 |
| `src/pages/Office.tsx` | 修改 | 文档库抽出为 `documentsLibrary` JSX；有 slot 时 `createPortal` 进侧栏，页面只留画布；否则回退 `OfficeLayout` |
| `src/widgets/layout/__tests__/Sidebar.office-slot.test.tsx` | 新增 | 侧栏路由分支 + 折叠清理 |
| `src/pages/__tests__/Office.sidebarPortal.test.tsx` | 新增 | portal 挂载 / 无 slot 回退 / 跨 tab 点击切回 documents |
| `src/pages/__tests__/Office.tabs.test.tsx` | 不改 | 无 Provider → `slotEl = null` → 走内联回退，保持绿 |
| `src/widgets/layout/__tests__/Sidebar.two-stage.test.tsx` | 不改 | 无 Provider，默认 context 必须安全 |

不涉及后端、IPC、数据库与依赖变更。

## 技术方案

### 1. 侧栏插槽 Context（新增）

```ts
// src/widgets/layout/SidebarSlotProvider.tsx
interface SidebarSlotContextValue {
  slotEl: HTMLElement | null;
  setSlotEl: (el: HTMLElement | null) => void;
}

const SidebarSlotContext = createContext<SidebarSlotContextValue>({
  slotEl: null,
  setSlotEl: () => {},
});

export function SidebarSlotProvider({ children }: { children: ReactNode }) {
  const [slotEl, setSlotEl] = useState<HTMLElement | null>(null);
  const value = useMemo(() => ({ slotEl, setSlotEl }), [slotEl]);
  return <SidebarSlotContext.Provider value={value}>{children}</SidebarSlotContext.Provider>;
}

export function useSidebarSlot(): SidebarSlotContextValue {
  return useContext(SidebarSlotContext);
}
```

- 默认值 `{ slotEl: null, setSlotEl: noop }` —— 现有测试 `<Sidebar />` / `<Office />` 不包 Provider 也安全；
- `setState` 的 setter 本身稳定，`value` 只随 `slotEl` 变化；
- **没有会话 store、没有把 `useOfficeDocuments` 上提**：portal 子树仍是 `Office` 的 React 子节点，
  所有 state 与 handlers 照旧通过 props 直接传递。

### 2. Layout 挂载 Provider

`Layout.tsx` 中：

```tsx
<SidebarSlotProvider>
  <Sidebar ... />
  <main ...> ... <Outlet /> ... </main>
</SidebarSlotProvider>
```

移动端抽屉骨架常驻（仅位移到屏幕外），所以移动端 slot 目标始终存在；桌面折叠时内容列整体卸载，
`slotEl` 会因 ref cleanup 归 `null`，`Office` 自动回退内联两栏。

### 3. Sidebar 路由作用域

```tsx
const location = useLocation();
const { setSlotEl } = useSidebarSlot();
const isOfficeRoute = location.pathname === '/office' || location.pathname.startsWith('/office/');

// 稳定 ref 回调，避免每次 render 触发 detach/attach → 状态抖动
const attachOfficeSlot = useCallback(
  (el: HTMLDivElement | null) => setSlotEl(el),
  [setSlotEl],
);
```

内容列结构变为：

```tsx
{!collapsed && (
  <div data-testid="sidebar-content" className="flex-1 min-w-0 flex flex-col">
    {/* 品牌头 —— 两种路由共用 */}
    <div className="h-12 ...">{t('sidebar.brand')}</div>

    {isOfficeRoute ? (
      <div
        ref={attachOfficeSlot}
        data-testid="sidebar-office-slot"
        className="flex-1 min-h-0 flex flex-col min-w-0"
      />
    ) : (
      <>
        <div data-testid="sidebar-primary-actions" ...>…</div>
        <nav data-testid="sidebar-scroll" ...>…</nav>
      </>
    )}

    {/* 连接状态 + 版本号 —— 两种路由共用 */}
    <div ... />
  </div>
)}
```

- `/office` 下不渲染「新建对话 / 搜索 / 会话分区 / Git 分区」，也不渲染 `sidebar-scroll`；
- 品牌头与底部状态栏保留，侧栏视觉连续；
- `RAIL_WIDTH`、折叠按钮、Sections 状态与审计函数不动。

### 4. Office 页面 portal 与回退

```tsx
const { slotEl } = useSidebarSlot();

const documentsLibrary = (
  <>
    {/* 原 OfficeLayout.left 的全部内容：view 切换 + OfficeDocumentList + 快照面板 */}
  </>
);
const documentsCanvas = (
  <>
    {/* 原 OfficeLayout.center 的全部内容：画布标题 + DocumentCanvas + 编辑对话框 */}
  </>
);
```

- **有 slot**：文档库通过 portal 挂进侧栏；`renderDocumentsTab()` 只返回画布，
  页面不再出现 `office-layout-left`：

  ```tsx
  {slotEl &&
    createPortal(
      <div
        data-testid="office-sidebar-library"
        className="flex-1 min-h-0 flex flex-col gap-3 px-3 pb-3 overflow-y-auto"
      >
        {documentsLibrary}
      </div>,
      slotEl,
    )}
  ```

  portal 挂在 `Office` 根节点（不在 TabContent 内），因此 `?tab=generate|rules|latex` 深链落地时
  侧栏文档库依然存在（keep-alive 与首次挂载顺序都不影响）。

- **无 slot（折叠 / 测试 / 异常）**：保持现有 `<OfficeLayout left={documentsLibrary} center={documentsCanvas} />`，
  `OfficeLayout.tsx` 不改。

- **跨 tab 选择文档**：`handleOpen` 与 `handlePreviewDocument` 开头加
  `if (activeTab !== 'documents') setTab('documents')`，避免在 generate tab 点侧栏列表后看不到预览。
  移动端抽屉会因 `location.search` 变化被 `Layout` 自动关闭，用户直接回到画布 —— 这正是期望行为。

### 5. 视觉与尺寸

- 侧栏宽度不变（默认 300px，可拖拽），文档库拿到与旧左列相当甚至更宽的可用宽度；
- 页面画布从「300 + 260 + 画布」变为「300 + 画布」；
- 列表滚动交给 portal 容器的 `overflow-y-auto`（`OfficeDocumentList` 根节点本身不滚动）。

## 实施步骤

- [x] 1. 新增 `SidebarSlotProvider.tsx`（Context + Provider + hook，默认值安全）
- [x] 2. `Layout.tsx` 包裹 Provider，跑通现有 `Layout` 相关测试
- [x] 3. `Sidebar.tsx` 增加 `/office` 分支与稳定 ref 回调，补 `data-testid="sidebar-office-slot"`
- [x] 4. `Office.tsx` 抽出 `documentsLibrary` / `documentsCanvas`，接入 `createPortal` + 内联回退
- [x] 5. `handleOpen` / `handlePreviewDocument` 增加跨 tab 切回 documents
- [x] 6. 新增 `Sidebar.office-slot.test.tsx`
- [x] 7. 新增 `Office.sidebarPortal.test.tsx`
- [x] 8. 本地验证：`npx tsc --noEmit`、`npx vitest run` 相关目录、`npx eslint` 改动文件、`node scripts/architecture-check.mjs`
- [x] 9. 浏览器实测：Vite 1546 + 后端 8891，1280×720 视口确认双列消失、侧栏列表可滚动、点选文档出预览、折叠侧栏回退内联、移动端抽屉可用
- [ ] 10. 提交 + PR + CI 绿 + 合并，再按分支规则同步 `release/win7`（先 `git diff origin/release/win7 -- <files>`）

## 风险评估与依赖

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| ref 回调身份不稳定 | 每次 render detach/attach → `setSlotEl(null)`/`(el)` 抖动，可能无限重渲 | `useCallback` 依赖 `[setSlotEl]`；`setSlotEl` 为 `useState` setter，恒稳定 |
| 首帧 `slotEl === null` | 初次挂载可能闪一帧内联列表再切到侧栏 | 可接受；如需消除可在 `Layout` 用 `useLayoutEffect` 同步，但收益极小 |
| 桌面折叠侧栏 | 内容列卸载 → 文档库无处可挂 | 已有回退分支，自动回到 `OfficeLayout` 两栏 |
| 移动端 | 文档库只在抽屉里 | 抽屉常驻 DOM，汉堡可开；选中后抽屉自动关闭回画布 |
| `Sidebar.tsx` 行数 | 706 → 约 730，逼近 800 棘轮 | 仍低于 `policy.global.maxFileLines`，不新增 baseline；若超限则把分支抽成 `SidebarOfficeSlot.tsx` |
| office barrel 符号数测试 | `officeIndex.p165.test.ts` 锁 14 个导出 | 不新增 barrel 导出，不新建需要导出的 office 组件；portal 逻辑留在 `Office.tsx` |
| 现有测试 | `Office.tabs.test.tsx` 无 Provider | 默认 `slotEl = null` → 走内联回退，断言不变 |
| 主题/暗色 | portal 脱离页面 DOM，CSS 变量按 `html` 层作用域，不受影响 | 侧栏与页面同属一个 document，无需额外处理 |

依赖：无新增 npm 包；`react-dom` 的 `createPortal` 已在依赖中（React 18）。
