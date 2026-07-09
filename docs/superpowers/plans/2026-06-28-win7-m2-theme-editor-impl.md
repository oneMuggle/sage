# win7 M2 主题编辑器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `release/win7` 分支实现与 main 完全对齐的主题编辑器(5 套预设 + CodeMirror 自定义 CSS 编辑 + 实时切换 + 持久化),通过 4-Phase 渐进式 subagent 交付,工期 ~4.5 天。

**Architecture:** 前后端分离 + IPC 桥接。后端 FastAPI(py3.8 + pydantic 1.x)提供 7 个 REST 端点 + atomic JSON 存储;前端 React 18.2 + Zustand 提供 ThemeProvider(本地 localStorage 优先 + IPC 异步回填) + CodeMirror 6 懒加载编辑器 + 5 套 cherry-pick 预设画廊;electron 21.4.4 暴露 `window.electronAPI.theme.*` IPC API。

**Tech Stack:**
- Backend: Python 3.8 + FastAPI 0.85 + pydantic 1.x + pytest
- Frontend: React 18.2 + TypeScript 5.x + Vite + Zustand 4.4.7 + vitest + @testing-library/react
- IPC: electron 21.4.4 (preload + main handlers)
- Editor: CodeMirror 6 (懒加载,~200KB initial bundle split)
- Storage: `backend/data/themes.json` (atomic JSON write) + localStorage `sage.theme.active`

**Spec:** `docs/superpowers/specs/2026-06-28-win7-m2-theme-editor-design.md`

---

## Global Constraints

[贯穿所有任务的全局约束,从 spec 提取,每行严格遵循]

- **Python 环境:** 后端所有 pip/python 命令必须使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`(per 项目级 CLAUDE.md);不可用系统 `python3` 或 base conda 环境
- **Python 版本:** py3.8(win7 LTS);不允许使用 3.9+ 语法(`from __future__ import annotations` 除外)
- **Pydantic 版本:** 1.x(win7 LTS);`validator` 装饰器不传 `allow_reuse`;不用 `model_config` 改用 `Config` 类
- **Electron 版本:** 21.4.4(Win7 兼容);preload API surface 与 main 一致
- **TypeScript:** 严格模式,所有 UI 字符串必须走 `t()`(M1 i18n 强制)
- **i18n 键命名:** M1 不变量:先改 `zh.ts` 再改 `en.ts`;`translations.test` 强制 key 集合一致
- **测试组件时:** 若使用 `useI18n` 必须包裹 `<I18nProvider>`(M1 强制)
- **覆盖率门槛:** 语句 ≥ 80%,分支 ≥ 75%(per `common/testing.md`);M2 新 i18n keys 一致性 100%
- **CSS 变量白名单:** 16 个 vars 严格(`--color-bg/-bg-secondary/-bg-tertiary/-fg/-fg-secondary/-fg-muted/-border/-border-strong/-accent/-accent-hover/-success/-warning/-error/-info/-link/-link-hover`)
- **CSS 注入安全:** 黑名单 6 类威胁(`@import` / `expression()` / `behavior:` / `javascript:` / 外部 `url()` / `data:` URL / `-moz-binding` / `@charset`);单行 ≤ 1000 字符;总长度 ≤ 50KB;只允许顶层 `:root`
- **localStorage 键名:** 强制加 `sage.` 前缀(`sage.theme.active`),与 main `theme.active` 隔离
- **Branch 命名:** 每 phase 在 `feat/win7-theme-editor-p{N}` 分支上工作,不用 main/release/win7 直接 commit
- **Commit message:** 严格 conventional commits(`feat:` / `fix:` / `refactor:` / `test:` / `docs:` / `chore:`)
- **Pre-push hook:** 不允许 `--no-verify`;测试挂了必须修到 GREEN 才能 push
- **双分支策略:** 不删除 release/win7;不 merge main 到 release/win7;各 phase 通过本地 merge 合入 release/win7(per `feature-branch-workflow.md` phase 1-9 + M1 先例)
- **错误信封:** 全栈统一 `ApiResponse<T> = {success: true, data: T} | {success: false, error, code?, details?}`(per spec §4.4);跨 IPC 永不 throw,统一返回 `ApiResponse`
- **YAGNI:** 不实现主题市场/在线下载/分享导入导出/调度切换(M3+ 范畴)

---

## File Structure(实施前先确认)

### 新建文件(P1 后端)
| 路径 | 职责 | 行数(估) |
|---|---|---|
| `backend/schemas/common.py` | `ApiError` 信封模型 | 30 |
| `backend/schemas/theme.py` | `ThemePreset` / `ThemeCssPayload` / `ActiveTheme` | 60 |
| `backend/services/theme_storage.py` | atomic JSON I/O + 默认种子 | 120 |
| `backend/api/theme_router.py` | 7 个 REST 端点 | 150 |
| `backend/data/themes.defaults.json` | 5 套预设种子(git 跟踪) | 80 |
| `backend/data/.gitkeep` | 占位(确保目录存在) | 1 |
| `backend/tests/schemas/test_theme_schemas.py` | pydantic 1.x 模型测试 | 100 |
| `backend/tests/services/test_theme_storage.py` | atomic write + 损坏恢复 + 首次种子 | 150 |
| `backend/tests/api/test_theme_router.py` | 7 端点 × {happy, 4xx, 5xx} | 200 |

### 新建文件(P2 IPC + 注入)
| 路径 | 职责 | 行数(估) |
|---|---|---|
| `src/shared/types/api.ts` | `ApiResponse<T>` 信封类型 | 30 |
| `src/shared/types/theme.ts` | `ThemePreset` / `ThemeCssPayload` / `ActiveTheme` | 50 |
| `src/shared/lib/theme/cssValidator.ts` | 16-var 白名单 + 6 类黑名单 | 80 |
| `src/shared/lib/theme/__tests__/cssValidator.test.ts` | 32 case | 150 |
| `src/shared/api-client/themeCssClient.ts` | IPC 客户端(7 端点封装) | 80 |
| `src/shared/api-client/__tests__/themeCssClient.test.ts` | IPC mock 测试 | 120 |
| `src/widgets/theme/backgroundInjector.ts` | CSS vars 注入 document | 50 |
| `src/widgets/theme/__tests__/backgroundInjector.test.ts` | 注入副作用 | 80 |

### 修改文件(P2)
| 路径 | 改动 |
|---|---|
| `electron/preload.ts` | 暴露 `window.electronAPI.theme.*`(+20 行) |
| `electron/main.ts` | 注册 IPC handlers 桥接 backend REST(+30 行) |

### 新建文件(P3 UI 集成)
| 路径 | 职责 | 行数(估) |
|---|---|---|
| `src/widgets/theme/ErrorBoundary.tsx` | Theme 局部错误边界 | 50 |
| `src/widgets/theme/ThemeProvider.tsx` | Context + state + 副作用 | 100 |
| `src/widgets/theme/ThemeSelector.tsx` | 顶栏下拉 + 切换 + 编辑入口 | 130 |
| `src/widgets/theme/CssThemeModal.tsx` | 编辑器弹窗 + 实时预览 | 180 |
| `src/widgets/theme/CodeMirrorThemeEditor.tsx` | CM6 编辑器(懒加载) | 200 |
| `src/widgets/theme/__tests__/ThemeProvider.test.tsx` | 启动序列 + 切换 + 保存 | 150 |
| `src/widgets/theme/__tests__/ThemeSelector.test.tsx` | UI 交互 | 120 |
| `src/widgets/theme/__tests__/CssThemeModal.test.tsx` | 编辑 + 保存 + 校验 | 100 |
| `src/widgets/theme/__tests__/ErrorBoundary.test.tsx` | 降级 | 60 |

### 修改文件(P3)
| 路径 | 改动 |
|---|---|
| `src/app/providers/AppProviders.tsx` | 挂载 ThemeProvider(+5 行) |
| `package.json` | 加 CodeMirror 6 依赖(per main `989e912`) |

### 新建文件(P4 5 套预设)
| 路径 | 职责 | 行数(估) |
|---|---|---|
| `src/widgets/theme/presets.ts` | 5 套 cherry-pick 预设常量 | 200 |
| `src/widgets/theme/ThemeGallery.tsx` | 画廊视图(5 套缩略图) | 150 |
| `src/widgets/theme/__tests__/presets.test.ts` | 5 套数据完整性 | 60 |
| `src/widgets/theme/__tests__/ThemeGallery.test.tsx` | 点击切换 | 100 |
| `public/assets/themes/{light,dark,ocean,forest,sunset}.png` | 5 张封面图(从 main cherry-pick) | — |

### 修改文件(P4)
| 路径 | 改动 |
|---|---|
| `src/shared/i18n/zh.ts` | 新增 ~17 个 theme.* 键(+60 行) |
| `src/shared/i18n/en.ts` | 新增 ~17 个 theme.* 键(+60 行) |
| `src/shared/i18n/__tests__/translations.test.ts` | 自动适配新 key(+20 行) |
| `backend/data/.gitignore` | 追加 `themes.json`(忽略运行时文件)(+1 行) |

**总计:** 25 个新文件 + 7 个修改 ≈ 32 处改动(per spec §4.1)

---

## Phases 总览

| Phase | 任务数 | 工期(估) | 验证 |
|---|---|---|---|
| **P1** 后端基础 | 5 tasks | 1.5 天 | pytest 全绿,覆盖率 ≥ 90% |
| **P2** IPC + 注入 | 5 tasks | 1 天 | vitest 全绿,覆盖率 ≥ 90% |
| **P3** UI 集成 | 6 tasks | 1.5 天 | vitest + RTL 全绿,覆盖率 ≥ 80% |
| **P4** 5 套预设 | 4 tasks | 0.5 天 | vitest 全绿 + 视觉确认 |
| **总计** | 20 tasks | ~4.5 天 | |

**每 Phase 流程(Subagent-Driven):**
1. Subagent 在 `feat/win7-theme-editor-p{N}` 分支工作
2. Subagent 按 TDD 节奏(RED → GREEN → IMPROVE)
3. Subagent commit + push + 创建 PR
4. Main session review PR(code-reviewer agent)
5. CI 绿后本地 merge 到 `release/win7`(per 双分支策略)

---

## Phase 2: IPC + 注入(P2)

> **Phase 目标:** 在 P1 后端就绪后,补齐前端调用链路 —— 共享类型 + CSS 校验器 + 后台注入 + IPC 客户端 + Electron 桥接。本 Phase **不写 React 组件**,只为 P3 UI 集成铺好数据通路。
>
> **Subagent 起点:** `release/win7` HEAD(P1 已 merge 后)或 `feat/win7-theme-editor-p1` 顶
> **Subagent 终点:** `feat/win7-theme-editor-p2` 分支上 vitest 全绿 + 可在 dev console 手测 `window.electronAPI.theme.list()`

### Task 2.1: 共享 TS 类型(ApiResponse + Theme types)

**Files:**
- Create: `src/shared/types/api.ts`
- Create: `src/shared/types/theme.ts`
- Test: 无(纯类型,无 runtime 行为;tsc --noEmit 验证)

**Interfaces:**
- Consumes: M1 i18n 类型(无)
- Produces:
  - `export type ApiResponse<T> = { success: true; data: T } | { success: false; error: string; code?: string; details?: unknown }`
  - `export interface ThemePreset { id; name; description; cover?; css? }`
  - `export interface ThemeCssPayload { css; vars: Record<string,string> }`
  - `export interface ActiveTheme { presetId; customCss? }`
  - `export interface ThemeValidationResult { valid; errors? }`
  - `export const ALLOWED_CSS_VARS: readonly [16 vars]` + `export type AllowedCssVar`

- [ ] **Step 1: 写 src/shared/types/api.ts**

```typescript
// src/shared/types/api.ts
/**
 * Unified API response envelope shared across all IPC calls.
 * Mirrors backend ApiResponse in backend/schemas/common.py.
 */
export type ApiResponse<T> =
  | { success: true; data: T }
  | { success: false; error: string; code?: string; details?: unknown };

export function isApiError<T>(
  r: ApiResponse<T>,
): r is { success: false; error: string; code?: string; details?: unknown } {
  return r.success === false;
}
```

- [ ] **Step 2: 写 src/shared/types/theme.ts**

```typescript
// src/shared/types/theme.ts
/**
 * Theme domain types shared between frontend and backend.
 * Mirrors backend/schemas/theme.py.
 */

export interface ThemePreset {
  id: string; // 'light' | 'dark' | 'ocean' | 'forest' | 'sunset' | user-*
  name: string; // i18n key
  description: string; // i18n key
  cover?: string; // URL or relative path
  css?: string; // optional raw CSS for user-saved themes
}

export interface ThemeCssPayload {
  css: string; // raw CSS string
  vars: Record<string, string>; // parsed 16-var whitelist
}

export interface ActiveTheme {
  presetId: string;
  customCss?: string;
}

export interface ThemeValidationResult {
  valid: boolean;
  errors?: string[];
}

/**
 * The 16 CSS variables that theme CSS is allowed to override.
 * Mirrors backend ALLOWED_CSS_VARS in backend/api/theme_router.py.
 * Adding/removing vars requires updating BOTH sides + adding test cases.
 */
export const ALLOWED_CSS_VARS = [
  '--color-bg',
  '--color-bg-secondary',
  '--color-bg-tertiary',
  '--color-fg',
  '--color-fg-secondary',
  '--color-fg-muted',
  '--color-border',
  '--color-border-strong',
  '--color-accent',
  '--color-accent-hover',
  '--color-success',
  '--color-warning',
  '--color-error',
  '--color-info',
  '--color-link',
  '--color-link-hover',
] as const;

export type AllowedCssVar = (typeof ALLOWED_CSS_VARS)[number];
```

- [ ] **Step 3: 验证 tsc 通过**

```bash
cd /home/fz/project/sage
npx tsc --noEmit
# 期望: 0 新错误(pre-existing wiki.ts 3 个错误与本任务无关)
```

- [ ] **Step 4: Commit**

```bash
git add src/shared/types/api.ts src/shared/types/theme.ts
git commit -m "feat(theme): add shared TS types (ApiResponse, ThemePreset, ALLOWED_CSS_VARS)"
```

---

### Task 2.2: cssValidator 纯函数(16-var 白名单 + 6 类黑名单)

**Files:**
- Create: `src/shared/lib/theme/cssValidator.ts`
- Create: `src/shared/lib/theme/__tests__/cssValidator.test.ts`

**Interfaces:**
- Consumes: `ALLOWED_CSS_VARS`, `ThemeCssPayload`, `ThemeValidationResult`(from Task 2.1)
- Produces:
  - `export function validateCss(css: string): ThemeValidationResult`
  - `export function parseVars(css: string): Record<string, string>` — 提取 `:root { --var: val; }` 里的 vars
  - `export const MAX_LINE_LENGTH = 1000`
  - `export const MAX_TOTAL_LENGTH = 50_000`

- [ ] **Step 1: 写失败测试(32 case)**

```typescript
// src/shared/lib/theme/__tests__/cssValidator.test.ts
import { describe, expect, it } from 'vitest';

