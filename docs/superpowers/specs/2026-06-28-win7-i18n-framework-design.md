---
name: win7-i18n-framework
description: win7 i18n framework 设计 spec（自研 React Context + Zustand persist + TS const 字典，对齐 main API 超越持久化/fallback）
metadata:
  type: spec
  status: design
  parent_spec: 2026-06-28-win7-modules-rollout-design
  author: brainstorm-session-2026-06-28
  related_files:
    - src/shared/lib/i18n/zh.ts
    - src/shared/lib/i18n/en.ts
    - src/shared/lib/i18n/useLocaleStore.ts
    - src/shared/lib/i18n/index.tsx
    - src/shared/lib/i18n/formatMessage.ts
    - src/app/providers/AppProviders.tsx
---

# win7 i18n Framework Design Spec

> M1 of win7-modules-rollout。**目标：win7 分支拥有与 main API 完全兼容的 i18n 框架，并在持久化/fallback/占位符三点上超越 main。**

## 1. Goal

让 `release/win7` 分支拥有可用、可测、可扩展的 i18n 基础设施，作为 M2-M9 模块接入的前提。具体：

- ✅ `useI18n()` API 与 main 完全兼容（main 的 `zh.ts`/`en.ts` 可直接 cherry-pick 到 win7）
- ✅ locale 选择持久化到 localStorage（用户重启后保留，main 缺失的能力）
- ✅ t() 函数 fallback 链：当前 locale → zh → key 字符串
- ✅ t() 函数支持 `{name}` 占位符（main 缺失的能力）
- ✅ 翻译键 TypeScript 类型安全（`type TranslationKey = keyof typeof zh`）
- ✅ M1 范围：骨架 + 16 个 win7 当前能用的 key（sidebar 4 + chat 6 + common 6）

**明确不在 M1 范围：**

- ❌ 语言切换 UI 组件（属 Settings 模块）
- ❌ 自动检测浏览器 locale
- ❌ 日期/数字 locale 格式化
- ❌ 一次性同步 main 的 130+ 翻译键
- ❌ 国际化文档（所有模块完成后再写）

## 2. Win7 上下文

### 2.1 当前状态（基线快照，2026-06-28）

- ✅ React 18.2 + Vite + TypeScript
- ✅ Zustand 4.4.7（`src/shared/lib/store.ts` 已用）
- ✅ vitest + @testing-library/react（已配）
- ❌ i18n：**零代码**（main 的 `src/shared/lib/i18n/` 不存在）
- ❌ locale 状态：未实现

### 2.2 Main 实现摘要（参照）

- 自研 React Context：`src/shared/lib/i18n/index.tsx`
- 静态字典：`zh.ts`（`as const` 主源）+ `en.ts`（`Record<TranslationKey, string>`）
- Locale 类型：`'zh' | 'en'`
- Fallback：`translations[locale][key] ?? key`
- 持久化：**无**
- 占位符：**无**
- Provider 位置：`AppProviders` 中 `ThemeProvider > I18nProvider > QueryClientProvider`

### 2.3 决策点回顾（brainstorm 结果）

| # | 决策点 | 选定 | 理由 |
|---|---|---|---|
| 1 | Locale 类型 | `'zh' \| 'en'` | 对齐 main，零成本 cherry-pick |
| 2 | 持久化 | localStorage + Zustand persist | 用 win7 已有 Zustand 依赖，零新增包 |
| 3 | Fallback 链 | current → zh → key 字符串 | 中文主用户覆盖未翻译 key |
| 4 | 加载策略 | 全部 eager import | zh+en 总共 < 10KB，零延迟切换 |
| 5 | 字典格式 | TS const 文件 | 对齐 main，TS 类型零配置派生 |
| 6 | M1 范围 | 骨架 + 16 个 win7 当前能用 key | 与预估半天工期匹配 |
| 7 | 架构方案 | Context API + Zustand 状态（方案 A） | 保留 main API，差异化在状态层 |

## 3. Architecture

### 3.1 模块分层

