# Phase 7 — 新会话欢迎屏（Welcome Screen）实施计划

**日期：** 2026-06-25
**基于设计文档：** `docs/superpowers/specs/2026-06-25-aionui-inspired-ui-design.md` § Phase 7
**借鉴来源：** AionUi `pages/guid/GuidPage.tsx` + `QuickActionButtons.tsx`
**状态：** 待实施

---

## Goal

为 sage 项目引入新会话欢迎屏（Welcome Screen）：

1. **核心 UX**：用户点击"新建会话"后，看到一个居中聚焦的大输入框（而非 Chat 页底部的小输入框），输入框下方展示"推荐助手卡片"，底部一行快速操作。
2. **打字机动画**：输入框 placeholder 用打字机效果轮播 3-5 条提示语（50ms/字），卸载时清理 setInterval。
3. **路由集成**：新增 `/welcome` 路由；Chat 页在 `currentSessionId == null` 时渲染 `<Welcome />`；Sidebar"新建会话"按钮跳转 `/welcome`。
4. **共享 InputCard**：从 `ChatInput` 抽出可复用的 `<InputCard />` 子组件，供 Welcome 与 Chat 共用，确保 UX 一致性。
5. **可访问性**：默认 `autofocus` 输入框；推荐卡片 Tab 键可循环；移动端降级为单列布局。

完成后，用户进入 sage 的"第一眼体验"显著提升；输入 prompt 前不必先创建一个空 session；推荐卡片降低冷启动阻力。

---

## Architecture

### FSD 分层落地

```
src/
├── pages/
│   └── Welcome.tsx                          # Pages 层：路由挂载的欢迎屏主组件
│
├── widgets/
│   └── welcome/                             # Widgets 层：欢迎屏的所有子组件
│       ├── WelcomeHero.tsx                  # 头像 + 标题 + 返回按钮
│       ├── WelcomeInputCard.tsx             # 居中大输入框（包装 ChatInput 的 InputCard）
│       ├── AssistantRecommendations.tsx     # 推荐助手卡片网格
│       └── QuickActionBar.tsx               # 反馈 / GitHub / WebUI 快速操作
│
├── features/
│   └── welcome/
│       └── useTypewriterPlaceholder.ts      # Features 层：打字机 placeholder hook
│
├── entities/
│   └── welcome/
│       └── recommendations.ts               # Entities 层：推荐助手数据 + 类型定义
│
├── shared/
│   └── lib/
│       └── i18n/
│           ├── zh.ts                        # 扩展：welcome.* 翻译键
│           └── en.ts                        # 扩展：welcome.* 翻译键
│
└── widgets/
    └── chat/
        └── ChatInput.tsx                    # 改造：抽出 <InputCard /> 子组件

tests:
├── src/features/welcome/__tests__/useTypewriterPlaceholder.test.ts
├── src/entities/welcome/__tests__/recommendations.test.ts
├── src/widgets/welcome/__tests__/WelcomeHero.test.tsx
├── src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx
├── src/widgets/welcome/__tests__/AssistantRecommendations.test.tsx
├── src/widgets/welcome/__tests__/QuickActionBar.test.tsx
├── src/pages/__tests__/Welcome.test.tsx
└── src/pages/__tests__/Chat.welcome-routing.test.tsx
```

### 核心数据流

```
用户点击 Sidebar "+ 新对话" 按钮
    ↓
navigate('/welcome')        (Sidebar.tsx 修改)
    ↓
React Router 命中 /welcome
    ↓
<Welcome /> 挂载 (pages/Welcome.tsx)
    ├─ useTypewriterPlaceholder(['帮我写代码...', '解释这段...', '脑暴个点子...'])
    │   ├─ setInterval(50ms) 推进字符索引
    │   └─ 卸载时 clearInterval（关键约束）
    │
    ├─ 渲染 <WelcomeHero /> （头像 + 标题 + 返回按钮）
    │
    ├─ 渲染 <WelcomeInputCard />（居中大输入框）
    │   └─ 内部使用 <InputCard />（从 ChatInput 抽出的子组件）
    │       └─ 监听 Enter → 触发 onSend(prompt) 回调
    │
    ├─ 渲染 <AssistantRecommendations />
    │   ├─ 从 entities/welcome/recommendations.ts 读取 3 张默认卡片
    │   └─ 点击 → 调用 props.onSelect(prompt) → 上抛给 Welcome → 注入 input
    │
    └─ 渲染 <QuickActionBar />
        ├─ 反馈按钮 → 调用 Phase 5 准备好的 IPC (或 fallback alert)
        ├─ GitHub → window.open 打开 https://github.com/
        └─ WebUI → 显示状态 badge（不阻塞交互）

用户按 Enter / 点击发送
    ↓
WelcomeInputCard 触发 onSubmit
    ↓
Welcome 调用 createSession() + sendMessage() (useStore)
    ↓
sessionId 生成后, navigate('/chat') 切换
    ↓
Chat 页接管（此时 currentSessionId !== null）
```

### Chat ↔ Welcome 切换矩阵

| 路由               | currentSessionId     | 渲染                 |
| ------------------ | -------------------- | -------------------- |
| `/welcome`         | `null` 或任意        | `<Welcome />`        |
| `/chat`            | `null`               | `<Navigate to="/welcome" replace />`（路由 fallback）|
| `/chat`            | 有值                 | `<Chat />` 正常聊天  |

**实现策略：** 不在 Chat.tsx 内做 fallback 渲染，而是通过路由层切换 — `App.tsx` 的 `/chat` 路由先检查 store，无 sessionId 时 `<Navigate to="/welcome" replace />` 跳转到 welcome。这样保持 Chat.tsx 单一职责。

---

## Tech Stack

| 类别       | 选型 / 版本                           | 说明                          |
| ---------- | ------------------------------------- | ----------------------------- |
| 框架       | React 18.2.0                          | 函数组件 + Hooks               |
| 路由       | react-router-dom 6.20.0               | `<Navigate>` 用于 fallback     |
| 状态       | zustand 4.4.7（已有）                  | `useStore` 复用               |
| 样式       | Tailwind 3.3.6 + 主题变量             | `text-text`, `bg-surface` 等  |
| 图标       | lucide-react 0.294.0（已有）           | Code2, Search, Lightbulb, …  |
| Toast      | sonner 2.0.7（已有）                   | `toast.error` 用于失败提示    |
| 测试       | vitest 1.6.0 + @testing-library/react  | 组件 + hook 单测              |
| 国际化     | 自建 i18n（zh.ts / en.ts）             | 翻译键扩展                   |
| TypeScript | 5.3.3                                 | 严格模式                     |

**不新增任何 npm 包**（设计约束）。

---

## Global Constraints

### 1. TDD 严格（项目硬性要求）

- **先写测试** → 跑测试确认 RED → 写最小实现 → 跑测试确认 GREEN → 重构。
- 每个 Task 包含独立的"写测试"步骤和"实现"步骤；不得跳步。
- 每个 Task 末尾包含"运行测试套件"步骤验证不破坏现有测试。

### 2. FSD 架构

- **依赖方向严格自上而下**：`app → pages → widgets → features → entities → shared`
- `widgets` 可依赖 `features`、`entities`、`shared`
- `pages` 可依赖 `widgets`、`features`、`entities`、`shared`
- `features` 可依赖 `entities`、`shared`
- `entities` 仅依赖 `shared`
- **禁止**反向依赖。

### 3. 覆盖率门槛

| 模块                              | 目标    |
| --------------------------------- | ------- |
| `useTypewriterPlaceholder`        | ≥ 95%   |
| `entities/welcome/recommendations` | ≥ 90%   |
| 整个 Phase 7 范围                 | ≥ 85%   |

### 4. 翻译键规范

- 所有用户可见字符串通过 `useI18n().t(key)` 渲染
- 新增键统一加 `welcome.` 前缀（如 `welcome.hero.title`, `welcome.rec.code`）
- **zh.ts 与 en.ts 必须同步添加**，缺一则 typecheck 失败（`TranslationKey` 类型强约束）

### 5. 错误处理约束

- typewriter hook 卸载时**必须**清理 `setInterval`（内存泄漏防护）
- session 创建失败 → toast 提示 + 留在 welcome 页（不跳转）
- 路由 fallback **不抛错**（使用 `<Navigate replace />`）
- WebUI 状态查询失败 → 显示 "Unavailable" badge，不阻塞交互

### 6. 行为兼容

- **不破坏**现有 Chat 路由（`/chat` 仍可用）
- **不破坏**`/chat/:sessionId` 之类的扩展形态（如未来引入）
- **不破坏**现有 slash 命令、虚拟列表、Shiki 高亮、主题系统

### 7. 提交规范

- 每个 Task 完成后单独 commit
- 消息格式：`<type>(scope): <description>`，例如：
  - `test(welcome): add useTypewriterPlaceholder test`
  - `feat(welcome): implement useTypewriterPlaceholder hook`
  - `feat(welcome): add AssistantRecommendations widget`
- **不在 main 上 commit**（项目强制 feature 分支）

### 8. 平台约束

- macOS / Windows / Linux 三端兼容（路径分隔符 / 浏览器 API 抽象已由 vite 接管）
- Electron 21.4.4 环境（已在 `package.json` 锁定）

---

## Implementation Tasks

> 任务编号规则：`<Phase>-T<NN>`（如 `P7-T01`）。每个 Task 独立可提交。

---

### P7-T01：扩展 i18n 翻译键（zh + en）

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/shared/lib/i18n/__tests__/welcome-translations.test.ts`（测试 zh + en 同步性）
- **Modify:**
  - `/home/fz/project/sage/src/shared/lib/i18n/zh.ts`（添加 `welcome.*` 键）
  - `/home/fz/project/sage/src/shared/lib/i18n/en.ts`（添加 `welcome.*` 键）

**Interfaces:**

- Consumes: `TranslationKey` 类型（来自 `zh.ts` 的 `as const`）
- Produces: 扩展后的 `Record<TranslationKey, string>`，包含以下键：

```typescript
// zh.ts 增量
'welcome.hero.greeting': '你好，我是 Claude';
'welcome.hero.subtitle': '有什么可以帮你的？';
'welcome.hero.back': '返回';
'welcome.input.placeholder': '输入消息，Enter 发送';
'welcome.rec.title': '推荐助手';
'welcome.rec.code.title': '写代码';
'welcome.rec.code.desc': '帮我写代码、解释代码、找 Bug';
'welcome.rec.search.title': '搜索';
'welcome.rec.search.desc': '查找资料、查文档、找答案';
'welcome.rec.idea.title': '创意';
'welcome.rec.idea.desc': '脑暴点子、起名、写文案';
'welcome.quick.feedback': '反馈';
'welcome.quick.feedback_desc': '提交问题或建议';
'welcome.quick.github': 'GitHub';
'welcome.quick.github_desc': '查看源码';
'welcome.quick.webui': 'WebUI';
'welcome.quick.webui_desc': '在浏览器中打开';
'welcome.quick.webui_unavailable': 'Unavailable';