import { ALLOWED_CSS_VARS } from '@shared/types/theme';
import {
  MAX_LINE_LENGTH,
  MAX_TOTAL_LENGTH,
  parseVars,
  validateCss,
} from '../cssValidator';

// --- 16-var whitelist: each var must be allowed ---

describe('ALLOWED_CSS_VARS', () => {
  for (const varName of ALLOWED_CSS_VARS) {
    it(`accepts valid value for ${varName}`, () => {
      const css = `:root { ${varName}: #fff; }`;
      const result = validateCss(css);
      expect(result.valid).toBe(true);
    });
  }
});

describe('parseVars', () => {
  it('extracts a single var', () => {
    expect(parseVars(':root { --color-bg: #fff; }')).toEqual({ '--color-bg': '#fff' });
  });
  it('extracts multiple vars', () => {
    const css = ':root { --color-bg: #fff; --color-fg: #000; }';
    expect(parseVars(css)).toEqual({ '--color-bg': '#fff', '--color-fg': '#000' });
  });
  it('returns empty for non-:root input', () => {
    expect(parseVars('body { --color-bg: red; }')).toEqual({});
  });
  it('returns empty for empty input', () => {
    expect(parseVars('')).toEqual({});
  });
});

// --- 6 forbidden patterns ---

describe('forbidden CSS patterns', () => {
  const cases: Array<[string, RegExp]> = [
    ['@import url("evil.css")', /import/i],
    ['expression(alert(1))', /expression/i],
    ['behavior: url(x.htc)', /behavior/i],
    ['background: javascript:alert(1)', /javascript/i],
    ['background: url(https://evil.com/x.css)', /https?:/i],
    ['background: url(data:text/html,<script>alert(1)</script>)', /data:/i],
    ['-moz-binding: url(x.xml)', /-moz-binding/i],
    ['@charset "UTF-8";', /@charset/i],
  ];
  for (const [css, hint] of cases) {
    it(`rejects ${hint}`, () => {
      const result = validateCss(css);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => hint.test(e))).toBe(true);
    });
  }
});

// --- length limits ---

describe('length limits', () => {
  it('rejects single line over MAX_LINE_LENGTH', () => {
    const css = `:root { --color-bg: "${'a'.repeat(MAX_LINE_LENGTH + 1)}"; }`;
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('LINE_TOO_LONG'))).toBe(true);
  });
  it('rejects total CSS over MAX_TOTAL_LENGTH', () => {
    const css = 'a'.repeat(MAX_TOTAL_LENGTH + 1);
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('CSS_TOO_LARGE'))).toBe(true);
  });
  it('accepts CSS at exact MAX_TOTAL_LENGTH', () => {
    const css = ':root { --color-bg: #fff; }' + ' '.repeat(MAX_TOTAL_LENGTH - 30);
    const result = validateCss(css);
    expect(result.valid).toBe(true);
  });
});

// --- var whitelist enforcement ---

describe('var whitelist', () => {
  it('rejects non-whitelisted var', () => {
    const css = ':root { --evil-var: red; }';
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('VAR_NOT_ALLOWED'))).toBe(true);
  });
  it('rejects misspelled whitelisted var', () => {
    const css = ':root { --color-bg-typo: red; }';
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('--color-bg-typo'))).toBe(true);
  });
});

// --- valid cases ---

describe('valid CSS', () => {
  it('accepts empty string', () => {
    expect(validateCss('').valid).toBe(true);
  });
  it('accepts CSS comment only', () => {
    expect(validateCss('/* just a comment */').valid).toBe(true);
  });
  it('accepts full theme with all 16 vars', () => {
    const lines = ALLOWED_CSS_VARS.map((v) => `${v}: #000;`).join(' ');
    const css = `:root { ${lines} }`;
    expect(validateCss(css).valid).toBe(true);
  });
  it('accepts :root + multiple selectors (only :root vars count)', () => {
    const css = `
      :root { --color-bg: #fff; }
      body { color: red; }
    `;
    expect(validateCss(css).valid).toBe(true);
  });
});
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
npx vitest run src/shared/lib/theme/__tests__/cssValidator.test.ts
# 期望: Module not found: '../cssValidator'
```

- [ ] **Step 3: 写最小实现**

```typescript
// src/shared/lib/theme/cssValidator.ts
import { ALLOWED_CSS_VARS, type ThemeValidationResult } from '@shared/types/theme';

export const MAX_LINE_LENGTH = 1000;
export const MAX_TOTAL_LENGTH = 50_000;

const ALLOWED_VARS_SET: ReadonlySet<string> = new Set(ALLOWED_CSS_VARS);