```
┌─────────────────────────────────────────────────────────────────┐
│ src/shared/lib/i18n/                                            │
│   ├── index.tsx          # I18nProvider + useI18n (对外 API)    │
│   ├── useLocaleStore.ts  # Zustand store (locale 状态 + 持久化) │
│   ├── formatMessage.ts   # ICU-lite 占位符格式化纯函数          │
│   ├── zh.ts              # 中文主源字典（as const）             │
│   ├── en.ts              # 英文字典（Record<TranslationKey, string>）│
│   └── __tests__/         # 单元测试                              │
│       ├── I18nProvider.test.tsx                                  │
│       ├── useLocaleStore.test.ts                                 │
│       ├── formatMessage.test.ts                                  │
│       └── translations.test.ts                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 模块职责

| 模块 | 职责 | 依赖 |
|---|---|---|
| `useLocaleStore` | Zustand store + `persist` middleware；state: `{locale, setLocale}`；持久化 key `sage-locale` | zustand |
| `I18nProvider` | 订阅 `useLocaleStore`，构造 `t(key, params?)` 函数（fallback 链），通过 Context 暴露 `{locale, setLocale, t}` | useLocaleStore, zh, en, formatMessage |
| `useI18n` | 仅 useContext(I18nContext)，未包裹 Provider 时抛错 | I18nContext |
| `formatMessage` | 纯函数：`'Hello, {name}!'` + `{name: 'Alice'}` → `'Hello, Alice!'` | 无 |
| `zh.ts` | `as const` 对象，`export type TranslationKey = keyof typeof zh` | 无 |
| `en.ts` | `Record<TranslationKey, string>` | TranslationKey（类型） |

### 3.3 Provider 嵌套（更新后）

```
ErrorBoundary
  └─ ThemeProvider
       └─ I18nProvider    ← 新增（夹在 Theme 与 QueryClient 之间，对齐 main）
            └─ QueryClientProvider
                 ├─ {children}
                 └─ ToastProvider
```

**为什么是这个位置：**

- Theme > I18n：Theme 是 CSS 层基础（决定字串渲染的字体/颜色）
- I18n > QueryClient：所有组件都可能调用 t()，必须在 server-state cache 之前就绪
- 对齐 main：main 在 `AppProviders.tsx` 用相同顺序

## 4. 接口契约

### 4.1 TypeScript 类型

```typescript
// Locale 标识符：对齐 main
export type Locale = 'zh' | 'en';

// TranslationKey 由 zh.ts 自动派生（zh 是唯一主源）
// 类型定义见 §4.2
```

### 4.2 主源文件（`zh.ts`）

```typescript
export const zh = {
  // ─── 侧边栏（win7 当前能用的） ──────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': '对话',
  'sidebar.nav.settings': '设置',
  'sidebar.new_chat': '新对话',

  // ─── 聊天页（win7 当前能用的） ──────
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
```

### 4.3 英文翻译（`en.ts`）

```typescript
import type { TranslationKey } from './zh';

export const en: Record<TranslationKey, string> = {
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': 'Chat',
  'sidebar.nav.settings': 'Settings',
  'sidebar.new_chat': 'New Chat',

  'chat.title': 'Chat',
  'chat.new_session': '+ New Chat',
  'chat.placeholder': 'Type a message...',
  'chat.send': 'Send',
  'chat.stop': 'Stop',
  'chat.config_warning': 'API endpoint or chat model not configured',

  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',
};
```

### 4.4 Zustand store（`useLocaleStore.ts`）

```typescript
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Locale } from './types';  // re-export from zh.ts

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
      name: 'sage-locale',                     // localStorage key
      storage: createJSONStorage(() => localStorage),
      version: 1,                                // 字典迁移用
    },
  ),
);
```

### 4.5 I18nProvider + useI18n（`index.tsx`）

```typescript
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { en } from './en';
import { zh, type TranslationKey } from './zh';
import { useLocaleStore } from './useLocaleStore';
import { formatMessage } from './formatMessage';
import type { Locale } from './types';

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

### 4.6 formatMessage（`formatMessage.ts`）

