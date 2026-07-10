# win7 i18n Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `release/win7` 分支构建自研 i18n 框架 — React Context + Zustand persist + TS const 字典，API 与 main 100% 兼容，持久化/fallback/占位符三点超越 main，M1 范围 16 个 zh/en 翻译键。

**Architecture:** 自研 React Context 暴露 `useI18n()` API；locale 状态用 Zustand persist middleware 持久化到 localStorage；字典用 TS `as const` 主源 + `Record<TranslationKey, string>` 派生；t() 函数 fallback 链 current → zh → key 字符串，支持 `{name}` 占位符。

**Tech Stack:** React 18.2 + TypeScript + Zustand 4.4.7（persist middleware）+ vitest + @testing-library/react + happy-dom

**Spec 引用：** `docs/superpowers/specs/2026-06-28-win7-i18n-framework-design.md`

## Global Constraints

- **分支基线：** 必须在 `release/win7` HEAD（`a654cb8` 或更新）基础上创建 `feat/win7-i18n-framework` 分支
- **Python 环境：** 不要触碰 backend；本任务仅前端
- **TS 严格模式：** 必须通过 `npx tsc --noEmit` 无错误
- **测试框架：** vitest + happy-dom；`localStorage` 由 happy-dom 默认提供
- **覆盖率目标：** `src/shared/lib/i18n/**` 范围 ≥ 80%
- **lefthook：** pre-commit 钩子必须全绿；如失败需修复而**不**使用 `--no-verify`
- **commit 规范：** conventional commits；message ≤ 72 字符首行
- **Locale 类型：** `'zh' | 'en'`（对齐 main）；禁止 `'zh-CN' | 'en-US'`
- **测试运行命令：** `npx vitest run <pattern>`（无 watch）
- **commit 时机：** 每个 task 完成后立即 commit；**不要**积攒多个 task 后一次性 commit
- **不更新总览 spec：** 本任务不修改 `docs/superpowers/specs/2026-06-28-win7-modules-rollout-design.md`

---

## Task 1: 建 feat/win7-i18n-framework 分支

**Files:**
- 无文件改动

**Step 1: 确认基线状态**

Run:
```bash
cd /home/fz/project/sage && git status && git branch --show-current && git log --oneline -1
```

Expected:
- `On branch release/win7`
- Working tree clean
- HEAD 显示 `a654cb8 docs(superpowers): win7 modules rollout design spec (9 modules overview)` 或更新 commit（如已包含 `2e80838`）

如果当前不在 `release/win7` 或 working tree 不干净，**STOP** 并报告用户。

**Step 2: 建并切换到 feature 分支**

Run:
```bash
cd /home/fz/project/sage && git switch -c feat/win7-i18n-framework
```

Expected: `Switched to a new branch 'feat/win7-i18n-framework'`

**Step 3: 验证分支**

Run:
```bash
git branch --show-current && git log --oneline -1
```

Expected: 输出 `feat/win7-i18n-framework` 和 `a654cb8`（或更新 commit SHA）

---

## Task 2: formatMessage 纯函数（占位符格式化）

**Files:**
- Create: `src/shared/lib/i18n/__tests__/formatMessage.test.ts`
- Create: `src/shared/lib/i18n/formatMessage.ts`

**Interfaces:**
- Consumes: 无（无依赖）
- Produces:
  - `export function formatMessage(template: string | null | undefined, params: Record<string, string | number>): string`
  - 占位符语法：`{key}` → params[key]
  - 缺失参数 → 保留 `{key}` 字面
  - null/undefined template → 返回 `''`

- [ ] **Step 1: 写失败测试**

