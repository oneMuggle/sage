# RightPanel 关闭按钮 — 设计 spec

**日期:** 2026-08-12
**作者:** Claude (brainstorming 后)
**状态:** 设计已批准,待实施

## 背景

`sage` 项目的"进度和产物"右侧面板 (`RightPanel`) 在打开后无法折叠 —— 用户只能通过顶部 `RightPanelToggle` 图标按钮触发关闭,但面板打开时该按钮**视觉上仍在原位且行为不直观**,用户实际感受是"打开后关不掉"。

## 根因

`RightPanel` 组件的接口里**已经声明了** `onToggle: () => void` (`src/widgets/chat/RightPanel.tsx:16`),并且 `Chat.tsx:289` 已经把 `onToggle={() => setRightPanelOpen(v => !v)}` 传入了。但是 `RightPanel.tsx:27-35` 解构 props 时**漏掉了 `onToggle`**,整个组件体内**没有任何调用 `onToggle` 的代码**,也没有任何关闭按钮渲染。

结论:水管已铺好,水龙头没接。修复属于"接通现有接口"而非新增机制。

## 目标

在 `RightPanel` 面板内部提供关闭入口,使得面板打开后用户可一键折叠。三种视图 (Progress / Artifacts 列表 / ArtifactViewer) 都需可关闭。

## 非目标

- 不改动 Chat.tsx 中 `rightPanelOpen` 状态管理逻辑
- 不持久化折叠状态(已由父组件 `useState` 管理)
- 不重做 tab 切换交互
- 不引入新的状态管理库或全局 store

## 设计

### 组件变更

文件:`src/widgets/chat/RightPanel.tsx`

1. **解构新增**:`onToggle` 加入 props 解构列表
2. **新增 import**:`import { X } from 'lucide-react'`
3. **抽 `<PanelHeader>` 子组件**:把现有 tab 切换行与 ArtifactViewer 视图的 header 统一为一个组件

```tsx
interface PanelHeaderProps {
  tab?: Tab;                    // list 视图传入,viewer 视图省略
  onTabChange?: (t: Tab) => void;
  onClose: () => void;
}

function PanelHeader({ tab, onTabChange, onClose }: PanelHeaderProps) {
  if (tab && onTabChange) {
    // list 视图:Progress | Artifacts | ×
    return (
      <div className="flex border-b border-border items-center">
        {(['progress','artifacts'] as Tab[]).map((t) => (
          <button key={t} className="flex-1 ..." onClick={() => onTabChange(t)}>
            {t === 'progress' ? 'Progress' : 'Artifacts'}
          </button>
        ))}
        <button
          className="ml-auto p-2 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
          onClick={onClose}
          title="关闭右侧面板"
          aria-label="关闭右侧面板"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    );
  }
  // ArtifactViewer 视图:仅 × 按钮,与 list 视图右对齐
  return (
    <div className="flex justify-end border-b border-border items-center h-10 px-2">
      <button
        className="p-2 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
        onClick={onClose}
        title="关闭右侧面板"
        aria-label="关闭右侧面板"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
```

4. **替换原 tab 行** (`RightPanel.tsx:48-65`):使用 `<PanelHeader tab={tab} onTabChange={setTab} onClose={onToggle} />`
5. **ArtifactViewer 视图加 header**:在 `ArtifactViewer` 上方加 `<PanelHeader onClose={onToggle} />`

### 样式约定

- 图标:`lucide-react` 的 `X`,与现有 `PanelRight` 同尺寸 `w-4 h-4`
- 颜色:`text-text-secondary hover:text-text`(与 `RightPanelToggle.tsx:13` 一致)
- 圆角:`rounded`(`RightPanelToggle` 用 `rounded`)
- hover 背景:`hover:bg-bg-hover`(沿用)

### 可访问性

- `aria-label="关闭右侧面板"` —— 屏幕阅读器友好
- `title="关闭右侧面板"` —— 鼠标 hover 提示(与 `RightPanelToggle` 风格对齐)
- 键盘可达:原生 `<button>` 元素,Enter/Space 触发

### 不引入的状态

折叠状态完全由父组件 `Chat.tsx` 的 `rightPanelOpen` 管理。本组件不持有副本,不写 `useEffect` 同步,纯函数式渲染。

## 测试

文件:`src/widgets/chat/__tests__/RightPanel.test.tsx` (已存在,新增 describe 块)

```tsx
describe('RightPanel - close button (F1)', () => {
  it('Progress tab: 点击 × 触发 onToggle', () => { ... })
  it('Artifacts tab: 点击 × 触发 onToggle', () => { ... })
  it('ArtifactViewer 视图: × 仍可见且触发 onToggle', () => { ... })
  it('关闭按钮 aria-label 为 "关闭右侧面板"', () => { ... })
})
```

沿用现有 `RightPanel.test.tsx` 的 defaultProps 模式与 `vitest` + `@testing-library/react` + `userEvent`。

## 风险与边界

- **风险 1:** ArtifactViewer 现有布局 (line 67 `h-[calc(100%-2.5rem)]`) 默认 header 占 2.5rem。Viewer 视图单独加 header 后总高度可能溢出。**缓解:** PanelHeader 固定 `h-10` (2.5rem),与原 tab 行高度一致;viewer 视图底部容器改为 `h-[calc(100%-2.5rem)]` 保持不变
- **风险 2:** `RightPanelToggle` (顶部) 与新的面板内 × 形成双入口。**接受:** 用户已选 "面板内部右上角 ×",顶部按钮保留作为 redundant affordance,与 iA Writer / Linear 等产品一致
- **不修改的范围:** `Chat.tsx` / `RightPanelToggle.tsx` / `useArtifacts` / 后端

## 实施清单

- [ ] T1:写 Red 测试,确认 RightPanel 内当前无 × 按钮(确认 bug 可复现)
- [ ] T2:RightPanel.tsx 解构 onToggle + 加 import
- [ ] T3:抽 PanelHeader 子组件(list 视图 + viewer 视图两个分支)
- [ ] T4:替换原 tab 行 + 在 ArtifactViewer 上方插入 PanelHeader
- [ ] T5:Green 测试通过,补全 4 个测试用例
- [ ] T6:AI code review + TS 类型检查
- [ ] T7:PR + CI 绿

## 工时估算

- 代码改动:RightPanel.tsx 净增约 +25 行(含 PanelHeader 抽出)
- 测试改动:RightPanel.test.tsx 净增约 +60 行(4 个用例)
- 总改动 < 100 行,单文件 +1 改动 + 测试文件改动,风险面 1 个组件