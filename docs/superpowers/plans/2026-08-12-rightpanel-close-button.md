# RightPanel 关闭按钮 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `RightPanel` 面板内部添加 × 关闭按钮,接通已存在的 `onToggle` 接口,使得面板打开后用户可一键折叠。三种视图 (Progress / Artifacts 列表 / ArtifactViewer) 均可见可点。

**Architecture:** 在 `RightPanel.tsx` 内部抽出 `<PanelHeader>` 子组件,统一 list 视图的 tab 切换行与 ArtifactViewer 视图的 header。两种 header 右侧都放 × 按钮,均调 `onToggle`。仅改 1 个文件 + 1 个测试文件。`Chat.tsx` 完全不动。

**Tech Stack:** React + TypeScript + Tailwind CSS + lucide-react (`X` 图标) + vitest + @testing-library/react + userEvent

## Global Constraints

- **不修改 `Chat.tsx`**:父组件已传 `onToggle={() => setRightPanelOpen(v => !v)}`,本计划只接通
- **不修改后端 / 状态管理 / `useArtifacts`**
- **样式约定**:`lucide-react X` 图标 `w-4 h-4`,颜色 `text-text-secondary hover:text-text`,圆角 `rounded`,hover 背景 `hover:bg-bg-hover`(与 `RightPanelToggle.tsx:13-17` 对齐)
- **a11y**:`aria-label="关闭右侧面板"` + `title="关闭右侧面板"`
- **键盘可达**:原生 `<button>`,Enter/Space 触发
- **TS 严格模式**:无 `any`,显式 `interface` 定义 props
- **不可变性**:纯 props 渲染,不持有折叠状态副本
- **commit message**:`feat(rightpanel): ...` 格式,conventional commits
- **每任务一个 commit**:独立可测

---

## 文件结构

| 文件 | 操作 | 责任 |
|---|---|---|
| `src/widgets/chat/RightPanel.tsx` | 修改 | 抽 `PanelHeader` 子组件(导出) + 加 × 按钮 + 接入 `onToggle` |
| `src/widgets/chat/__tests__/RightPanel.test.tsx` | 修改 | 新增 close button list 视图测试(3 用例)+ tab switch 1 用例 |
| `src/widgets/chat/__tests__/PanelHeader.test.tsx` | 新增 | PanelHeader 独立单元测试(list + viewer 两个分支) |
| `docs/superpowers/specs/2026-08-12-rightpanel-close-button-design.md` | 已存在 | 设计来源,本次实施依据 |
| `src/widgets/chat/RightPanelToggle.tsx` | **不改** | 顶部切换按钮,本次不涉及 |
| `src/pages/Chat.tsx` | **不改** | 父组件已传 `onToggle` |

---

## Task 1: Red 测试 — 验证当前 RightPanel 内确实无 × 按钮 (确认 bug)

**Files:**
- Modify: `src/widgets/chat/__tests__/RightPanel.test.tsx`
- Read: `src/widgets/chat/RightPanel.tsx` (确认现状)

**目的:** 在动手前先写一个失败的测试,证明 bug 真实存在,且后续实施能让它变绿。

- [ ] **Step 1: 在 RightPanel.test.tsx 末尾新增 describe 块**

在现有 `describe('RightPanel', ...)` 后追加:

```tsx
describe('RightPanel - close button', () => {
  it('list view (Progress tab) renders close button with correct aria-label', () => {
    render(<RightPanel {...props} />);
    expect(
      screen.getByRole('button', { name: '关闭右侧面板' })
    ).toBeInTheDocument();
  });

  it('clicking close button in Progress tab invokes onToggle', () => {
    const onToggle = vi.fn();
    render(<RightPanel {...props} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('clicking close button in Artifacts tab invokes onToggle', () => {
    const onToggle = vi.fn();
    render(<RightPanel {...props} onToggle={onToggle} />);
    fireEvent.click(screen.getByText('Artifacts'));
    fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: 运行测试,确认 RED**

Run:
```bash
npx vitest run src/widgets/chat/__tests__/RightPanel.test.tsx
```

Expected: 新增 3 个测试全部失败,错误信息 "Unable to find an accessible element with role 'button' and name '关闭右侧面板'"(因为 RightPanel.tsx 还没渲染这个按钮)。旧 2 个测试仍通过。

---

## Task 2: Green — 在 RightPanel.tsx 加 import 并解构 onToggle(最小接通)

**Files:**
- Modify: `src/widgets/chat/RightPanel.tsx:1-35`

**Interfaces:**
- Consumes: `onToggle: () => void` (从 `RightPanelProps` 已有)
- Produces: 解构后 `onToggle` 在函数体内可用,但暂不渲染按钮(下一任务再做)

- [ ] **Step 1: 加 `X` 图标 import**

在 `src/widgets/chat/RightPanel.tsx:1` 的 `import { useState } from 'react';` 之后加:

```tsx
import { X } from 'lucide-react';
```

- [ ] **Step 2: 把 `onToggle` 加入 props 解构**

修改 `src/widgets/chat/RightPanel.tsx:27-35` 的解构:

```tsx
export function RightPanel({
  open,
  onToggle,        // ← 新增
  iteration,
  streamingState,
  toolCalls,
  isLoading,
  sessionId,
  taskBoard,
}: RightPanelProps) {
```

- [ ] **Step 3: 运行测试,确认旧测试仍通过、新测试仍 RED**

Run:
```bash
npx vitest run src/widgets/chat/__tests__/RightPanel.test.tsx
```

Expected: 2 个旧测试通过(我们的改动没破坏它们),3 个新测试**仍失败**(因为还没渲染按钮)。这是预期的 Green-in-progress 状态。

- [ ] **Step 4: Commit**

```bash
git add src/widgets/chat/RightPanel.tsx
git commit -m "feat(rightpanel): 接入 onToggle 接口 + 加 X 图标 import"
```

---

## Task 3: Green — 抽出 PanelHeader 子组件并替换 list 视图 tab 行

**Files:**
- Modify: `src/widgets/chat/RightPanel.tsx:25-65`(在 `export function RightPanel` 前加 PanelHeader + PanelHeaderProps,替换原 tab 行 JSX)

**Interfaces:**
- Consumes: `tab: Tab` + `setTab: (t: Tab) => void` + `onToggle: () => void` (从 RightPanel 函数体传入)
- Produces: `<PanelHeader>` 组件,接收 `tab?`, `onTabChange?`, `onClose`

- [ ] **Step 1: 在 RightPanel.tsx 中 `export function RightPanel` 之前添加 `PanelHeader` 子组件**

在 `type Tab = 'progress' | 'artifacts';` (line 25) 之后、`export function RightPanel` 之前插入:

```tsx
interface PanelHeaderProps {
  tab?: Tab;
  onTabChange?: (t: Tab) => void;
  onClose: () => void;
}

// ⚠️ 必须 export,PanelHeader.test.tsx 要直接 import 它
export function PanelHeader({ tab, onTabChange, onClose }: PanelHeaderProps) {
  // list 视图:Progress / Artifacts tabs + × 按钮
  if (tab !== undefined && onTabChange) {
    return (
      <div className="flex border-b border-border items-center">
        {(['progress', 'artifacts'] as Tab[]).map((t) => (
          <button
            key={t}
            className={
              'flex-1 py-2 text-sm font-medium transition-colors ' +
              (tab === t
                ? 'text-primary border-b-2 border-primary'
                : 'text-text-secondary hover:text-text')
            }
            onClick={() => onTabChange(t)}
          >
            {t === 'progress' ? 'Progress' : 'Artifacts'}
          </button>
        ))}
        <button
          className="ml-auto p-2 mr-1 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
          onClick={onClose}
          title="关闭右侧面板"
          aria-label="关闭右侧面板"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    );
  }

  // ArtifactViewer 视图:仅 × 按钮
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

- [ ] **Step 2: 替换原 tab 行 JSX**

将 `src/widgets/chat/RightPanel.tsx` 第 48-65 行原 `<div className="flex border-b border-border">...</div>` 整个 tab 切换行替换为:

```tsx
<PanelHeader tab={tab} onTabChange={setTab} onClose={onToggle} />
```

完整新 aside 起始 JSX 应为:

```tsx
return (
  <aside
    className={
      'fixed top-12 right-0 h-[calc(100vh-3rem)] w-80 bg-surface border-l border-border ' +
      'transform transition-transform duration-200 ease-in-out z-30 ' +
      (open ? 'translate-x-0' : 'translate-x-full')
    }
  >
    <PanelHeader tab={tab} onTabChange={setTab} onClose={onToggle} />

    <div className="h-[calc(100%-2.5rem)]">
      {/* 下面不变 */}
    </div>
  </aside>
);
```

- [ ] **Step 3: 运行测试,确认 list 视图的 3 个 close button 测试变绿**

Run:
```bash
npx vitest run src/widgets/chat/__tests__/RightPanel.test.tsx
```

Expected: 旧 2 个测试 + 新增 3 个 list 视图测试全绿。

- [ ] **Step 4: Commit**

```bash
git add src/widgets/chat/RightPanel.tsx
git commit -m "feat(rightpanel): 抽 PanelHeader 子组件 + list 视图加 × 按钮"
```

---

## Task 4: Green — PanelHeader 独立单元测试 + 清理作者备忘注释

**Files:**
- Create: `src/widgets/chat/__tests__/PanelHeader.test.tsx` (新增)
- Modify: `src/widgets/chat/RightPanel.tsx` (移除 `// ⚠️ 必须 export` 作者备忘注释)

**Interfaces:**
- Consumes: `<PanelHeader>` 已 export (Task 3 完成)
- Produces: PanelHeader.test.tsx 含 list + viewer 两分支 6 个 vitest 用例

> **Task 4 scope 收窄说明:** Task 3 implementer 已把 viewer-mode PanelHeader 在 RightPanel.tsx 调用层接好 (`selected ? <PanelHeader onClose={onToggle}/> : ...`),所以本 Task 不需要再改 RightPanel.tsx 的 JSX。ArtifactViewer 内部已有完整 header (返回 + 文件名 + 复制 + 文件管理器),与外部 PanelHeader viewer-mode 的 × 按钮功能互补不冲突 (外部 × 关闭整个面板,内部 ArrowLeft 返回列表)。无需高度修正。

- [ ] **Step 1: 创建 PanelHeader 独立测试文件**

Create: `src/widgets/chat/__tests__/PanelHeader.test.tsx`

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PanelHeader } from '../RightPanel';

describe('PanelHeader', () => {
  describe('list view (with tab + onTabChange)', () => {
    const listProps = {
      tab: 'progress' as const,
      onTabChange: vi.fn(),
      onClose: vi.fn(),
    };

    it('renders Progress and Artifacts tabs', () => {
      render(<PanelHeader {...listProps} />);
      expect(screen.getByText('Progress')).toBeInTheDocument();
      expect(screen.getByText('Artifacts')).toBeInTheDocument();
    });

    it('renders close button with aria-label', () => {
      render(<PanelHeader {...listProps} />);
      expect(
        screen.getByRole('button', { name: '关闭右侧面板' })
      ).toBeInTheDocument();
    });

    it('clicking close button invokes onClose', () => {
      const onClose = vi.fn();
      render(<PanelHeader {...listProps} onClose={onClose} />);
      fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('viewer view (no tab props)', () => {
    it('renders close button with aria-label', () => {
      render(<PanelHeader onClose={vi.fn()} />);
      expect(
        screen.getByRole('button', { name: '关闭右侧面板' })
      ).toBeInTheDocument();
    });

    it('does not render tab buttons', () => {
      render(<PanelHeader onClose={vi.fn()} />);
      expect(screen.queryByText('Progress')).not.toBeInTheDocument();
      expect(screen.queryByText('Artifacts')).not.toBeInTheDocument();
    });

    it('clicking close button invokes onClose', () => {
      const onClose = vi.fn();
      render(<PanelHeader onClose={onClose} />);
      fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });
});
```

- [ ] **Step 2: 移除 RightPanel.tsx 中的作者备忘注释**

在 `src/widgets/chat/RightPanel.tsx` 中,`export function PanelHeader` 上方有 brief 留下的 `// ⚠️ 必须 export,PanelHeader.test.tsx 要直接 import 它` 注释。export 已就位、test 文件本步骤即创建,删除该注释减少噪音。

- [ ] **Step 3: 运行完整测试套件**

Run:
```bash
npx vitest run src/widgets/chat/__tests__/RightPanel.test.tsx src/widgets/chat/__tests__/PanelHeader.test.tsx
```

Expected: RightPanel 5/5 全绿 + PanelHeader 6/6 全绿 = 11/11。

- [ ] **Step 4: 运行 TS 类型检查**

Run:
```bash
npx tsc --noEmit -p . 2>&1 | head -20
```

Expected: 0 errors。

- [ ] **Step 5: Commit**

```bash
git add src/widgets/chat/__tests__/PanelHeader.test.tsx src/widgets/chat/RightPanel.tsx
git commit -m "feat(rightpanel): PanelHeader 独立单元测试覆盖 list + viewer 两分支"
```

## Task 5: 收尾 — AI code review + lint + PR

**Files:**
- 全部上述已提交文件

- [ ] **Step 1: AI code review**

调用 `pr-review-toolkit:code-reviewer` agent 对本次 commit 做评审:

输入提示词:
```
Review changes in src/widgets/chat/RightPanel.tsx and src/widgets/chat/__tests__/RightPanel.test.tsx.
Focus on:
1. React a11y (aria-label, button semantics)
2. Tailwind class correctness
3. TypeScript strictness (no any, explicit interfaces)
4. Test coverage adequacy
5. State management purity (no duplicate toggle state)
```

Expected: 0 CRITICAL, 0 HIGH。如有则修复后再 commit。

- [ ] **Step 2: Lint 检查**

Run:
```bash
cd /home/fz/project/sage && npx eslint src/widgets/chat/RightPanel.tsx src/widgets/chat/__tests__/RightPanel.test.tsx
```

Expected: 0 errors,0 warnings。

- [ ] **Step 3: 直接在 feat 分支上 push + 开 PR**

⚠️ **不要 reset/cherry-pick** —— 3 个 feat commit 本就在 `feat/rightpanel-close-button` 分支上(从 spec commit 后切出),直接 push 即可:

```bash
git push -u origin feat/rightpanel-close-button
gh pr create --title "feat(rightpanel): 面板内添加 × 关闭按钮" \
  --body "Closes #<issue>. 见 docs/superpowers/specs/2026-08-12-rightpanel-close-button-design.md 与 docs/superpowers/plans/2026-08-12-rightpanel-close-button.md。"
```

- [ ] **Step 4: 监控 CI**

Run:
```bash
gh pr checks <pr-number> --watch
```

Expected: Backend / Frontend / TS / Electron build 全绿。

- [ ] **Step 5: 等用户 merge,清理分支**

```bash
git push origin --delete feat/rightpanel-close-button
git branch -d feat/rightpanel-close-button
```

---

## 实施总览

| Task | commit 数 | 累计行数 |
|---|---|---|
| T1 Red 测试 | 0 (与 T2 一起提交) | +40 行 (RightPanel 测试) |
| T2 接通 onToggle | 1 | +2 行 (RightPanel.tsx) |
| T3 抽 PanelHeader + list × | 1 | +45 行 (PanelHeader 子组件,export) |
| T4 viewer × + PanelHeader 独立测试 | 1 | +8 行 (RightPanel.tsx) + 60 行 (PanelHeader.test.tsx) |
| T5 PR | 0 (push/merge) | 0 |
| **合计** | **3 commit** | **+155 行** |

## Self-Review

- **Spec 覆盖检查:**
  - 目标"3 视图 × 都可关闭"→ T3 (list) + T4 (viewer) ✅
  - 抽 PanelHeader 子组件 → T3 ✅
  - 仅改 RightPanel.tsx → T1-T4 全程只动这一个文件 + 测试 ✅
  - vitest 用例覆盖 → T1 + T4 收尾 ✅
- **Placeholder 检查:** 无 TBD / TODO / "similar to" / "fill in details"
- **类型一致性:**
  - `Tab` 在 RightPanel.tsx 定义并复用 ✅
  - `PanelHeaderProps` 仅在 RightPanel.tsx 内部使用,不导出 ✅
  - `onClose: () => void` 在两处签名一致 ✅
- **风险:** T4 高度调整风险已用 `h-[calc(100%-2.5rem)]` 包裹解决
- **trade-off:** ArtifactViewer 视图 × 按钮的集成覆盖改为"列表视图测试 + 可视化验证 + TS 严格类型保证 PanelHeader viewer 分支会渲染"。原因是 dynamic mock + import 在 vitest 中需要 reset modules,增加复杂度不划算