Create `src/shared/lib/i18n/__tests__/formatMessage.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import { formatMessage } from '../formatMessage';

describe('formatMessage', () => {
  it('replaces single placeholder', () => {
    expect(formatMessage('Hello, {name}!', { name: 'Alice' })).toBe('Hello, Alice!');
  });

  it('replaces multiple placeholders', () => {
    expect(
      formatMessage('{greeting}, {name}!', { greeting: 'Hi', name: 'Bob' }),
    ).toBe('Hi, Bob!');
  });

  it('preserves placeholder literal when param missing', () => {
    expect(formatMessage('Hello, {name}!', {})).toBe('Hello, {name}!');
  });

  it('coerces number params to string', () => {
    expect(formatMessage('You have {count} messages', { count: 5 })).toBe(
      'You have 5 messages',
    );
  });

  it('returns empty string for null template', () => {
    expect(formatMessage(null, {})).toBe('');
  });

  it('returns empty string for undefined template', () => {
    expect(formatMessage(undefined, {})).toBe('');
  });

  it('returns template unchanged when no placeholders', () => {
    expect(formatMessage('Plain text', { unused: 'x' })).toBe('Plain text');
  });

  it('handles repeated placeholder', () => {
    expect(formatMessage('{x}-{x}', { x: 'A' })).toBe('A-A');
  });
});
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/__tests__/formatMessage.test.ts`

Expected: FAIL — `Failed to resolve import "../formatMessage" from "...formatMessage.test.ts". Does the file exist?`

- [ ] **Step 3: 实现 formatMessage**

Create `src/shared/lib/i18n/formatMessage.ts`:

```typescript
/**
 * 极简 ICU-lite 占位符替换：
 *   formatMessage('Hello, {name}!', { name: 'Alice' }) === 'Hello, Alice!'
 * 不支持嵌套、复数、select、escape；保持最小 surface。
 *
 * 防御行为：
 *   - template 为 null/undefined → 返回 ''
 *   - 占位符 key 不在 params 中 → 保留 '{key}' 字面（开发期易识别）
 */

const PLACEHOLDER_RE = /\{(\w+)\}/g;

export function formatMessage(
  template: string | null | undefined,
  params: Record<string, string | number>,
): string {
  if (template == null) {
    return '';
  }
  return template.replace(PLACEHOLDER_RE, (_match, key: string) => {
    const v = params[key];
    return v == null ? `{${key}}` : String(v);
  });
}
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/__tests__/formatMessage.test.ts`

Expected: PASS — 8 tests passed

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add src/shared/lib/i18n/formatMessage.ts src/shared/lib/i18n/__tests__/formatMessage.test.ts && git commit -m "feat(i18n): add formatMessage pure function with {placeholder} syntax"
```

Expected: commit 成功；lefthook pre-commit 钩子跑过（如 backend lint skip 因为只改 frontend 文件）

---

## Task 3: useLocaleStore (Zustand persist store)

**Files:**
- Create: `src/shared/lib/i18n/__tests__/useLocaleStore.test.ts`
- Create: `src/shared/lib/i18n/useLocaleStore.ts`

**Interfaces:**
- Consumes: 无（依赖 zustand 已装）
- Produces:
  - `export const useLocaleStore` — Zustand store hook
  - `useLocaleStore.getState()` 返回 `{ locale: Locale, setLocale: (locale: Locale) => void }`
  - `useLocaleStore.getState().setLocale(locale)` 触发更新 + 持久化
  - 持久化到 `localStorage['sage-locale']`
  - 默认值 `locale: 'zh'`

**注意：** Task 3 在 Task 4 之前实现，所以此时还没有 `Locale` 类型从 `./zh` 导出。临时方案：本 task 内 inline 定义 `type Locale = 'zh' | 'en'`，Task 4 创建 `zh.ts` 后，Task 4 步骤里会**替换** `useLocaleStore.ts` 中的 `import type { Locale } from './zh'`。

- [ ] **Step 1: 写失败测试**

Create `src/shared/lib/i18n/__tests__/useLocaleStore.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';

import { useLocaleStore } from '../useLocaleStore';