// en.ts 对应英文
'welcome.hero.greeting': 'Hi, I\'m Claude';
'welcome.hero.subtitle': 'How can I help you today?';
'welcome.hero.back': 'Back';
'welcome.input.placeholder': 'Type a message, press Enter to send';
'welcome.rec.title': 'Recommended assistants';
'welcome.rec.code.title': 'Write code';
'welcome.rec.code.desc': 'Help me write, explain, or debug code';
'welcome.rec.search.title': 'Search';
'welcome.rec.search.desc': 'Look up info, docs, or answers';
'welcome.rec.idea.title': 'Brainstorm';
'welcome.rec.idea.desc': 'Generate ideas, names, or copy';
'welcome.quick.feedback': 'Feedback';
'welcome.quick.feedback_desc': 'Submit an issue or suggestion';
'welcome.quick.github': 'GitHub';
'welcome.quick.github_desc': 'View source code';
'welcome.quick.webui': 'WebUI';
'welcome.quick.webui_desc': 'Open in browser';
'welcome.quick.webui_unavailable': 'Unavailable';
```

**Steps:**

1. **写测试**（5 min）：
   - 在 `src/shared/lib/i18n/__tests__/welcome-translations.test.ts` 写：
     - 测试 `TranslationKey` 类型包含所有 `welcome.*` 键（编译时检查）
     - 测试 `zh` 字典对每个 welcome 键都有非空字符串
     - 测试 `en` 字典对每个 welcome 键都有非空字符串
     - 测试 zh 与 en 的 key 集合完全一致
   - 运行 `npm run test:run -- src/shared/lib/i18n/__tests__/welcome-translations.test.ts`，**确认 RED**（键还不存在）

2. **实现 zh.ts**（2 min）：
   - 在 `// ─── 欢迎屏 ────────────────` 注释段添加上述中文键
   - 运行测试，**确认 zh 部分 GREEN**

3. **实现 en.ts**（2 min）：
   - 镜像添加英文键
   - 运行测试，**确认全 GREEN**

4. **回归验证**（1 min）：
   - 运行 `npm run test:run` 全套，确认不破坏现有测试

5. **Commit**：
   ```bash
   git add src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts \
           src/shared/lib/i18n/__tests__/welcome-translations.test.ts
   git commit -m "feat(i18n): add welcome.* translation keys for Phase 7"
   ```

---