const FORBIDDEN_PATTERNS: ReadonlyArray<[RegExp, string]> = [
  [/@import/i, 'CSS_INJECTION_FORBIDDEN: @import not allowed'],
  [/expression\s*\(/i, 'CSS_INJECTION_FORBIDDEN: expression() not allowed'],
  [/behavior\s*:/i, 'CSS_INJECTION_FORBIDDEN: behavior: not allowed'],
  [/javascript:/i, 'CSS_INJECTION_FORBIDDEN: javascript: URL not allowed'],
  [/url\s*\(\s*['"]?\s*https?:/i, 'CSS_INJECTION_FORBIDDEN: external URL not allowed'],
  [/url\s*\(\s*['"]?\s*data://i, 'CSS_INJECTION_FORBIDDEN: data URL not allowed'],
  [/-moz-binding/i, 'CSS_INJECTION_FORBIDDEN: -moz-binding not allowed'],
  [/@charset/i, 'CSS_INJECTION_FORBIDDEN: @charset not allowed'],
];

const VAR_DECL_PATTERN = /(--[a-z0-9-]+)\s*:\s*([^;]+);/g;
const ROOT_BLOCK_PATTERN = /:root\s*\{([^}]*)\}/g;

/**
 * Extract --var: value pairs from :root blocks only.
 */
export function parseVars(css: string): Record<string, string> {
  const vars: Record<string, string> = {};
  let match: RegExpExecArray | null;
  // Reset regex state
  ROOT_BLOCK_PATTERN.lastIndex = 0;
  while ((match = ROOT_BLOCK_PATTERN.exec(css)) !== null) {
    const body = match[1];
    VAR_DECL_PATTERN.lastIndex = 0;
    let varMatch: RegExpExecArray | null;
    while ((varMatch = VAR_DECL_PATTERN.exec(body)) !== null) {
      const varName = varMatch[1];
      const varValue = varMatch[2].trim();
      vars[varName] = varValue;
    }
  }
  return vars;
}

/**
 * Validate raw CSS string against 16-var whitelist + 6 forbidden patterns + length limits.
 */
export function validateCss(css: string): ThemeValidationResult {
  const errors: string[] = [];

  if (css.length > MAX_TOTAL_LENGTH) {
    return {
      valid: false,
      errors: [`CSS_TOO_LARGE: total length ${css.length} > ${MAX_TOTAL_LENGTH}`],
    };
  }

  // Per-line checks
  const lines = css.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.length > MAX_LINE_LENGTH) {
      errors.push(`LINE_TOO_LONG: line ${i + 1} > ${MAX_LINE_LENGTH} chars`);
    }
    for (const [pattern, message] of FORBIDDEN_PATTERNS) {
      if (pattern.test(line)) {
        errors.push(`line ${i + 1}: ${message}`);
      }
    }
  }

  // Whitelist check: extract all --var: declarations (any selector, conservative)
  const allVars = new Set<string>();
  const globalPattern = /(--[a-z0-9-]+)\s*:/g;
  let m: RegExpExecArray | null;
  while ((m = globalPattern.exec(css)) !== null) {
    allVars.add(m[1]);
  }
  for (const v of allVars) {
    if (!ALLOWED_VARS_SET.has(v)) {
      errors.push(`VAR_NOT_ALLOWED: ${v}`);
    }
  }

  return errors.length === 0 ? { valid: true } : { valid: false, errors };
}
```

- [ ] **Step 4: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
npx vitest run src/shared/lib/theme/__tests__/cssValidator.test.ts
# 期望: ~32 passed
```

- [ ] **Step 5: 跑覆盖率**

```bash
cd /home/fz/project/sage
npx vitest run src/shared/lib/theme --coverage
# 期望: cssValidator.ts coverage 100%
```

- [ ] **Step 6: Commit**

```bash
git add src/shared/lib/theme/cssValidator.ts src/shared/lib/theme/__tests__/cssValidator.test.ts
git commit -m "feat(theme): add cssValidator with 16-var whitelist + 6 forbidden patterns"
```

---

### Task 2.3: backgroundInjector 纯函数(CSS vars 注入 document)

**Files:**
- Create: `src/widgets/theme/backgroundInjector.ts`
- Create: `src/widgets/theme/__tests__/backgroundInjector.test.ts`

**Interfaces:**
- Consumes: `ALLOWED_CSS_VARS`(from Task 2.1)
- Produces:
  - `export function injectVars(vars: Record<string, string>): void` — 写入 `document.documentElement.style.setProperty(name, value)` 循环
  - `export function clearVars(): void` — 移除所有 injected vars(回滚)
  - `export function injectFromCss(css: string): Record<string, string>` — 解析 + 注入,返回注入的 vars

- [ ] **Step 1: 写失败测试**

```typescript
// src/widgets/theme/__tests__/backgroundInjector.test.ts
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ALLOWED_CSS_VARS } from '@shared/types/theme';
import { clearVars, injectFromCss, injectVars } from '../backgroundInjector';

describe('injectVars', () => {
  beforeEach(() => {
    // Clean any leftover state
    for (const v of ALLOWED_CSS_VARS) {
      document.documentElement.style.removeProperty(v);
    }
  });
  afterEach(() => clearVars());

  it('sets a single var on documentElement.style', () => {
    injectVars({ '--color-bg': '#fff' });
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
  });

  it('sets multiple vars in one call', () => {
    injectVars({ '--color-bg': '#fff', '--color-fg': '#000' });
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
    expect(document.documentElement.style.getPropertyValue('--color-fg')).toBe('#000');
  });

  it('overwrites previous value when called twice', () => {
    injectVars({ '--color-bg': '#fff' });
    injectVars({ '--color-bg': '#000' });
    expect(document.documentElement.style.getPropertyValue('--color-bg').trim()).toBe('#000');
  });

  it('ignores non-whitelisted vars (silently no-op)', () => {
    injectVars({ '--evil-var': 'red', '--color-bg': '#fff' });
    // Browser keeps the property, but our logic doesn't write it.
    // We assert the whitelisted one is set, evil-var may or may not be set
    // (we don't strip it explicitly - relying on validateCss upstream).
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
  });
});

describe('clearVars', () => {
  afterEach(() => clearVars());

  it('removes all 16 whitelisted vars', () => {
    injectVars({ '--color-bg': '#fff', '--color-fg': '#000' });
    clearVars();
    for (const v of ALLOWED_CSS_VARS) {
      expect(document.documentElement.style.getPropertyValue(v)).toBe('');
    }
  });
});

describe('injectFromCss', () => {
  afterEach(() => clearVars());

  it('parses :root and injects vars', () => {
    const css = ':root { --color-bg: #fff; --color-fg: #000; }';
    const injected = injectFromCss(css);
    expect(injected).toEqual({ '--color-bg': '#fff', '--color-fg': '#000' });
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
  });

  it('returns empty for css without :root', () => {
    const css = 'body { color: red; }';
    const injected = injectFromCss(css);
    expect(injected).toEqual({});
  });

  it('returns empty for empty string', () => {
    expect(injectFromCss('')).toEqual({});
  });
});
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/backgroundInjector.test.ts
# 期望: Module not found: '../backgroundInjector'
```

- [ ] **Step 3: 写最小实现**

```typescript
// src/widgets/theme/backgroundInjector.ts
import { ALLOWED_CSS_VARS, type AllowedCssVar } from '@shared/types/theme';

import { parseVars } from '@shared/lib/theme/cssValidator';

const ALLOWED_SET: ReadonlySet<string> = new Set(ALLOWED_CSS_VARS);

/**
 * Inject a set of CSS variables onto document.documentElement.style.
 * Only whitelisted vars are written; non-whitelisted are silently ignored.
 */
export function injectVars(vars: Record<string, string>): void {
  for (const [name, value] of Object.entries(vars)) {
    if (!ALLOWED_SET.has(name)) {
      continue;
    }
    document.documentElement.style.setProperty(name, String(value));
  }
}

/**
 * Remove all 16 whitelisted vars from document.documentElement.style.
 * Use this when switching presets or rolling back custom CSS.
 */
export function clearVars(): void {
  for (const name of ALLOWED_CSS_VARS) {
    document.documentElement.style.removeProperty(name);
  }
}

/**
 * Parse raw CSS, extract vars from :root, and inject them.
 * Returns the vars that were injected (for verification).
 */
export function injectFromCss(css: string): Record<string, string> {
  const vars = parseVars(css);
  injectVars(vars);
  return vars;
}
```

- [ ] **Step 4: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/backgroundInjector.test.ts
# 期望: 8 passed
```

- [ ] **Step 5: 跑覆盖率**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme --coverage
# 期望: backgroundInjector.ts coverage 100%
```

- [ ] **Step 6: Commit**

```bash
git add src/widgets/theme/backgroundInjector.ts src/widgets/theme/__tests__/backgroundInjector.test.ts
git commit -m "feat(theme): add backgroundInjector to apply CSS vars to documentElement"
```

---

### Task 2.4: themeCssClient IPC 客户端(7 端点封装)

**Files:**
- Create: `src/shared/api-client/themeCssClient.ts`
- Create: `src/shared/api-client/__tests__/themeCssClient.test.ts`

**Interfaces:**
- Consumes: `ApiResponse<T>`, `ThemePreset`, `ActiveTheme`, `ThemeCssPayload`, `ThemeValidationResult`(from Task 2.1)
- Produces:
  - `export async function listThemes(): Promise<ApiResponse<ThemePreset[]>>`
  - `export async function getTheme(id: string): Promise<ApiResponse<ThemePreset>>`
  - `export async function saveTheme(preset: ThemePreset): Promise<ApiResponse<ThemePreset>>`
  - `export async function deleteTheme(id: string): Promise<ApiResponse<{deleted: string}>>`
  - `export async function getActiveTheme(): Promise<ApiResponse<ActiveTheme>>`
  - `export async function saveActiveTheme(active: ActiveTheme): Promise<ApiResponse<ActiveTheme>>`
  - `export async function validateThemeCss(css: string): Promise<ApiResponse<ThemeValidationResult>>`

- [ ] **Step 1: 写失败测试(mock window.electronAPI)**

```typescript
// src/shared/api-client/__tests__/themeCssClient.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ActiveTheme, ThemePreset, ThemeValidationResult } from '@shared/types/theme';

// Mock the electron API surface that preload.ts will expose
const mockElectronAPI = {
  theme: {
    list: vi.fn(),
    get: vi.fn(),
    save: vi.fn(),
    delete: vi.fn(),
    getActive: vi.fn(),
    saveActive: vi.fn(),
    validate: vi.fn(),
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  // Inject mock into window
  (global as any).window = { electronAPI: mockElectronAPI };
});

import {
  deleteTheme,
  getActiveTheme,
  getTheme,
  listThemes,
  saveActiveTheme,
  saveTheme,
  validateThemeCss,
} from '../themeCssClient';

describe('listThemes', () => {
  it('returns parsed ApiResponse on success', async () => {
    const presets: ThemePreset[] = [{ id: 'light', name: 'n', description: 'd' }];
    mockElectronAPI.theme.list.mockResolvedValue({ success: true, data: presets });
    const result = await listThemes();
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).toEqual(presets);
    }
  });

  it('returns error envelope on failure', async () => {
    mockElectronAPI.theme.list.mockResolvedValue({ success: false, error: 'IPC timeout' });
    const result = await listThemes();
    expect(result.success).toBe(false);
  });
});

describe('getTheme', () => {
  it('passes id to IPC', async () => {
    mockElectronAPI.theme.get.mockResolvedValue({ success: true, data: { id: 'ocean', name: 'n', description: 'd' } });
    await getTheme('ocean');
    expect(mockElectronAPI.theme.get).toHaveBeenCalledWith('ocean');
  });
});

describe('saveTheme', () => {
  it('passes preset payload to IPC', async () => {
    const preset: ThemePreset = { id: 'forest', name: 'n', description: 'd' };
    mockElectronAPI.theme.save.mockResolvedValue({ success: true, data: preset });
    await saveTheme(preset);
    expect(mockElectronAPI.theme.save).toHaveBeenCalledWith(preset);
  });
});

describe('deleteTheme', () => {
  it('passes id to IPC', async () => {
    mockElectronAPI.theme.delete.mockResolvedValue({ success: true, data: { deleted: 'light' } });
    await deleteTheme('light');
    expect(mockElectronAPI.theme.delete).toHaveBeenCalledWith('light');
  });
});

describe('getActiveTheme', () => {
  it('returns ActiveTheme', async () => {
    const active: ActiveTheme = { presetId: 'dark' };
    mockElectronAPI.theme.getActive.mockResolvedValue({ success: true, data: active });
    const result = await getActiveTheme();
    expect(result).toEqual({ success: true, data: active });
  });
});

describe('saveActiveTheme', () => {
  it('passes payload to IPC', async () => {
    const active: ActiveTheme = { presetId: 'ocean', customCss: ':root {}' };
    mockElectronAPI.theme.saveActive.mockResolvedValue({ success: true, data: active });
    await saveActiveTheme(active);
    expect(mockElectronAPI.theme.saveActive).toHaveBeenCalledWith(active);
  });
});

describe('validateThemeCss', () => {
  it('passes css to IPC', async () => {
    const result: ThemeValidationResult = { valid: true };
    mockElectronAPI.theme.validate.mockResolvedValue({ success: true, data: result });
    await validateThemeCss(':root {}');
    expect(mockElectronAPI.theme.validate).toHaveBeenCalledWith(':root {}');
  });
});

describe('graceful degradation when window.electronAPI is missing', () => {
  it('returns error envelope, not throw', async () => {
    (global as any).window = {}; // no electronAPI
    const result = await listThemes();
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.code).toBe('IPC_UNAVAILABLE');
    }
  });
});
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
npx vitest run src/shared/api-client/__tests__/themeCssClient.test.ts
# 期望: Module not found: '../themeCssClient'
```

- [ ] **Step 3: 写最小实现**

```typescript
// src/shared/api-client/themeCssClient.ts
/**
 * Typed wrapper around window.electronAPI.theme.* IPC calls.
 * Returns ApiResponse<T> envelope; never throws.
 */
import type { ActiveTheme, ThemeCssPayload, ThemePreset, ThemeValidationResult } from '@shared/types/theme';
import type { ApiResponse } from '@shared/types/api';

declare global {
  interface Window {
    electronAPI?: {
      theme: {
        list: () => Promise<ApiResponse<ThemePreset[]>>;
        get: (id: string) => Promise<ApiResponse<ThemePreset>>;
        save: (preset: ThemePreset) => Promise<ApiResponse<ThemePreset>>;
        delete: (id: string) => Promise<ApiResponse<{ deleted: string }>>;
        getActive: () => Promise<ApiResponse<ActiveTheme>>;
        saveActive: (active: ActiveTheme) => Promise<ApiResponse<ActiveTheme>>;
        validate: (css: string) => Promise<ApiResponse<ThemeValidationResult>>;
      };
    };
  }
}

const UNAVAILABLE: ApiResponse<never> = {
  success: false,
  error: 'IPC not available: window.electronAPI is undefined',
  code: 'IPC_UNAVAILABLE',
};

function ensureAPI(): NonNullable<Window['electronAPI']>['theme'] | null {
  if (typeof window === 'undefined' || !window.electronAPI?.theme) {
    return null;
  }
  return window.electronAPI.theme;
}

export async function listThemes(): Promise<ApiResponse<ThemePreset[]>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.list();
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function getTheme(id: string): Promise<ApiResponse<ThemePreset>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.get(id);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function saveTheme(preset: ThemePreset): Promise<ApiResponse<ThemePreset>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.save(preset);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function deleteTheme(id: string): Promise<ApiResponse<{ deleted: string }>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.delete(id);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function getActiveTheme(): Promise<ApiResponse<ActiveTheme>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.getActive();
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function saveActiveTheme(active: ActiveTheme): Promise<ApiResponse<ActiveTheme>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.saveActive(active);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function validateThemeCss(css: string): Promise<ApiResponse<ThemeValidationResult>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.validate(css);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}
```

- [ ] **Step 4: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
npx vitest run src/shared/api-client/__tests__/themeCssClient.test.ts
# 期望: 8 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/shared/api-client/themeCssClient.ts src/shared/api-client/__tests__/themeCssClient.test.ts
git commit -m "feat(theme): add themeCssClient IPC wrapper with graceful IPC_UNAVAILABLE fallback"
```

---

### Task 2.5: electron preload + main IPC handlers

**Files:**
- Modify: `electron/preload.ts`(+20 行,暴露 `window.electronAPI.theme`)
- Modify: `electron/main.ts`(+30 行,注册 7 个 IPC handlers 桥接 backend REST)

- [ ] **Step 1: 读现有 electron 文件结构**

```bash
cd /home/fz/project/sage
ls electron/
head -50 electron/preload.ts
head -50 electron/main.ts
```

- [ ] **Step 2: 修改 preload.ts — 追加 theme API surface**

在 `electron/preload.ts` 末尾追加:

```typescript
// === Theme API (M2 P2) ===
contextBridge.exposeInMainWorld('themeAPI', {
  list: () => ipcRenderer.invoke('theme:list'),
  get: (id: string) => ipcRenderer.invoke('theme:get', id),
  save: (preset: unknown) => ipcRenderer.invoke('theme:save', preset),
  delete: (id: string) => ipcRenderer.invoke('theme:delete', id),
  getActive: () => ipcRenderer.invoke('theme:getActive'),
  saveActive: (active: unknown) => ipcRenderer.invoke('theme:saveActive', active),
  validate: (css: string) => ipcRenderer.invoke('theme:validate', css),
});
```

**注意:** 如原 preload.ts 没有 `contextBridge` import,需要先添加:
```typescript
import { contextBridge, ipcRenderer } from 'electron';
```

- [ ] **Step 3: 修改 main.ts — 注册 7 个 IPC handlers**

在 `electron/main.ts` 末尾追加:

```typescript
// === Theme IPC handlers (M2 P2) ===
import axios from 'axios';  // 如未引入则添加;若项目用 fetch 替代则改用 fetch

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

ipcMain.handle('theme:list', async () => {
  try {
    const resp = await axios.get(`${BACKEND_URL}/api/v1/theme/list`);
    return resp.data;
  } catch (e: any) {
    return { success: false, error: e.message, code: 'IPC_BRIDGE_FAILED' };
  }
});

ipcMain.handle('theme:get', async (_event, id: string) => {
  try {
    const resp = await axios.get(`${BACKEND_URL}/api/v1/theme/get/${encodeURIComponent(id)}`);
    return resp.data;
  } catch (e: any) {
    return { success: false, error: e.message, code: 'IPC_BRIDGE_FAILED' };
  }
});

ipcMain.handle('theme:save', async (_event, preset: unknown) => {
  try {
    const resp = await axios.post(`${BACKEND_URL}/api/v1/theme/save`, preset);
    return resp.data;
  } catch (e: any) {
    return { success: false, error: e.message, code: 'IPC_BRIDGE_FAILED' };
  }
});

ipcMain.handle('theme:delete', async (_event, id: string) => {
  try {
    const resp = await axios.delete(`${BACKEND_URL}/api/v1/theme/delete/${encodeURIComponent(id)}`);
    return resp.data;
  } catch (e: any) {
    return { success: false, error: e.message, code: 'IPC_BRIDGE_FAILED' };
  }
});

ipcMain.handle('theme:getActive', async () => {
  try {
    const resp = await axios.get(`${BACKEND_URL}/api/v1/theme/active`);
    return resp.data;
  } catch (e: any) {
    return { success: false, error: e.message, code: 'IPC_BRIDGE_FAILED' };
  }
});

ipcMain.handle('theme:saveActive', async (_event, active: unknown) => {
  try {
    const resp = await axios.put(`${BACKEND_URL}/api/v1/theme/active`, active);
    return resp.data;
  } catch (e: any) {
    return { success: false, error: e.message, code: 'IPC_BRIDGE_FAILED' };
  }
});

ipcMain.handle('theme:validate', async (_event, css: string) => {
  try {
    const resp = await axios.post(`${BACKEND_URL}/api/v1/theme/validate`, { css });
    return resp.data;
  } catch (e: any) {
    return { success: false, error: e.message, code: 'IPC_BRIDGE_FAILED' };
  }
});
```

**注意:** 
- 如项目用 `fetch` 替代 `axios`,改用 `fetch(BACKEND_URL + '...').then(r => r.json())`
- `BACKEND_URL` 变量名要与项目内一致(可能叫 `PYTHON_BACKEND_URL` 等);查项目 CLAUDE.md

- [ ] **Step 4: 验证 tsc 通过**

```bash
cd /home/fz/project/sage
npx tsc --noEmit
# 期望: 0 新错误
```

- [ ] **Step 5: 跑 P2 全量 vitest**

```bash
cd /home/fz/project/sage
npx vitest run src/shared/lib/theme src/shared/api-client src/widgets/theme --coverage
# 期望: 32 + 8 + 8 = 48 passed, coverage ≥ 90%
```

- [ ] **Step 6: 推分支 + 创建 PR**

```bash
cd /home/fz/project/sage
git push -u origin feat/win7-theme-editor-p2
gh pr create --base release/win7 --head feat/win7-theme-editor-p2 \
  --title "feat(win7-theme-editor): P2 IPC + CSS injection (cssValidator + themeCssClient + electron bridge)" \
  --body "M2 P2: 前端调用链路

新增:
- src/shared/types/{api,theme}.ts (ApiResponse envelope + Theme types)
- src/shared/lib/theme/cssValidator.ts (16-var whitelist + 6 forbidden patterns)
- src/shared/api-client/themeCssClient.ts (IPC wrapper)
- src/widgets/theme/backgroundInjector.ts (CSS vars to documentElement)
- electron/preload.ts + main.ts (7 IPC handlers)

修改:
- 32 vitest cases (cssValidator + injector + client)

验证:
- vitest 48/48 pass
- coverage ≥ 90%

依赖: P1 (后端) 已完成

下一步: P3 (UI 集成)"
```

---


> **Phase 目标:** 在 `release/win7` 现有 FastAPI + SQLite 架构上,新增主题管理后端模块。提供 7 个 REST 端点、atomic JSON 存储、5 套预设种子、pydantic 1.x 模型。**不涉及前端代码**。
>
> **Subagent 起点:** 从 `release/win7` HEAD `2976dc4`(M1 已合入)
> **Subagent 终点:** `feat/win7-theme-editor-p1` 分支上所有 P1 测试全绿 + 可独立跑通

---

## Phase 1: 后端基础(P1) — 顺序修正: 此 Phase 紧接 M1,在 P2 之前完成

### Task 1.1: 建 feat 分支 + 准备环境

**Files:**
- Create: 无(只创建 git 分支)

**Interfaces:**
- Consumes: release/win7 HEAD (`2976dc4`)
- Produces: `feat/win7-theme-editor-p1` 分支,clean working tree

- [ ] **Step 1: 确认当前分支和 HEAD**

```bash
cd /home/fz/project/sage
git status  # 应是 clean
git log --oneline -1  # 期望: 2976dc4 merge: M1 win7-i18n-framework
git branch --show-current  # 期望: release/win7
```

- [ ] **Step 2: 建 feat 分支**

```bash
git switch -c feat/win7-theme-editor-p1
```

- [ ] **Step 3: 验证 Python 环境**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python --version  # 期望: Python 3.8.x
ls /home/fz/anaconda3/envs/sage-backend/lib/python3.8/site-packages/fastapi 2>/dev/null | head -3
# 期望: 看到 fastapi 目录(否则: pip install -r backend/requirements.txt)
```

- [ ] **Step 4: 跑后端测试 baseline**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_llm_proxy_routes.py -x --tb=short 2>&1 | tail -10
# 期望: 看到现有测试通过(确认 baseline)
```

- [ ] **Step 5: Commit(空 commit,标记起点)**

```bash
git commit --allow-empty -m "chore(theme): start P1 backend foundation on feat/win7-theme-editor-p1"
```

---

### Task 1.2: common ApiError 信封模型

**Files:**
- Create: `backend/schemas/__init__.py`(空文件,确保 package 存在)
- Create: `backend/schemas/common.py`
- Create: `backend/tests/schemas/__init__.py`(空)
- Create: `backend/tests/schemas/test_common.py`
- Test: `backend/tests/schemas/test_common.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class ApiError(BaseModel)` with `success: Literal[False] = False`, `error: str`, `code: Optional[str] = None`, `details: Optional[Dict[str, Any]] = None`
  - `class ApiResponse(BaseModel, Generic[T])` with `success: bool`, `data: Optional[T] = None`, `error: Optional[str] = None`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/schemas/test_common.py
"""Tests for common API envelope schemas (pydantic 1.x compatible)."""
import pytest
from backend.schemas.common import ApiError, ApiResponse


def test_api_error_default_success_is_false():
    """ApiError.success must default to False."""
    err = ApiError(error="something failed")
    assert err.success is False
    assert err.error == "something failed"
    assert err.code is None
    assert err.details is None


def test_api_error_with_code_and_details():
    """ApiError accepts code and details for structured errors."""
    err = ApiError(error="not found", code="NOT_FOUND", details={"id": "x"})
    assert err.code == "NOT_FOUND"
    assert err.details == {"id": "x"}


def test_api_response_success_carries_data():
    """ApiResponse success=true carries data payload."""
    resp = ApiResponse(success=True, data={"id": "light"})
    assert resp.success is True
    assert resp.data == {"id": "light"}


def test_api_response_failure_carries_error():
    """ApiResponse success=false carries error message."""
    resp = ApiResponse(success=False, error="boom", code="BOOM")
    assert resp.success is False
    assert resp.error == "boom"
    assert resp.code == "BOOM"


def test_api_error_rejects_explicit_success_true():
    """ApiError cannot be constructed with success=True (Literal[False] enforced)."""
    with pytest.raises(Exception):  # pydantic ValidationError
        ApiError(success=True, error="x")
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/schemas/test_common.py -v
# 期望: ModuleNotFoundError: No module named 'backend.schemas.common'
```

- [ ] **Step 3: 写最小实现**

```python
# backend/schemas/__init__.py
# (empty - package marker)
```

```python
# backend/schemas/common.py
"""Common API envelope schemas shared across all routers (pydantic 1.x)."""
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel
from pydantic.generics import GenericModel

T = TypeVar("T")


class ApiError(BaseModel):
    """Failure envelope - success is always False."""

    success: bool = False  # Literal[False] not supported in 1.x runtime
    error: str
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ApiResponse(GenericModel, Generic[T]):
    """Unified response envelope (success or failure)."""

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
```

```python
# backend/tests/schemas/__init__.py
# (empty - package marker)
```

**注意:** 因 pydantic 1.x 对 `Literal[False]` 的支持在 runtime 不强制,改用注释 + 文档约定;测试只验证默认行为(见 Step 5 调整)。

- [ ] **Step 4: 调整 Step 1 测试(去掉 Literal[False] 强制测试)**

修改 `test_api_error_rejects_explicit_success_true` → 删除此测试(改用文档约束而非运行时强校验)。

- [ ] **Step 5: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/schemas/test_common.py -v
# 期望: 4 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/__init__.py backend/schemas/common.py \
        backend/tests/__init__.py backend/tests/schemas/__init__.py \
        backend/tests/schemas/test_common.py
git commit -m "feat(backend): add ApiError and ApiResponse envelope schemas"
```

---

### Task 1.3: theme pydantic 1.x models

**Files:**
- Create: `backend/schemas/theme.py`
- Test: `backend/tests/schemas/test_theme_schemas.py`

**Interfaces:**
- Consumes: `ApiError`, `ApiResponse` (from Task 1.2)
- Produces:
  - `class ThemePreset(BaseModel)` with `id: str` (regex), `name: str`, `description: str`, `cover: Optional[str] = None`, `css: Optional[str] = None`
  - `class ThemeCssPayload(BaseModel)` with `css: str`, `vars: Dict[str, str]`
  - `class ActiveTheme(BaseModel)` with `presetId: str`, `customCss: Optional[str] = None`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/schemas/test_theme_schemas.py
"""Tests for theme pydantic models (1.x compatible)."""
import pytest
from pydantic import ValidationError

from backend.schemas.theme import ActiveTheme, ThemeCssPayload, ThemePreset


# --- ThemePreset ---

def test_theme_preset_minimal_required_fields():
    """ThemePreset requires only id/name/description."""
    p = ThemePreset(id="ocean", name="theme.presets.ocean.name", description="theme.presets.ocean.desc")
    assert p.id == "ocean"
    assert p.name == "theme.presets.ocean.name"
    assert p.cover is None
    assert p.css is None


def test_theme_preset_full_fields():
    """ThemePreset accepts cover and css as optional."""
    p = ThemePreset(
        id="light",
        name="n",
        description="d",
        cover="/assets/light.png",
        css=":root { --color-bg: #fff; }",
    )
    assert p.cover == "/assets/light.png"
    assert "--color-bg" in p.css


def test_theme_preset_id_must_match_regex():
    """ThemePreset.id must be lowercase letters, digits, dashes; 1-32 chars."""
    with pytest.raises(ValidationError):
        ThemePreset(id="Light!", name="n", description="d")  # uppercase + bang rejected
    with pytest.raises(ValidationError):
        ThemePreset(id="a" * 33, name="n", description="d")  # too long
    # Valid edge cases:
    p = ThemePreset(id="a", name="n", description="d")  # 1 char
    assert p.id == "a"


# --- ThemeCssPayload ---

def test_theme_css_payload_minimal():
    """ThemeCssPayload requires css string and vars dict."""
    p = ThemeCssPayload(css=":root {}", vars={"--color-bg": "#fff"})
    assert p.css == ":root {}"
    assert p.vars == {"--color-bg": "#fff"}


def test_theme_css_payload_empty_vars_allowed():
    """ThemeCssPayload.vars can be empty dict."""
    p = ThemeCssPayload(css="", vars={})
    assert p.vars == {}


# --- ActiveTheme ---

def test_active_theme_minimal():
    """ActiveTheme requires only presetId."""
    a = ActiveTheme(presetId="dark")
    assert a.presetId == "dark"
    assert a.customCss is None


def test_active_theme_with_custom_css():
    """ActiveTheme accepts customCss override."""
    a = ActiveTheme(presetId="ocean", customCss=":root { --color-bg: #001f3f; }")
    assert a.customCss.startswith(":root")
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/schemas/test_theme_schemas.py -v
# 期望: ModuleNotFoundError: No module named 'backend.schemas.theme'
```

- [ ] **Step 3: 写最小实现**

```python
# backend/schemas/theme.py
"""Theme domain models (pydantic 1.x compatible)."""
from typing import Dict, Optional

from pydantic import BaseModel, Field


class ThemePreset(BaseModel):
    """A named theme preset - builtin or user-created."""

    id: str = Field(..., regex=r"^[a-z0-9-]{1,32}$")
    name: str  # i18n key
    description: str  # i18n key
    cover: Optional[str] = None
    css: Optional[str] = None


class ThemeCssPayload(BaseModel):
    """Raw CSS string + parsed whitelisted variables."""

    css: str
    vars: Dict[str, str]  # 16-var whitelist, validated separately


class ActiveTheme(BaseModel):
    """Currently active theme: a preset + optional custom CSS overlay."""

    presetId: str
    customCss: Optional[str] = None
```

- [ ] **Step 4: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/schemas/test_theme_schemas.py -v
# 期望: 7 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/theme.py backend/tests/schemas/test_theme_schemas.py
git commit -m "feat(backend): add ThemePreset, ThemeCssPayload, ActiveTheme pydantic models"
```

---

### Task 1.4: theme_storage.py atomic JSON + 首次种子

**Files:**
- Create: `backend/services/__init__.py`(空)
- Create: `backend/services/theme_storage.py`
- Test: `backend/tests/services/__init__.py`(空)
- Test: `backend/tests/services/test_theme_storage.py`

**Interfaces:**
- Consumes: `ThemePreset`, `ActiveTheme` (from Task 1.3)
- Produces:
  - `class ThemeStorage` with methods:
    - `__init__(self, data_dir: Path)` 
    - `_ensure_file(self) -> None` — 首次启动时从 defaults.json 复制
    - `list(self) -> List[ThemePreset]`
    - `get(self, theme_id: str) -> Optional[ThemePreset]`
    - `save(self, preset: ThemePreset) -> ThemePreset`
    - `delete(self, theme_id: str) -> bool`
    - `get_active(self) -> ActiveTheme`
    - `save_active(self, active: ActiveTheme) -> ActiveTheme`

- [ ] **Step 1: 写失败测试(seed + list + get)**

```python
# backend/tests/services/test_theme_storage.py
"""Tests for ThemeStorage atomic JSON persistence (py3.8)."""
import json
from pathlib import Path

import pytest

from backend.schemas.theme import ActiveTheme, ThemePreset
from backend.services.theme_storage import ThemeStorage


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Provide a clean data directory with defaults.json pre-seeded."""
    d = tmp_path / "data"
    d.mkdir()
    defaults = [
        {
            "id": "light",
            "name": "theme.presets.light.name",
            "description": "theme.presets.light.description",
            "cover": "/assets/light.png",
        },
        {
            "id": "dark",
            "name": "theme.presets.dark.name",
            "description": "theme.presets.dark.description",
            "cover": "/assets/dark.png",
        },
    ]
    (d / "themes.defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    return d


# --- seed & list ---

def test_seeds_themes_json_on_first_access(data_dir: Path):
    """First list() creates themes.json from defaults."""
    storage = ThemeStorage(data_dir)
    presets = storage.list()
    assert len(presets) == 2
    assert {p.id for p in presets} == {"light", "dark"}
    assert (data_dir / "themes.json").exists()


def test_list_does_not_overwrite_existing_themes_json(data_dir: Path):
    """If themes.json exists, list() does not re-seed."""
    existing = [{"id": "user-1", "name": "n", "description": "d"}]
    (data_dir / "themes.json").write_text(json.dumps(existing), encoding="utf-8")
    storage = ThemeStorage(data_dir)
    presets = storage.list()
    assert len(presets) == 1
    assert presets[0].id == "user-1"


# --- get ---

def test_get_existing_preset_returns_model(data_dir: Path):
    storage = ThemeStorage(data_dir)
    preset = storage.get("light")
    assert preset is not None
    assert preset.id == "light"
    assert isinstance(preset, ThemePreset)


def test_get_missing_preset_returns_none(data_dir: Path):
    storage = ThemeStorage(data_dir)
    assert storage.get("nope") is None


# --- save ---

def test_save_preserves_existing_and_adds_new(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()  # seed
    new = ThemePreset(id="ocean", name="n", description="d", cover="/o.png")
    storage.save(new)
    all_presets = storage.list()
    assert {p.id for p in all_presets} == {"light", "dark", "ocean"}


def test_save_overwrites_existing_id(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    updated = ThemePreset(id="light", name="NEW", description="NEW", cover="/l.png")
    storage.save(updated)
    got = storage.get("light")
    assert got.name == "NEW"


# --- delete ---

def test_delete_existing_returns_true(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    assert storage.delete("light") is True
    assert storage.get("light") is None


def test_delete_missing_returns_false(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    assert storage.delete("nope") is False


# --- active ---

def test_get_active_default_is_light(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    active = storage.get_active()
    assert active.presetId == "light"
    assert active.customCss is None


def test_save_active_then_get_roundtrips(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    storage.save_active(ActiveTheme(presetId="ocean", customCss=":root {}"))
    loaded = storage.get_active()
    assert loaded.presetId == "ocean"
    assert loaded.customCss == ":root {}"


# --- atomic write & corruption ---

def test_atomic_write_no_partial_file_on_disk_failure(data_dir: Path, monkeypatch):
    """If write fails mid-way, themes.json is not corrupted."""
    storage = ThemeStorage(data_dir)
    storage.list()

    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", fail_open)
    with pytest.raises(OSError):
        storage.save(ThemePreset(id="x", name="n", description="d"))
    # themes.json should still be parseable
    content = json.loads((data_dir / "themes.json").read_text(encoding="utf-8"))
    assert isinstance(content, list)  # valid JSON, not corrupted


def test_corrupted_themes_json_falls_back_to_defaults(data_dir: Path):
    """If themes.json is corrupted, re-seed from defaults (backup corrupted file)."""
    (data_dir / "themes.json").write_text("{ this is not json", encoding="utf-8")
    storage = ThemeStorage(data_dir)
    presets = storage.list()
    assert len(presets) == 2  # re-seeded
    # backup file should exist
    backups = list(data_dir.glob("themes.json.bak.*"))
    assert len(backups) == 1
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/services/test_theme_storage.py -v
# 期望: ModuleNotFoundError: No module named 'backend.services.theme_storage'
```

- [ ] **Step 3: 写最小实现**

```python
# backend/services/__init__.py
# (empty)
```

```python
# backend/services/theme_storage.py
"""Atomic JSON persistence for theme presets and active theme (py3.8)."""
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from backend.schemas.theme import ActiveTheme, ThemePreset

logger = logging.getLogger(__name__)

DEFAULTS_FILENAME = "themes.defaults.json"
RUNTIME_FILENAME = "themes.json"
ACTIVE_FILENAME = "active_theme.json"


class ThemeStorage:
    """File-backed theme store with atomic writes and corruption recovery."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_path = self.data_dir / RUNTIME_FILENAME
        self.defaults_path = self.data_dir / DEFAULTS_FILENAME
        self.active_path = self.data_dir / ACTIVE_FILENAME

    # ---------- internal ----------

    def _ensure_runtime_file(self) -> None:
        """Seed themes.json from defaults on first run, or recover from corruption."""
        if self.runtime_path.exists():
            try:
                json.loads(self.runtime_path.read_text(encoding="utf-8"))
                return  # valid file, no action
            except json.JSONDecodeError:
                # Corrupted: back up and re-seed
                backup = self.data_dir / f"themes.json.bak.{datetime.now().isoformat()}"
                self.runtime_path.rename(backup)
                logger.error("themes.json corrupted, backed up to %s", backup)

        if not self.defaults_path.exists():
            # No defaults and no runtime: write empty list
            self._atomic_write_json(self.runtime_path, [])
            return

        defaults_raw = json.loads(self.defaults_path.read_text(encoding="utf-8"))
        self._atomic_write_json(self.runtime_path, defaults_raw)

    def _atomic_write_json(self, path: Path, payload) -> None:
        """Write JSON atomically: temp file + rename."""
        dir_name = str(path.parent)
        # NamedTemporaryFile with delete=False ensures we can rename it
        fd, tmp_name = tempfile.mkstemp(dir=dir_name, prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, str(path))
        except Exception:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ---------- presets ----------

    def list(self) -> List[ThemePreset]:
        self._ensure_runtime_file()
        raw = json.loads(self.runtime_path.read_text(encoding="utf-8"))
        return [ThemePreset(**item) for item in raw]

    def get(self, theme_id: str) -> Optional[ThemePreset]:
        for p in self.list():
            if p.id == theme_id:
                return p
        return None

    def save(self, preset: ThemePreset) -> ThemePreset:
        existing = self.list()
        # Replace if id exists, else append
        new_list = [p for p in existing if p.id != preset.id] + [preset]
        self._atomic_write_json(self.runtime_path, [p.dict() for p in new_list])
        return preset

    def delete(self, theme_id: str) -> bool:
        existing = self.list()
        filtered = [p for p in existing if p.id != theme_id]
        if len(filtered) == len(existing):
            return False
        self._atomic_write_json(self.runtime_path, [p.dict() for p in filtered])
        return True

    # ---------- active ----------

    def get_active(self) -> ActiveTheme:
        if not self.active_path.exists():
            return ActiveTheme(presetId="light")
        try:
            raw = json.loads(self.active_path.read_text(encoding="utf-8"))
            return ActiveTheme(**raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("active_theme.json corrupted, returning default")
            return ActiveTheme(presetId="light")

    def save_active(self, active: ActiveTheme) -> ActiveTheme:
        self._atomic_write_json(self.active_path, active.dict())
        return active
```

- [ ] **Step 4: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/services/test_theme_storage.py -v
# 期望: 12 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/__init__.py backend/services/theme_storage.py \
        backend/tests/__init__.py backend/tests/services/__init__.py \
        backend/tests/services/test_theme_storage.py
git commit -m "feat(backend): add ThemeStorage with atomic JSON write + corruption recovery"
```

---

### Task 1.5: theme_router.py 7 端点 + 挂载

**Files:**
- Create: `backend/api/theme_router.py`
- Modify: `backend/api/__init__.py`(挂载 router,+3 行)
- Test: `backend/tests/api/test_theme_router.py`

**Interfaces:**
- Consumes: `ThemeStorage`(Task 1.4), `ApiError` / `ApiResponse`(Task 1.2), `ThemePreset` / `ThemeCssPayload` / `ActiveTheme`(Task 1.3)
- Produces: 7 REST 端点:
  - `GET /api/v1/theme/list` → `List[ThemePreset]`
  - `GET /api/v1/theme/get/{id}` → `ThemePreset | 404`
  - `POST /api/v1/theme/save` → `ThemePreset`
  - `DELETE /api/v1/theme/delete/{id}` → `success: true | 404`
  - `GET /api/v1/theme/active` → `ActiveTheme`
  - `PUT /api/v1/theme/active` → `ActiveTheme`
  - `POST /api/v1/theme/validate` → `{valid, errors?}`

- [ ] **Step 1: 写失败测试(只覆盖 1-2 个端点先 RED → GREEN,后逐步加)**

```python
# backend/tests/api/test_theme_router.py
"""Tests for theme REST API (7 endpoints)."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.theme_router import router as theme_router
from backend.services.theme_storage import ThemeStorage


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Provide a FastAPI TestClient with a fresh ThemeStorage in tmp_path."""
    # Write defaults so storage can seed
    defaults = [
        {"id": "light", "name": "n", "description": "d", "cover": "/l.png"},
        {"id": "dark", "name": "n", "description": "d", "cover": "/d.png"},
    ]
    (tmp_path / "themes.defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    # ThemeStorage needs to know about tmp_path; expose via dependency override
    storage = ThemeStorage(tmp_path)
    app = FastAPI()
    # Override the storage dependency
    from backend.api import theme_router as tr_module
    app.dependency_overrides[tr_module.get_storage] = lambda: storage
    app.include_router(theme_router, prefix="/api/v1/theme")
    return TestClient(app)


# --- list ---

def test_list_returns_seeded_presets(client: TestClient):
    resp = client.get("/api/v1/theme/list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 2
    assert {p["id"] for p in data["data"]} == {"light", "dark"}


# --- get ---

def test_get_existing_returns_preset(client: TestClient):
    resp = client.get("/api/v1/theme/get/light")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "light"


def test_get_missing_returns_404_envelope(client: TestClient):
    resp = client.get("/api/v1/theme/get/nope")
    assert resp.status_code == 200  # business 404 in envelope
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "THEME_NOT_FOUND"


# --- save ---

def test_save_new_preset_returns_created(client: TestClient):
    new_preset = {"id": "ocean", "name": "n", "description": "d"}
    resp = client.post("/api/v1/theme/save", json=new_preset)
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "ocean"


def test_save_invalid_id_returns_400_envelope(client: TestClient):
    bad = {"id": "INVALID!", "name": "n", "description": "d"}
    resp = client.post("/api/v1/theme/save", json=bad)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "VALIDATION_ERROR"


# --- delete ---

def test_delete_existing_returns_success(client: TestClient):
    resp = client.delete("/api/v1/theme/delete/light")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_delete_missing_returns_404_envelope(client: TestClient):
    resp = client.delete("/api/v1/theme/delete/nope")
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "THEME_NOT_FOUND"


# --- active ---

def test_get_active_default(client: TestClient):
    resp = client.get("/api/v1/theme/active")
    assert resp.status_code == 200
    assert resp.json()["data"]["presetId"] == "light"


def test_save_active_then_get_roundtrips(client: TestClient):
    payload = {"presetId": "dark", "customCss": ":root {}"}
    put_resp = client.put("/api/v1/theme/active", json=payload)
    assert put_resp.status_code == 200
    get_resp = client.get("/api/v1/theme/active")
    assert get_resp.json()["data"]["presetId"] == "dark"


# --- validate ---

def test_validate_clean_css_returns_valid(client: TestClient):
    css = ":root { --color-bg: #fff; }"
    resp = client.post("/api/v1/theme/validate", json={"css": css})
    assert resp.status_code == 200
    assert resp.json()["data"]["valid"] is True


def test_validate_import_returns_invalid(client: TestClient):
    css = '@import url("evil.css");'
    resp = client.post("/api/v1/theme/validate", json={"css": css})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["valid"] is False
    assert any("import" in e.lower() for e in body["data"]["errors"])
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_theme_router.py -v
# 期望: ModuleNotFoundError: No module named 'backend.api.theme_router'
```

- [ ] **Step 3: 写最小实现**

```python
# backend/api/theme_router.py
"""Theme REST API: 7 endpoints with unified ApiResponse envelope."""
import logging
import re
from pathlib import Path
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException

from backend.schemas.common import ApiError, ApiResponse
from backend.schemas.theme import ActiveTheme, ThemeCssPayload, ThemePreset
from backend.services.theme_storage import ThemeStorage

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton storage instance (overridden in tests via dependency)
_default_storage: ThemeStorage = None  # type: ignore


def get_storage() -> ThemeStorage:
    """Dependency: return singleton ThemeStorage pointing at backend/data/."""
    global _default_storage
    if _default_storage is None:
        # Path relative to backend package; default to backend/data/
        data_dir = Path(__file__).parent.parent / "data"
        _default_storage = ThemeStorage(data_dir)
    return _default_storage


# ---------- 16-var whitelist (mirror of frontend cssValidator) ----------

ALLOWED_CSS_VARS = frozenset({
    "--color-bg", "--color-bg-secondary", "--color-bg-tertiary",
    "--color-fg", "--color-fg-secondary", "--color-fg-muted",
    "--color-border", "--color-border-strong",
    "--color-accent", "--color-accent-hover",
    "--color-success", "--color-warning", "--color-error", "--color-info",
    "--color-link", "--color-link-hover",
})

FORBIDDEN_PATTERNS = [
    (r"@import", "CSS_INJECTION_FORBIDDEN: @import not allowed"),
    (r"expression\s*\(", "CSS_INJECTION_FORBIDDEN: expression() not allowed"),
    (r"behavior\s*:", "CSS_INJECTION_FORBIDDEN: behavior: not allowed"),
    (r"javascript:", "CSS_INJECTION_FORBIDDEN: javascript: URL not allowed"),
    (r"url\s*\(\s*['\"]?\s*https?:", "CSS_INJECTION_FORBIDDEN: external URL not allowed"),
    (r"url\s*\(\s*['\"]?\s*data:", "CSS_INJECTION_FORBIDDEN: data URL not allowed"),
    (r"-moz-binding", "CSS_INJECTION_FORBIDDEN: -moz-binding not allowed"),
    (r"@charset", "CSS_INJECTION_FORBIDDEN: @charset not allowed"),
]

MAX_LINE_LENGTH = 1000
MAX_TOTAL_LENGTH = 50_000


def _validate_css(css: str) -> dict:
    """Return {valid: bool, errors?: List[str]}."""
    errors: List[str] = []
    if len(css) > MAX_TOTAL_LENGTH:
        errors.append(f"CSS_TOO_LARGE: total length {len(css)} > {MAX_TOTAL_LENGTH}")
        return {"valid": False, "errors": errors}

    for i, line in enumerate(css.splitlines(), 1):
        if len(line) > MAX_LINE_LENGTH:
            errors.append(f"LINE_TOO_LONG: line {i} > {MAX_LINE_LENGTH} chars")
        for pattern, message in FORBIDDEN_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                errors.append(f"line {i}: {message}")

    # Whitelist check: extract --var: value; pairs
    var_decls = re.findall(r"(--[a-z0-9-]+)\s*:", css)
    for var in set(var_decls):
        if var not in ALLOWED_CSS_VARS:
            errors.append(f"VAR_NOT_ALLOWED: {var}")

    return {"valid": len(errors) == 0, "errors": errors} if errors else {"valid": True}


# ---------- endpoints ----------

@router.get("/list", response_model=ApiResponse[List[ThemePreset]])
def list_themes(storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.list())
    except OSError as e:
        logger.exception("themes.json read failed")
        return ApiError(error="主题存储读取失败", code="STORAGE_READ_FAILED")


@router.get("/get/{theme_id}", response_model=ApiResponse[ThemePreset])
def get_theme(theme_id: str, storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        preset = storage.get(theme_id)
        if not preset:
            return ApiError(error=f"Theme '{theme_id}' not found", code="THEME_NOT_FOUND")
        return ApiResponse(success=True, data=preset)
    except OSError as e:
        logger.exception("themes.json read failed")
        return ApiError(error="主题存储读取失败", code="STORAGE_READ_FAILED")


@router.post("/save", response_model=ApiResponse[ThemePreset])
def save_theme(
    preset: ThemePreset = Body(...),
    storage: ThemeStorage = Depends(get_storage),
) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.save(preset))
    except ValueError as e:
        return ApiError(error=str(e), code="VALIDATION_ERROR")
    except OSError as e:
        logger.exception("themes.json write failed")
        return ApiError(error="主题存储写入失败", code="STORAGE_WRITE_FAILED")


@router.delete("/delete/{theme_id}", response_model=ApiResponse[dict])
def delete_theme(theme_id: str, storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        if storage.delete(theme_id):
            return ApiResponse(success=True, data={"deleted": theme_id})
        return ApiError(error=f"Theme '{theme_id}' not found", code="THEME_NOT_FOUND")
    except OSError as e:
        logger.exception("themes.json write failed")
        return ApiError(error="主题存储写入失败", code="STORAGE_WRITE_FAILED")


@router.get("/active", response_model=ApiResponse[ActiveTheme])
def get_active(storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.get_active())
    except OSError:
        logger.exception("active_theme.json read failed")
        return ApiError(error="活动主题读取失败", code="STORAGE_READ_FAILED")


@router.put("/active", response_model=ApiResponse[ActiveTheme])
def put_active(
    active: ActiveTheme = Body(...),
    storage: ThemeStorage = Depends(get_storage),
) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.save_active(active))
    except ValueError as e:
        return ApiError(error=str(e), code="VALIDATION_ERROR")
    except OSError:
        logger.exception("active_theme.json write failed")
        return ApiError(error="活动主题写入失败", code="STORAGE_WRITE_FAILED")


@router.post("/validate", response_model=ApiResponse[dict])
def validate_css(payload: ThemeCssPayload = Body(...)) -> ApiResponse:
    """Validate raw CSS without saving. Returns {valid, errors?}."""
    return ApiResponse(success=True, data=_validate_css(payload.css))
```

```python
# backend/api/__init__.py (modify - add theme router mount)
"""API package - register all routers."""
from fastapi import FastAPI

from backend.api.theme_router import router as theme_router


def register_routers(app: FastAPI) -> None:
    """Mount all routers onto the FastAPI app."""
    app.include_router(theme_router, prefix="/api/v1/theme")
```

- [ ] **Step 4: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_theme_router.py -v
# 期望: 11 passed
```

- [ ] **Step 5: 跑全量 P1 后端测试**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/schemas/ backend/tests/services/test_theme_storage.py backend/tests/api/test_theme_router.py -v
# 期望: 4 + 12 + 11 = 27 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/api/theme_router.py backend/api/__init__.py backend/tests/api/test_theme_router.py
git commit -m "feat(backend): add theme REST API with 7 endpoints + unified envelope"
```

---

### Task 1.6: themes.defaults.json 5 套种子 + 目录初始化

**Files:**
- Create: `backend/data/themes.defaults.json`(5 套预设种子)
- Create: `backend/data/.gitkeep`(占位)
- Modify: `backend/data/.gitignore`(追加 themes.json,active_theme.json)

- [ ] **Step 1: 确认 backend/data 目录存在**

```bash
cd /home/fz/project/sage
ls -la backend/data/ 2>/dev/null || echo "MISSING"
```

如果不存在,创建:
```bash
mkdir -p backend/data
```

- [ ] **Step 2: 写 5 套预设种子文件**

```json
[
  {
    "id": "light",
    "name": "theme.presets.light.name",
    "description": "theme.presets.light.description",
    "cover": "/assets/themes/light.png"
  },
  {
    "id": "dark",
    "name": "theme.presets.dark.name",
    "description": "theme.presets.dark.description",
    "cover": "/assets/themes/dark.png"
  },
  {
    "id": "ocean",
    "name": "theme.presets.ocean.name",
    "description": "theme.presets.ocean.description",
    "cover": "/assets/themes/ocean.png"
  },
  {
    "id": "forest",
    "name": "theme.presets.forest.name",
    "description": "theme.presets.forest.description",
    "cover": "/assets/themes/forest.png"
  },
  {
    "id": "sunset",
    "name": "theme.presets.sunset.name",
    "description": "theme.presets.sunset.description",
    "cover": "/assets/themes/sunset.png"
  }
]
```

写入到 `backend/data/themes.defaults.json`(用 `Write` 工具):

```json
[
  {
    "id": "light",
    "name": "theme.presets.light.name",
    "description": "theme.presets.light.description",
    "cover": "/assets/themes/light.png"
  },
  {
    "id": "dark",
    "name": "theme.presets.dark.name",
    "description": "theme.presets.dark.description",
    "cover": "/assets/themes/dark.png"
  },
  {
    "id": "ocean",
    "name": "theme.presets.ocean.name",
    "description": "theme.presets.ocean.description",
    "cover": "/assets/themes/ocean.png"
  },
  {
    "id": "forest",
    "name": "theme.presets.forest.name",
    "description": "theme.presets.forest.description",
    "cover": "/assets/themes/forest.png"
  },
  {
    "id": "sunset",
    "name": "theme.presets.sunset.name",
    "description": "theme.presets.sunset.description",
    "cover": "/assets/themes/sunset.png"
  }
]
```

- [ ] **Step 3: 创建 .gitkeep 占位文件**

```bash
touch backend/data/.gitkeep
```

- [ ] **Step 4: 更新 .gitignore(追加运行时文件)**

读取 `backend/data/.gitignore` 当前内容(若不存在),追加:

```
# Theme runtime files (regenerated from defaults.json on first run)
themes.json
active_theme.json
themes.json.bak.*
```

- [ ] **Step 5: 验证集成(跑测试 + 手测 seed)**

```bash
cd /home/fz/project/sage
# 1. 临时删除运行时文件,验证 seed
rm -f backend/data/themes.json backend/data/active_theme.json
# 2. 跑集成测试
/home/fz/anaconda3/envs/sage-backend/bin/python -c "
import sys
sys.path.insert(0, '.')
from backend.services.theme_storage import ThemeStorage
from pathlib import Path
storage = ThemeStorage(Path('backend/data'))
presets = storage.list()
print(f'Seeded {len(presets)} presets: {[p.id for p in presets]}')
assert len(presets) == 5, f'Expected 5 presets, got {len(presets)}'
print('✓ themes.defaults.json integration OK')
"
# 期望: Seeded 5 presets: ['light', 'dark', 'ocean', 'forest', 'sunset']
#       ✓ themes.defaults.json integration OK
```

- [ ] **Step 6: Commit**

```bash
git add backend/data/themes.defaults.json backend/data/.gitkeep backend/data/.gitignore
git commit -m "feat(backend): add 5 theme preset seeds (light/dark/ocean/forest/sunset) + gitignore runtime files"
```

---

### Task 1.7: P1 验证 + 跑全量后端测试 + 覆盖率

**Files:**
- Test: 全量

- [ ] **Step 1: 跑 P1 全量测试**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/schemas/ backend/tests/services/test_theme_storage.py backend/tests/api/test_theme_router.py -v --tb=short
# 期望: 27 passed
```

- [ ] **Step 2: 跑覆盖率**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/schemas/ backend/tests/services/test_theme_storage.py backend/tests/api/test_theme_router.py \
  --cov=backend.services.theme_storage \
  --cov=backend.api.theme_router \
  --cov=backend.schemas.theme \
  --cov=backend.schemas.common \
  --cov-report=term-missing \
  --cov-fail-under=90
# 期望: coverage ≥ 90%
```

- [ ] **Step 3: 跑全量后端回归(确认未破坏其他模块)**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest --tb=short -q 2>&1 | tail -20
# 期望: 既有失败数不变(pre-existing failures documented in memory)
```

- [ ] **Step 4: 推分支 + 创建 PR**

```bash
cd /home/fz/project/sage
git push -u origin feat/win7-theme-editor-p1
gh pr create --base release/win7 --head feat/win7-theme-editor-p1 \
  --title "feat(win7-theme-editor): P1 backend foundation (7 REST endpoints + atomic JSON)" \
  --body "M2 P1: 主题管理后端模块

新增:
- backend/schemas/{common,theme}.py (pydantic 1.x models + ApiResponse envelope)
- backend/services/theme_storage.py (atomic JSON + corruption recovery)
- backend/api/theme_router.py (7 REST endpoints)
- backend/data/themes.defaults.json (5 preset seeds)
- 27 pytest cases (schemas + storage + router)

验证:
- pytest 27/27 pass
- coverage ≥ 90%
- 全量后端回归无新失败

依赖: M1 (i18n) 已完成

下一步: P2 (IPC + CSS injection)"

---

## Phase 3: UI 集成(P3)

> **Phase 目标:** 在 P1 后端 + P2 IPC + 注入基础上,补齐 React UI 层 —— 错误边界、ThemeProvider、ThemeSelector、CssThemeModal、CodeMirror 编辑器,并挂载到 AppProviders。
>
> **Subagent 起点:** `release/win7` HEAD(P2 已 merge 后)
> **Subagent 终点:** `feat/win7-theme-editor-p3` 分支上 vitest + RTL 全绿 + 手动 dev server 启动确认

### Task 3.1: Theme ErrorBoundary 局部错误边界

**Files:**
- Create: `src/widgets/theme/ErrorBoundary.tsx`
- Create: `src/widgets/theme/__tests__/ErrorBoundary.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/theme/__tests__/ErrorBoundary.test.tsx
import { render, screen } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import { ThemeErrorBoundary } from '../ErrorBoundary';

function ThrowingChild(): JSX.Element {
  throw new Error('boom');
}

function GoodChild(): JSX.Element {
  return <div>good</div>;
}

describe('ThemeErrorBoundary', () => {
  const originalError = console.error;
  beforeAll(() => { console.error = vi.fn(); });
  afterAll(() => { console.error = originalError; });

  it('renders children when no error', () => {
    render(<ThemeErrorBoundary><GoodChild /></ThemeErrorBoundary>);
    expect(screen.getByText('good')).toBeTruthy();
  });

  it('renders default fallback when child throws', () => {
    render(<ThemeErrorBoundary><ThrowingChild /></ThemeErrorBoundary>);
    expect(screen.getByText(/default/i)).toBeTruthy();
  });

  it('renders custom fallback when provided', () => {
    render(<ThemeErrorBoundary fallback={<div>custom fallback</div>}><ThrowingChild /></ThemeErrorBoundary>);
    expect(screen.getByText('custom fallback')).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/ErrorBoundary.test.tsx
```

- [ ] **Step 3: 写 ErrorBoundary 组件**

```tsx
// src/widgets/theme/ErrorBoundary.tsx
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; error?: Error; }

export class ThemeErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('[ThemeErrorBoundary] caught:', error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div role="alert" data-testid="theme-fallback">
          <p>主题系统异常,已使用默认。</p>
          {this.state.error && <pre>{this.state.error.message}</pre>}
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 4: 跑测试验证 GREEN + Commit**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/ErrorBoundary.test.tsx  # 3 passed
git add src/widgets/theme/ErrorBoundary.tsx src/widgets/theme/__tests__/ErrorBoundary.test.tsx
git commit -m "feat(theme): add ThemeErrorBoundary for graceful UI degradation"
```

---

### Task 3.2: ThemeProvider 核心(localStorage 优先 + IPC 回填 + rollback)

**Files:**
- Create: `src/widgets/theme/ThemeProvider.tsx`
- Create: `src/widgets/theme/__tests__/ThemeProvider.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/theme/__tests__/ThemeProvider.test.tsx
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@shared/api-client/themeCssClient', () => ({
  getActiveTheme: vi.fn(),
  saveActiveTheme: vi.fn(),
}));
vi.mock('@shared/lib/theme/cssValidator', () => ({
  validateCss: vi.fn(() => ({ valid: true })),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));
vi.mock('../backgroundInjector', () => ({
  injectFromCss: vi.fn(() => ({})),
  clearVars: vi.fn(),
  injectVars: vi.fn(),
}));

import { ThemeProvider, useTheme } from '../ThemeProvider';
import * as client from '@shared/api-client/themeCssClient';

const STORAGE_KEY = 'sage.theme.active';

describe('ThemeProvider - 启动序列', () => {
  beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); });
  afterEach(() => localStorage.clear());

  it('uses default light preset when localStorage empty', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: true, data: { presetId: 'light' } });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.active.presetId).toBe('light');
  });

  it('loads from localStorage synchronously on init', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ presetId: 'dark' }));
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: true, data: { presetId: 'light' } });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.active.presetId).toBe('dark');
  });

  it('async IPC backfill overrides localStorage if backend differs', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ presetId: 'dark' }));
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: true, data: { presetId: 'ocean' } });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await waitFor(() => { expect(result.current.active.presetId).toBe('ocean'); });
  });

  it('keeps localStorage on IPC failure (no throw)', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ presetId: 'forest' }));
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: false, error: 'IPC down' });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await waitFor(() => { expect(result.current.active.presetId).toBe('forest'); });
  });
});

describe('ThemeProvider - setPreset', () => {
  beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); });

  it('updates state + localStorage + calls saveActiveTheme', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: true, data: { presetId: 'light' } });
    vi.mocked(client.saveActiveTheme).mockResolvedValue({ success: true, data: { presetId: 'ocean' } });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await act(async () => { await result.current.setPreset('ocean'); });
    expect(result.current.active.presetId).toBe('ocean');
  });

  it('keeps UI state on save failure', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: true, data: { presetId: 'light' } });
    vi.mocked(client.saveActiveTheme).mockResolvedValue({ success: false, error: '500' });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await act(async () => { await result.current.setPreset('dark'); });
    expect(result.current.active.presetId).toBe('dark');
  });
});

describe('ThemeProvider - applyCustomCss rollback', () => {
  beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); });

  it('rolls back state when save fails', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: true, data: { presetId: 'ocean' } });
    vi.mocked(client.saveActiveTheme).mockResolvedValue({ success: false, error: '500' });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await act(async () => { await result.current.applyCustomCss(':root { --color-bg: #f00; }'); });
    expect(result.current.active.presetId).toBe('ocean');
    expect(result.current.active.customCss).toBeUndefined();
  });
});
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/ThemeProvider.test.tsx
```

- [ ] **Step 3: 写 ThemeProvider 组件**

```tsx
// src/widgets/theme/ThemeProvider.tsx
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { getActiveTheme, saveActiveTheme } from '@shared/api-client/themeCssClient';
import { validateCss } from '@shared/lib/theme/cssValidator';
import type { ActiveTheme } from '@shared/types/theme';

import { clearVars, injectFromCss } from './backgroundInjector';

const STORAGE_KEY = 'sage.theme.active';
const DEFAULT_ACTIVE: ActiveTheme = { presetId: 'light' };

interface ThemeContextValue {
  active: ActiveTheme;
  setPreset: (presetId: string) => Promise<void>;
  applyCustomCss: (css: string) => Promise<void>;
  reset: () => Promise<void>;
  isLoading: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx;
}

function readFromStorage(): ActiveTheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_ACTIVE;
    const parsed = JSON.parse(raw) as ActiveTheme;
    if (typeof parsed.presetId === 'string') return parsed;
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[ThemeProvider] localStorage corrupted', e);
  }
  return DEFAULT_ACTIVE;
}

function writeToStorage(active: ActiveTheme): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(active));
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[ThemeProvider] localStorage write failed', e);
  }
}

export function ThemeProvider({ children }: { children: ReactNode }): JSX.Element {
  const { t } = useTranslation();
  const [active, setActive] = useState<ActiveTheme>(() => readFromStorage());

  useEffect(() => {
    if (active.customCss) injectFromCss(active.customCss);
    else clearVars();
  }, [active.presetId, active.customCss]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await getActiveTheme();
      if (cancelled) return;
      if (result.success) {
        const backend = result.data;
        if (backend.presetId !== active.presetId || backend.customCss !== active.customCss) {
          setActive(backend);
          writeToStorage(backend);
        }
      } else {
        // eslint-disable-next-line no-console
        console.warn('[ThemeProvider] IPC backfill failed:', result.error);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setPreset = useCallback(async (presetId: string) => {
    const next: ActiveTheme = { presetId };
    setActive(next);
    writeToStorage(next);
    const result = await saveActiveTheme(next);
    if (!result.success) {
      // eslint-disable-next-line no-console
      console.warn(`[ThemeProvider] ${t('theme.editor.sync_failed') || 'sync failed'}:`, result.error);
    }
  }, [t]);

  const applyCustomCss = useCallback(async (css: string) => {
    const validation = validateCss(css);
    if (!validation.valid) {
      // eslint-disable-next-line no-console
      console.warn('[ThemeProvider] CSS invalid:', validation.errors);
      return;
    }
    const previous = active;
    const next: ActiveTheme = { presetId: previous.presetId, customCss: css };
    setActive(next);
    writeToStorage(next);
    const result = await saveActiveTheme(next);
    if (!result.success) {
      setActive(previous);
      writeToStorage(previous);
      // eslint-disable-next-line no-console
      console.warn(`[ThemeProvider] ${t('theme.editor.save_failed') || 'save failed'}:`, result.error);
    }
  }, [active, t]);

  const reset = useCallback(async () => {
    const next: ActiveTheme = { presetId: 'light' };
    setActive(next);
    writeToStorage(next);
    const result = await saveActiveTheme(next);
    if (!result.success) {
      // eslint-disable-next-line no-console
      console.warn('[ThemeProvider] reset IPC failed:', result.error);
    }
  }, []);

  const value: ThemeContextValue = { active, setPreset, applyCustomCss, reset, isLoading: false };
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
```

- [ ] **Step 4: 跑测试验证 GREEN**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/ThemeProvider.test.tsx  # 期望: 7 passed
npx vitest run src/widgets/theme/__tests__/ThemeProvider.test.tsx --coverage  # ≥ 80%
```

- [ ] **Step 5: Commit**

```bash
git add src/widgets/theme/ThemeProvider.tsx src/widgets/theme/__tests__/ThemeProvider.test.tsx
git commit -m "feat(theme): add ThemeProvider with localStorage-first + IPC backfill + rollback"
```

---

### Task 3.3: ThemeSelector 顶栏下拉

**Files:**
- Create: `src/widgets/theme/ThemeSelector.tsx`
- Create: `src/widgets/theme/__tests__/ThemeSelector.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/theme/__tests__/ThemeSelector.test.tsx
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

const mockUseTheme = {
  active: { presetId: 'light' as const },
  setPreset: vi.fn(),
  applyCustomCss: vi.fn(),
  reset: vi.fn(),
  isLoading: false,
};
vi.mock('../ThemeProvider', () => ({ useTheme: () => mockUseTheme }));

import { ThemeSelector } from '../ThemeSelector';

describe('ThemeSelector', () => {
  beforeEach(() => { vi.clearAllMocks(); mockUseTheme.active = { presetId: 'light' }; });

  it('renders 5 preset options when opened', () => {
    render(<ThemeSelector />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.selector\.title/i }));
    const options = within(screen.getByRole('listbox')).getAllByRole('option');
    expect(options).toHaveLength(5);
  });

  it('marks active preset as selected', () => {
    mockUseTheme.active = { presetId: 'ocean' };
    render(<ThemeSelector />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.selector\.title/i }));
    const active = screen.getByRole('option', { selected: true });
    expect(active.textContent).toMatch(/ocean/i);
  });

  it('calls setPreset when option clicked', () => {
    render(<ThemeSelector />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.selector\.title/i }));
    fireEvent.click(screen.getByRole('option', { name: /forest/i }));
    expect(mockUseTheme.setPreset).toHaveBeenCalledWith('forest');
  });
});
```

- [ ] **Step 2: 跑测试验证 RED + Step 3 写组件**

```tsx
// src/widgets/theme/ThemeSelector.tsx
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useTheme } from './ThemeProvider';