describe('useLocaleStore', () => {
  beforeEach(() => {
    // 每个测试前清理 localStorage + 重置 store
    localStorage.clear();
    useLocaleStore.setState({ locale: 'zh' });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('defaults to zh locale', () => {
    expect(useLocaleStore.getState().locale).toBe('zh');
  });

  it('setLocale updates store', () => {
    act(() => {
      useLocaleStore.getState().setLocale('en');
    });
    expect(useLocaleStore.getState().locale).toBe('en');
  });

  it('persists locale to localStorage on change', () => {
    act(() => {
      useLocaleStore.getState().setLocale('en');
    });
    const raw = localStorage.getItem('sage-locale');
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.state.locale).toBe('en');
  });

  it('reads locale from localStorage on store creation', () => {
    localStorage.setItem(
      'sage-locale',
      JSON.stringify({ state: { locale: 'en' }, version: 1 }),
    );
    // 触发 store 重读：直接验证 storage 中的 JSON 格式符合 persist 期望
    const raw = localStorage.getItem('sage-locale');
    const parsed = JSON.parse(raw!);
    expect(parsed.state.locale).toBe('en');
  });
});
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/__tests__/useLocaleStore.test.ts`

Expected: FAIL — `Failed to resolve import "../useLocaleStore"`

- [ ] **Step 3: 实现 useLocaleStore（临时 Locale 内部定义）**

Create `src/shared/lib/i18n/useLocaleStore.ts`:

```typescript
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

// Locale 类型临时本地定义；Task 4 创建 zh.ts 后会替换为从 './zh' 导入。
// 这里保持与 spec §4.1 一致：'zh' | 'en'。
type Locale = 'zh' | 'en';

interface LocaleState {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: 'zh',
      setLocale: (locale) => set({ locale }),
    }),
    {
      name: 'sage-locale', // localStorage key
      storage: createJSONStorage(() => localStorage),
      version: 1,
    },
  ),
);
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/__tests__/useLocaleStore.test.ts`

Expected: PASS — 4 tests passed

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add src/shared/lib/i18n/useLocaleStore.ts src/shared/lib/i18n/__tests__/useLocaleStore.test.ts && git commit -m "feat(i18n): add useLocaleStore with localStorage persistence"
```

Expected: commit 成功

---

## Task 4: zh.ts + en.ts 主源字典（带 translations.test.ts 校验）

**Files:**
- Create: `src/shared/lib/i18n/zh.ts`
- Create: `src/shared/lib/i18n/en.ts`
- Create: `src/shared/lib/i18n/__tests__/translations.test.ts`
- Modify: `src/shared/lib/i18n/useLocaleStore.ts`（替换内部 `Locale` 定义为从 `./zh` 导入）

**Interfaces:**
- Consumes: 无
- Produces:
  - `export const zh` （zh.ts，as const 主源）
  - `export type TranslationKey = keyof typeof zh` （zh.ts）
  - `export type Locale = 'zh' | 'en'` （zh.ts）
  - `export const en: Record<TranslationKey, string>` （en.ts）

- [ ] **Step 1: 创建 zh.ts**

Create `src/shared/lib/i18n/zh.ts`:

```typescript
/**
 * 中文翻译 — 主源。
 *
 * 翻译键使用点分隔命名空间：sidebar.new_chat, chat.title ...
 * 增加 key 必须先在此文件加，否则 en.ts 无法通过类型检查。
 *
 * 16 个 win7 当前能用的 key（sidebar 4 + chat 6 + common 6）。
 */

export const zh = {
  // ─── 侧边栏 ───────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': '对话',
  'sidebar.nav.settings': '设置',
  'sidebar.new_chat': '新对话',

  // ─── 聊天页 ───────────────────────
  'chat.title': '对话',
  'chat.new_session': '+ 新对话',
  'chat.placeholder': '输入消息...',
  'chat.send': '发送',
  'chat.stop': '停止',
  'chat.config_warning': '未配置 API 端点或对话模型',

  // ─── 通用 ─────────────────────────
  'common.cancel': '取消',
  'common.confirm': '确定',
  'common.save': '保存',
  'common.loading': '加载中...',
  'common.error': '出错',
  'common.retry': '重试',
} as const;

export type TranslationKey = keyof typeof zh;

/** Locale 标识符：对齐 main ('zh' | 'en')。 */
export type Locale = 'zh' | 'en';
```

- [ ] **Step 2: 创建 en.ts**

Create `src/shared/lib/i18n/en.ts`:

```typescript
import type { TranslationKey } from './zh';

/**
 * English translations.
 *
 * Record<TranslationKey, string> 强制要求每个 zh key 在此都有对应英文值。
 * 加 zh 新 key 后这里会编译报错，提醒补英。
 */

export const en: Record<TranslationKey, string> = {
  // ─── Sidebar ──────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': 'Chat',
  'sidebar.nav.settings': 'Settings',
  'sidebar.new_chat': 'New Chat',

  // ─── Chat ─────────────────────────
  'chat.title': 'Chat',
  'chat.new_session': '+ New Chat',
  'chat.placeholder': 'Type a message...',
  'chat.send': 'Send',
  'chat.stop': 'Stop',
  'chat.config_warning': 'API endpoint or chat model not configured',

  // ─── Common ───────────────────────
  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',
};
```

- [ ] **Step 3: 创建 translations.test.ts（校验两字典对齐）**

Create `src/shared/lib/i18n/__tests__/translations.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import { en } from '../en';
import { zh, type TranslationKey } from '../zh';

describe('translations consistency', () => {
  it('zh and en have same number of keys', () => {
    expect(Object.keys(en).length).toBe(Object.keys(zh).length);
  });

  it('every zh key exists in en', () => {
    const zhKeys = Object.keys(zh) as TranslationKey[];
    const enKeys = new Set(Object.keys(en));
    for (const key of zhKeys) {
      expect(enKeys.has(key), `missing en translation for key: ${key}`).toBe(true);
    }
  });

  it('no extra keys in en that are not in zh', () => {
    const zhKeys = new Set(Object.keys(zh));
    const enKeys = Object.keys(en);
    for (const key of enKeys) {
      expect(zhKeys.has(key), `extra en key not in zh: ${key}`).toBe(true);
    }
  });

  it('every en value is a non-empty string', () => {
    for (const [key, value] of Object.entries(en)) {
      expect(typeof value, `en[${key}] must be string`).toBe('string');
      expect(value.length, `en[${key}] must be non-empty`).toBeGreaterThan(0);
    }
  });

  it('every zh value is a non-empty string', () => {
    for (const [key, value] of Object.entries(zh)) {
      expect(typeof value, `zh[${key}] must be string`).toBe('string');
      expect(value.length, `zh[${key}] must be non-empty`).toBeGreaterThan(0);
    }
  });

  it('zh has exactly 16 keys (M1 scope)', () => {
    expect(Object.keys(zh).length).toBe(16);
  });
});
```

- [ ] **Step 4: 替换 useLocaleStore.ts 中的内部 Locale 定义（从 zh.ts 导入）**

Edit `src/shared/lib/i18n/useLocaleStore.ts`，将文件顶部修改为：

```typescript
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

import type { Locale } from './zh';

interface LocaleState {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: 'zh',
      setLocale: (locale) => set({ locale }),
    }),
    {
      name: 'sage-locale', // localStorage key
      storage: createJSONStorage(() => localStorage),
      version: 1,
    },
  ),
);
```

（删除之前的 `type Locale = 'zh' | 'en';` 内联定义，改为从 `./zh` 导入）