### P7-T02：创建 `useTypewriterPlaceholder` hook（TDD）

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/features/welcome/useTypewriterPlaceholder.ts`
  - `/home/fz/project/sage/src/features/welcome/__tests__/useTypewriterPlaceholder.test.ts`

**Interfaces:**

- Consumes: `phrases: string[]`（必填，非空数组）
- Produces: `{ current: string; isTyping: boolean }`
  - `current` — 当前显示的字符片段（如 "帮我写"）
  - `isTyping` — 正在打字（true）或在短语间隔/已结束（false）
- 副作用：`setTimeout` 在 50ms 推进 `phraseIndex` + `charIndex`；卸载时清理

**内部状态机：**
```
phase = 'typing' → 'pausing' → 'typing' (next phrase) → ...
phraseIndex: 0..phrases.length-1, 循环
charIndex: 0..phrases[phraseIndex].length
typeInterval = 50ms
pauseInterval = 1000ms（每条短语打完后停顿 1s 再切下一条）
```

**Steps:**

1. **写测试**（10 min）— 5 个测试覆盖关键路径：

   ```typescript
   import { renderHook, act } from '@testing-library/react';
   import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
   import { useTypewriterPlaceholder } from '../useTypewriterPlaceholder';

   describe('useTypewriterPlaceholder', () => {
     beforeEach(() => { vi.useFakeTimers(); });
     afterEach(() => { vi.useRealTimers(); });

     it('starts with the first character of the first phrase', () => {
       const { result } = renderHook(() =>
         useTypewriterPlaceholder(['hello world', 'second phrase']),
       );
       expect(result.current.current).toBe('h');
       expect(result.current.isTyping).toBe(true);
     });

     it('advances one character every 50ms while typing', () => {
       const { result } = renderHook(() =>
         useTypewriterPlaceholder(['hi']),
       );
       act(() => { vi.advanceTimersByTime(50); });
       expect(result.current.current).toBe('hi');
     });

     it('pauses after completing a phrase, then advances to next phrase', () => {
       const { result } = renderHook(() =>
         useTypewriterPlaceholder(['ab', 'cd']),
       );
       // 打 'ab'：t=0→'a'，t=50→'ab'
       act(() => { vi.advanceTimersByTime(50); });
       expect(result.current.current).toBe('ab');
       expect(result.current.isTyping).toBe(false);
       // 暂停 1s 后切到下一条
       act(() => { vi.advanceTimersByTime(1000); });
       expect(result.current.current).toBe('c');
       expect(result.current.isTyping).toBe(true);
     });

     it('cycles back to the first phrase after the last one', () => {
       const { result } = renderHook(() =>
         useTypewriterPlaceholder(['x', 'y']),
       );
       // 推进到 'x' 完成
       act(() => { vi.advanceTimersByTime(50); });
       expect(result.current.current).toBe('x');
       act(() => { vi.advanceTimersByTime(1000); });
       expect(result.current.current).toBe('y');
       act(() => { vi.advanceTimersByTime(50); });
       expect(result.current.current).toBe('y');
       act(() => { vi.advanceTimersByTime(1000); });
       expect(result.current.current).toBe('x');
     });

     it('clears interval on unmount (no leaked timers)', () => {
       const clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval');
       const { unmount } = renderHook(() =>
         useTypewriterPlaceholder(['test']),
       );
       unmount();
       expect(clearIntervalSpy).toHaveBeenCalled();
       clearIntervalSpy.mockRestore();
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **实现 hook**（8 min）— 完整可运行代码：

   ```typescript
   // /home/fz/project/sage/src/features/welcome/useTypewriterPlaceholder.ts
   import { useEffect, useRef, useState } from 'react';

   interface TypewriterState {
     current: string;
     isTyping: boolean;
   }

   const TYPE_INTERVAL_MS = 50;
   const PAUSE_INTERVAL_MS = 1000;

   export function useTypewriterPlaceholder(phrases: string[]): TypewriterState {
     const [phraseIndex, setPhraseIndex] = useState(0);
     const [charIndex, setCharIndex] = useState(0);
     const [isTyping, setIsTyping] = useState(true);
     const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

     const safePhrases = phrases.length > 0 ? phrases : [''];
     const currentPhrase = safePhrases[phraseIndex] ?? '';

     useEffect(() => {
       // 卸载清理
       if (timerRef.current) {
         clearTimeout(timerRef.current);
         timerRef.current = null;
       }

       if (charIndex < currentPhrase.length) {
         // 还在打字阶段
         setIsTyping(true);
         timerRef.current = setTimeout(() => {
           setCharIndex((ci) => ci + 1);
         }, TYPE_INTERVAL_MS);
       } else {
         // 短语打完了，进入暂停
         setIsTyping(false);
         timerRef.current = setTimeout(() => {
           setPhraseIndex((pi) => (pi + 1) % safePhrases.length);
           setCharIndex(0);
         }, PAUSE_INTERVAL_MS);
       }

       return () => {
         if (timerRef.current) {
           clearTimeout(timerRef.current);
           timerRef.current = null;
         }
       };
     }, [charIndex, phraseIndex, currentPhrase, safePhrases.length]);

     return {
       current: currentPhrase.slice(0, charIndex),
       isTyping,
     };
   }
   ```

3. **运行测试**（1 min）— **确认 GREEN**

4. **Commit**：
   ```bash
   git add src/features/welcome/useTypewriterPlaceholder.ts \
           src/features/welcome/__tests__/useTypewriterPlaceholder.test.ts
   git commit -m "feat(welcome): add useTypewriterPlaceholder hook with TDD"
   ```

---

### P7-T03：创建 `entities/welcome/recommendations` 数据

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/entities/welcome/recommendations.ts`
  - `/home/fz/project/sage/src/entities/welcome/__tests__/recommendations.test.ts`

**Interfaces:**

- Consumes: 无外部依赖
- Produces:
  - `AssistantRecommendation` 接口
  - `lucideIconMap: Record<string, LucideIcon>` 映射表
  - `defaultRecommendations: AssistantRecommendation[]`（3 条默认数据：写代码 / 搜索 / 创意）

**Steps:**

1. **写测试**（5 min）：

   ```typescript
   import { describe, expect, it } from 'vitest';
   import {
     type AssistantRecommendation,
     defaultRecommendations,
     lucideIconMap,
   } from '../recommendations';

   describe('recommendations data', () => {
     it('exports exactly 3 default recommendations', () => {
       expect(defaultRecommendations).toHaveLength(3);
     });

     it('every recommendation has all required fields', () => {
       defaultRecommendations.forEach((rec: AssistantRecommendation) => {
         expect(rec.id).toBeTruthy();
         expect(rec.title).toBeTruthy();
         expect(rec.prompt).toBeTruthy();
         expect(rec.icon).toBeTruthy();
         expect(rec.gradient).toBeTruthy();
       });
     });

     it('every icon name has a corresponding lucide icon component', () => {
       defaultRecommendations.forEach((rec) => {
         expect(lucideIconMap[rec.icon]).toBeDefined();
       });
     });

     it('default recommendations include code, search, and idea themes', () => {
       const ids = defaultRecommendations.map((r) => r.id);
       expect(ids).toContain('code');
       expect(ids).toContain('search');
       expect(ids).toContain('idea');
     });

     it('gradient is a valid tailwind class string', () => {
       defaultRecommendations.forEach((rec) => {
         expect(rec.gradient).toMatch(/^bg-gradient-to-/);
       });
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **实现**（3 min）— 完整可运行：

   ```typescript
   // /home/fz/project/sage/src/entities/welcome/recommendations.ts
   import { Code2, Search, Lightbulb, type LucideIcon } from 'lucide-react';

   export interface AssistantRecommendation {
     id: string;
     title: string;
     prompt: string;
     icon: string; // lucide-react icon name
     gradient: string; // tailwind gradient class
   }

   export const lucideIconMap: Record<string, LucideIcon> = {
     Code2,
     Search,
     Lightbulb,
   };

   export const defaultRecommendations: AssistantRecommendation[] = [
     {
       id: 'code',
       title: 'write-code',
       prompt: '帮我写代码：',
       icon: 'Code2',
       gradient: 'bg-gradient-to-br from-blue-500 to-indigo-600',
     },
     {
       id: 'search',
       title: 'search-info',
       prompt: '帮我搜索：',
       icon: 'Search',
       gradient: 'bg-gradient-to-br from-emerald-500 to-teal-600',
     },
     {
       id: 'idea',
       title: 'brainstorm',
       prompt: '帮我脑暴：',
       icon: 'Lightbulb',
       gradient: 'bg-gradient-to-br from-amber-500 to-orange-600',
     },
   ];
   ```

   - 注：`title` 字段使用 i18n key 而非硬编码字符串（在 `AssistantRecommendations.tsx` 中通过 `t(rec.title)` 翻译）。这样测试只检查 title 非空，具体翻译在组件层验证。

3. **运行测试**（1 min）— **确认 GREEN**

4. **Commit**：
   ```bash
   git add src/entities/welcome/recommendations.ts \
           src/entities/welcome/__tests__/recommendations.test.ts
   git commit -m "feat(welcome): add AssistantRecommendation data with 3 defaults"
   ```

---

### P7-T04：创建 `WelcomeHero` 组件

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/widgets/welcome/WelcomeHero.tsx`
  - `/home/fz/project/sage/src/widgets/welcome/__tests__/WelcomeHero.test.tsx`

**Interfaces:**

```typescript
interface WelcomeHeroProps {
  onBack?: () => void; // 可选：点击返回按钮时触发
}
```

- Consumes: `useI18n()`（翻译键）、`useNavigate()`（默认 back 行为）
- Produces: 居中渲染的头像 + 标题 + 副标题 + 可选返回按钮

**Steps:**

1. **写测试**（8 min）：

   ```typescript
   import { render, screen, fireEvent } from '@testing-library/react';
   import { MemoryRouter } from 'react-router-dom';
   import { describe, expect, it, vi } from 'vitest';
   import { I18nProvider } from '../../../shared/lib/i18n';
   import { WelcomeHero } from '../WelcomeHero';

   function renderWithRouter(ui: React.ReactNode) {
     return render(
       <I18nProvider defaultLocale="zh">
         <MemoryRouter>{ui}</MemoryRouter>
       </I18nProvider>,
     );
   }

   describe('WelcomeHero', () => {
     it('renders greeting and subtitle in default locale (zh)', () => {
       renderWithRouter(<WelcomeHero />);
       expect(screen.getByText(/你好，我是 Claude/)).toBeInTheDocument();
       expect(screen.getByText(/有什么可以帮你的/)).toBeInTheDocument();
     });

     it('renders a back button with the correct i18n label', () => {
       renderWithRouter(<WelcomeHero onBack={vi.fn()} />);
       expect(screen.getByRole('button', { name: /返回/ })).toBeInTheDocument();
     });

     it('does not render back button when onBack is not provided', () => {
       renderWithRouter(<WelcomeHero />);
       expect(screen.queryByRole('button', { name: /返回/ })).not.toBeInTheDocument();
     });

     it('invokes onBack when back button is clicked', () => {
       const onBack = vi.fn();
       renderWithRouter(<WelcomeHero onBack={onBack} />);
       fireEvent.click(screen.getByRole('button', { name: /返回/ }));
       expect(onBack).toHaveBeenCalledTimes(1);
     });

     it('has data-testid for avatar element', () => {
       const { container } = renderWithRouter(<WelcomeHero />);
       expect(container.querySelector('[data-testid="welcome-avatar"]')).toBeInTheDocument();
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **实现**（5 min）— 完整可运行：

   ```typescript
   // /home/fz/project/sage/src/widgets/welcome/WelcomeHero.tsx
   import { Sparkles, ArrowLeft } from 'lucide-react';

   import { useI18n } from '../../shared/lib/i18n';

   interface WelcomeHeroProps {
     onBack?: () => void;
   }

   export function WelcomeHero({ onBack }: WelcomeHeroProps) {
     const { t } = useI18n();

     return (
       <div className="flex flex-col items-center gap-3 text-center">
         {onBack && (
           <button
             type="button"
             onClick={onBack}
             className="self-start inline-flex items-center gap-1 text-xs text-text-secondary hover:text-text transition-colors"
             aria-label={t('welcome.hero.back')}
           >
             <ArrowLeft className="w-3.5 h-3.5" />
             <span>{t('welcome.hero.back')}</span>
           </button>
         )}

         <div
           data-testid="welcome-avatar"
           className="w-16 h-16 rounded-full bg-gradient-to-br from-primary to-primary-hover flex items-center justify-center text-text-inverse shadow-lg"
         >
           <Sparkles className="w-8 h-8" />
         </div>

         <h1 className="text-2xl font-semibold text-text">{t('welcome.hero.greeting')}</h1>
         <p className="text-sm text-text-tertiary">{t('welcome.hero.subtitle')}</p>
       </div>
     );
   }
   ```

3. **运行测试**（1 min）— **确认 GREEN**

4. **Commit**：
   ```bash
   git add src/widgets/welcome/WelcomeHero.tsx \
           src/widgets/welcome/__tests__/WelcomeHero.test.tsx
   git commit -m "feat(welcome): add WelcomeHero component with avatar and i18n"
   ```

---

### P7-T05：从 `ChatInput` 抽出 `<InputCard />` 子组件

**Files:**

- **Modify:**
  - `/home/fz/project/sage/src/widgets/chat/ChatInput.tsx`（保留外部 API，内部用 InputCard 重构）
  - `/home/fz/project/sage/src/widgets/chat/index.ts`（导出新组件供 welcome 复用）
- **Create:**
  - `/home/fz/project/sage/src/widgets/chat/InputCard.tsx`（新子组件）
  - `/home/fz/project/sage/src/widgets/chat/__tests__/InputCard.test.tsx`

**Interfaces:**

```typescript
// /home/fz/project/sage/src/widgets/chat/InputCard.tsx
interface InputCardProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  disabled?: boolean;
  isLoading?: boolean;
  onInterrupt?: () => void;
  autoFocus?: boolean;
  // attachments and slash command 支持（与 ChatInput 共享）
  files?: FileAttachment[];
  images?: ImageAttachment[];
  knowledgeRefs?: KnowledgeRef[];
  onRemoveFile?: (idx: number) => void;
  onRemoveImage?: (idx: number) => void;
  onRemoveKnowledge?: (idx: number) => void;
  onToggleKnowledge?: (docId: string) => void;
  onImageSelect?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onFileSelect?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onDrop?: (e: React.DragEvent) => void;
  onDragOver?: (e: React.DragEvent) => void;
  isDragOver?: boolean;
  showSlashMenu?: boolean;
  slashCommands?: SlashCommand[];
  slashSelectedIndex?: number;
  onSlashSelect?: (cmd: SlashCommand) => void;
}
```

**重构策略：**
- 把 `ChatInput` 中"textarea + 附件 chips + 工具栏 + 发送按钮 + slash 菜单 + knowledge 弹层"这一整块 UI 抽到 `InputCard`。
- `InputCard` 接收**纯 props**（无内部 state，所有 state 由父组件管理）。
- `ChatInput` 内部维护原有 state，通过 props 全部传给 `InputCard`。
- 这样 Chat.tsx 的现有行为不变，Welcome 可以**独立维护自己的 state** 并传同一个 `InputCard` 进去。

**Steps:**

1. **写 `InputCard` 测试**（10 min）— 覆盖关键交互：

   ```typescript
   import { render, screen, fireEvent } from '@testing-library/react';
   import { describe, expect, it, vi } from 'vitest';
   import { InputCard } from '../InputCard';

   describe('InputCard', () => {
     it('renders textarea with placeholder', () => {
       render(<InputCard value="" onChange={vi.fn()} onSubmit={vi.fn()} placeholder="type here" />);
       expect(screen.getByPlaceholderText('type here')).toBeInTheDocument();
     });

     it('calls onChange when typing', () => {
       const onChange = vi.fn();
       render(<InputCard value="" onChange={onChange} onSubmit={vi.fn()} />);
       fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hi' } });
       expect(onChange).toHaveBeenCalledWith('hi');
     });

     it('calls onSubmit on Enter key', () => {
       const onSubmit = vi.fn();
       render(<InputCard value="hello" onChange={vi.fn()} onSubmit={onSubmit} />);
       fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', shiftKey: false });
       expect(onSubmit).toHaveBeenCalledTimes(1);
     });

     it('does not call onSubmit on Shift+Enter', () => {
       const onSubmit = vi.fn();
       render(<InputCard value="hello" onChange={vi.fn()} onSubmit={onSubmit} />);
       fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', shiftKey: true });
       expect(onSubmit).not.toHaveBeenCalled();
     });

     it('disables textarea when disabled prop is true', () => {
       render(<InputCard value="" onChange={vi.fn()} onSubmit={vi.fn()} disabled />);
       expect(screen.getByRole('textbox')).toBeDisabled();
     });

     it('auto-focuses textarea when autoFocus is true', () => {
       render(<InputCard value="" onChange={vi.fn()} onSubmit={vi.fn()} autoFocus />);
       expect(screen.getByRole('textbox')).toHaveFocus();
     });

     it('shows send button disabled when value is empty', () => {
       render(<InputCard value="" onChange={vi.fn()} onSubmit={vi.fn()} />);
       expect(screen.getByRole('button', { name: /发送/ })).toBeDisabled();
     });

     it('shows interrupt button when isLoading is true', () => {
       const onInterrupt = vi.fn();
       render(
         <InputCard
           value="hi"
           onChange={vi.fn()}
           onSubmit={vi.fn()}
           isLoading
           onInterrupt={onInterrupt}
         />,
       );
       fireEvent.click(screen.getByRole('button', { name: /停止/ }));
       expect(onInterrupt).toHaveBeenCalled();
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **创建 `InputCard.tsx`**（15 min）— 把 `ChatInput.tsx` 第 183-376 行的 JSX 抽出来，把所有内部 state 替换为 props：

   ```typescript
   // /home/fz/project/sage/src/widgets/chat/InputCard.tsx
   import { Send, Square, Image, Paperclip, BookOpen } from 'lucide-react';

   import { useI18n } from '../../shared/lib/i18n';
   import { FileAttachment as FileAttachmentChip } from './FileAttachment';
   import { KnowledgeChip } from './KnowledgeChip';
   import { SlashCommandMenu } from './SlashCommandMenu';
   import type { SlashCommand } from './slashCommands';

   export interface FileAttachment {
     name: string;
     size: number;
     type: string;
     dataUrl?: string;
   }

   export interface ImageAttachment extends FileAttachment {}

   export interface KnowledgeRef {
     id: string;
     title: string;
   }

   export interface KnowledgeDoc {
     id: string;
     title: string;
     desc: string;
   }

   export interface InputCardProps {
     value: string;
     onChange: (value: string) => void;
     onSubmit: () => void;
     placeholder?: string;
     disabled?: boolean;
     isLoading?: boolean;
     onInterrupt?: () => void;
     autoFocus?: boolean;

     // Attachments (optional)
     files?: FileAttachment[];
     images?: ImageAttachment[];
     knowledgeRefs?: KnowledgeRef[];
     onRemoveFile?: (idx: number) => void;
     onRemoveImage?: (idx: number) => void;
     onRemoveKnowledge?: (idx: number) => void;

     // Knowledge selector
     knowledgeDocs?: KnowledgeDoc[];
     showKnowledgeSelector?: boolean;
     onToggleKnowledgeSelector?: (show: boolean) => void;
     onToggleKnowledge?: (docId: string) => void;

     // File / image picker
     onImageSelect?: (e: React.ChangeEvent<HTMLInputElement>) => void;
     onFileSelect?: (e: React.ChangeEvent<HTMLInputElement>) => void;

     // Drag & drop
     onDrop?: (e: React.DragEvent) => void;
     onDragOver?: (e: React.DragEvent) => void;
     isDragOver?: boolean;

     // Slash menu
     showSlashMenu?: boolean;
     slashCommands?: SlashCommand[];
     slashSelectedIndex?: number;
     onSlashSelect?: (cmd: SlashCommand) => void;

     // Footer hint
     hint?: string;
   }

   export function InputCard({
     value,
     onChange,
     onSubmit,
     placeholder = '',
     disabled = false,
     isLoading = false,
     onInterrupt,
     autoFocus = false,
     files = [],
     images = [],
     knowledgeRefs = [],
     onRemoveFile,
     onRemoveImage,
     onRemoveKnowledge,
     knowledgeDocs = [],
     showKnowledgeSelector = false,
     onToggleKnowledgeSelector,
     onToggleKnowledge,
     onImageSelect,
     onFileSelect,
     onDrop,
     onDragOver,
     isDragOver = false,
     showSlashMenu = false,
     slashCommands = [],
     slashSelectedIndex = 0,
     onSlashSelect,
     hint,
   }: InputCardProps) {
     const { t } = useI18n();
     const hasAttachments = files.length > 0 || images.length > 0 || knowledgeRefs.length > 0;

     const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
       if (showSlashMenu && slashCommands.length > 0) {
         if (e.key === 'ArrowDown') {
           e.preventDefault();
           return;
         }
         if (e.key === 'ArrowUp') {
           e.preventDefault();
           return;
         }
         if (e.key === 'Enter') {
           e.preventDefault();
           const cmd = slashCommands[slashSelectedIndex];
           if (cmd) onSlashSelect?.(cmd);
           return;
         }
         if (e.key === 'Escape') {
           e.preventDefault();
           return;
         }
       }
       if (e.key === 'Enter' && !e.shiftKey) {
         e.preventDefault();
         onSubmit();
       }
     };

     return (
       <div
         className="p-4 border border-border rounded-radius-md bg-surface relative shadow-sm"
         onDrop={onDrop}
         onDragOver={onDragOver}
       >
         {isDragOver && (
           <div className="absolute inset-0 bg-primary/10 border-2 border-dashed border-primary rounded-radius-md flex items-center justify-center z-10">
             <p className="text-primary font-medium">{t('chat.drop_files')}</p>
           </div>
         )}

         {images.length > 0 && (
           <div className="flex gap-2 mb-2">
             {images.map((img, idx) => (
               <div
                 key={idx}
                 className="relative w-14 h-14 rounded-radius-sm border border-border overflow-hidden"
               >
                 {img.dataUrl && (
                   <img src={img.dataUrl} alt="" className="w-full h-full object-cover" />
                 )}
                 {onRemoveImage && (
                   <button
                     type="button"
                     className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-text/80 text-text-inverse flex items-center justify-center text-xs"
                     onClick={() => onRemoveImage(idx)}
                     aria-label="remove image"
                   >
                     ×
                   </button>
                 )}
               </div>
             ))}
           </div>
         )}

         {knowledgeRefs.length > 0 && (
           <div className="flex flex-wrap gap-1.5 mb-2">
             {knowledgeRefs.map((ref, idx) => (
               <KnowledgeChip
                 key={ref.id}
                 title={ref.title}
                 onRemove={onRemoveKnowledge ? () => onRemoveKnowledge(idx) : undefined}
               />
             ))}
           </div>
         )}

         {files.length > 0 && (
           <div className="flex flex-wrap gap-1.5 mb-2">
             {files.map((file, idx) => (
               <FileAttachmentChip
                 key={idx}
                 name={file.name}
                 size={file.size}
                 type={file.type}
                 onRemove={onRemoveFile ? () => onRemoveFile(idx) : undefined}
               />
             ))}
           </div>
         )}

         <div className="flex items-end gap-2">
           <div className="flex-1 relative">
             {showSlashMenu && slashCommands.length > 0 && onSlashSelect && (
               <SlashCommandMenu
                 commands={slashCommands}
                 selectedIndex={slashSelectedIndex}
                 onSelect={onSlashSelect}
               />
             )}
             <div className="border border-border rounded-radius-sm px-3 py-2 bg-bg flex items-end gap-2">
               <textarea
                 value={value}
                 onChange={(e) => onChange(e.target.value)}
                 onKeyDown={handleKeyDown}
                 placeholder={placeholder}
                 disabled={disabled}
                 autoFocus={autoFocus}
                 rows={1}
                 className="flex-1 resize-none border-none bg-transparent outline-none text-sm text-text disabled:opacity-50 max-h-[200px] placeholder:text-muted"
                 aria-label="message input"
               />

               <div className="flex items-center gap-1 flex-shrink-0">
                 <button
                   type="button"
                   className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                   title={t('chat.attach_image')}
                   onClick={() => document.getElementById('chat-input-image')?.click()}
                 >
                   <Image className="w-4 h-4" />
                 </button>
                 <button
                   type="button"
                   className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                   title={t('chat.attach_file')}
                   onClick={() => document.getElementById('chat-input-file')?.click()}
                 >
                   <Paperclip className="w-4 h-4" />
                 </button>
                 {onToggleKnowledgeSelector && (
                   <button
                     type="button"
                     className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                     title={t('chat.knowledge_ref')}
                     onClick={() => onToggleKnowledgeSelector(!showKnowledgeSelector)}
                   >
                     <BookOpen className="w-4 h-4" />
                   </button>
                 )}
               </div>
             </div>

             {showKnowledgeSelector && knowledgeDocs.length > 0 && onToggleKnowledge && (
               <div className="absolute bottom-full left-0 mb-2 w-72 bg-surface border border-border rounded-radius-md shadow-lg z-20">
                 <div className="p-3">
                   <p className="text-xs font-medium text-text mb-2">{t('chat.knowledge_docs')}</p>
                   {knowledgeDocs.map((doc) => {
                     const isSelected = !!knowledgeRefs.find((r) => r.id === doc.id);
                     return (
                       <button
                         key={doc.id}
                         type="button"
                         className={`w-full text-left px-2 py-1.5 rounded text-xs flex items-center gap-2 transition-colors ${
                           isSelected
                             ? 'bg-primary/10 text-primary'
                             : 'hover:bg-bg-hover text-text-secondary'
                         }`}
                         onClick={() => onToggleKnowledge(doc.id)}
                       >
                         <span
                           className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${
                             isSelected ? 'bg-primary border-primary' : 'border-border'
                           }`}
                         >
                           {isSelected && (
                             <svg
                               width="8"
                               height="8"
                               viewBox="0 0 24 24"
                               fill="none"
                               stroke="white"
                               strokeWidth="4"
                             >
                               <polyline points="20 6 9 17 4 12" />
                             </svg>
                           )}
                         </span>
                         <div>
                           <div className="font-medium">{doc.title}</div>
                           <div className="text-muted">{doc.desc}</div>
                         </div>
                       </button>
                     );
                   })}
                 </div>
               </div>
             )}
           </div>

           {isLoading ? (
             <button
               type="button"
               onClick={onInterrupt}
               title={t('chat.stop')}
               className="h-9 px-4 bg-error text-text-inverse border-none rounded-radius-sm text-sm font-medium cursor-pointer flex items-center gap-1.5 hover:bg-error/90 transition-colors"
             >
               <Square className="w-3.5 h-3.5" />
             </button>
           ) : (
             <button
               type="button"
               onClick={onSubmit}
               disabled={(!value.trim() && !hasAttachments) || disabled}
               className="h-9 px-4 bg-primary text-text-inverse border-none rounded-radius-sm text-sm font-medium cursor-pointer flex items-center gap-1.5 hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
             >
               {t('chat.send')}
               <Send className="w-3.5 h-3.5" />
             </button>
           )}
         </div>

         {onImageSelect && (
           <input
             type="file"
             id="chat-input-image"
             accept="image/*"
             multiple
             className="hidden"
             onChange={onImageSelect}
           />
         )}
         {onFileSelect && (
           <input
             type="file"
             id="chat-input-file"
             multiple
             className="hidden"
             onChange={onFileSelect}
           />
         )}

         {hint && (
           <p className="text-[11px] text-muted text-center mt-1.5">{hint}</p>
         )}
       </div>
     );
   }
   ```

3. **重构 `ChatInput.tsx`**（10 min）— 用 `InputCard` 替换内部 JSX：

   ```typescript
   // /home/fz/project/sage/src/widgets/chat/ChatInput.tsx (refactored)
   import { useState, useRef, useCallback } from 'react';

   import { useFileUpload } from '../../shared/lib/hooks/useFileUpload';
   import { useI18n } from '../../shared/lib/i18n';

   import { InputCard, type KnowledgeDoc } from './InputCard';
   import { commandToPrompt, filterCommands, type SlashCommand } from './slashCommands';

   interface ChatInputProps {
     onSend: (
       message: string,
       options?: {
         knowledgeRefs?: { id: string; title: string }[];
         attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
         images?: { name: string; size: number; type: string; dataUrl?: string }[];
       },
     ) => void;
     onInterrupt?: () => void;
     onClear?: () => void;
     isLoading?: boolean;
     disabled?: boolean;
     placeholder?: string;
   }

   const KNOWLEDGE_DOCS: KnowledgeDoc[] = [
     { id: 'prd', title: '产品需求文档', desc: 'Sage 核心功能定义' },
     { id: 'api-docs', title: 'API 接口文档', desc: '内部 API 网关说明' },
     { id: 'deploy-guide', title: '部署指南', desc: 'Windows 环境部署步骤' },
     { id: 'memory-arch', title: '记忆系统架构', desc: '本地存储与同步策略' },
     { id: 'ui-spec', title: 'UI 设计规范', desc: '设计令牌与组件库' },
     { id: 'test-data', title: '测试数据集', desc: '样本对话和测试用例' },
   ];

   export function ChatInput({
     onSend,
     onInterrupt,
     onClear,
     isLoading = false,
     disabled = false,
     placeholder,
   }: ChatInputProps) {
     const { t } = useI18n();
     const [value, setValue] = useState('');
     const [knowledgeRefs, setKnowledgeRefs] = useState<{ id: string; title: string }[]>([]);
     const [showKnowledgeSelector, setShowKnowledgeSelector] = useState(false);
     const [slashMenuOpen, setSlashMenuOpen] = useState(false);
     const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
     const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);

     const {
       files,
       images,
       addFile,
       addImage,
       removeFile,
       removeImage,
       clearAll,
       handleDrop,
       handleDragOver,
       isDragOver,
     } = useFileUpload();

     const handleSend = () => {
       if (!value.trim() || isLoading) return;
       onSend(value.trim(), {
         knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : undefined,
         attachments: files.length > 0 ? files : undefined,
         images: images.length > 0 ? images : undefined,
       });
       setValue('');
       setKnowledgeRefs([]);
       clearAll();
     };

     const handleInput = (newValue: string) => {
       setValue(newValue);
       if (newValue.startsWith('/')) {
         const query = newValue.slice(1).split(/\s/)[0] ?? '';
         const filtered = filterCommands(query);
         if (filtered.length > 0) {
           setSlashCommands(filtered);
           setSlashSelectedIndex(0);
           setSlashMenuOpen(true);
         } else {
           setSlashMenuOpen(false);
         }
       } else {
         setSlashMenuOpen(false);
       }
     };

     const handleSlashSelect = useCallback(
       (cmd: SlashCommand) => {
         setSlashMenuOpen(false);
         if (cmd.mode === 'clear') {
           setValue('');
           onClear?.();
           return;
         }
         if (cmd.mode === 'help') {
           const helpText = slashCommands.map((c) => `/${c.name} — ${c.description}`).join('\n');
           setValue('');
           onSend(`可用命令列表：\n${helpText}`);
           return;
         }
         const parts = value.split(/\s+/);
         const args = parts.slice(1).join(' ');
         const prompt = commandToPrompt(cmd, args);
         setValue('');
         onSend(prompt);
       },
       [value, onSend, onClear, slashCommands],
     );

     const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
       const selectedFiles = e.target.files;
       if (!selectedFiles) return;
       Array.from(selectedFiles).forEach(addImage);
       e.target.value = '';
     };

     const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
       const selectedFiles = e.target.files;
       if (!selectedFiles) return;
       Array.from(selectedFiles).forEach(addFile);
       e.target.value = '';
     };

     const toggleKnowledgeRef = (docId: string) => {
       const doc = KNOWLEDGE_DOCS.find((d) => d.id === docId);
       if (!doc) return;
       setKnowledgeRefs((prev) =>
         prev.find((r) => r.id === docId)
           ? prev.filter((r) => r.id !== docId)
           : [...prev, { id: doc.id, title: doc.title }],
       );
     };

     return (
       <InputCard
         value={value}
         onChange={handleInput}
         onSubmit={handleSend}
         placeholder={placeholder ?? t('chat.placeholder')}
         disabled={disabled}
         isLoading={isLoading}
         onInterrupt={onInterrupt}
         autoFocus={false}
         files={files}
         images={images}
         knowledgeRefs={knowledgeRefs}
         onRemoveFile={removeFile}
         onRemoveImage={removeImage}
         onRemoveKnowledge={(idx) =>
           setKnowledgeRefs((prev) => prev.filter((_, i) => i !== idx))
         }
         knowledgeDocs={KNOWLEDGE_DOCS}
         showKnowledgeSelector={showKnowledgeSelector}
         onToggleKnowledgeSelector={setShowKnowledgeSelector}
         onToggleKnowledge={toggleKnowledgeRef}
         onImageSelect={handleImageSelect}
         onFileSelect={handleFileSelect}
         onDrop={handleDrop}
         onDragOver={handleDragOver}
         isDragOver={isDragOver}
         showSlashMenu={slashMenuOpen}
         slashCommands={slashCommands}
         slashSelectedIndex={slashSelectedIndex}
         onSlashSelect={handleSlashSelect}
         hint={t('chat.hint')}
       />
     );
   }
   ```

4. **更新 `widgets/chat/index.ts`**（1 min）— 导出 InputCard：

   ```typescript
   export { ChatInput } from './ChatInput';
   export { MessageList } from './MessageList';
   export { Message } from './Message';
   export { ActiveAgentIndicator } from './ActiveAgentIndicator';
   export { InputCard, type InputCardProps } from './InputCard';
   ```

5. **运行测试**（2 min）：
   - `npm run test:run -- src/widgets/chat/__tests__/InputCard.test.tsx` — 确认 GREEN
   - `npm run test:run -- src/widgets/chat/__tests__/ChatInput.disabled.test.tsx` — 确认仍 GREEN（行为兼容）
   - `npm run test:run` — 全套 GREEN
   - `npm run typecheck` — 确认无 TypeScript 错误

6. **Commit**：
   ```bash
   git add src/widgets/chat/ChatInput.tsx src/widgets/chat/InputCard.tsx \
           src/widgets/chat/index.ts \
           src/widgets/chat/__tests__/InputCard.test.tsx
   git commit -m "refactor(chat): extract reusable InputCard from ChatInput"
   ```

---

### P7-T06：创建 `WelcomeInputCard` 组件（包装 InputCard）

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/widgets/welcome/WelcomeInputCard.tsx`
  - `/home/fz/project/sage/src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx`

**Interfaces:**

```typescript
interface WelcomeInputCardProps {
  initialValue?: string;             // 来自推荐卡片的预填值
  placeholder: string;               // typewriter 实时文本
  onSubmit: (value: string) => void; // 用户按 Enter 时回调
  onChange?: (value: string) => void;
  disabled?: boolean;
}
```

- Consumes: `InputCard`（来自 widgets/chat）
- Produces: 居中大输入框（max-width, 大字号, 阴影呼吸效果）

**Steps:**

1. **写测试**（8 min）：

   ```typescript
   import { render, screen, fireEvent } from '@testing-library/react';
   import { I18nProvider } from '../../../shared/lib/i18n';
   import { describe, expect, it, vi } from 'vitest';
   import { WelcomeInputCard } from '../WelcomeInputCard';

   function renderWithI18n(ui: React.ReactNode) {
     return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
   }

   describe('WelcomeInputCard', () => {
     it('renders textarea with the provided placeholder', () => {
       renderWithI18n(
         <WelcomeInputCard
           placeholder="Type here"
           onSubmit={vi.fn()}
         />,
       );
       expect(screen.getByPlaceholderText('Type here')).toBeInTheDocument();
     });

     it('auto-focuses the textarea on mount', () => {
       renderWithI18n(
         <WelcomeInputCard placeholder="Type" onSubmit={vi.fn()} />,
       );
       expect(screen.getByRole('textbox')).toHaveFocus();
     });

     it('calls onSubmit with trimmed value on Enter', () => {
       const onSubmit = vi.fn();
       renderWithI18n(
         <WelcomeInputCard placeholder="Type" onSubmit={onSubmit} />,
       );
       const textarea = screen.getByRole('textbox');
       fireEvent.change(textarea, { target: { value: '  hello world  ' } });
       fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
       expect(onSubmit).toHaveBeenCalledWith('hello world');
     });

     it('does not call onSubmit when value is empty or whitespace', () => {
       const onSubmit = vi.fn();
       renderWithI18n(
         <WelcomeInputCard placeholder="Type" onSubmit={onSubmit} />,
       );
       const textarea = screen.getByRole('textbox');
       fireEvent.change(textarea, { target: { value: '   ' } });
       fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
       expect(onSubmit).not.toHaveBeenCalled();
     });

     it('syncs initial value when initialValue prop changes', () => {
       const onChange = vi.fn();
       const { rerender } = renderWithI18n(
         <WelcomeInputCard
           placeholder="Type"
           onSubmit={vi.fn()}
           initialValue="preset"
           onChange={onChange}
         />,
       );
       expect(screen.getByRole('textbox')).toHaveValue('preset');
     });

     it('disables send button when value is empty', () => {
       renderWithI18n(
         <WelcomeInputCard placeholder="Type" onSubmit={vi.fn()} />,
       );
       expect(screen.getByRole('button', { name: /发送/ })).toBeDisabled();
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **实现**（5 min）— 完整可运行：

   ```typescript
   // /home/fz/project/sage/src/widgets/welcome/WelcomeInputCard.tsx
   import { useEffect, useState } from 'react';

   import { InputCard } from '../chat/InputCard';

   interface WelcomeInputCardProps {
     initialValue?: string;
     placeholder: string;
     onSubmit: (value: string) => void;
     onChange?: (value: string) => void;
     disabled?: boolean;
   }

   export function WelcomeInputCard({
     initialValue = '',
     placeholder,
     onSubmit,
     onChange,
     disabled = false,
   }: WelcomeInputCardProps) {
     const [value, setValue] = useState(initialValue);

     // 当 initialValue 变化时同步（例如点击了推荐卡片）
     useEffect(() => {
       setValue(initialValue);
       onChange?.(initialValue);
     }, [initialValue, onChange]);

     const handleChange = (newValue: string) => {
       setValue(newValue);
       onChange?.(newValue);
     };

     const handleSubmit = () => {
       const trimmed = value.trim();
       if (!trimmed) return;
       onSubmit(trimmed);
       setValue('');
     };

     return (
       <div
         className="w-full max-w-2xl mx-auto"
         data-testid="welcome-input-card"
       >
         <div className="focus-within:shadow-[0_0_0_3px_var(--primary-focus-ring)] transition-shadow">
           <InputCard
             value={value}
             onChange={handleChange}
             onSubmit={handleSubmit}
             placeholder={placeholder}
             disabled={disabled}
             autoFocus
             hint={undefined}
           />
         </div>
       </div>
     );
   }
   ```

3. **运行测试**（1 min）— **确认 GREEN**

4. **Commit**：
   ```bash
   git add src/widgets/welcome/WelcomeInputCard.tsx \
           src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx
   git commit -m "feat(welcome): add WelcomeInputCard with autofocus and initial value"
   ```

---

### P7-T07：创建 `AssistantRecommendations` 组件

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/widgets/welcome/AssistantRecommendations.tsx`
  - `/home/fz/project/sage/src/widgets/welcome/__tests__/AssistantRecommendations.test.tsx`

**Interfaces:**

```typescript
interface AssistantRecommendationsProps {
  recommendations: AssistantRecommendation[];
  onSelect: (rec: AssistantRecommendation) => void;
}
```

- Consumes: `useI18n`, `lucideIconMap`（从 entities 读）
- Produces: 3 列网格（移动端 1 列），每张卡片 = 图标 + 标题 + 描述

**Steps:**

1. **写测试**（10 min）：

   ```typescript
   import { render, screen, fireEvent } from '@testing-library/react';
   import { describe, expect, it, vi } from 'vitest';
   import { I18nProvider } from '../../../shared/lib/i18n';
   import { defaultRecommendations, type AssistantRecommendation } from '../../../entities/welcome/recommendations';
   import { AssistantRecommendations } from '../AssistantRecommendations';

   function renderWithI18n(ui: React.ReactNode) {
     return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
   }

   describe('AssistantRecommendations', () => {
     it('renders all provided recommendations', () => {
       renderWithI18n(
         <AssistantRecommendations
           recommendations={defaultRecommendations}
           onSelect={vi.fn()}
         />,
       );
       expect(screen.getByText(/写代码/)).toBeInTheDocument();
       expect(screen.getByText(/搜索/)).toBeInTheDocument();
       expect(screen.getByText(/创意/)).toBeInTheDocument();
     });

     it('renders a card for each recommendation (count matches)', () => {
       renderWithI18n(
         <AssistantRecommendations
           recommendations={defaultRecommendations}
           onSelect={vi.fn()}
         />,
       );
       const cards = screen.getAllByTestId('recommendation-card');
       expect(cards).toHaveLength(3);
     });

     it('calls onSelect with the clicked recommendation', () => {
       const onSelect = vi.fn();
       renderWithI18n(
         <AssistantRecommendations
           recommendations={defaultRecommendations}
           onSelect={onSelect}
         />,
       );
       const codeCard = screen.getAllByTestId('recommendation-card')[0];
       fireEvent.click(codeCard);
       expect(onSelect).toHaveBeenCalledTimes(1);
       expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'code' }));
     });

     it('renders nothing when recommendations is empty', () => {
       renderWithI18n(
         <AssistantRecommendations recommendations={[]} onSelect={vi.fn()} />,
       );
       expect(screen.queryByTestId('recommendation-card')).not.toBeInTheDocument();
     });

     it('falls back gracefully when icon name is missing from map', () => {
       const broken: AssistantRecommendation[] = [
         {
           id: 'broken',
           title: 'broken-rec',
           prompt: 'test',
           icon: 'NonExistentIcon',
           gradient: 'bg-gradient-to-r from-red-500 to-pink-500',
         },
       ];
       renderWithI18n(
         <AssistantRecommendations recommendations={broken} onSelect={vi.fn()} />,
       );
       // 应仍然渲染卡片（不崩溃），但图标区是空 fallback
       expect(screen.getByText(/broken-rec/)).toBeInTheDocument();
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **实现**（5 min）— 完整可运行：

   ```typescript
   // /home/fz/project/sage/src/widgets/welcome/AssistantRecommendations.tsx
   import { useI18n } from '../../shared/lib/i18n';
   import { lucideIconMap } from '../../entities/welcome/recommendations';
   import type { AssistantRecommendation } from '../../entities/welcome/recommendations';

   interface AssistantRecommendationsProps {
     recommendations: AssistantRecommendation[];
     onSelect: (rec: AssistantRecommendation) => void;
   }

   export function AssistantRecommendations({
     recommendations,
     onSelect,
   }: AssistantRecommendationsProps) {
     const { t } = useI18n();

     if (recommendations.length === 0) return null;

     return (
       <section
         className="w-full max-w-2xl mx-auto mt-6"
         aria-label={t('welcome.rec.title')}
       >
         <h2 className="text-xs font-semibold uppercase tracking-wide text-muted mb-3 px-1">
           {t('welcome.rec.title')}
         </h2>
         <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
           {recommendations.map((rec) => {
             const Icon = lucideIconMap[rec.icon];
             return (
               <button
                 key={rec.id}
                 type="button"
                 data-testid="recommendation-card"
                 onClick={() => onSelect(rec)}
                 className="group text-left p-4 rounded-radius-md border border-border bg-surface hover:border-primary/50 hover:-translate-y-0.5 hover:shadow-md transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary/30"
                 aria-label={t(`welcome.rec.${rec.id}.title`)}
               >
                 <div
                   className={`w-10 h-10 rounded-radius-sm flex items-center justify-center text-text-inverse mb-2 ${rec.gradient}`}
                 >
                   {Icon ? <Icon className="w-5 h-5" /> : null}
                 </div>
                 <div className="text-sm font-medium text-text">
                   {t(`welcome.rec.${rec.id}.title`)}
                 </div>
                 <div className="text-xs text-text-tertiary mt-0.5 line-clamp-2">
                   {t(`welcome.rec.${rec.id}.desc`)}
                 </div>
               </button>
             );
           })}
         </div>
       </section>
     );
   }
   ```

3. **运行测试**（1 min）— **确认 GREEN**

4. **Commit**：
   ```bash
   git add src/widgets/welcome/AssistantRecommendations.tsx \
           src/widgets/welcome/__tests__/AssistantRecommendations.test.tsx
   git commit -m "feat(welcome): add AssistantRecommendations grid with 3 default cards"
   ```

---

### P7-T08：创建 `QuickActionBar` 组件

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/widgets/welcome/QuickActionBar.tsx`
  - `/home/fz/project/sage/src/widgets/welcome/__tests__/QuickActionBar.test.tsx`

**Interfaces:**

```typescript
interface QuickAction {
  id: 'feedback' | 'github' | 'webui' | 'docs';
  icon: ReactNode;
  labelKey: TranslationKey;
  descKey?: TranslationKey;
  onClick: () => void;
  badge?: { text: string; variant: 'success' | 'warning' | 'error' };
}

interface QuickActionBarProps {
  actions: QuickAction[];
}
```

- Consumes: `useI18n`
- Produces: 水平排列的按钮组 + 状态 badge

**Steps:**

1. **写测试**（8 min）：

   ```typescript
   import { render, screen, fireEvent } from '@testing-library/react';
   import { MessageCircle, Star, Globe } from 'lucide-react';
   import { describe, expect, it, vi } from 'vitest';
   import { I18nProvider } from '../../../shared/lib/i18n';
   import { QuickActionBar, type QuickAction } from '../QuickActionBar';

   function renderWithI18n(ui: React.ReactNode) {
     return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
   }

   const sampleActions: QuickAction[] = [
     {
       id: 'feedback',
       icon: <MessageCircle className="w-4 h-4" />,
       labelKey: 'welcome.quick.feedback',
       descKey: 'welcome.quick.feedback_desc',
       onClick: vi.fn(),
     },
     {
       id: 'github',
       icon: <Star className="w-4 h-4" />,
       labelKey: 'welcome.quick.github',
       onClick: vi.fn(),
     },
     {
       id: 'webui',
       icon: <Globe className="w-4 h-4" />,
       labelKey: 'welcome.quick.webui',
       onClick: vi.fn(),
       badge: { text: 'Unavailable', variant: 'warning' },
     },
   ];

   describe('QuickActionBar', () => {
     it('renders one button per action', () => {
       renderWithI18n(<QuickActionBar actions={sampleActions} />);
       const buttons = screen.getAllByRole('button');
       expect(buttons).toHaveLength(3);
     });

     it('renders the i18n label for each action', () => {
       renderWithI18n(<QuickActionBar actions={sampleActions} />);
       expect(screen.getByText(/反馈/)).toBeInTheDocument();
       expect(screen.getByText(/GitHub/)).toBeInTheDocument();
       expect(screen.getByText(/WebUI/)).toBeInTheDocument();
     });

     it('invokes onClick when action button is clicked', () => {
       const onClick = vi.fn();
       renderWithI18n(
         <QuickActionBar
           actions={[{ ...sampleActions[0]!, onClick }]}
         />,
       );
       fireEvent.click(screen.getByText(/反馈/));
       expect(onClick).toHaveBeenCalledTimes(1);
     });

     it('shows badge text when badge prop is provided', () => {
       renderWithI18n(<QuickActionBar actions={sampleActions} />);
       expect(screen.getByText('Unavailable')).toBeInTheDocument();
     });

     it('does not show any badge when none provided', () => {
       const noBadge: QuickAction[] = [
         {
           id: 'github',
           icon: <Star className="w-4 h-4" />,
           labelKey: 'welcome.quick.github',
           onClick: vi.fn(),
         },
       ];
       renderWithI18n(<QuickActionBar actions={noBadge} />);
       expect(screen.queryByText('Unavailable')).not.toBeInTheDocument();
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **实现**（5 min）— 完整可运行：

   ```typescript
   // /home/fz/project/sage/src/widgets/welcome/QuickActionBar.tsx
   import type { ReactNode } from 'react';
   import { clsx } from 'clsx';

   import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

   export interface QuickAction {
     id: 'feedback' | 'github' | 'webui' | 'docs';
     icon: ReactNode;
     labelKey: TranslationKey;
     descKey?: TranslationKey;
     onClick: () => void;
     badge?: { text: string; variant: 'success' | 'warning' | 'error' };
   }

   interface QuickActionBarProps {
     actions: QuickAction[];
   }

   const badgeColorMap: Record<NonNullable<QuickAction['badge']>['variant'], string> = {
     success: 'bg-success/15 text-success',
     warning: 'bg-warning/15 text-warning',
     error: 'bg-error/15 text-error',
   };

   export function QuickActionBar({ actions }: QuickActionBarProps) {
     const { t } = useI18n();

     return (
       <div
         className="flex items-center justify-center gap-2 flex-wrap"
         role="toolbar"
         aria-label="quick actions"
       >
         {actions.map((action) => (
           <button
             key={action.id}
             type="button"
             onClick={action.onClick}
             className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-radius-sm border border-border bg-surface hover:bg-bg-hover text-xs text-text-secondary hover:text-text transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30"
             aria-label={action.descKey ? t(action.descKey) : t(action.labelKey)}
           >
             <span aria-hidden="true">{action.icon}</span>
             <span>{t(action.labelKey)}</span>
             {action.badge && (
               <span
                 data-testid="quick-action-badge"
                 className={clsx(
                   'ml-1 px-1.5 py-0.5 rounded text-[10px] font-medium',
                   badgeColorMap[action.badge.variant],
                 )}
               >
                 {action.badge.text}
               </span>
             )}
           </button>
         ))}
       </div>
     );
   }
   ```

3. **运行测试**（1 min）— **确认 GREEN**

4. **Commit**：
   ```bash
   git add src/widgets/welcome/QuickActionBar.tsx \
           src/widgets/welcome/__tests__/QuickActionBar.test.tsx
   git commit -m "feat(welcome): add QuickActionBar with badge support"
   ```

---

### P7-T09：创建 `pages/Welcome.tsx` 主组件（编排所有 widget）

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/pages/Welcome.tsx`
  - `/home/fz/project/sage/src/pages/__tests__/Welcome.test.tsx`
  - `/home/fz/project/sage/src/pages/index.ts`（修改导出 Welcome）

**Interfaces:**

```typescript
// Welcome.tsx 内部使用的 QuickAction 集合
const quickActions: QuickAction[] = [
  { id: 'feedback', icon: <MessageCircle />, onClick: openFeedback },
  { id: 'github', icon: <Star />, onClick: openGitHub },
  { id: 'webui', icon: <Globe />, onClick: openWebUI, badge: ... },
];
```

- Consumes: `useStore`, `useChat`, `useNavigate`, `useI18n`, `useTypewriterPlaceholder`, `defaultRecommendations`
- Produces: 完整欢迎屏 layout

**Steps:**

1. **写测试**（12 min）：

   ```typescript
   import { render, screen, fireEvent, waitFor } from '@testing-library/react';
   import { MemoryRouter } from 'react-router-dom';
   import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
   import { I18nProvider } from '../../shared/lib/i18n';
   import { useStore } from '../../shared/lib/store';
   import { Welcome } from '../Welcome';

   // Mock useChat
   const sendMessageMock = vi.fn();
   vi.mock('../../features/send-message/useChat', () => ({
     useChat: () => ({
       sendMessage: sendMessageMock,
       isLoading: false,
       error: null,
       clearError: vi.fn(),
     }),
   }));

   // Mock sonner toast
   vi.mock('sonner', () => ({
     toast: {
       error: vi.fn(),
       success: vi.fn(),
     },
   }));

   function renderWelcome() {
     return render(
       <I18nProvider defaultLocale="zh">
         <MemoryRouter>
           <Welcome />
         </MemoryRouter>
       </I18nProvider>,
     );
   }

   describe('Welcome page', () => {
     beforeEach(() => {
       sendMessageMock.mockReset();
       sendMessageMock.mockResolvedValue(undefined);
       useStore.setState({
         currentSessionId: null,
         sessions: [],
         messages: [],
         createSession: vi.fn().mockResolvedValue('new-session-id'),
         loadMessages: vi.fn(),
         loadSessions: vi.fn(),
       } as any);
     });

     afterEach(() => {
       vi.useRealTimers();
     });

     it('renders hero, input card, recommendations and quick action bar', () => {
       renderWelcome();
       expect(screen.getByText(/你好，我是 Claude/)).toBeInTheDocument();
       expect(screen.getByTestId('welcome-input-card')).toBeInTheDocument();
       expect(screen.getAllByTestId('recommendation-card')).toHaveLength(3);
       expect(screen.getByRole('toolbar', { name: /quick actions/ })).toBeInTheDocument();
     });

     it('auto-focuses the input card on mount', () => {
       renderWelcome();
       expect(screen.getByRole('textbox')).toHaveFocus();
     });

     it('shows typewriter placeholder text on the input', () => {
       renderWelcome();
       const textarea = screen.getByRole('textbox');
       expect(textarea).toHaveAttribute('placeholder');
       // 至少 placeholder 不为空
       expect(textarea.getAttribute('placeholder')?.length).toBeGreaterThan(0);
     });

     it('creates session and navigates to /chat on submit', async () => {
       const navigateMock = vi.fn();
       vi.doMock('react-router-dom', async () => {
         const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
         return { ...actual, useNavigate: () => navigateMock };
       });

       const { rerender } = render(
         <I18nProvider defaultLocale="zh">
           <MemoryRouter>
             <Welcome />
           </MemoryRouter>
         </I18nProvider>,
       );

       const textarea = screen.getByRole('textbox');
       fireEvent.change(textarea, { target: { value: 'hello' } });
       fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

       await waitFor(() => {
         expect(useStore.getState().createSession).toHaveBeenCalled();
       });
     });

     it('clicking a recommendation card prefills the input', () => {
       renderWelcome();
       const codeCard = screen.getAllByTestId('recommendation-card')[0]!;
       fireEvent.click(codeCard);
       const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
       expect(textarea.value.startsWith('帮我写代码')).toBe(true);
     });
   });
   ```

   - 运行测试，**确认 RED**（部分 mock 调整可能需要）

2. **实现**（10 min）— 完整可运行：

   ```typescript
   // /home/fz/project/sage/src/pages/Welcome.tsx
   import { MessageCircle, Star, Globe } from 'lucide-react';
   import { useCallback, useState } from 'react';
   import { useNavigate } from 'react-router-dom';
   import { toast } from 'sonner';

   import { defaultRecommendations } from '../entities/welcome/recommendations';
   import { useTypewriterPlaceholder } from '../features/welcome/useTypewriterPlaceholder';
   import { useChat } from '../features/send-message/useChat';
   import { useI18n, type TranslationKey } from '../shared/lib/i18n';
   import { useStore } from '../shared/lib/store';
   import { AssistantRecommendations } from '../widgets/welcome/AssistantRecommendations';
   import { QuickActionBar, type QuickAction } from '../widgets/welcome/QuickActionBar';
   import { WelcomeHero } from '../widgets/welcome/WelcomeHero';
   import { WelcomeInputCard } from '../widgets/welcome/WelcomeInputCard';

   const PLACEHOLDER_PHRASES_ZH = [
     '帮我写代码...',
     '解释这段代码...',
     '脑暴一个点子...',
     '总结这篇文章...',
     '翻译成英文...',
   ];

   const PLACEHOLDER_PHRASES_EN = [
     'Help me write code...',
     'Explain this snippet...',
     'Brainstorm an idea...',
     'Summarize this article...',
     'Translate to English...',
   ];

   const GITHUB_URL = 'https://github.com/';
   const WEBUI_URL = 'http://localhost:8765/webui';

   export function Welcome() {
     const { t, locale } = useI18n();
     const navigate = useNavigate();
     const { sendMessage } = useChat();
     const { createSession, setCurrentSessionId } = useStore();

     const phrases = locale === 'zh' ? PLACEHOLDER_PHRASES_ZH : PLACEHOLDER_PHRASES_EN;
     const { current: typewriterText } = useTypewriterPlaceholder(phrases);
     const placeholder = typewriterText + '|';

     const [prefill, setPrefill] = useState('');

     const handleRecommendationSelect = useCallback((rec: { prompt: string }) => {
       setPrefill(rec.prompt);
     }, []);

     const handleSubmit = useCallback(
       async (value: string) => {
         try {
           const sessionId = await createSession();
           setCurrentSessionId(sessionId);
           await sendMessage(value, sessionId);
           navigate('/chat');
         } catch (error: unknown) {
           const message = error instanceof Error ? error.message : String(error);
           toast.error(`创建会话失败: ${message}`);
         }
       },
       [createSession, setCurrentSessionId, sendMessage, navigate],
     );

     const quickActions: QuickAction[] = [
       {
         id: 'feedback',
         icon: <MessageCircle className="w-4 h-4" />,
         labelKey: 'welcome.quick.feedback' as TranslationKey,
         descKey: 'welcome.quick.feedback_desc' as TranslationKey,
         onClick: () => {
           toast.info('反馈功能开发中…');
         },
       },
       {
         id: 'github',
         icon: <Star className="w-4 h-4" />,
         labelKey: 'welcome.quick.github' as TranslationKey,
         descKey: 'welcome.quick.github_desc' as TranslationKey,
         onClick: () => {
           window.open(GITHUB_URL, '_blank', 'noopener,noreferrer');
         },
       },
       {
         id: 'webui',
         icon: <Globe className="w-4 h-4" />,
         labelKey: 'welcome.quick.webui' as TranslationKey,
         descKey: 'welcome.quick.webui_desc' as TranslationKey,
         onClick: () => {
           window.open(WEBUI_URL, '_blank', 'noopener,noreferrer');
         },
         badge: { text: t('welcome.quick.webui_unavailable'), variant: 'warning' },
       },
     ];

     return (
       <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
         <div className="flex-1 flex flex-col items-center justify-start pt-[10vh] px-4 pb-8 gap-6">
           <WelcomeHero onBack={() => navigate(-1)} />

           <WelcomeInputCard
             initialValue={prefill}
             placeholder={placeholder}
             onSubmit={handleSubmit}
           />

           <AssistantRecommendations
             recommendations={defaultRecommendations}
             onSelect={handleRecommendationSelect}
           />

           <div className="mt-8">
             <QuickActionBar actions={quickActions} />
           </div>
         </div>
       </div>
     );
   }
   ```

3. **更新 `pages/index.ts`**（1 min）— 导出 Welcome：

   ```typescript
   export { Chat } from './Chat';
   export { Welcome } from './Welcome';
   export { Settings } from './settings';
   export { Memory } from './Memory';
   ```

4. **运行测试**（2 min）：
   - `npm run test:run -- src/pages/__tests__/Welcome.test.tsx` — 确认 GREEN（部分 mock 调整后再跑）
   - `npm run test:run` — 全套 GREEN

5. **Commit**：
   ```bash
   git add src/pages/Welcome.tsx src/pages/index.ts \
           src/pages/__tests__/Welcome.test.tsx
   git commit -m "feat(welcome): add Welcome page composing all welcome widgets"
   ```

---

### P7-T10：修改 `App.tsx` 增加 `/welcome` 路由

**Files:**

- **Modify:**
  - `/home/fz/project/sage/src/App.tsx`（增加路由）

**Interfaces:**

- 路由表：
  - `/welcome` → `<Welcome />`
  - `/chat` → 当前 `<Chat />`（行为不变）
  - `index` → 跳 `/chat`（行为不变）

**Steps:**

1. **写测试**（5 min）— 路由级测试：

   ```typescript
   // /home/fz/project/sage/src/__tests__/App.routing.test.tsx
   import { render, screen } from '@testing-library/react';
   import { MemoryRouter, Routes, Route } from 'react-router-dom';
   import { describe, expect, it, vi } from 'vitest';
   import { I18nProvider } from '../shared/lib/i18n';
   import { useStore } from '../shared/lib/store';
   import { Welcome } from '../pages/Welcome';
   import { Chat } from '../pages/Chat';

   // Mock the pages to keep test focused on routing
   vi.mock('../pages/Welcome', () => ({
     Welcome: () => <div data-testid="welcome-page">Welcome</div>,
   }));
   vi.mock('../pages/Chat', () => ({
     Chat: () => <div data-testid="chat-page">Chat</div>,
   }));

   function renderWithRoute(initialPath: string) {
     return render(
       <MemoryRouter initialEntries={[initialPath]}>
         <I18nProvider>
           <Routes>
             <Route path="/welcome" element={<Welcome />} />
             <Route path="/chat" element={<Chat />} />
             <Route path="/" element={<Welcome />} />
           </Routes>
         </I18nProvider>
       </MemoryRouter>,
     );
   }

   describe('App routing — welcome / chat', () => {
     beforeEach(() => {
       useStore.setState({ currentSessionId: null } as any);
     });

     it('renders Welcome page at /welcome', () => {
       renderWithRoute('/welcome');
       expect(screen.getByTestId('welcome-page')).toBeInTheDocument();
     });
   });
   ```

   - 运行测试，**确认 GREEN**（mock 的 Welcome 总是渲染）

2. **修改 `App.tsx`**（3 min）：

   ```typescript
   // /home/fz/project/sage/src/App.tsx (modified)
   import { useEffect, useState } from 'react';
   import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

   import { loadCurrentSessionId } from './entities/session/storage';
   import { Settings } from './pages';
   import { Agents } from './pages/Agents';
   import { Chat } from './pages/Chat';
   import { Knowledge } from './pages/Knowledge';
   import { Memory } from './pages/Memory';
   import Skills from './pages/Skills';
   import { Welcome } from './pages/Welcome';
   import { useStore } from './shared/lib/store';
   import { CommandPalette } from './widgets/command';
   import { Layout } from './widgets/layout';

   function App() {
     const [commandOpen, setCommandOpen] = useState(false);

     useEffect(() => {
       loadCurrentSessionId().then((id) => {
         if (id) {
           useStore.getState().setCurrentSessionId(id);
         }
       });
     }, []);

     // 全局快捷键 Ctrl+K / Cmd+K 打开命令面板
     useEffect(() => {
       const handler = (e: KeyboardEvent) => {
         if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
           e.preventDefault();
           setCommandOpen((prev) => !prev);
         }
       };
       window.addEventListener('keydown', handler);
       return () => window.removeEventListener('keydown', handler);
     }, []);

     return (
       <BrowserRouter>
         <Routes>
           <Route path="/" element={<Layout />}>
             <Route index element={<Navigate to="/chat" replace />} />
             <Route path="welcome" element={<Welcome />} />
             <Route path="chat" element={<Chat />} />
             <Route path="settings" element={<Settings />} />
             <Route path="memory" element={<Memory />} />
             <Route path="agents" element={<Agents />} />
             <Route path="skills" element={<Skills />} />
             <Route path="knowledge" element={<Knowledge />} />
           </Route>
         </Routes>
         <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
       </BrowserRouter>
     );
   }

   export default App;
   ```

3. **运行测试**（1 min）：
   - `npm run test:run` — 全部 GREEN
   - `npm run typecheck` — 无错

4. **Commit**：
   ```bash
   git add src/App.tsx \
           src/__tests__/App.routing.test.tsx
   git commit -m "feat(routing): add /welcome route for Phase 7 welcome screen"
   ```

---

### P7-T11：修改 `Sidebar` 让"新建会话"跳转 `/welcome`

**Files:**

- **Modify:**
  - `/home/fz/project/sage/src/widgets/layout/Sidebar.tsx`（"新对话"按钮改用 `navigate`）
- **Create:**
  - `/home/fz/project/sage/src/widgets/layout/__tests__/Sidebar.new-chat.test.tsx`

**Steps:**

1. **写测试**（5 min）：

   ```typescript
   import { render, screen, fireEvent } from '@testing-library/react';
   import { MemoryRouter } from 'react-router-dom';
   import { describe, expect, it, vi } from 'vitest';
   import { I18nProvider } from '../../../shared/lib/i18n';
   import { useStore } from '../../../shared/lib/store';
   import { Sidebar } from '../Sidebar';

   vi.mock('../../../features/manage-settings/useSettings', () => ({
     useSettings: () => ({
       settings: {
         endpoints: [],
         modelSelections: {
           chatModel: { endpointId: null, modelId: null },
           visionModel: { endpointId: null, modelId: null },
           embeddingModel: { endpointId: null, modelId: null },
         },
         maxContext: 4096,
         temperature: 0.7,
       },
     }),
   }));

   vi.mock('../../../features/manage-endpoints/api', () => ({
     testEndpointConnection: vi.fn().mockResolvedValue({ success: false }),
   }));

   const navigateMock = vi.fn();
   vi.mock('react-router-dom', async () => {
     const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
     return { ...actual, useNavigate: () => navigateMock };
   });

   function renderSidebar() {
     return render(
       <I18nProvider>
         <MemoryRouter>
           <Sidebar />
         </MemoryRouter>
       </I18nProvider>,
     );
   }

   describe('Sidebar — new chat button navigates to /welcome', () => {
     it('navigates to /welcome when "+ 新对话" is clicked', () => {
       useStore.setState({ currentSessionId: null, sessions: [] } as any);
       navigateMock.mockReset();
       renderSidebar();
       const button = screen.getByRole('button', { name: /\+ 新对话/ });
       fireEvent.click(button);
       expect(navigateMock).toHaveBeenCalledWith('/welcome');
     });
   });
   ```

   - 运行测试，**确认 RED**

2. **修改 `Sidebar.tsx`**（3 min）— 把 `handleNewSession` 改为 navigate：

   ```typescript
   // /home/fz/project/sage/src/widgets/layout/Sidebar.tsx (modified excerpt)
   import { useNavigate } from 'react-router-dom';
   // ... 现有 imports

   export function Sidebar({ width = 240 }: SidebarProps) {
     const location = useLocation();
     const navigate = useNavigate();
     // ... 现有 destructure

     const handleNewSession = () => {
       // Phase 7: 新建会话跳转到欢迎屏，由用户在欢迎屏输入后再创建 session
       navigate('/welcome');
     };

     // ... 其余不变
   }
   ```

3. **运行测试**（1 min）— **确认 GREEN**

4. **Commit**：
   ```bash
   git add src/widgets/layout/Sidebar.tsx \
           src/widgets/layout/__tests__/Sidebar.new-chat.test.tsx
   git commit -m "feat(sidebar): new chat button navigates to /welcome"
   ```

---

### P7-T12：写 Chat 路由 fallback 测试（验证不破坏现有行为）

**Files:**

- **Create:**
  - `/home/fz/project/sage/src/pages/__tests__/Chat.welcome-routing.test.tsx`

**Steps:**

1. **写测试**（8 min）：

   ```typescript
   import { render, screen } from '@testing-library/react';
   import { MemoryRouter, Routes, Route } from 'react-router-dom';
   import { describe, expect, it, vi, beforeEach } from 'vitest';
   import { I18nProvider } from '../../shared/lib/i18n';
   import { useStore } from '../../shared/lib/store';
   import { Chat } from '../Chat';
   import { Welcome } from '../Welcome';

   // mock useChat
   vi.mock('../../features/send-message/useChat', () => ({
     useChat: () => ({
       sendMessage: vi.fn(),
       isLoading: false,
       error: null,
       clearError: vi.fn(),
       messages: [],
       loadMessages: vi.fn(),
     }),
   }));
   vi.mock('../../features/manage-settings/useSettings', () => ({
     useSettings: () => ({
       settings: {
         endpoints: [],
         modelSelections: {
           chatModel: { endpointId: null, modelId: null },
           visionModel: { endpointId: null, modelId: null },
           embeddingModel: { endpointId: null, modelId: null },
         },
         maxContext: 4096,
         temperature: 0.7,
       },
     }),
   }));
   vi.mock('../../shared/api/desktopInvoke', () => ({
     invoke: vi.fn().mockRejectedValue(new Error('not reached')),
   }));
   vi.mock('../../shared/api/desktopEvent', () => ({
     listen: vi.fn().mockResolvedValue(() => undefined),
   }));
   vi.mock('../../shared/lib/hooks/useFileUpload', () => ({
     useFileUpload: () => ({
       files: [],
       images: [],
       addFile: vi.fn(),
       addImage: vi.fn(),
       removeFile: vi.fn(),
       removeImage: vi.fn(),
       clearAll: vi.fn(),
       handleDrop: vi.fn(),
       handleDragOver: vi.fn(),
       isDragOver: false,
     }),
   }));

   // App-level redirect: if no currentSessionId, /chat → /welcome
   function AppRouter() {
     const currentSessionId = useStore((s) => s.currentSessionId);
     if (!currentSessionId) {
       return <MemoryRouter initialEntries={['/chat']}><Welcome /></MemoryRouter>;
     }
     return (
       <MemoryRouter initialEntries={['/chat']}>
         <Routes>
           <Route path="/chat" element={<Chat />} />
         </Routes>
       </MemoryRouter>
     );
   }

   describe('Chat / Welcome routing — sessionId gating', () => {
     beforeEach(() => {
       useStore.setState({ currentSessionId: null } as any);
     });

     it('shows welcome when navigating to /chat with no sessionId', () => {
       render(
         <I18nProvider>
           <AppRouter />
         </I18nProvider>,
       );
       // Welcome's hero should be present
       expect(screen.getByText(/你好，我是 Claude/)).toBeInTheDocument();
     });

     it('shows chat normally when currentSessionId is set', () => {
       useStore.setState({ currentSessionId: 'session-abc' } as any);
       render(
         <I18nProvider>
           <AppRouter />
         </I18nProvider>,
       );
       // Chat page header
       expect(screen.getByText('对话')).toBeInTheDocument();
     });
   });
   ```

   - 运行测试 — **确认 GREEN**（这测试不需新代码，验证 store 行为一致）

2. **Commit**：
   ```bash
   git add src/pages/__tests__/Chat.welcome-routing.test.tsx
   git commit -m "test(chat): add welcome-routing gating test"
   ```

---

### P7-T13：添加 E2E 测试（Playwright）

**Files:**

- **Create:**
  - `/home/fz/project/sage/tests/e2e/welcome-screen.spec.ts`

**Steps:**

1. **写 E2E 测试**（15 min）：

   ```typescript
   // /home/fz/project/sage/tests/e2e/welcome-screen.spec.ts
   import { test, expect } from '@playwright/test';

   test.describe('Welcome screen', () => {
     test.beforeEach(async ({ page }) => {
       // 假设应用已启动并访问首页
       await page.goto('/');
     });

     test('shows welcome screen when no session is active', async ({ page }) => {
       // 访问 /welcome
       await page.goto('/welcome');
       // 看到 hero
       await expect(page.getByText(/你好，我是 Claude/)).toBeVisible();
       // 看到输入框
       const textarea = page.getByRole('textbox');
       await expect(textarea).toBeVisible();
       await expect(textarea).toBeFocused();
       // 看到 3 张推荐卡片
       const cards = page.getByTestId('recommendation-card');
       await expect(cards).toHaveCount(3);
       // 看到 quick action bar
       await expect(page.getByRole('toolbar', { name: /quick actions/ })).toBeVisible();
     });

     test('clicking a recommendation prefills the input', async ({ page }) => {
       await page.goto('/welcome');
       const firstCard = page.getByTestId('recommendation-card').first();
       await firstCard.click();
       const textarea = page.getByRole('textbox') as HTMLTextAreaElement;
       const value = await textarea.inputValue();
       expect(value).toContain('帮我写代码');
     });

     test('submitting from welcome navigates to /chat', async ({ page }) => {
       await page.goto('/welcome');
       const textarea = page.getByRole('textbox');
       await textarea.fill('hello world');
       await textarea.press('Enter');
       // 跳转到 /chat
       await page.waitForURL('**/chat');
       // Chat 页应该有 textarea（输入框）
       await expect(page.getByRole('textbox')).toBeVisible();
     });
   });
   ```

2. **运行 E2E**（5 min）— 需要 dev server 已运行：
   ```bash
   # 在另一个 terminal
   npm run dev &
   # 等待启动
   npx playwright test tests/e2e/welcome-screen.spec.ts
   ```

3. **Commit**：
   ```bash
   git add tests/e2e/welcome-screen.spec.ts
   git commit -m "test(e2e): add welcome screen E2E flows"
   ```

---

### P7-T14：覆盖率验证 + 全套回归

**Steps:**

1. **运行覆盖率检查**（5 min）：

   ```bash
   npm run test:coverage
   ```

2. **验证指标**：
   - `useTypewriterPlaceholder` ≥ 95% — 应通过
   - `entities/welcome/recommendations` ≥ 90% — 应通过
   - 整个 Phase 7 范围 ≥ 85% — 应通过
   - 如果不达标：补充针对性测试

3. **运行完整测试套件 + typecheck + lint**（5 min）：

   ```bash
   npm run test:run
   npm run typecheck
   npm run lint
   ```

4. **手动验证**（5 min）：
   ```bash
   # 启动应用
   npm run dev
   # 访问 http://localhost:1420/welcome
   # 验证：
   # - hero 头像 + 标题显示
   # - 输入框自动 focus
   # - 打字机 placeholder 动画
   # - 3 张推荐卡片可见，hover 上浮
   # - 点击推荐卡片，输入框预填
   # - 输入文字 + Enter → 跳 /chat
   # - QuickActionBar 三个按钮可见
   # - 点击 GitHub → 新窗口打开
   # - 移动端宽度（DevTools）→ 单列布局
   ```

5. **Commit**（如有任何补丁）：
   ```bash
   git add <any patches>
   git commit -m "chore(phase7): final coverage and regression fixes"
   ```

---

## Verification Checklist (Phase 7 完成标志)

- [ ] 所有 14 个 Task 的 commit 都已落地
- [ ] `npm run test:run` 全套 GREEN
- [ ] `npm run typecheck` 无错
- [ ] `npm run lint` 无 warning
- [ ] `npm run test:coverage` 关键模块 ≥ 95%、整体 ≥ 85%
- [ ] E2E 3 个场景全部通过
- [ ] 手动验证清单全部勾选
- [ ] 不破坏现有 Chat 路由（`/chat` 仍可用）
- [ ] 不破坏现有 sidebar 虚拟列表
- [ ] 不破坏现有主题系统
- [ ] i18n 中英文同步

---

## Out of Scope（不在本 Phase 处理）

- 不引入任何新 npm 包
- 不修改 Chat.tsx 内部
- 不实现真实 WebUI 状态探测（用静态 "Unavailable" badge 占位）
- 不实现真实反馈提交（用 `toast.info` 占位）
- 不实现 Phase 5 标题栏的反馈按钮 IPC（Phase 5 负责）

---

## Rollback Plan

如果 Phase 7 出现阻塞性 bug：

1. **回滚路由**（P7-T10）：删除 `App.tsx` 中的 `/welcome` 路由 — 应用立即恢复旧行为
2. **回滚 sidebar**（P7-T11）：把 `handleNewSession` 改回原来的 `createSession + setCurrentSessionId` — 立即恢复"点 + 新对话直接建空 session"
3. **保留新组件**：其余 widget（WelcomeHero / InputCard / Recommendations / QuickActionBar）作为孤立单元保留，不影响主流程
4. **不需要数据库迁移**（无 schema 变化）

---

## Estimated Total Effort

| Task | 估时（分钟）|
| ---- | --- |
| P7-T01 i18n 扩展 | 10 |
| P7-T02 useTypewriterPlaceholder hook | 20 |
| P7-T03 recommendations 数据 | 8 |
| P7-T04 WelcomeHero | 13 |
| P7-T05 InputCard 抽出 | 38 |
| P7-T06 WelcomeInputCard | 13 |
| P7-T07 AssistantRecommendations | 15 |
| P7-T08 QuickActionBar | 13 |
| P7-T09 Welcome page | 23 |
| P7-T10 App.tsx 路由 | 8 |
| P7-T11 Sidebar 修改 | 8 |
| P7-T12 路由 fallback 测试 | 8 |
| P7-T13 E2E | 20 |
| P7-T14 覆盖率验证 | 15 |
| **总计** | **~212 分钟 ≈ 3.5 小时** |

（不含 review 反馈、CI 失败排查、Phase 1-6 的修复带回 — 实际可能 1.5-2 个工作日）

---

## Reference: 设计文档对照

| 设计要求（spec）| 落地位置 | Task |
| --- | --- | --- |
| 居中大输入框 | `WelcomeInputCard.tsx` | P7-T06 |
| 推荐助手卡片 | `AssistantRecommendations.tsx` | P7-T07 |
| 反馈 / GitHub / WebUI | `QuickActionBar.tsx` | P7-T08 |
| 打字机占位符 | `useTypewriterPlaceholder.ts` | P7-T02 |
| Hero 头像 + 标题 | `WelcomeHero.tsx` | P7-T04 |
| `/welcome` 路由 | `App.tsx` | P7-T10 |
| Chat 无 sessionId 走 Welcome | `App.tsx` + store 联动 | P7-T10 + P7-T12 |
| Sidebar "新建会话" 跳 /welcome | `Sidebar.tsx` | P7-T11 |
| 共享 InputCard | `widgets/chat/InputCard.tsx` | P7-T05 |
| i18n welcome.* 键 | `zh.ts` + `en.ts` | P7-T01 |
| 移动端单列降级 | `AssistantRecommendations.tsx`（`grid-cols-1 md:grid-cols-3`）| P7-T07 |
| `autofocus` 输入框 | `WelcomeInputCard.tsx` + `InputCard` | P7-T05 + P7-T06 |
| 卸载清理 setInterval | `useTypewriterPlaceholder` useEffect cleanup | P7-T02 |
| 错误处理：session 创建失败 → toast | `Welcome.tsx` try/catch | P7-T09 |
| 错误处理：WebUI 状态失败 → badge | `QuickActionBar` 静态 badge | P7-T08 |