```typescript
/**
 * 极简 ICU-lite 占位符替换：
 *   formatMessage('Hello, {name}!', { name: 'Alice' }) === 'Hello, Alice!'
 * 不支持嵌套、复数、select、escape；保持最小 surface。
 */
const PLACEHOLDER_RE = /\{(\w+)\}/g;

export function formatMessage(
  template: string,
  params: Record<string, string | number>,
): string {
  return template.replace(PLACEHOLDER_RE, (_, key: string) => {
    const v = params[key];
    return v == null ? `{${key}}` : String(v);
  });
}
```

**防御行为：**

- `template == null` → 返回 `''`
- 占位符 `key` 不在 `params` 中 → 保留 `{key}` 字面（开发期易识别）

### 4.7 对外 API 表面

| 导出 | 来源 | 用途 |
|---|---|---|
| `<I18nProvider>` | `index.tsx` | 包裹应用根 |
| `useI18n()` | `index.tsx` | 组件内取 `{t, locale, setLocale}` |
| `useLocaleStore` | `useLocaleStore.ts` | Zustand store 直接订阅（极少用） |
| `type Locale` | `zh.ts` | `'zh' \| 'en'` |
| `type TranslationKey` | `zh.ts` | 全部合法翻译键联合 |
| `formatMessage` | `formatMessage.ts` | 占位符格式化纯函数 |

## 5. 数据流

### 5.1 用户切换语言

```
用户在 SettingsPage 点击「语言: English」
  ↓
调用 setLocale('en')
  ↓
useLocaleStore.set({ locale: 'en' })
  ↓ (Zustand persist middleware 自动)
localStorage.setItem('sage-locale', JSON.stringify({state: {locale: 'en'}, version: 1}))
  ↓ (Zustand subscriber 触发)
所有 useLocaleStore((s) => s.locale) 订阅者触发 re-render
  ↓ (I18nProvider 内的 selector 触发)
I18nProvider 重渲染 → useMemo 重建 t 函数（依赖 locale）
  ↓ (Context value 变化)
所有 useI18n() 消费者触发 re-render
  ↓
UI 文本切换为英文 ✓
```

### 5.2 应用启动恢复 locale

```
Vite SPA 加载
  ↓
main.tsx 渲染 <App />
  ↓
<AppProviders> 包裹（I18nProvider 在内部）
  ↓
I18nProvider mount：
  - useLocaleStore((s) => s.locale) → 默认 'zh'（store 初始值）
  - Zustand persist middleware 自动从 localStorage 读 'sage-locale'
  - 如果读到有效值，store 自动 update → 触发 Provider re-render
  - 第一次渲染用户看到中文 → 一帧后切到 localStorage 中的 locale（极快，肉眼无感）
```

### 5.3 t() 函数的 fallback 链

```typescript
t('chat.title')
// 当前 locale 是 'en':
//   translations.en['chat.title'] = 'Chat' ✓ 直接命中
// 当前 locale 是 'en'，但 key 在 en 中遗漏：
//   translations.en['foo.bar'] = undefined
//   → translations.zh['foo.bar'] = '某个中文' ✓ 命中 zh
// 当前 locale 是 'en'，但 zh 也遗漏：
//   → 'foo.bar'（key 字符串，开发期易识别）
```

## 6. 错误处理

| 失败场景 | 行为 |
|---|---|
| 组件调用 `useI18n()` 但不在 Provider 内 | 抛 `Error('useI18n must be used within an <I18nProvider>')`（main 同款） |
| `t('unknown.key')` 当前 locale 无 | fallback 到 zh |
| `t('unknown.key')` zh 也无 | 返回 key 字符串（不抛错，让 UI 不崩） |
| localStorage 写入失败（quota exceeded 等） | Zustand persist 内部捕获、保留 in-memory 状态；不抛错 |
| localStorage JSON 损坏 | Zustand persist 自动 fallback 到 store 初始值 `locale: 'zh'`；不抛错 |
| `formatMessage` 收到 null/undefined template | 返回 `''`（防御性） |
| `formatMessage` 占位符未在 params 中 | 保留 `{key}` 字面（开发期易识别） |

## 7. 测试策略（覆盖率 ≥ 80%）

### 7.1 单测文件（4 个）