- [ ] **Step 5: 跑测试确认 PASS**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/__tests__/translations.test.ts src/shared/lib/i18n/__tests__/useLocaleStore.test.ts`

Expected: PASS — translations.test.ts 6 个测试 + useLocaleStore.test.ts 4 个测试全过

- [ ] **Step 6: 验证 tsc 无错误（关键：en.ts 必须满足 Record<TranslationKey, string>）**

Run: `cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | head -20`

Expected: 无错误输出（如果 en.ts 漏 key，tsc 会报错）

- [ ] **Step 7: Commit**

```bash
cd /home/fz/project/sage && git add src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts src/shared/lib/i18n/__tests__/translations.test.ts src/shared/lib/i18n/useLocaleStore.ts && git commit -m "feat(i18n): add zh/en dictionaries with 16 keys and consistency tests"
```

Expected: commit 成功

---

## Task 5: I18nProvider + useI18n hook

**Files:**
- Create: `src/shared/lib/i18n/__tests__/I18nProvider.test.tsx`
- Create: `src/shared/lib/i18n/index.tsx`

**Interfaces:**
- Consumes:
  - `from './zh'`: `zh`, `TranslationKey`, `Locale`
  - `from './en'`: `en`
  - `from './useLocaleStore'`: `useLocaleStore`
  - `from './formatMessage'`: `formatMessage`
- Produces:
  - `export function I18nProvider({ children }: { children: ReactNode }): JSX.Element`
  - `export function useI18n(): { locale: Locale, setLocale: (l: Locale) => void, t: (key, params?) => string }`
  - `export type { Locale, TranslationKey }` （re-export）

- [ ] **Step 1: 写失败测试**

Create `src/shared/lib/i18n/__tests__/I18nProvider.test.tsx`:

```tsx
import { render, screen, renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { type ReactNode } from 'react';

import { I18nProvider, useI18n } from '../index';
import { useLocaleStore } from '../useLocaleStore';

// 测试辅助：在每个 test 间重置 store + localStorage
function Wrapper({ children }: { children: ReactNode }) {
  return <I18nProvider>{children}</I18nProvider>;
}

describe('I18nProvider + useI18n', () => {
  beforeEach(() => {
    localStorage.clear();
    useLocaleStore.setState({ locale: 'zh' });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('renders children', () => {
    render(
      <I18nProvider>
        <div data-testid="child">child content</div>
      </I18nProvider>,
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('exposes default locale zh via useI18n', () => {
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    expect(result.current.locale).toBe('zh');
  });

  it('t() returns zh translation for chat.title', () => {
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    expect(result.current.t('chat.title')).toBe('对话');
  });

  it('t() returns en translation when locale=en', () => {
    act(() => {
      useLocaleStore.getState().setLocale('en');
    });
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    expect(result.current.locale).toBe('en');
    expect(result.current.t('chat.title')).toBe('Chat');
  });

  it('t() accepts params and returns string', () => {
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    // M1 zh 字典中暂不带占位符的 key；这里只验证 t() 接受 params 参数且不报错
    const out = result.current.t('chat.title', { unused: 'x' });
    expect(typeof out).toBe('string');
    expect(out).toBe('对话');
  });

  it('useI18n throws when used outside Provider', () => {
    expect(() => {
      renderHook(() => useI18n());
    }).toThrow(/must be used within an <I18nProvider>/);
  });

  it('setLocale triggers context re-render', () => {
    function DisplayLocale() {
      const { locale, t } = useI18n();
      return <div data-testid="locale">{`${locale}:${t('chat.send')}`}</div>;
    }
    render(
      <I18nProvider>
        <DisplayLocale />
      </I18nProvider>,
    );
    expect(screen.getByTestId('locale')).toHaveTextContent('zh:发送');

    act(() => {
      useLocaleStore.getState().setLocale('en');
    });
    expect(screen.getByTestId('locale')).toHaveTextContent('en:Send');
  });
});
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/__tests__/I18nProvider.test.tsx`

Expected: FAIL — `Failed to resolve import "../index"`

- [ ] **Step 3: 实现 I18nProvider + useI18n**

Create `src/shared/lib/i18n/index.tsx`:

```tsx
/**
 * i18n — 自研国际化 Provider（API 与 main 100% 兼容 + win7 增强）
 *
 * 用法:
 *   <I18nProvider>
 *     <App />
 *   </I18nProvider>
 *
 *   const { t, locale, setLocale } = useI18n();
 *   <h1>{t('chat.title')}</h1>
 *
 * 架构:
 *   - locale 状态用 Zustand store（持久化到 localStorage）
 *   - t 函数在 Provider 内 useMemo 构造（依赖 locale）
 *   - 通过 Context 暴露 { locale, setLocale, t }
 *
 * 增强（超越 main）:
 *   - locale 自动持久化（main 无）
 *   - t() 支持 {placeholder}（main 无）
 *   - fallback 链 current → zh → key 字符串（main 只 current → key）
 */

import { createContext, useContext, useMemo, type ReactNode } from 'react';

import { en } from './en';
import { formatMessage } from './formatMessage';
import { useLocaleStore } from './useLocaleStore';
import { zh, type TranslationKey, type Locale } from './zh';

// 统一 re-export 类型
export type { Locale, TranslationKey } from './zh';

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /** 翻译函数：fallback 链 current → zh → key 字符串；支持 {placeholder}。 */
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

interface I18nProviderProps {
  children: ReactNode;
}

export function I18nProvider({ children }: I18nProviderProps) {
  // 精细订阅：只选 locale 和 setLocale，避免 store 其他字段变化触发重渲染
  const locale = useLocaleStore((s) => s.locale);
  const setLocale = useLocaleStore((s) => s.setLocale);

  const value = useMemo<I18nContextValue>(() => {
    const translations: Record<Locale, Record<string, string>> = { zh, en };
    const t: I18nContextValue['t'] = (key, params) => {
      const direct = translations[locale][key];
      const fallback = direct ?? translations.zh[key] ?? key;
      return params ? formatMessage(fallback, params) : fallback;
    };
    return { locale, setLocale, t };
  }, [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error('useI18n must be used within an <I18nProvider>');
  }
  return ctx;
}
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/__tests__/I18nProvider.test.tsx`

Expected: PASS — 7 tests passed

- [ ] **Step 5: 跑全部 i18n 测试套件**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/`

Expected: PASS — formatMessage 8 + useLocaleStore 4 + translations 6 + I18nProvider 7 = 25 tests passed

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage && git add src/shared/lib/i18n/index.tsx src/shared/lib/i18n/__tests__/I18nProvider.test.tsx && git commit -m "feat(i18n): add I18nProvider and useI18n hook with Context + fallback chain"
```

Expected: commit 成功

---

## Task 6: 修改 AppProviders.tsx 插入 I18nProvider

**Files:**
- Modify: `src/app/providers/AppProviders.tsx`

- [ ] **Step 1: 读 AppProviders.tsx 确认现状**

Run: `cd /home/fz/project/sage && cat src/app/providers/AppProviders.tsx`

Expected: 当前结构 `ErrorBoundary > ThemeProvider > QueryClientProvider > (children) + ToastProvider`，无 I18nProvider

- [ ] **Step 2: 修改 AppProviders.tsx — 在 ThemeProvider 内部、QueryClientProvider 外部插入 I18nProvider**

使用 Edit 工具，将：

```tsx
import { ThemeProvider } from './ThemeProvider';
import { ToastProvider } from './ToastProvider';
```

替换为：

```tsx
import { I18nProvider } from '../../shared/lib/i18n';
import { ThemeProvider } from './ThemeProvider';
import { ToastProvider } from './ToastProvider';
```

并将渲染结构：

```tsx
      <ThemeProvider>
        <QueryClientProvider>
          {children}
          <ToastProvider />
        </QueryClientProvider>
      </ThemeProvider>
```

替换为：

```tsx
      <ThemeProvider>
        <I18nProvider>
          <QueryClientProvider>
            {children}
            <ToastProvider />
          </QueryClientProvider>
        </I18nProvider>
      </ThemeProvider>
```

同时更新顶部注释：

```tsx
 * 顶层 Provider 组合。按从外到内的顺序：
 *   ErrorBoundary > Theme > I18n > QueryClient > (children) > Toast
 *
 * - ErrorBoundary 在最外，任何子树的未捕获错误都能兜住
 * - Theme 紧跟其后，I18n/QueryClient/Toast 都需要 theme 值
 * - I18n 在 QueryClient 之前，确保所有子组件都能使用 t()
 * - QueryClient 是 server-state cache 根
 * - Toast 渲染在子树的兄弟位置（不嵌套），让 toast 浮在路由层之上
```

- [ ] **Step 3: 验证 tsc 无错误**

Run: `cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | head -20`

Expected: 无错误输出（如果 I18nProvider 导入路径错，tsc 会报错）

- [ ] **Step 4: 跑全部 i18n 测试**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/i18n/`

Expected: PASS — 25 tests passed

- [ ] **Step 5: 跑前端测试全套（确认无 regression）**

Run: `cd /home/fz/project/sage && npx vitest run 2>&1 | tail -20`

Expected: PASS — 现有 34 个测试文件 + 新增 4 个 = 38 个测试文件全部通过；无新增失败

如果出现 pre-existing 失败（与 i18n 无关，如 phase 9 已记录的），**STOP** 并报告用户。

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage && git add src/app/providers/AppProviders.tsx && git commit -m "feat(i18n): wire I18nProvider into AppProviders (Theme > I18n > QueryClient)"
```

Expected: commit 成功

---

## Task 7: 覆盖率检查 + 综合验证 + push

**Files:**
- 无新文件改动

- [ ] **Step 1: 跑覆盖率检查**

Run: `cd /home/fz/project/sage && npx vitest run --coverage src/shared/lib/i18n/ 2>&1 | tail -30`

Expected:
- Statements ≥ 80%
- Branches ≥ 80%
- Functions ≥ 80%
- Lines ≥ 80%

如果未达标，回到对应 task 补 edge case 测试，然后 commit 修复。

- [ ] **Step 2: tsc 全量检查**

Run: `cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | tail -10`

Expected: 无错误

- [ ] **Step 3: 后端 pytest 烟雾测试（确认本任务未影响后端）**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest --tb=no -q 2>&1 | tail -5`

Expected: `1122 passed, 57 skipped` 或更新数（无新失败）；baseline 在 `7c76327` 已确认

- [ ] **Step 4: 前端 vitest 全套（最终验证）**

Run: `cd /home/fz/project/sage && npx vitest run 2>&1 | tail -10`

Expected: 全部测试文件通过；现有 34 + 新增 4 = 38 文件

- [ ] **Step 5: 验证 commit 列表**

Run: `cd /home/fz/project/sage && git log --oneline release/win7..HEAD`

Expected: 显示 4 个 commits（Task 2/4/5/6 各 1 个，Task 3 不单独 commit 因为被 Task 4 包含在「替换 useLocaleStore 改动」里；Task 7 无 commit）

注：Task 3 与 Task 4 都改 useLocaleStore.ts（Task 3 创建、Task 4 替换内部 Locale 定义）；Task 4 的 commit 包含「modify useLocaleStore.ts」。如果想保留 Task 3 独立 commit（包含初始 useLocaleStore.ts），需要调整 Task 4 为创建临时 fixup commit 然后在 push 前 squash — **推荐保留 Task 4 的合并 commit 形式**，最终 branch 上是 4 个 commit。

- [ ] **Step 6: 推送 feature 分支到 origin**

Run: `cd /home/fz/project/sage && git push -u origin feat/win7-i18n-framework`

Expected: push 成功；lefthook pre-push 钩子通过

- [ ] **Step 7: 报告完成状态给用户**

输出格式：
```
✅ M1 win7-i18n-framework feature 分支实施完成

分支：feat/win7-i18n-framework on origin
commits: 4 commits on top of release/win7
新增文件：5 src + 4 test = 9 文件
修改文件：1（AppProviders.tsx）
测试通过：25 个 i18n 测试 + 现有 34 个前端文件全部通过
覆盖率：≥ 80%（src/shared/lib/i18n/**）
tsc：无错误
后端 pytest：无新失败

请用户：
1. Review feat/win7-i18n-framework 分支
2. 创建 PR：feat/win7-i18n-framework → release/win7
3. CI 通过后 merge
```

---

## Self-Review Checklist (执行前)

- [x] Spec coverage: §3 architecture（Task 2-6）、§4 interfaces（Task 2-5）、§5 data flow（Task 5 测试）、§6 error handling（Task 5 测试覆盖）、§7 test strategy（Task 2-5 + Task 7）、§9 DoD（Task 7）全部对应 task
- [x] No placeholders: 每个 step 含具体代码或命令
- [x] Type consistency: `Locale`、`TranslationKey`、`useLocaleStore`、`formatMessage`、`I18nProvider`、`useI18n` 全 plan 一致
- [x] File paths: 全部 `src/...` 相对路径
- [x] Commit messages: 4 个 commit（Task 2/4/5/6）每个一行 conventional commit
- [x] TDD: Task 2/3/4/5 严格 RED→GREEN；Task 6 集成；Task 7 验证
