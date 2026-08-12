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
| `src/widgets/chat/RightPanel.tsx` | 修改 | 抽 `PanelHeader` 子组件 + 加 × 按钮 + 接入 `onToggle` |
| `src/widgets/chat/__tests__/RightPanel.test.tsx` | 修改 | 新增 close button 测试用例 |
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

function PanelHeader({ tab, onTabChange, onClose }: PanelHeaderProps) {
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

## Task 4: Green — ArtifactViewer 视图加 PanelHeader + 高度修正

**Files:**
- Modify: `src/widgets/chat/RightPanel.tsx:67-94` (在 `<div className="h-[calc(100%-2.5rem)]">` 内 viewer 分支前)

**Interfaces:**
- Consumes: `<PanelHeader>` 已存在
- Produces: viewer 视图调用 `<PanelHeader onClose={onToggle} />`

- [ ] **Step 1: 在 viewer 视图分支顶部加 PanelHeader + 高度修正**

修改 `<div className="h-[calc(100%-2.5rem)]">` 内部 JSX 为:

```tsx
<div className="h-[calc(100%-2.5rem)]">
  {selected && sessionId ? (
    <>
      <PanelHeader onClose={onToggle} />
      <div className="h-[calc(100%-2.5rem)]">
        <ArtifactViewer
          artifact={selected}
          sessionId={sessionId}
          onBack={() => setSelected(null)}
        />
      </div>
    </>
  ) : tab === 'progress' ? (
    <ProgressSection
      iteration={iteration}
      streamingState={streamingState}
      toolCalls={toolCalls}
      isLoading={isLoading}
      taskBoard={taskBoard}
    />
  ) : (
    <ArtifactsSection
      artifacts={artifacts}
      loading={loading}
      sessionId={sessionId}
      onRefresh={refresh}
      onSelect={setSelected}
      onReveal={(a) => {
        if (sessionId) revealArtifact(sessionId, a.id).catch(() => {});
      }}
    />
  )}
</div>
```

外层 `<div className="h-[calc(100%-2.5rem)]">` 占满 aside 剩余空间;viewer 分支内 header 2.5rem + viewer 容器 `h-[calc(100%-2.5rem)]` = 总高度填满 ✅。Progress / Artifacts 分支不变。

- [ ] **Step 2: 检查 ArtifactViewer 是否依赖固定父高度**

Read: `src/widgets/chat/artifacts/ArtifactViewer.tsx`

如果内部用了 `h-full` 或类似充满父容器,Step 1 的双层 `h-[calc(100%-2.5rem)]` 正确。如果用了 `h-screen` 这类绝对高度,需记录 follow-up issue。本次双层结构是兜底方案,**应能 work**。

- [ ] **Step 3: 可视化验证**

启动 dev server:
```bash
cd /home/fz/project/sage && npm run dev
```

打开 http://localhost:1420 手工验证:
1. 进入 Chat 页 → 点顶部 PanelRight 图标 → RightPanel 滑出,显示 Progress/Artifacts tabs + 右上 ×
2. 点 × → 面板滑出收起 ✅
3. 再点 PanelRight → 面板滑出,点 Artifacts tab → × 仍在 ✅
4. (如果有 artifact)点某个 artifact 进入 viewer 视图 → × 仍在 viewer header ✅
5. 点 viewer × → 面板收起 ✅

- [ ] **Step 4: 运行 TS 类型检查**

Run:
```bash
npx tsc --noEmit
```

Expected: 0 errors。

- [ ] **Step 5: 运行完整 RightPanel 测试套件**

Run:
```bash
npx vitest run src/widgets/chat/__tests__/RightPanel.test.tsx
```

Expected: 所有测试绿(旧 2 + 新 3 个)。

- [ ] **Step 6: Commit**

```bash
git add src/widgets/chat/RightPanel.tsx src/widgets/chat/__tests__/RightPanel.test.tsx
git commit -m "feat(rightpanel): ArtifactViewer 视图加 × 按钮"
```

---

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

- [ ] **Step 3: 切 feature 分支 + cherry-pick 走 PR 流程**

按 `feature-branch-workflow` 规范,**3 个 feat commit 当前在 main 上,需回退到 feature 分支**:

```bash
git switch -c feat/rightpanel-close-button <spec-commit-sha>   # 从 spec 之前切出
git cherry-pick <feat-commit-1> <feat-commit-2> <feat-commit-3>
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
| T1 Red 测试 | 0 (与 T2 一起提交) | +35 行 (测试) |
| T2 接通 onToggle | 1 | +2 行 (RightPanel.tsx) |
| T3 抽 PanelHeader + list × | 1 | +45 行 (PanelHeader 子组件) |
| T4 viewer × | 1 | +8 行 (RightPanel.tsx 顶部 viewer header) |
| T5 PR | 0 (push/merge) | 0 |
| **合计** | **3 commit** | **+90 行** |

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