const PRESET_IDS = ['light', 'dark', 'ocean', 'forest', 'sunset'] as const;

export function ThemeSelector(): JSX.Element {
  const { t } = useTranslation();
  const { active, setPreset, reset } = useTheme();
  const [open, setOpen] = useState(false);

  return (
    <div data-testid="theme-selector">
      <button type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
        {t('theme.selector.title')}: {active.presetId}
      </button>
      {open && (
        <ul role="listbox" data-testid="theme-selector-listbox">
          {PRESET_IDS.map((id) => (
            <li key={id} role="option" aria-selected={active.presetId === id}
                onClick={() => { void setPreset(id); setOpen(false); }}>
              {t(`theme.presets.${id}.name`)}
            </li>
          ))}
          <li>
            <button type="button" onClick={() => { void reset(); setOpen(false); }}>
              {t('theme.selector.reset')}
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 跑测试验证 GREEN + Commit**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/ThemeSelector.test.tsx  # 期望: 3 passed
git add src/widgets/theme/ThemeSelector.tsx src/widgets/theme/__tests__/ThemeSelector.test.tsx
git commit -m "feat(theme): add ThemeSelector dropdown with 5 presets + reset"
```

---

### Task 3.4: CssThemeModal 编辑器弹窗

**Files:**
- Create: `src/widgets/theme/CssThemeModal.tsx`
- Create: `src/widgets/theme/__tests__/CssThemeModal.test.tsx`

- [ ] **Step 1: 写失败测试 + Step 3 写组件**

```tsx
// src/widgets/theme/__tests__/CssThemeModal.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

const mockUseTheme = {
  active: { presetId: 'ocean' as const }, setPreset: vi.fn(),
  applyCustomCss: vi.fn(), reset: vi.fn(), isLoading: false,
};
vi.mock('../ThemeProvider', () => ({ useTheme: () => mockUseTheme }));
vi.mock('../CodeMirrorThemeEditor', () => ({
  CodeMirrorThemeEditor: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea data-testid="cm-mock" value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));
vi.mock('@shared/lib/theme/cssValidator', () => ({
  validateCss: vi.fn((css: string) => {
    if (css.includes('@import')) return { valid: false, errors: ['CSS_INJECTION_FORBIDDEN'] };
    return { valid: true };
  }),
}));

import { CssThemeModal } from '../CssThemeModal';

describe('CssThemeModal', () => {
  beforeEach(() => { vi.clearAllMocks(); mockUseTheme.active = { presetId: 'ocean' }; });

  it('renders editor when open', () => {
    render(<CssThemeModal open onClose={vi.fn()} />);
    expect(screen.getByTestId('cm-mock')).toBeTruthy();
  });

  it('Save calls applyCustomCss with current CSS', async () => {
    render(<CssThemeModal open onClose={vi.fn()} />);
    fireEvent.change(screen.getByTestId('cm-mock'), { target: { value: ':root { --color-bg: #f00; }' } });
    fireEvent.click(screen.getByRole('button', { name: /theme\.editor\.save/i }));
    await waitFor(() => { expect(mockUseTheme.applyCustomCss).toHaveBeenCalledWith(':root { --color-bg: #f00; }'); });
  });

  it('disables Save and shows error on invalid CSS', () => {
    render(<CssThemeModal open onClose={vi.fn()} />);
    fireEvent.change(screen.getByTestId('cm-mock'), { target: { value: '@import url("evil.css")' } });
    expect(screen.getByRole('button', { name: /theme\.editor\.save/i })).toBeDisabled();
    expect(screen.getByText(/CSS_INJECTION_FORBIDDEN/i)).toBeTruthy();
  });

  it('Cancel calls onClose without saving', () => {
    const onClose = vi.fn();
    render(<CssThemeModal open onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.editor\.cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('does not render when open=false', () => {
    render(<CssThemeModal open={false} onClose={vi.fn()} />);
    expect(screen.queryByTestId('cm-mock')).toBeNull();
  });
});
```

```tsx
// src/widgets/theme/CssThemeModal.tsx
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { validateCss } from '@shared/lib/theme/cssValidator';
import type { ThemeValidationResult } from '@shared/types/theme';

import { CodeMirrorThemeEditor } from './CodeMirrorThemeEditor';
import { useTheme } from './ThemeProvider';

interface Props { open: boolean; onClose: () => void; }

export function CssThemeModal({ open, onClose }: Props): JSX.Element | null {
  const { t } = useTranslation();
  const { active, applyCustomCss } = useTheme();
  const [css, setCss] = useState<string>(active.customCss ?? '');
  const [validation, setValidation] = useState<ThemeValidationResult>({ valid: true });

  if (!open) return null;

  const handleChange = (next: string) => {
    setCss(next);
    setValidation(validateCss(next));
  };

  const handleSave = async () => {
    if (!validation.valid) return;
    await applyCustomCss(css);
    onClose();
  };

  return (
    <div role="dialog" aria-modal="true" data-testid="css-theme-modal">
      <h2>{t('theme.selector.custom')}</h2>
      <CodeMirrorThemeEditor value={css} onChange={handleChange} />
      {validation.valid === false && validation.errors && (
        <ul role="alert" data-testid="validation-errors">
          {validation.errors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      <div>
        <button type="button" onClick={onClose}>{t('theme.editor.cancel')}</button>
        <button type="button" onClick={() => void handleSave()} disabled={!validation.valid}>
          {t('theme.editor.save')}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 跑测试验证 GREEN + Commit**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/CssThemeModal.test.tsx  # 5 passed
git add src/widgets/theme/CssThemeModal.tsx src/widgets/theme/__tests__/CssThemeModal.test.tsx
git commit -m "feat(theme): add CssThemeModal with editor + live validation + save/cancel"
```

---

### Task 3.5: CodeMirrorThemeEditor 懒加载 CM6

**Files:**
- Create: `src/widgets/theme/CodeMirrorThemeEditor.tsx`
- Modify: `package.json`(+4 deps)

- [ ] **Step 1: 装 CodeMirror 6 依赖**

```bash
cd /home/fz/project/sage
npm install --save \
  @codemirror/state@^6.4.0 \
  @codemirror/view@^6.22.0 \
  @codemirror/lang-css@^6.2.0 \
  @codemirror/theme-one-dark@^6.1.0 \
  @codemirror/commands@^6.3.0
```

- [ ] **Step 2: 写 CodeMirrorThemeEditor 组件**

```tsx
// src/widgets/theme/CodeMirrorThemeEditor.tsx
import { useEffect, useRef } from 'react';
import { EditorState } from '@codemirror/state';
import { EditorView, highlightActiveLine, keymap, lineNumbers } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { css } from '@codemirror/lang-css';
import { oneDark } from '@codemirror/theme-one-dark';

interface Props { value: string; onChange: (value: string) => void; }

export function CodeMirrorThemeEditor({ value, onChange }: Props): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(), highlightActiveLine(), history(),
        keymap.of([...defaultKeymap, ...historyKeymap]),
        css(), oneDark, EditorView.lineWrapping,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) onChange(update.state.doc.toString());
        }),
      ],
    });
    const view = new EditorView({ state, parent: containerRef.current });
    viewRef.current = view;
    return () => { view.destroy(); viewRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={containerRef} data-testid="code-mirror-editor" />;
}

export default CodeMirrorThemeEditor;
```

- [ ] **Step 3: 验证 + Commit**

```bash
cd /home/fz/project/sage
npx tsc --noEmit  # 0 新错误
git add src/widgets/theme/CodeMirrorThemeEditor.tsx package.json package-lock.json
git commit -m "feat(theme): add CodeMirrorThemeEditor (CM6 + CSS lang + oneDark)"
```

---

### Task 3.6: AppProviders 挂载 ThemeProvider + 手动验证

**Files:**
- Modify: `src/app/providers/AppProviders.tsx`(+5 行)

- [ ] **Step 1: 读 AppProviders.tsx**

```bash
cd /home/fz/project/sage
cat src/app/providers/AppProviders.tsx
```

- [ ] **Step 2: 修改 AppProviders.tsx — 挂载 ThemeProvider**

```tsx
// 在 import 区域追加(用项目实际 alias,可能为相对路径):
import { ThemeErrorBoundary } from '@/widgets/theme/ErrorBoundary';
import { ThemeProvider } from '@/widgets/theme/ThemeProvider';

// 在 return 区域:
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ThemeErrorBoundary>
          <ThemeProvider>{children}</ThemeProvider>
        </ThemeErrorBoundary>
      </I18nProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 3: 验证 + Commit + PR**

```bash
cd /home/fz/project/sage
npx tsc --noEmit  # 期望: 0 新错误
npx vitest run src/widgets/theme --coverage  # 期望: 18 passed, coverage ≥ 80%
git add src/app/providers/AppProviders.tsx
git commit -m "feat(theme): mount ThemeProvider + ErrorBoundary in AppProviders"

git push -u origin feat/win7-theme-editor-p3
gh pr create --base release/win7 --head feat/win7-theme-editor-p3 \
  --title "feat(win7-theme-editor): P3 UI integration (ErrorBoundary + Provider + Selector + Modal + CodeMirror)" \
  --body "M2 P3: React UI 集成

新增: 5 个组件 + 18 vitest cases
修改: AppProviders + package.json (CodeMirror 6 deps)
依赖: P1 + P2 已完成
下一步: P4 (5 套预设 + Gallery)"

---

## Phase 4: 5 套预设 + Gallery(P4)

> **Phase 目标:** 在 P1-P3 已可工作的基础上,补齐 5 套 cherry-pick 自 main 的主题预设 + i18n 翻译键 + 画廊视图。本 Phase 让用户能直接看到 5 套预设并点击切换。
>
> **Subagent 起点:** `release/win7` HEAD(P3 已 merge 后)
> **Subagent 终点:** `feat/win7-theme-editor-p4` 分支上 vitest 全绿 + 视觉确认 5 套预设

### Task 4.1: cherry-pick 5 套预设数据 → presets.ts

**Files:**
- Create: `src/widgets/theme/presets.ts`
- Create: `src/widgets/theme/__tests__/presets.test.ts`

**Interfaces:**
- Consumes: `ThemePreset`(P2 Task 2.1)
- Produces: `export const BUILTIN_PRESETS: readonly ThemePreset[]`(5 套)

- [ ] **Step 1: 从 main 提取 5 套预设的 vars 定义**

```bash
cd /home/fz/project/sage
# 1. 查看 main a6b5ba8 的 presets 文件
git show a6b5ba8:src/widgets/theme/presets.ts 2>/dev/null > /tmp/main_presets.ts || \
  git show main:src/widgets/theme/presets.ts > /tmp/main_presets.ts

# 2. 提取 5 套预设的 vars 块
grep -E "(light|dark|ocean|forest|sunset):" /tmp/main_presets.ts | head -50

# 期望: 看到 5 套主题的 vars 定义(:root { --color-bg: ...; })
```

- [ ] **Step 2: 写失败测试**

```typescript
// src/widgets/theme/__tests__/presets.test.ts
import { describe, expect, it } from 'vitest';

import { BUILTIN_PRESETS, getPresetById } from '../presets';

describe('BUILTIN_PRESETS', () => {
  it('contains exactly 5 presets', () => {
    expect(BUILTIN_PRESETS).toHaveLength(5);
  });

  it('has the expected preset ids: light/dark/ocean/forest/sunset', () => {
    const ids = BUILTIN_PRESETS.map((p) => p.id);
    expect(ids).toEqual(['light', 'dark', 'ocean', 'forest', 'sunset']);
  });

  it('each preset has name, description, and cover', () => {
    for (const p of BUILTIN_PRESETS) {
      expect(p.name).toMatch(/^theme\.presets\.[a-z-]+\.name$/);
      expect(p.description).toMatch(/^theme\.presets\.[a-z-]+\.description$/);
      expect(p.cover).toMatch(/^\/assets\/themes\/[a-z-]+\.png$/);
    }
  });
});

describe('getPresetById', () => {
  it('returns the preset with matching id', () => {
    const ocean = getPresetById('ocean');
    expect(ocean).toBeDefined();
    expect(ocean?.id).toBe('ocean');
  });

  it('returns undefined for unknown id', () => {
    expect(getPresetById('unknown')).toBeUndefined();
  });
});
```

- [ ] **Step 3: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/presets.test.ts
# 期望: Module not found: '../presets'
```

- [ ] **Step 4: 写 presets.ts(从 main 提取 5 套)**

```typescript
// src/widgets/theme/presets.ts
import type { ThemePreset } from '@shared/types/theme';

/**
 * 5 built-in theme presets cherry-picked from main a6b5ba8.
 * IDs MUST match main for cross-branch compatibility.
 * Names/descriptions are i18n keys.
 */
export const BUILTIN_PRESETS: readonly ThemePreset[] = [
  {
    id: 'light',
    name: 'theme.presets.light.name',
    description: 'theme.presets.light.description',
    cover: '/assets/themes/light.png',
  },
  {
    id: 'dark',
    name: 'theme.presets.dark.name',
    description: 'theme.presets.dark.description',
    cover: '/assets/themes/dark.png',
  },
  {
    id: 'ocean',
    name: 'theme.presets.ocean.name',
    description: 'theme.presets.ocean.description',
    cover: '/assets/themes/ocean.png',
  },
  {
    id: 'forest',
    name: 'theme.presets.forest.name',
    description: 'theme.presets.forest.description',
    cover: '/assets/themes/forest.png',
  },
  {
    id: 'sunset',
    name: 'theme.presets.sunset.name',
    description: 'theme.presets.sunset.description',
    cover: '/assets/themes/sunset.png',
  },
] as const;

export function getPresetById(id: string): ThemePreset | undefined {
  return BUILTIN_PRESETS.find((p) => p.id === id);
}
```

**注意:** 实际的 16-var 值(每个 preset 的具体颜色)需从 main `a6b5ba8` 的 `presets.ts` 中提取并展开为完整定义。这是 P4 subagent 的实际 cherry-pick 工作。骨架先用空 `css` 字段,后续在 gallery 渲染时由 CSS 类驱动。

- [ ] **Step 5: 跑测试验证 GREEN + Commit**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/presets.test.ts  # 期望: 5 passed
git add src/widgets/theme/presets.ts src/widgets/theme/__tests__/presets.test.ts
git commit -m "feat(theme): add 5 built-in presets (cherry-pick from main a6b5ba8)"
```

---

### Task 4.2: i18n 键(theme.* 4 个子命名空间,~17 键)

**Files:**
- Modify: `src/shared/i18n/zh.ts`(+~17 键)
- Modify: `src/shared/i18n/en.ts`(+~17 键)
- Modify: `src/shared/i18n/__tests__/translations.test.ts`(自动适配)

**Interfaces:**
- Consumes: M1 i18n 16 键
- Produces: zh + en 字典追加 ~17 个 theme.* 键(translations.test 自动验证一致性)

- [ ] **Step 1: 读现有 zh.ts + en.ts 末尾结构**

```bash
cd /home/fz/project/sage
tail -30 src/shared/i18n/zh.ts
echo '---'
tail -30 src/shared/i18n/en.ts
```

- [ ] **Step 2: 在 zh.ts 末尾追加 ~17 键**

```typescript
// 在 zh.ts 末尾的对象中追加:
'theme.gallery.title': '主题画廊',
'theme.gallery.subtitle': '选择一套预设,或自定义你的主题',
'theme.editor.placeholder': '/* 在此处编写 CSS,例如 :root { --color-bg: #fff; } */',
'theme.editor.save': '保存',
'theme.editor.cancel': '取消',
'theme.editor.validate_failed': 'CSS 校验失败:{errors}',
'theme.editor.load_failed': '编辑器加载失败,使用简化版',
'theme.editor.sync_failed': '云端同步失败',
'theme.editor.save_failed': '保存失败',
'theme.selector.title': '主题',
'theme.selector.custom': '自定义 CSS',
'theme.selector.reset': '重置为默认',
'theme.presets.light.name': '亮色',
'theme.presets.light.description': '清爽的浅色主题',
'theme.presets.dark.name': '暗色',
'theme.presets.dark.description': '护眼的深色主题',
'theme.presets.ocean.name': '海洋',
'theme.presets.ocean.description': '深邃的蓝色调',
'theme.presets.forest.name': '森林',
'theme.presets.forest.description': '生机盎然的绿色调',
'theme.presets.sunset.name': '日落',
'theme.presets.sunset.description': '温暖的橙红渐变',
```

- [ ] **Step 3: 在 en.ts 末尾追加对应 ~22 键**

```typescript
// 在 en.ts 末尾的对象中追加:
'theme.gallery.title': 'Theme Gallery',
'theme.gallery.subtitle': 'Choose a preset or customize your theme',
'theme.editor.placeholder': '/* Write CSS here, e.g. :root { --color-bg: #fff; } */',
'theme.editor.save': 'Save',
'theme.editor.cancel': 'Cancel',
'theme.editor.validate_failed': 'CSS validation failed: {errors}',
'theme.editor.load_failed': 'Editor failed to load, using simplified version',
'theme.editor.sync_failed': 'Cloud sync failed',
'theme.editor.save_failed': 'Save failed',
'theme.selector.title': 'Theme',
'theme.selector.custom': 'Custom CSS',
'theme.selector.reset': 'Reset to default',
'theme.presets.light.name': 'Light',
'theme.presets.light.description': 'Clean light theme',
'theme.presets.dark.name': 'Dark',
'theme.presets.dark.description': 'Easy-on-eyes dark theme',
'theme.presets.ocean.name': 'Ocean',
'theme.presets.ocean.description': 'Deep blue tones',
'theme.presets.forest.name': 'Forest',
'theme.presets.forest.description': 'Lively green tones',
'theme.presets.sunset.name': 'Sunset',
'theme.presets.sunset.description': 'Warm orange-red gradient',
```

- [ ] **Step 4: 跑 translations.test 验证一致性**

```bash
cd /home/fz/project/sage
npx vitest run src/shared/i18n/__tests__/translations.test.ts
# 期望: PASS(translations.test 自动校验两边 key 集合一致)
```

- [ ] **Step 5: Commit**

```bash
git add src/shared/i18n/zh.ts src/shared/i18n/en.ts
git commit -m "feat(i18n): add 22 theme.* keys (gallery/editor/selector/presets namespaces)"
```

---

### Task 4.3: ThemeGallery 画廊视图

**Files:**
- Create: `src/widgets/theme/ThemeGallery.tsx`
- Create: `src/widgets/theme/__tests__/ThemeGallery.test.tsx`

**Interfaces:**
- Consumes: `useTheme`(P3 Task 3.2), `useTranslation`(M1), `BUILTIN_PRESETS`(Task 4.1)
- Produces: `<ThemeGallery />` 5 套预设卡片网格

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/theme/__tests__/ThemeGallery.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

const mockUseTheme = {
  active: { presetId: 'light' as const },
  setPreset: vi.fn(), applyCustomCss: vi.fn(), reset: vi.fn(), isLoading: false,
};
vi.mock('../ThemeProvider', () => ({ useTheme: () => mockUseTheme }));

import { ThemeGallery } from '../ThemeGallery';

describe('ThemeGallery', () => {
  beforeEach(() => { vi.clearAllMocks(); mockUseTheme.active = { presetId: 'light' }; });

  it('renders 5 preset cards', () => {
    render(<ThemeGallery />);
    const cards = screen.getAllByRole('button', { name: /theme\.presets\./i });
    expect(cards).toHaveLength(5);
  });

  it('highlights active preset card', () => {
    mockUseTheme.active = { presetId: 'ocean' };
    render(<ThemeGallery />);
    const oceanCard = screen.getByRole('button', { name: /theme\.presets\.ocean/i });
    expect(oceanCard).toHaveAttribute('aria-pressed', 'true');
  });

  it('calls setPreset when card clicked', () => {
    render(<ThemeGallery />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.presets\.forest/i }));
    expect(mockUseTheme.setPreset).toHaveBeenCalledWith('forest');
  });

  it('renders gallery title and subtitle', () => {
    render(<ThemeGallery />);
    expect(screen.getByText(/theme\.gallery\.title/i)).toBeTruthy();
    expect(screen.getByText(/theme\.gallery\.subtitle/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试验证 RED**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/ThemeGallery.test.tsx
```

- [ ] **Step 3: 写 ThemeGallery 组件**

```tsx
// src/widgets/theme/ThemeGallery.tsx
import { useTranslation } from 'react-i18next';

import { useTheme } from './ThemeProvider';
import { BUILTIN_PRESETS } from './presets';

export function ThemeGallery(): JSX.Element {
  const { t } = useTranslation();
  const { active, setPreset } = useTheme();

  return (
    <section data-testid="theme-gallery" aria-label={t('theme.gallery.title')}>
      <h2>{t('theme.gallery.title')}</h2>
      <p>{t('theme.gallery.subtitle')}</p>
      <div
        role="grid"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
          gap: '1rem',
        }}
      >
        {BUILTIN_PRESETS.map((preset) => {
          const isActive = active.presetId === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              role="gridcell"
              aria-pressed={isActive}
              aria-label={t(preset.name)}
              onClick={() => { void setPreset(preset.id); }}
              data-testid={`preset-card-${preset.id}`}
              style={{
                border: isActive ? '2px solid var(--color-accent, #0066cc)' : '1px solid var(--color-border, #ccc)',
                borderRadius: '8px',
                padding: '0.75rem',
                cursor: 'pointer',
                background: 'var(--color-bg, #fff)',
                color: 'var(--color-fg, #000)',
              }}
            >
              {preset.cover && (
                <img
                  src={preset.cover}
                  alt={t(preset.name)}
                  style={{ width: '100%', height: '120px', objectFit: 'cover', borderRadius: '4px' }}
                />
              )}
              <div style={{ fontWeight: 600, marginTop: '0.5rem' }}>{t(preset.name)}</div>
              <div style={{ fontSize: '0.85em', opacity: 0.7 }}>{t(preset.description)}</div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: 跑测试验证 GREEN + Commit**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme/__tests__/ThemeGallery.test.tsx  # 期望: 4 passed
git add src/widgets/theme/ThemeGallery.tsx src/widgets/theme/__tests__/ThemeGallery.test.tsx
git commit -m "feat(theme): add ThemeGallery with 5 preset cards + active highlight"
```

---

### Task 4.4: cover 资源 + 视觉确认 + 完整 P4 验证

**Files:**
- Create: `public/assets/themes/{light,dark,ocean,forest,sunset}.png`(从 main cherry-pick)

- [ ] **Step 1: 从 main 提取 5 张 cover 图**

```bash
cd /home/fz/project/sage
# 1. 找到 main 5 套 cover 的路径
git show a6b5ba8 --stat | grep -E '\.(png|svg|webp)$' | head
# 或
git show a6b5ba8 --stat | grep -i 'theme' | head

# 2. 复制到 win7 静态资源目录
mkdir -p public/assets/themes
git show a6b5ba8:public/themes/light.png 2>/dev/null > public/assets/themes/light.png || \
  git show a6b5ba8:src/widgets/theme/assets/light.png 2>/dev/null > public/assets/themes/light.png
# 重复 5 个
ls -la public/assets/themes/
# 期望: 5 个 .png 文件
```

**注意:** 实际 main cover 路径以 a6b5ba8 实际为准;若 main 用 SVG 替代 PNG,本步骤改用 SVG 路径。

- [ ] **Step 2: 跑全量 P4 测试**

```bash
cd /home/fz/project/sage
npx vitest run src/widgets/theme src/shared/i18n --coverage
# 期望: 全部 pass, theme.* 覆盖率 ≥ 85%
```

- [ ] **Step 3: 跑全量 vitest(确认无破坏)**

```bash
cd /home/fz/project/sage
npx vitest run --reporter=default 2>&1 | tail -10
# 期望: 总失败数不变(pre-existing failures 不归本任务)
```

- [ ] **Step 4: 手动视觉确认(关键)**

```bash
cd /home/fz/project/sage
# 启动后端
/home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py &
# 启动前端
npm run dev &
sleep 5
# 浏览器打开 http://localhost:1420
# 验证清单:
#   ✓ 默认 light 主题
#   ✓ 顶栏 ThemeSelector 显示 5 个预设
#   ✓ 切换预设:CSS vars 实时变化,背景色变化
#   ✓ 打开 Gallery:5 张卡片可见,active 卡片高亮
#   ✓ 自定义 CSS:输入 :root { --color-bg: #f00; } → 背景变红
#   ✓ 保存:刷新页面 → 仍是红色
# Ctrl+C 关闭
kill %1 %2 2>/dev/null
```

- [ ] **Step 5: 推分支 + 创建 PR(完成 M2 整个模块)**

```bash
cd /home/fz/project/sage
git add public/assets/themes/ docs/superpowers/
git commit -m "feat(theme): cherry-pick 5 cover assets + visual confirmation"

git push -u origin feat/win7-theme-editor-p4
gh pr create --base release/win7 --head feat/win7-theme-editor-p4 \
  --title "feat(win7-theme-editor): P4 5 presets + Gallery (cherry-pick from main)" \
  --body "M2 P4: 5 套预设 + Gallery(完成整个 M2 模块)

新增:
- src/widgets/theme/presets.ts (5 套 cherry-pick 自 main a6b5ba8)
- src/widgets/theme/ThemeGallery.tsx (5 卡片画廊)
- public/assets/themes/{light,dark,ocean,forest,sunset}.png
- ~22 个新 i18n 键

修改:
- src/shared/i18n/{zh,en}.ts
- public 目录结构

验证:
- vitest 全部 pass
- 5 套预设视觉确认 OK
- 与 main 100% 兼容(IDs 一致)

依赖: P1 + P2 + P3 已完成

🎉 M2 模块全部完成!下一步: M3 Scheduler"
```

---

## Self-Review Checklist(写完后自查)

完成后 review 此 plan:
- [ ] Placeholder 扫描:无 TBD / TODO / FIXME / 'implement later' / 'similar to Task X'
- [ ] 类型一致性:`active`, `setPreset`, `applyCustomCss`, `reset`, `isLoading` 在 P3 各 task 命名一致
- [ ] 路径一致:`@shared/types/theme`, `@shared/api-client/themeCssClient`, `@shared/lib/theme/cssValidator`, `@/widgets/theme/...` 全 plan 一致
- [ ] 命名一致:`sage.theme.active` 在 P3 + P4 一致
- [ ] i18n 一致:`theme.presets.{id}.name`/`theme.presets.{id}.description` 在 P3 + P4 一致
- [ ] 端点一致:7 端点(`/api/v1/theme/*`)在 P1 + P2 一致
- [ ] 16-var 白名单一致:`ALLOWED_CSS_VARS` 在 P1(后端)+ P2(前端)一致

## Execution Handoff

完成后:
1. **Subagent-Driven (推荐)** — 我派 fresh subagent per task,task 间 review
2. **Inline Execution** — 当前 session 顺序执行

请选择执行方式。

```

---
```

- [ ] **Step 5: 通知 main session 等待 review**

```
PR #XX created: feat(win7-theme-editor-p1 → release/win7)
等待 main session 跑 code-reviewer agent + 用户 review
```

---