| 文件 | 覆盖点 |
|---|---|
| `__tests__/useLocaleStore.test.ts` | 默认值、setLocale、persist 写入 localStorage（mock）、localStorage 损坏回退到默认 |
| `__tests__/I18nProvider.test.tsx` | 渲染 children、locale 切换触发 re-render、t() 在 en/zh 下正确返回、useI18n 抛错（无 Provider） |
| `__tests__/formatMessage.test.ts` | 单占位符、多占位符、缺失参数保留 `{key}`、null/undefined template、number 转换 |
| `__tests__/translations.test.ts` | 静态校验：`Object.keys(en).length === Object.keys(zh).length`；所有 zh key 在 en 中都有值；`TranslationKey` 类型覆盖所有 keys（编译期由 TS 保证） |

### 7.2 测试工具

- vitest + @testing-library/react（win7 已装）
- localStorage mock：`vi.spyOn(Storage.prototype, 'setItem')` + happy-dom 默认提供

### 7.3 集成验证

- 手动 smoke：dev 模式启动 → 通过 dev console 调用 `useLocaleStore.getState().setLocale('en')` → 验证切换有效、刷新后保留

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Zustand persist 在 vitest happy-dom 环境下 localStorage mock 失败 | 中 | Step 3 测试失败 | 用 `vi.spyOn(Storage.prototype, 'setItem')` 验证 persist 写入；若不可行，fallback 写 in-memory store |
| `useLocaleStore` 在 Provider 外部调用导致 Context 错误边界外抛错 | 低 | 应用启动崩溃 | I18nProvider 始终在 AppProviders 中 |
| main 后续新增翻译键 → win7 cherry-pick 时 en.ts 编译失败 | 高 | 长期维护 | 接受此约束：win7 cherry-pick main 的 zh.ts/en.ts 时必须整文件覆盖 |
| 总览 spec §4.1 草案 `Locale = 'zh-CN' \| 'en-US'` 与本 spec `'zh' \| 'en'` 不一致 | 已确定 | 文档误导 | 本 spec 通过后顺手更新总览 spec §4.1（docs 修正 commit） |
| 测试覆盖率不达标（< 80%） | 低 | DoD 阻塞 | 单测目标覆盖关键路径；不足则补 edge case |
| `useI18n` 在单测中忘了 wrap Provider | 低 | 测试 fail | 写 test helper `renderWithProviders()` 集中封装 |
| Pre-push hook 的 lefthook 与 vitest 不兼容 | 极低 | 推送阻塞 | phase 9 已验证可跑 34 个 vitest 文件，本 M1 加 4 个新文件同框架应无冲突 |

## 9. DoD 清单（M1）

- [ ] 9 个新文件全部存在（5 src + 4 test）
- [ ] `src/app/providers/AppProviders.tsx` 含 `<I18nProvider>` 且位于 Theme > I18n > QueryClient 位置
- [ ] 4 个测试文件全部通过
- [ ] 覆盖率 ≥ 80%（仅 `src/shared/lib/i18n/**` 范围）
- [ ] `npx tsc --noEmit` 无错误
- [ ] `lefthook pre-commit` 全绿
- [ ] 后端 pytest 无新失败（应无影响）
- [ ] 前端 vitest 全套（含现有 34 files）无新失败
- [ ] 1 个 commit on `feat/win7-i18n-framework`
- [ ] 用户 review 通过 → merge 到 release/win7
- [ ] 不动总览 spec `2026-06-28-win7-modules-rollout-design.md`（保留总览；如需更新 §4.1 单独 commit）

## 10. 实施步骤预览（TDD 红绿重构）

```
Step 1: 建 feat/win7-i18n-framework 分支
  $ git switch -c feat/win7-i18n-framework    # 基于 release/win7 HEAD a654cb8

Step 2 [RED→GREEN]: 写 formatMessage.test.ts + 实现 formatMessage
  - 测试：单占位符、多占位符、缺失参数、null template、number 转换

Step 3 [RED→GREEN]: 写 useLocaleStore.test.ts + 实现 useLocaleStore
  - 测试：默认值 'zh'、setLocale 触发更新、persist 写入 localStorage

Step 4 [RED→GREEN]: 写 I18nProvider.test.tsx + 实现 I18nProvider + useI18n
  - 测试：渲染 children、locale 切换、t() zh/en/fallback、占位符、Provider 外抛错

Step 5 [RED→GREEN]: 写 translations.test.ts + 写 zh.ts + en.ts
  - 测试：Object.keys 长度对齐
  - 实现：先填 zh（主源），再填 en（满足类型约束）

Step 6: 修改 AppProviders.tsx 插入 <I18nProvider>
  - ThemeProvider > I18nProvider > QueryClientProvider
  - 跑现有测试套件确保无 regression

Step 7: 覆盖率 + 自审 + commit + push
  - npx vitest run --coverage（目标 ≥ 80%）
  - npx tsc --noEmit（无错误）
  - lefthook pre-commit 全绿
  - commit: feat(i18n): self-hosted i18n framework (Context + Zustand persist + 16 zh/en keys)
  - push → 等用户 merge
```

## 11. 后续模块对齐（M2-M9）

每个后续模块 PR 实施时的工作流：

```
1. 在 win7 feat/<module> 分支开工前：
   - 跑 git log main --oneline | grep "feat(i18n):"
   - 提取 main 该模块新增的 zh.ts/en.ts key（cherry-pick 仅这两个文件）
   - 应用到 win7 zh.ts/en.ts（若冲突，cherry-pick 整文件覆盖）

2. 组件实现时：
   - import { useI18n } from '@/shared/lib/i18n'
   - const { t } = useI18n()
   - 用 t('module.key') 替换硬编码字符串

3. 测试时：
   - 所有新组件的测试包裹 <I18nProvider>
   - 测试用固定 locale（默认 'zh'）断言翻译结果
```

**关键不变量（M1 之后所有模块遵循）：**

- ✅ 任何 UI 文本字符串**禁止硬编码**，必须走 t()
- ✅ 加新翻译键必须先改 zh.ts 再改 en.ts（TS 类型强制）
- ✅ 任何修改 zh.ts/en.ts 的 PR 必须保持两边 key 集合完全一致（translations.test.ts 校验）
- ✅ 测试组件时若使用 useI18n 必须包裹 <I18nProvider>

## 12. 与 main 的能力对齐声明

| 维度 | main 状态 | win7 M1 后 | 差异 |
|---|---|---|---|
| I18nProvider | ✅ Context 实现 | ✅ 同款 Context 实现 | 0（API 完全兼容） |
| useI18n hook | ✅ Context consumer | ✅ 同款 | 0 |
| t() 函数签名 | `(key: TranslationKey) => string` | `(key, params?) => string` | **win7 增强**：加 params 占位符支持 |
| 持久化 | ❌ 无 | ✅ localStorage + Zustand persist | **win7 超越** |
| Fallback 链 | 当前 locale → key | 当前 locale → zh → key | **win7 增强** |
| 翻译键覆盖 | 130+ key | 16 key（M1 阶段） | **后续模块陆续补齐**（非 M1 DoD） |
| 类型安全 | TranslationKey union | 同款 | 0 |

**结论：** M1 完成后 win7 i18n **API 100% 兼容 main**，且在持久化、fallback 链、占位符三点上**优于** main。

## 13. 参考

- 项目级 CLAUDE.md：`/home/fz/project/sage/.claude/CLAUDE.md`（双分支策略、Python 环境、测试要求）
- 总览 spec：`docs/superpowers/specs/2026-06-28-win7-modules-rollout-design.md`
- main i18n 实现：commit `26eba9c`（feat(ui): 会话虚拟化 + Shiki 高亮 + i18n 基础设施）
- main 后续 i18n 改动：commits `b92290d`, `66603b1`, `dc78e54`, `e616bb2`
- 历史同步记录：`/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-win7-sync-progress.md`

---

**Spec 状态：** ✅ 设计完成，待用户最终 review。

**下一步：** 用户 review 本 spec → 确认后启动 writing-plans skill 创建 `docs/superpowers/plans/2026-06-28-win7-i18n-framework-impl.md`。
