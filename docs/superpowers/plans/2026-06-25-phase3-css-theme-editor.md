# Phase 3 — 自定义 CSS 主题编辑器

**日期：** 2026-06-25
**项目：** sage (AionUi 借鉴方案 Phase 3)
**状态：** 待用户审阅
**覆盖率目标：** themeCssValidator 100%，themeCssClient 90%，整体 ≥ 82%

---

## Goal

为 sage 桌面端增加 **自定义 CSS 主题编辑器**（核心差异化功能），允许用户在 Settings 页面通过 CodeMirror 6 编辑 CSS（仅限 16 个白名单 CSS 变量），上传封面图，命名后保存到后端 JSON 文件，实时预览。Phase 3 必须：

1. **不破坏现有 6 套预设主题**（indigo / sage-green / ocean / ember / mono / cyberpunk）。
2. **遵循 FSD 架构**（features/theme 切片、shared/api、entities/theme、pages/settings、app/providers）。
3. **严格 TDD 流程**（先写失败测试，再写最小实现，最后重构）。
4. **后端使用 `sage-backend` conda 环境**（`/home/fz/anaconda3/envs/sage-backend/bin/python`）。
5. **覆盖率达标**：themeCssValidator 100%、themeCssClient 90%、新增 Python 模块 ≥ 80%。

---

## Architecture

### 数据流

```
┌─────────────────────────────────────────────────────────────────┐
│  用户打开 Settings → 点击 [新建自定义主题]                       │
│  → CssThemeModal 打开                                            │
│  → CodeMirrorThemeEditor 显示默认 16 变量模板                    │
│  → 用户编辑 CSS (onChange) → themeCssValidator.validate(css)   │
│    ├─ 失败 → 编辑器红波浪线 + Modal 保存按钮 disabled            │
│    └─ 成功 → backgroundInjector.injectPreview(css) 实时注入       │
│  → 用户填写 名称 + 上传 封面图 (可选)                            │
│  → 点击 [保存] → themeCssClient.save(payload)                   │
│    → invoke('theme_save', { payload }) → backend HTTP POST      │
│    → backend/api/theme_router.py::save_theme                    │
│    → backend/services/theme_storage.py::save (atomic write)     │
│    → backend/data/themes/<id>.json 落盘                          │
│  → 启动加载: ThemeProvider 初始化 → themeCssClient.list()        │
│    → 对每个 payload → injectStyleTag(id, css) → <style id="..."> │
└─────────────────────────────────────────────────────────────────┘
```

### 模块划分

```
src/features/theme/           # FSD features 切片（编辑器 UI + 校验器）
  ├── CodeMirrorThemeEditor.tsx       # CodeMirror 6 + CSS 语言
  ├── CssThemeModal.tsx               # 编辑器 + 名称 + 封面 + 保存/删除/取消
  ├── backgroundInjector.ts           # 封面图 + CSS 注入工具
  ├── themeCssValidator.ts            # 16 变量白名单 + 危险模式拒绝
  └── __tests__/                      # 单元测试

src/shared/api/
  ├── themeCssClient.ts               # IPC 客户端（4 个方法）
  └── __tests__/themeCssClient.test.ts

src/entities/theme/
  ├── storage.ts                      # 修改: 增加 css/cover 持久化
  ├── presets.ts                      # 修改: 增加 cover 可选字段
  └── __tests__/storage.test.ts       # 修改: 新增测试

src/pages/settings/
  └── ThemeSelector.tsx               # 修改: 增加 [新建自定义] 按钮

src/app/providers/
  ├── ThemeProvider.tsx               # 修改: 支持 CSS 主题动态注入
  ├── useTheme.ts                     # 修改: 增加 cssThemes 状态
  └── __tests__/ThemeProvider.test.tsx

backend/
  ├── api/theme_router.py             # 新增: /api/theme/{save,list,delete,get}
  ├── services/theme_storage.py       # 新增: JSON 文件原子读写
  ├── data/themes/                    # 新增目录: 主题文件
  ├── data/themes/.gitkeep            # 占位
  └── tests/
      ├── unit/test_theme_storage.py
      └── integration/test_theme_router.py
```

### 核心契约

```typescript
// IPC 桥
interface ThemeCssBridge {
  save(payload: ThemeCssPayload): Promise<{ id: string }>;
  list(): Promise<ThemeCssPayload[]>;
  delete(id: string): Promise<void>;
  get(id: string): Promise<ThemeCssPayload | null>;
}

// 主题载荷
interface ThemeCssPayload {
  id: string;                      // UUID v4（前端生成）
  name: string;                    // 1-32 字符
  cover?: string;                  // data: URL 或空
  css: string;                     // 1-8192 字符
  appearance: 'light' | 'dark';    // 仅影响注入的 [data-theme] 选择器
  created_at: number;              // ms timestamp
  updated_at: number;              // ms timestamp
}

// 16 个白名单变量
const ALLOWED_VARS: readonly string[] = [
  '--bg-base', '--bg-1', '--bg-2', '--bg-3', '--bg-4', '--bg-5',
  '--text-primary', '--text-secondary', '--text-muted',
  '--primary', '--primary-hover', '--border-base',
  '--success', '--error', '--warning', '--info',
];

// 危险模式（拒绝）
const FORBIDDEN_PATTERNS: readonly RegExp[] = [
  /@import\b/i,                    // 外链 CSS
  /expression\s*\(/i,              // IE expression()
  /url\s*\(\s*["']?(https?:|//)/i, // 外链 url()
  /<script\b/i,                    // script 标签
  /javascript:/i,                  // JS 协议
];

// 校验结果
interface ValidationResult {
  ok: boolean;
  errors: Array<{ line: number; col: number; message: string }>;
}
```

---

## Tech Stack

| 层 | 技术 |
|---|---|
| 编辑器 | `@uiw/react-codemirror` ^4.23.0 + `@codemirror/lang-css` ^6.3.0 |
| UI 框架 | React 18 + Tailwind 3 |
| 模态框 | `@headlessui/react`（已有） |
| 前端状态 | React Context（ThemeProvider 内扩展）+ `useState` |
| 持久化 | localStorage（缓存）+ 后端 JSON 文件（权威） |
| IPC | `window.electronAPI.invoke('theme_*')`（已存在 desktopInvoke shim） |
| 后端 | FastAPI 0.109 + pydantic 2.5 |
| 后端存储 | `backend/data/themes/<id>.json`（单文件 1-10 KB） |
| 测试前端 | vitest 1.6 + @testing-library/react 16.3 + jsdom |
| 测试后端 | pytest 8 + pytest-asyncio + httpx |
| Python 路径 | `/home/fz/anaconda3/envs/sage-backend/bin/python` |

---

## Global Constraints

1. **环境隔离**：所有后端命令必须用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，**严禁**使用系统 `python3` 或 `pip`。
2. **不破坏现有主题**：`themePresets` 数组必须保留 6 个内置条目；`ThemePreset` 类型扩展必须**向后兼容**（`css?` / `cover?` 可选）。
3. **白名单硬约束**：16 个白名单变量、禁止 `@import` / `expression()` / 外链 `url()`。
4. **FSD 严格**：编辑器和校验器放 `features/theme/`，IPC 客户端放 `shared/api/`，禁止跨层引用（如 features 直接 import pages）。
5. **TDD 严格**：每个 Task 都先写测试 → 看到失败 → 写最小实现 → 看到绿色 → 重构。
6. **CodeMirror 体积**：`@uiw/react-codemirror` + `@codemirror/lang-css` 约 150 KB gzip（已知 trade-off）。
7. **不 commit**：本 Phase 实施过程中**禁止**自动 `git commit`，由用户在 review 后手动 commit。
8. **依赖安装**：`npm install` 前必须先 `cd /home/fz/project/sage`；Python 依赖用 `pip install` 到 `sage-backend` 环境。
9. **覆盖率门槛**：themeCssValidator 必须 100%（安全关键），themeCssClient 必须 90%（IPC 关键路径）。
10. **文件路径**：所有路径使用**绝对路径**（如 `/home/fz/project/sage/src/features/theme/...`）。

---

## 实施任务清单

共 **5 大 Task 群、19 个子任务、95 个 TDD 步骤**。每个步骤 2-5 分钟。

- **Task Group 1** — 数据契约 + 校验器（5 子任务）
- **Task Group 2** — 后端存储 + API（4 子任务）
- **Task Group 3** — IPC 客户端 + 注入工具（3 子任务）
- **Task Group 4** — 编辑器 UI + 模态框（4 子任务）
- **Task Group 5** — ThemeProvider 集成 + ThemeSelector 入口（3 子任务）

---

# Task Group 1 — 数据契约 + 校验器

## Task 1.1: 定义 ThemeCssPayload 类型 + zod schema

**Goal:** 在 `shared/types/` 定义前后端共享的类型（前端）和 pydantic 模型（后端）。

### Files

- **Create:** `/home/fz/project/sage/src/shared/types/themeCss.ts`（前端 TS 类型）
- **Create:** `/home/fz/project/sage/src/shared/types/__tests__/themeCss.test.ts`（类型守卫测试）
- **Create:** `/home/fz/project/sage/src/shared/types/index.ts`（re-export）

### Interfaces

- **Consumes:** 无（基础类型）
- **Produces:**
  - `ThemeCssPayload` interface
  - `ThemeCssBridge` interface
  - `ValidationResult` interface
  - `isThemeCssPayload(value: unknown): value is ThemeCssPayload`（type guard）

### Step 1.1.1 — 创建 types 目录和 index 出口

```bash
mkdir -p /home/fz/project/sage/src/shared/types/__tests__
```

### Step 1.1.2 — 写失败的类型测试

创建文件 `/home/fz/project/sage/src/shared/types/__tests__/themeCss.test.ts`：

```typescript
import { describe, expect, it } from 'vitest';

import { isThemeCssPayload, type ThemeCssPayload } from '../themeCss';

describe('isThemeCssPayload', () => {
  it('accepts a valid payload', () => {
    const payload: ThemeCssPayload = {
      id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
      name: 'My Theme',
      css: ':root { --bg-base: #fff; }',
      appearance: 'light',
      created_at: 1700000000000,
      updated_at: 1700000000000,
    };
    expect(isThemeCssPayload(payload)).toBe(true);
  });

  it('accepts payload with cover', () => {
    const payload: ThemeCssPayload = {
      id: 'b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e',
      name: 'Covered',
      cover: 'data:image/png;base64,iVBOR',
      css: ':root { --bg-base: #000; }',
      appearance: 'dark',
      created_at: 1700000000000,
      updated_at: 1700000000000,
    };
    expect(isThemeCssPayload(payload)).toBe(true);
  });

  it('rejects payload with wrong appearance', () => {
    const bad = {
      id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
      name: 'x',
      css: ':root {}',
      appearance: 'sepia',
      created_at: 1,
      updated_at: 1,
    };
    expect(isThemeCssPayload(bad)).toBe(false);
  });

  it('rejects payload with empty name', () => {
    const bad = {
      id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
      name: '',
      css: ':root {}',
      appearance: 'light',
      created_at: 1,
      updated_at: 1,
    };
    expect(isThemeCssPayload(bad)).toBe(false);
  });

  it('rejects payload with non-uuid id', () => {
    const bad = {
      id: 'not-a-uuid',
      name: 'x',
      css: ':root {}',
      appearance: 'light',
      created_at: 1,
      updated_at: 1,
    };
    expect(isThemeCssPayload(bad)).toBe(false);
  });

  it('rejects payload with missing css', () => {
    const bad = {
      id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
      name: 'x',
      appearance: 'light',
      created_at: 1,
      updated_at: 1,
    };
    expect(isThemeCssPayload(bad)).toBe(false);
  });

  it('rejects non-object', () => {
    expect(isThemeCssPayload('string')).toBe(false);
    expect(isThemeCssPayload(null)).toBe(false);
    expect(isThemeCssPayload(undefined)).toBe(false);
    expect(isThemeCssPayload(42)).toBe(false);
  });
});
```

运行 `cd /home/fz/project/sage && npx vitest run src/shared/types/__tests__/themeCss.test.ts` — **应失败**（模块未找到）。

### Step 1.1.3 — 写类型文件

创建文件 `/home/fz/project/sage/src/shared/types/themeCss.ts`：

```typescript
/**
 * 自定义 CSS 主题 — 前后端共享类型
 */

export type ThemeAppearance = 'light' | 'dark';

export interface ThemeCssPayload {
  id: string;
  name: string;
  cover?: string;
  css: string;
  appearance: ThemeAppearance;
  created_at: number;
  updated_at: number;
}

export interface ThemeCssBridge {
  save(payload: ThemeCssPayload): Promise<{ id: string }>;
  list(): Promise<ThemeCssPayload[]>;
  delete(id: string): Promise<void>;
  get(id: string): Promise<ThemeCssPayload | null>;
}

export interface ValidationResult {
  ok: boolean;
  errors: Array<{ line: number; col: number; message: string }>;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isThemeCssPayload(value: unknown): value is ThemeCssPayload {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  if (typeof v.id !== 'string' || !UUID_RE.test(v.id)) return false;
  if (typeof v.name !== 'string' || v.name.length === 0 || v.name.length > 32) return false;
  if (typeof v.css !== 'string' || v.css.length === 0) return false;
  if (v.appearance !== 'light' && v.appearance !== 'dark') return false;
  if (typeof v.created_at !== 'number') return false;
  if (typeof v.updated_at !== 'number') return false;
  if (v.cover !== undefined && typeof v.cover !== 'string') return false;
  return true;
}
```

### Step 1.1.4 — 写 index 出口

创建文件 `/home/fz/project/sage/src/shared/types/index.ts`：

```typescript
export * from './themeCss';
```

### Step 1.1.5 — 运行测试，验证全绿

```bash
cd /home/fz/project/sage && npx vitest run src/shared/types/__tests__/themeCss.test.ts
```

**Commit 步骤：** 不执行（用户手动 commit）。

---

## Task 1.2: 实现 themeCssValidator — 16 变量白名单

**Goal:** 写一个纯函数 `validateThemeCss(css: string): ValidationResult`，拒绝任何非白名单变量、危险模式、缺失 `:root` / `[data-theme="..."]` 选择器。

### Files

- **Create:** `/home/fz/project/sage/src/features/theme/themeCssValidator.ts`
- **Create:** `/home/fz/project/sage/src/features/theme/__tests__/themeCssValidator.test.ts`

### Interfaces

- **Consumes:** `ValidationResult` (from `shared/types/themeCss`)
- **Produces:**
  - `validateThemeCss(css: string): ValidationResult`
  - `ALLOWED_VARS: readonly string[]`（导出，便于 editor 提示）
  - `FORBIDDEN_PATTERNS: readonly RegExp[]`（导出，便于测试）

### Step 1.2.1 — 创建 features/theme 目录

```bash
mkdir -p /home/fz/project/sage/src/features/theme/__tests__
```

### Step 1.2.2 — 写失败的测试

创建文件 `/home/fz/project/sage/src/features/theme/__tests__/themeCssValidator.test.ts`：

```typescript
import { describe, expect, it } from 'vitest';

import {
  ALLOWED_VARS,
  validateThemeCss,
} from '../themeCss';

describe('validateThemeCss', () => {
  describe('valid CSS', () => {
    it('accepts :root with one whitelisted var', () => {
      const css = ':root { --bg-base: #ffffff; }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(true);
      expect(result.errors).toEqual([]);
    });

    it('accepts :root with all 16 whitelisted vars', () => {
      const vars = ALLOWED_VARS.map((v) => `${v}: #000;`).join('\n  ');
      const css = `:root { ${vars} }`;
      const result = validateThemeCss(css);
      expect(result.ok).toBe(true);
    });

    it('accepts [data-theme="dark"] selector', () => {
      const css = '[data-theme="dark"] { --bg-base: #000; }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(true);
    });

    it('accepts multi-line CSS with comments', () => {
      const css = `
        /* My theme */
        :root {
          --bg-base: #fff; /* main bg */
          --primary: #4f46e5;
        }
      `;
      const result = validateThemeCss(css);
      expect(result.ok).toBe(true);
    });

    it('accepts multiple selectors', () => {
      const css = `
        :root { --bg-base: #fff; }
        [data-theme="dark"] { --bg-base: #000; }
      `;
      const result = validateThemeCss(css);
      expect(result.ok).toBe(true);
    });
  });

  describe('forbidden patterns', () => {
    it('rejects @import', () => {
      const css = ':root { @import url("evil.css"); }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
      expect(result.errors[0].message).toMatch(/@import/i);
    });

    it('rejects expression()', () => {
      const css = ':root { --primary: expression(alert(1)); }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
      expect(result.errors[0].message).toMatch(/expression/i);
    });

    it('rejects url() with http://', () => {
      const css = ':root { --bg-base: url("http://evil.com/x.png"); }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
      expect(result.errors[0].message).toMatch(/url/i);
    });

    it('rejects url() with https://', () => {
      const css = ':root { --bg-base: url("https://evil.com/x.png"); }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
    });

    it('rejects url() with protocol-relative //', () => {
      const css = ':root { --bg-base: url("//evil.com/x.png"); }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
    });

    it('rejects <script>', () => {
      const css = ':root { --bg-base: <script>alert(1)</script>; }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
    });

    it('rejects javascript: protocol', () => {
      const css = ':root { --bg-base: url("javascript:alert(1)"); }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
    });
  });

  describe('non-whitelisted variables', () => {
    it('rejects --not-in-whitelist', () => {
      const css = ':root { --evil-var: red; }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
      expect(result.errors[0].message).toMatch(/not allowed/i);
    });

    it('rejects --bg-99 (looks like whitelist but not)', () => {
      const css = ':root { --bg-99: red; }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
    });

    it('error includes variable name', () => {
      const css = ':root { --foo-bar: red; }';
      const result = validateThemeCss(css);
      expect(result.errors[0].message).toContain('--foo-bar');
    });

    it('error includes line and col', () => {
      const css = ':root {\n  --evil: red;\n}';
      const result = validateThemeCss(css);
      expect(result.errors[0].line).toBe(2);
      expect(result.errors[0].col).toBeGreaterThan(0);
    });
  });

  describe('missing :root or [data-theme]', () => {
    it('rejects CSS with no :root', () => {
      const css = 'body { --bg-base: red; }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
      expect(result.errors[0].message).toMatch(/:root|data-theme/i);
    });

    it('rejects empty CSS', () => {
      const result = validateThemeCss('');
      expect(result.ok).toBe(false);
    });

    it('rejects whitespace-only CSS', () => {
      const result = validateThemeCss('   \n  ');
      expect(result.ok).toBe(false);
    });
  });

  describe('nested selectors', () => {
    it('rejects non-root selectors', () => {
      const css = 'div.card { --bg-base: red; }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
    });
  });

  describe('size limits', () => {
    it('rejects CSS > 8192 chars', () => {
      const css = ':root { ' + 'a'.repeat(9000) + ' }';
      const result = validateThemeCss(css);
      expect(result.ok).toBe(false);
    });
  });
});
```

运行 `cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/themeCssValidator.test.ts` — **应失败**（模块未找到）。

### Step 1.2.3 — 写最小实现

创建文件 `/home/fz/project/sage/src/features/theme/themeCssValidator.ts`：

```typescript
/**
 * CSS 主题校验器 — 16 变量白名单 + 危险模式拒绝
 *
 * 关键安全约束（绝不能放宽）：
 * 1. 仅允许 16 个白名单 CSS 变量
 * 2. 禁止 @import（外链 CSS）
 * 3. 禁止 expression()（IE 表达式）
 * 4. 禁止 url() 外链（http/https/protocol-relative）
 * 5. 必须包含 :root 或 [data-theme="..."] 选择器
 */

import type { ValidationResult } from '../../shared/types/themeCss';

export const ALLOWED_VARS: readonly string[] = [
  '--bg-base', '--bg-1', '--bg-2', '--bg-3', '--bg-4', '--bg-5',
  '--text-primary', '--text-secondary', '--text-muted',
  '--primary', '--primary-hover', '--border-base',
  '--success', '--error', '--warning', '--info',
];

export const FORBIDDEN_PATTERNS: ReadonlyArray<{ pattern: RegExp; message: string }> = [
  { pattern: /@import\b/i, message: '@import is not allowed' },
  { pattern: /expression\s*\(/i, message: 'expression() is not allowed' },
  { pattern: /url\s*\(\s*["']?https?:\/\//i, message: 'external url() is not allowed' },
  { pattern: /url\s*\(\s*["']?\/\//i, message: 'protocol-relative url() is not allowed' },
  { pattern: /<script\b/i, message: '<script> is not allowed' },
  { pattern: /javascript:/i, message: 'javascript: protocol is not allowed' },
];

const MAX_CSS_SIZE = 8192;
const VAR_DECL_RE = /(--[a-z0-9-]+)\s*:/gi;
const ROOT_SELECTOR_RE = /:root\b|\[data-theme=["'][^"']*["']\]/;

interface Position {
  line: number;
  col: number;
}

function findVarPosition(css: string, varName: string): Position {
  const lines = css.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const col = lines[i].indexOf(varName);
    if (col !== -1) {
      return { line: i + 1, col: col + 1 };
    }
  }
  return { line: 1, col: 1 };
}

export function validateThemeCss(css: string): ValidationResult {
  const errors: ValidationResult['errors'] = [];

  if (typeof css !== 'string' || css.trim().length === 0) {
    return { ok: false, errors: [{ line: 1, col: 1, message: 'CSS must not be empty' }] };
  }

  if (css.length > MAX_CSS_SIZE) {
    return {
      ok: false,
      errors: [
        { line: 1, col: 1, message: `CSS exceeds max size of ${MAX_CSS_SIZE} chars` },
      ],
    };
  }

  for (const { pattern, message } of FORBIDDEN_PATTERNS) {
    if (pattern.test(css)) {
      const match = css.match(pattern);
      const pos = match ? findVarPosition(css, match[0]) : { line: 1, col: 1 };
      errors.push({ line: pos.line, col: pos.col, message });
    }
  }

  if (!ROOT_SELECTOR_RE.test(css)) {
    errors.push({ line: 1, col: 1, message: 'CSS must contain :root or [data-theme="..."] selector' });
  }

  for (const match of css.matchAll(VAR_DECL_RE)) {
    const varName = match[1].toLowerCase();
    if (!ALLOWED_VARS.includes(varName)) {
      const pos = findVarPosition(css, varName);
      errors.push({ line: pos.line, col: pos.col, message: `Variable "${varName}" is not in the allowlist` });
    }
  }

  return { ok: errors.length === 0, errors };
}
```

### Step 1.2.4 — 运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/themeCssValidator.test.ts
```

期望：所有 22 个测试通过。**Commit 步骤：** 不执行（用户手动 commit）。

---

# Task Group 2 — 后端存储 + API

## Task 2.1: 实现 theme_storage.py — JSON 文件原子读写

**Goal:** 写一个 `ThemeStorage` 类，提供 `save / list / get / delete` 4 个方法，每个方法原子写（temp file + rename）。

### Files

- **Create:** `/home/fz/project/sage/backend/services/__init__.py`（空文件）
- **Create:** `/home/fz/project/sage/backend/services/theme_storage.py`
- **Create:** `/home/fz/project/sage/backend/data/themes/.gitkeep`（空文件）
- **Create:** `/home/fz/project/sage/backend/tests/unit/test_theme_storage.py`

### Interfaces

- **Consumes:** `dict` (payload)
- **Produces:**
  - `class ThemeStorage` with methods:
    - `save(payload: dict) -> str` (returns id)
    - `list() -> list[dict]`
    - `get(id: str) -> dict | None`
    - `delete(id: str) -> bool`

### Step 2.1.1 — 创建目录和占位

```bash
mkdir -p /home/fz/project/sage/backend/services
mkdir -p /home/fz/project/sage/backend/data/themes
touch /home/fz/project/sage/backend/services/__init__.py
touch /home/fz/project/sage/backend/data/themes/.gitkeep
```

### Step 2.1.2 — 写失败测试

创建文件 `/home/fz/project/sage/backend/tests/unit/test_theme_storage.py`：

```python
"""theme_storage 单元测试 — TDD"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.theme_storage import ThemeStorage


@pytest.fixture()
def storage(tmp_path: Path) -> ThemeStorage:
    """使用临时目录作为存储根"""
    return ThemeStorage(storage_dir=tmp_path)


@pytest.fixture()
def sample_payload() -> dict:
    return {
        "id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "name": "Test Theme",
        "css": ":root { --bg-base: #fff; }",
        "appearance": "light",
        "created_at": 1700000000000,
        "updated_at": 1700000000000,
    }


class TestThemeStorageSave:
    def test_save_creates_file(self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path) -> None:
        theme_id = storage.save(sample_payload)
        assert theme_id == sample_payload["id"]
        file_path = tmp_path / f"{sample_payload['id']}.json"
        assert file_path.exists()

    def test_save_writes_valid_json(self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path) -> None:
        storage.save(sample_payload)
        file_path = tmp_path / f"{sample_payload['id']}.json"
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert data["name"] == "Test Theme"
        assert data["css"] == ":root { --bg-base: #fff; }"

    def test_save_overwrites_existing(self, storage: ThemeStorage, sample_payload: dict) -> None:
        storage.save(sample_payload)
        sample_payload["name"] = "Updated"
        storage.save(sample_payload)
        result = storage.get(sample_payload["id"])
        assert result is not None
        assert result["name"] == "Updated"

    def test_save_uses_atomic_write(self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path) -> None:
        """保存后不应残留 .tmp 文件"""
        storage.save(sample_payload)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_rejects_missing_id(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="id"):
            storage.save({"name": "x", "css": ":root {}", "appearance": "light"})

    def test_save_rejects_missing_name(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="name"):
            storage.save({"id": "abc", "css": ":root {}", "appearance": "light"})

    def test_save_rejects_missing_css(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="css"):
            storage.save({"id": "abc", "name": "x", "appearance": "light"})

    def test_save_rejects_invalid_appearance(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="appearance"):
            storage.save({"id": "abc", "name": "x", "css": ":root {}", "appearance": "sepia"})


class TestThemeStorageList:
    def test_list_empty(self, storage: ThemeStorage) -> None:
        assert storage.list() == []

    def test_list_returns_all(self, storage: ThemeStorage, sample_payload: dict) -> None:
        storage.save(sample_payload)
        second = {**sample_payload, "id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e", "name": "Other"}
        storage.save(second)
        result = storage.list()
        assert len(result) == 2

    def test_list_skips_corrupted_json(self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path) -> None:
        storage.save(sample_payload)
        (tmp_path / "corrupted.json").write_text("{bad json", encoding="utf-8")
        result = storage.list()
        assert len(result) == 1
        assert result[0]["id"] == sample_payload["id"]


class TestThemeStorageGet:
    def test_get_existing(self, storage: ThemeStorage, sample_payload: dict) -> None:
        storage.save(sample_payload)
        result = storage.get(sample_payload["id"])
        assert result is not None
        assert result["name"] == "Test Theme"

    def test_get_missing(self, storage: ThemeStorage) -> None:
        assert storage.get("nonexistent-id") is None


class TestThemeStorageDelete:
    def test_delete_existing(self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path) -> None:
        storage.save(sample_payload)
        assert storage.delete(sample_payload["id"]) is True
        assert not (tmp_path / f"{sample_payload['id']}.json").exists()

    def test_delete_missing(self, storage: ThemeStorage) -> None:
        assert storage.delete("nonexistent-id") is False
```

运行：

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_theme_storage.py -v
```

应失败（模块未找到）。

### Step 2.1.3 — 写最小实现

创建文件 `/home/fz/project/sage/backend/services/theme_storage.py`：

```python
"""主题存储 — 单文件 JSON 原子读写"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "name", "css", "appearance")
VALID_APPEARANCES = frozenset({"light", "dark"})


class ThemeStorage:
    """JSON 文件持久化 — 每主题一个文件 <id>.json"""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path(__file__).resolve().parent.parent / "data" / "themes"
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, theme_id: str) -> Path:
        return self._dir / f"{theme_id}.json"

    def _validate(self, payload: dict) -> None:
        for field in REQUIRED_FIELDS:
            if field not in payload:
                raise ValueError(f"Missing required field: {field!r}")
        if payload["appearance"] not in VALID_APPEARANCES:
            raise ValueError(
                f"Invalid appearance: {payload['appearance']!r}, must be one of {VALID_APPEARANCES}"
            )

    def save(self, payload: dict) -> str:
        """原子写入 payload，返回 id"""
        self._validate(payload)
        target = self._path(payload["id"])
        # 原子写：temp file + rename
        fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
        return payload["id"]

    def list(self) -> list[dict]:
        """列出所有主题，跳过损坏文件（记录 warning）"""
        results: list[dict] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("跳过损坏的主题文件 %s: %s", path.name, exc)
        return results

    def get(self, theme_id: str) -> dict | None:
        """按 id 获取主题"""
        path = self._path(theme_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取主题文件失败 %s: %s", path.name, exc)
            return None

    def delete(self, theme_id: str) -> bool:
        """按 id 删除主题，返回是否成功"""
        path = self._path(theme_id)
        if not path.exists():
            return False
        path.unlink()
        return True
```

### Step 2.1.4 — 运行测试

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_theme_storage.py -v
```

期望：13 个测试全绿。

### Step 2.1.5 — 检查覆盖率

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_theme_storage.py --cov=backend.services.theme_storage --cov-report=term-missing
```

期望：theme_storage.py 覆盖率 ≥ 95%。

**Commit 步骤：** 不执行。

---

## Task 2.2: 实现 theme_router.py — FastAPI 路由

**Goal:** 写 4 个 HTTP 端点 `/api/theme/{save,list,delete,get}`，使用 pydantic 模型验证请求。

### Files

- **Create:** `/home/fz/project/sage/backend/api/theme_router.py`
- **Create:** `/home/fz/project/sage/backend/tests/integration/test_theme_router.py`

### Interfaces

- **Consumes:** HTTP 请求（pydantic 模型）
- **Produces:**
  - `POST /api/theme/save` → `{ "id": str }`
  - `GET /api/theme/list` → `[ThemeCssPayload, ...]`
  - `POST /api/theme/delete` → `{ "ok": bool }` (body: `{ "id": str }`)
  - `GET /api/theme/get/{id}` → `ThemeCssPayload | { "error": "not_found" }`

### Step 2.2.1 — 写失败测试

创建文件 `/home/fz/project/sage/backend/tests/integration/test_theme_router.py`：

```python
"""theme_router 集成测试 — TDD"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest_asyncio.fixture()
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """使用临时 themes 目录的 HTTP 客户端"""
    from backend.services import theme_storage

    storage = theme_storage.ThemeStorage(storage_dir=tmp_path)
    monkeypatch.setattr("backend.api.theme_router._storage", storage, raising=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture()
def sample_payload() -> dict:
    return {
        "id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "name": "Test Theme",
        "css": ":root { --bg-base: #fff; }",
        "appearance": "light",
        "created_at": 1700000000000,
        "updated_at": 1700000000000,
    }


class TestSaveTheme:
    @pytest.mark.asyncio
    async def test_save_returns_id(self, client: AsyncClient, sample_payload: dict) -> None:
        resp = await client.post("/api/theme/save", json=sample_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sample_payload["id"]

    @pytest.mark.asyncio
    async def test_save_validates_payload(self, client: AsyncClient) -> None:
        bad = {"id": "x", "name": "y", "css": "z", "appearance": "sepia"}
        resp = await client.post("/api/theme/save", json=bad)
        assert resp.status_code == 422


class TestListThemes:
    @pytest.mark.asyncio
    async def test_list_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/theme/list")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_returns_saved(self, client: AsyncClient, sample_payload: dict) -> None:
        await client.post("/api/theme/save", json=sample_payload)
        resp = await client.get("/api/theme/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == sample_payload["id"]


class TestDeleteTheme:
    @pytest.mark.asyncio
    async def test_delete_existing(self, client: AsyncClient, sample_payload: dict) -> None:
        await client.post("/api/theme/save", json=sample_payload)
        resp = await client.post("/api/theme/delete", json={"id": sample_payload["id"]})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_delete_missing(self, client: AsyncClient) -> None:
        resp = await client.post("/api/theme/delete", json={"id": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is False


class TestGetTheme:
    @pytest.mark.asyncio
    async def test_get_existing(self, client: AsyncClient, sample_payload: dict) -> None:
        await client.post("/api/theme/save", json=sample_payload)
        resp = await client.get(f"/api/theme/get/{sample_payload['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Theme"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/theme/get/nonexistent")
        assert resp.status_code == 404
```

### Step 2.2.2 — 写最小实现

创建文件 `/home/fz/project/sage/backend/api/theme_router.py`：

```python
"""CSS 主题 API 路由"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.theme_storage import ThemeStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/theme", tags=["theme"])

_storage = ThemeStorage(
    storage_dir=Path(__file__).resolve().parent.parent / "data" / "themes"
)


class ThemeCssPayload(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=32)
    cover: str | None = None
    css: str = Field(min_length=1, max_length=8192)
    appearance: str = Field(pattern="^(light|dark)$")
    created_at: int
    updated_at: int


class DeleteRequest(BaseModel):
    id: str


@router.post("/save")
def save_theme(payload: ThemeCssPayload) -> dict:
    _storage.save(payload.model_dump())
    return {"id": payload.id}


@router.get("/list")
def list_themes() -> list[dict]:
    return _storage.list()


@router.post("/delete")
def delete_theme(req: DeleteRequest) -> dict:
    ok = _storage.delete(req.id)
    return {"ok": ok}


@router.get("/get/{theme_id}")
def get_theme(theme_id: str) -> dict:
    data = _storage.get(theme_id)
    if data is None:
        raise HTTPException(status_code=404, detail="not_found")
    return data
```

### Step 2.2.3 — 挂载到 FastAPI app

修改 `/home/fz/project/sage/backend/main.py`，找到 router 装载区域（搜索 `app.include_router`），追加：

```python
from backend.api.theme_router import router as theme_router
# ...existing code...
app.include_router(theme_router)
```

具体位置参考 `app.include_router(legacy_router)` 或 `app.include_router(hex_router)` 之后。

### Step 2.2.4 — 运行测试

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_theme_router.py -v
```

期望：8 个测试全绿。

### Step 2.2.5 — 检查覆盖率

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_theme_router.py --cov=backend.api.theme_router --cov-report=term-missing
```

期望：theme_router.py 覆盖率 ≥ 90%。

**Commit 步骤：** 不执行。

---

## Task 2.3: 后端 IPC 桥接（Electron main 进程注册 `theme_*` 命令）

**Goal:** 在 Electron main 进程（`src-tauri` 或 `electron`）注册 4 个 `theme_save / theme_list / theme_delete / theme_get` IPC 命令，桥接到 FastAPI HTTP。

### Files

- **Find:** `/home/fz/project/sage/electron/main.ts`（如存在），或 `src-tauri/src/main.rs`（如 Tauri）

### Step 2.3.1 — 定位 IPC 注册文件

```bash
ls /home/fz/project/sage/electron/ 2>&1 | head -5
ls /home/fz/project/sage/src-tauri/src/ 2>&1 | head -5
```

### Step 2.3.2 — 在 ipcMain.handle 区域追加 4 个 handler

在 `electron/main.ts` 找到 `ipcMain.handle('get_settings', ...)` 类似位置，追加：

```typescript
import { app, BrowserWindow, ipcMain } from 'electron';
// ...existing code...

const BACKEND_URL = 'http://127.0.0.1:8765';

async function postToBackend(path: string, body: unknown): Promise<unknown> {
  const resp = await fetch(`${BACKEND_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`Backend ${path} failed: ${resp.status}`);
  return resp.json();
}

async function getFromBackend(path: string): Promise<unknown> {
  const resp = await fetch(`${BACKEND_URL}${path}`);
  if (!resp.ok) throw new Error(`Backend ${path} failed: ${resp.status}`);
  return resp.json();
}

ipcMain.handle('theme_save', async (_e, payload) => postToBackend('/api/theme/save', payload));
ipcMain.handle('theme_list', async () => getFromBackend('/api/theme/list'));
ipcMain.handle('theme_delete', async (_e, body) => postToBackend('/api/theme/delete', body));
ipcMain.handle('theme_get', async (_e, id: string) => {
  try {
    return await getFromBackend(`/api/theme/get/${encodeURIComponent(id)}`);
  } catch (e) {
    if (e instanceof Error && e.message.includes('404')) return null;
    throw e;
  }
});
```

**Commit 步骤：** 不执行。

---

# Task Group 3 — IPC 客户端 + 注入工具

## Task 3.1: 实现 themeCssClient.ts — 4 个 IPC 方法

**Goal:** 写前端 IPC 客户端，封装 `invoke('theme_*')` 调用，提供 5s 超时降级。

### Files

- **Create:** `/home/fz/project/sage/src/shared/api/themeCssClient.ts`
- **Create:** `/home/fz/project/sage/src/shared/api/__tests__/themeCssClient.test.ts`

### Interfaces

- **Consumes:** `ThemeCssPayload`, `ThemeCssBridge` (from `shared/types/themeCss`)
- **Produces:** `themeCssClient: ThemeCssBridge`

### Step 3.1.1 — 写失败测试

创建文件 `/home/fz/project/sage/src/shared/api/__tests__/themeCssClient.test.ts`：

```typescript
/**
 * themeCssClient 测试 — 验证 invoke 契约
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const invokeMock = vi.fn();
vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

import { themeCssClient } from '../themeCssClient';
import type { ThemeCssPayload } from '../../types/themeCss';

const SAMPLE: ThemeCssPayload = {
  id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
  name: 'Sample',
  css: ':root { --bg-base: #fff; }',
  appearance: 'light',
  created_at: 1700000000000,
  updated_at: 1700000000000,
};

beforeEach(() => {
  invokeMock.mockReset();
});

afterEach(() => {
  invokeMock.mockReset();
});

describe('themeCssClient.save', () => {
  it('calls theme_save with payload', async () => {
    invokeMock.mockResolvedValue({ id: SAMPLE.id });
    const result = await themeCssClient.save(SAMPLE);
    expect(invokeMock).toHaveBeenCalledWith('theme_save', { payload: SAMPLE });
    expect(result).toEqual({ id: SAMPLE.id });
  });

  it('throws on backend error', async () => {
    invokeMock.mockRejectedValue(new Error('Network error'));
    await expect(themeCssClient.save(SAMPLE)).rejects.toThrow('Network error');
  });
});

describe('themeCssClient.list', () => {
  it('calls theme_list and returns array', async () => {
    invokeMock.mockResolvedValue([SAMPLE]);
    const result = await themeCssClient.list();
    expect(invokeMock).toHaveBeenCalledWith('theme_list', {});
    expect(result).toEqual([SAMPLE]);
  });

  it('returns empty array on error', async () => {
    invokeMock.mockRejectedValue(new Error('fail'));
    const result = await themeCssClient.list();
    expect(result).toEqual([]);
  });
});

describe('themeCssClient.delete', () => {
  it('calls theme_delete with id', async () => {
    invokeMock.mockResolvedValue({ ok: true });
    await themeCssClient.delete(SAMPLE.id);
    expect(invokeMock).toHaveBeenCalledWith('theme_delete', { id: SAMPLE.id });
  });

  it('throws on error', async () => {
    invokeMock.mockRejectedValue(new Error('fail'));
    await expect(themeCssClient.delete('x')).rejects.toThrow();
  });
});

describe('themeCssClient.get', () => {
  it('returns payload when found', async () => {
    invokeMock.mockResolvedValue(SAMPLE);
    const result = await themeCssClient.get(SAMPLE.id);
    expect(invokeMock).toHaveBeenCalledWith('theme_get', { id: SAMPLE.id });
    expect(result).toEqual(SAMPLE);
  });

  it('returns null on 404', async () => {
    invokeMock.mockResolvedValue(null);
    const result = await themeCssClient.get('missing');
    expect(result).toBeNull();
  });
});
```

运行 `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/themeCssClient.test.ts` — **应失败**（模块未找到）。

### Step 3.1.2 — 写实现

创建文件 `/home/fz/project/sage/src/shared/api/themeCssClient.ts`：

```typescript
/**
 * CSS 主题 IPC 客户端
 *
 * 失败语义：
 * - list(): 失败时返回空数组（不抛，UI 永不阻塞）
 * - get(): 失败时返回 null
 * - save() / delete(): 抛出错误（用户操作需感知）
 */

import type { ThemeCssBridge, ThemeCssPayload } from '../types/themeCss';

import { invoke } from './desktopInvoke';

const LOAD_TIMEOUT_MS = 5000;

async function ipcCall<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  return Promise.race([
    invoke<T>(cmd, args ?? {}),
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`IPC ${cmd} timeout`)), LOAD_TIMEOUT_MS),
    ),
  ]);
}

export const themeCssClient: ThemeCssBridge = {
  async save(payload: ThemeCssPayload): Promise<{ id: string }> {
    return ipcCall<{ id: string }>('theme_save', { payload });
  },

  async list(): Promise<ThemeCssPayload[]> {
    try {
      return await ipcCall<ThemeCssPayload[]>('theme_list');
    } catch (e) {
      console.warn('[themeCssClient.list] failed:', e);
      return [];
    }
  },

  async delete(id: string): Promise<void> {
    await ipcCall<{ ok: boolean }>('theme_delete', { id });
  },

  async get(id: string): Promise<ThemeCssPayload | null> {
    try {
      return await ipcCall<ThemeCssPayload | null>('theme_get', { id });
    } catch (e) {
      console.warn(`[themeCssClient.get(${id})] failed:`, e);
      return null;
    }
  },
};
```

### Step 3.1.3 — 在 shared/api/index.ts re-export

修改 `/home/fz/project/sage/src/shared/api/index.ts`，追加：

```typescript
export { themeCssClient } from './themeCssClient';
```

### Step 3.1.4 — 运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/themeCssClient.test.ts
```

期望：10 个测试全绿，覆盖率 ≥ 90%。

### Step 3.1.5 — 检查覆盖率

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/themeCssClient.test.ts --coverage
```

**Commit 步骤：** 不执行。

---

## Task 3.2: 实现 backgroundInjector.ts — 实时预览注入

**Goal:** 写两个工具函数：`injectPreviewCss(css)` 注入到 `<style id="theme-preview">`，`injectPersistedStyle(id, css)` 注入到 `<style id="theme-{id}">`，`removeStyle(id)` 移除。

### Files

- **Create:** `/home/fz/project/sage/src/features/theme/backgroundInjector.ts`
- **Create:** `/home/fz/project/sage/src/features/theme/__tests__/backgroundInjector.test.ts`

### Interfaces

- **Consumes:** `css: string`, `id: string`
- **Produces:**
  - `injectPreviewCss(css: string): void`
  - `clearPreviewCss(): void`
  - `injectPersistedStyle(id: string, css: string): void`
  - `removePersistedStyle(id: string): void`
  - `setCoverImage(dataUrl: string): void`（设置 `--cover-image` CSS 变量）

### Step 3.2.1 — 写失败测试

创建文件 `/home/fz/project/sage/src/features/theme/__tests__/backgroundInjector.test.ts`：

```typescript
/**
 * backgroundInjector 测试 — jsdom 环境
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  clearPreviewCss,
  injectPersistedStyle,
  injectPreviewCss,
  removePersistedStyle,
  setCoverImage,
} from '../backgroundInjector';

describe('backgroundInjector', () => {
  beforeEach(() => {
    document.head.innerHTML = '';
  });

  afterEach(() => {
    document.head.innerHTML = '';
  });

  describe('injectPreviewCss', () => {
    it('creates a style element with id theme-preview', () => {
      injectPreviewCss(':root { --bg-base: #fff; }');
      const el = document.getElementById('theme-preview');
      expect(el).not.toBeNull();
      expect(el?.tagName).toBe('STYLE');
    });

    it('replaces existing preview on second call', () => {
      injectPreviewCss(':root { --bg-base: #fff; }');
      injectPreviewCss(':root { --bg-base: #000; }');
      const els = document.querySelectorAll('#theme-preview');
      expect(els.length).toBe(1);
      expect(els[0].textContent).toContain('#000');
    });
  });

  describe('clearPreviewCss', () => {
    it('removes preview element', () => {
      injectPreviewCss(':root {}');
      clearPreviewCss();
      expect(document.getElementById('theme-preview')).toBeNull();
    });
  });

  describe('injectPersistedStyle', () => {
    it('creates style with id theme-{id}', () => {
      injectPersistedStyle('my-id', ':root {}');
      const el = document.getElementById('theme-my-id');
      expect(el).not.toBeNull();
    });

    it('replaces existing on second call', () => {
      injectPersistedStyle('my-id', ':root { --bg-base: #fff; }');
      injectPersistedStyle('my-id', ':root { --bg-base: #000; }');
      const els = document.querySelectorAll('#theme-my-id');
      expect(els.length).toBe(1);
    });
  });

  describe('removePersistedStyle', () => {
    it('removes style by id', () => {
      injectPersistedStyle('my-id', ':root {}');
      removePersistedStyle('my-id');
      expect(document.getElementById('theme-my-id')).toBeNull();
    });
  });

  describe('setCoverImage', () => {
    it('sets --cover-image CSS variable on :root', () => {
      setCoverImage('data:image/png;base64,abc');
      const value = document.documentElement.style.getPropertyValue('--cover-image');
      expect(value).toBe('url("data:image/png;base64,abc")');
    });

    it('clears variable when called with empty string', () => {
      setCoverImage('data:image/png;base64,abc');
      setCoverImage('');
      const value = document.documentElement.style.getPropertyValue('--cover-image');
      expect(value).toBe('');
    });
  });
});
```

配置 jsdom（如果尚未配置）：确保 `vitest.config.ts` 有 `environment: 'jsdom'` 或在测试文件顶部 `// @vitest-environment jsdom`。

### Step 3.2.2 — 写实现

创建文件 `/home/fz/project/sage/src/features/theme/backgroundInjector.ts`：

```typescript
/**
 * CSS / 封面图注入工具
 *
 * 三种标签：
 * - <style id="theme-preview">  — 实时预览，编辑器 onChange 时更新
 * - <style id="theme-{id}">      — 已保存主题，启动时批量注入
 * - :root { --cover-image }      — 封面图 data URL
 */

const PREVIEW_ID = 'theme-preview';

function persistId(id: string): string {
  return `theme-${id}`;
}

function escapeDataUrl(dataUrl: string): string {
  return dataUrl.replace(/"/g, '\\"');
}

export function injectPreviewCss(css: string): void {
  if (typeof document === 'undefined') return;
  let el = document.getElementById(PREVIEW_ID) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement('style');
    el.id = PREVIEW_ID;
    document.head.appendChild(el);
  }
  el.textContent = css;
}

export function clearPreviewCss(): void {
  if (typeof document === 'undefined') return;
  document.getElementById(PREVIEW_ID)?.remove();
}

export function injectPersistedStyle(id: string, css: string): void {
  if (typeof document === 'undefined') return;
  const tagId = persistId(id);
  let el = document.getElementById(tagId) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement('style');
    el.id = tagId;
    document.head.appendChild(el);
  }
  el.textContent = css;
}

export function removePersistedStyle(id: string): void {
  if (typeof document === 'undefined') return;
  document.getElementById(persistId(id))?.remove();
}

export function setCoverImage(dataUrl: string): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement.style;
  if (dataUrl.length === 0) {
    root.removeProperty('--cover-image');
  } else {
    root.setProperty('--cover-image', `url("${escapeDataUrl(dataUrl)}")`);
  }
}
```

### Step 3.2.3 — 运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/backgroundInjector.test.ts
```

期望：8 个测试全绿。

**Commit 步骤：** 不执行。

---

## Task 3.3: 修改 ThemePreset 类型，扩展 css/cover 字段

**Goal:** 在 `entities/theme/presets.ts` 的 `ThemePreset` 接口加 `css?: string` 和 `cover?: string` 可选字段；6 个内置主题的 `cover` 暂时都置 `undefined`（不传）。

### Files

- **Modify:** `/home/fz/project/sage/src/entities/theme/presets.ts`

### Step 3.3.1 — 修改接口

打开 `/home/fz/project/sage/src/entities/theme/presets.ts`，将第 32-38 行替换为：

```typescript
/** 主题预设 */
export interface ThemePreset {
  id: string;
  name: string;
  description: string;
  colors: ThemeColors;
  darkColors: ThemeColors;
  /** 可选：自定义 CSS（CSS 主题用） */
  css?: string;
  /** 可选：封面图 data URL（CSS 主题用） */
  cover?: string;
}
```

6 个内置主题（indigo / sage-green / ocean / ember / mono / cyberpunk）**不传** `cover` 字段（保持向后兼容）。

### Step 3.3.2 — 验证现有测试不破坏

```bash
cd /home/fz/project/sage && npx vitest run src/entities/theme/__tests__/
```

期望：所有现有测试通过。

**Commit 步骤：** 不执行。

---

# Task Group 4 — 编辑器 UI + 模态框

## Task 4.1: 安装 CodeMirror 依赖

**Goal:** 在 `package.json` 添加 `@uiw/react-codemirror` 和 `@codemirror/lang-css`。

### Files

- **Modify:** `/home/fz/project/sage/package.json`

### Step 4.1.1 — 安装

```bash
cd /home/fz/project/sage && npm install --save @uiw/react-codemirror@^4.23.0 @codemirror/lang-css@^6.3.0
```

### Step 4.1.2 — 验证安装

```bash
cd /home/fz/project/sage && cat package.json | grep -A1 codemirror
```

期望：`@uiw/react-codemirror` 和 `@codemirror/lang-css` 出现在 `dependencies`。

**Commit 步骤：** 不执行。

---

## Task 4.2: 实现 CodeMirrorThemeEditor.tsx

**Goal:** 写一个受控 CodeMirror 组件，接收 `value` / `onChange` props，使用 CSS 语言高亮。

### Files

- **Create:** `/home/fz/project/sage/src/features/theme/CodeMirrorThemeEditor.tsx`
- **Create:** `/home/fz/project/sage/src/features/theme/__tests__/CodeMirrorThemeEditor.test.tsx`

### Interfaces

- **Consumes:** `value: string`, `onChange: (value: string) => void`, `errors?: ValidationResult['errors']`
- **Produces:** React 组件

### Step 4.2.1 — 写失败组件测试

创建文件 `/home/fz/project/sage/src/features/theme/__tests__/CodeMirrorThemeEditor.test.tsx`：

```typescript
// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CodeMirrorThemeEditor } from '../CodeMirrorThemeEditor';

describe('CodeMirrorThemeEditor', () => {
  it('renders with initial value', () => {
    render(<CodeMirrorThemeEditor value=":root { --bg-base: #fff; }" onChange={() => {}} />);
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('does not crash with errors prop', () => {
    const errors = [{ line: 1, col: 1, message: 'Variable "--evil" is not allowed' }];
    render(<CodeMirrorThemeEditor value="" onChange={() => {}} errors={errors} />);
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('does not crash with readOnly=true', () => {
    render(<CodeMirrorThemeEditor value=":root {}" onChange={() => {}} readOnly />);
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });
});
```

### Step 4.2.2 — 写组件实现

创建文件 `/home/fz/project/sage/src/features/theme/CodeMirrorThemeEditor.tsx`：

```typescript
/**
 * CodeMirror 6 主题编辑器
 */

import { css } from '@codemirror/lang-css';
import CodeMirror from '@uiw/react-codemirror';
import type { Extension } from '@codemirror/state';
import { useMemo } from 'react';

import type { ValidationResult } from '../../shared/types/themeCss';

interface CodeMirrorThemeEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** 校验错误（暂未注入到 linter，预留给未来扩展） */
  errors?: ValidationResult['errors'];
  readOnly?: boolean;
}

export function CodeMirrorThemeEditor({
  value,
  onChange,
  readOnly = false,
}: CodeMirrorThemeEditorProps) {
  const extensions: Extension[] = useMemo(() => [css()], []);

  return (
    <div className="border border-border rounded-radius-md overflow-hidden" data-testid="cm-editor">
      <CodeMirror
        value={value}
        height="320px"
        extensions={extensions}
        onChange={onChange}
        readOnly={readOnly}
        placeholder=":root { --bg-base: #ffffff; }"
        basicSetup={{
          lineNumbers: true,
          highlightActiveLine: true,
          foldGutter: true,
        }}
      />
    </div>
  );
}
```

### Step 4.2.3 — 运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/CodeMirrorThemeEditor.test.tsx
```

期望：3 个测试全绿（jsdom 环境）。

**Commit 步骤：** 不执行。

---

## Task 4.3: 实现 CssThemeModal.tsx — 编辑器 + 名称 + 封面 + 保存/删除/取消

**Goal:** 写一个模态框组件，包含：CodeMirror 编辑器、名称输入框、封面图上传、实时校验、保存/删除/取消按钮。

### Files

- **Create:** `/home/fz/project/sage/src/features/theme/CssThemeModal.tsx`
- **Create:** `/home/fz/project/sage/src/features/theme/__tests__/CssThemeModal.test.tsx`

### Interfaces

- **Consumes:**
  - `mode: 'create' | 'edit'`
  - `initial?: Partial<ThemeCssPayload>`
  - `onSave: (payload: ThemeCssPayload) => Promise<void>`
  - `onDelete?: (id: string) => Promise<void>`
  - `onClose: () => void`
- **Produces:** React 组件

### Step 4.3.1 — 写失败组件测试

创建文件 `/home/fz/project/sage/src/features/theme/__tests__/CssThemeModal.test.tsx`：

```typescript
// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { CssThemeModal } from '../CssThemeModal';

// Mock crypto.randomUUID for jsdom (older versions lack it)
if (!globalThis.crypto) {
  // @ts-expect-error test shim
  globalThis.crypto = {};
}
if (!globalThis.crypto.randomUUID) {
  globalThis.crypto.randomUUID = () => 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';
}

const VALID_CSS = ':root { --bg-base: #ffffff; --primary: #4f46e5; }';

describe('CssThemeModal', () => {
  beforeEach(() => {
    // jsdom lacks confirm by default
    window.confirm = vi.fn(() => true);
  });

  it('renders with default state in create mode', () => {
    render(
      <CssThemeModal mode="create" onSave={vi.fn()} onClose={vi.fn()} />
    );
    expect(screen.getByText('新建自定义主题')).toBeInTheDocument();
    expect(screen.getByLabelText('主题名称')).toBeInTheDocument();
  });

  it('save button disabled when name is empty', () => {
    render(
      <CssThemeModal mode="create" onSave={vi.fn()} onClose={vi.fn()} />
    );
    const saveBtn = screen.getByText('保存');
    expect(saveBtn).toBeDisabled();
  });

  it('save button enabled when name and valid CSS provided', async () => {
    render(
      <CssThemeModal mode="create" onSave={vi.fn()} onClose={vi.fn()} />
    );
    fireEvent.change(screen.getByLabelText('主题名称'), { target: { value: 'My Theme' } });
    // CSS 默认就是 :root 模板，应已 valid
    await waitFor(() => {
      expect(screen.getByText('保存')).not.toBeDisabled();
    });
  });

  it('calls onSave with correct payload', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <CssThemeModal mode="create" onSave={onSave} onClose={vi.fn()} />
    );
    fireEvent.change(screen.getByLabelText('主题名称'), { target: { value: 'Test' } });
    fireEvent.click(screen.getByText('保存'));
    await waitFor(() => {
      expect(onSave).toHaveBeenCalledTimes(1);
      const call = onSave.mock.calls[0][0];
      expect(call.name).toBe('Test');
      expect(call.css).toContain('--bg-base');
      expect(call.appearance).toMatch(/light|dark/);
      expect(call.id).toMatch(/^[0-9a-f-]{36}$/);
    });
  });

  it('calls onClose when cancel clicked', () => {
    const onClose = vi.fn();
    render(
      <CssThemeModal mode="create" onSave={vi.fn()} onClose={onClose} />
    );
    fireEvent.click(screen.getByText('取消'));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows delete button in edit mode', () => {
    render(
      <CssThemeModal
        mode="edit"
        initial={{ id: 'abc', name: 'x', css: ':root {}', appearance: 'light', created_at: 1, updated_at: 1 }}
        onSave={vi.fn()}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText('删除')).toBeInTheDocument();
  });
});
```

### Step 4.3.2 — 写组件实现

创建文件 `/home/fz/project/sage/src/features/theme/CssThemeModal.tsx`：

```typescript
/**
 * CSS 主题编辑模态框
 */

import { Dialog, Transition } from '@headlessui/react';
import { Fragment, useEffect, useMemo, useState } from 'react';

import type { ThemeCssPayload } from '../../shared/types/themeCss';

import { CodeMirrorThemeEditor } from './CodeMirrorThemeEditor';
import { validateThemeCss } from './themeCssValidator';

interface CssThemeModalProps {
  mode: 'create' | 'edit';
  initial?: Partial<ThemeCssPayload>;
  onSave: (payload: ThemeCssPayload) => Promise<void>;
  onDelete?: (id: string) => Promise<void>;
  onClose: () => void;
}

const DEFAULT_CSS = `:root {
  --bg-base: #ffffff;
  --primary: #4f46e5;
  --text-primary: #111827;
  --border-base: #e5e7eb;
}`;

const MAX_COVER_SIZE = 2 * 1024 * 1024; // 2MB
const ALLOWED_COVER_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

function uuid(): string {
  return crypto.randomUUID();
}

export function CssThemeModal({
  mode,
  initial,
  onSave,
  onDelete,
  onClose,
}: CssThemeModalProps) {
  const [name, setName] = useState(initial?.name ?? '');
  const [css, setCss] = useState(initial?.css ?? DEFAULT_CSS);
  const [cover, setCover] = useState<string | undefined>(initial?.cover);
  const [appearance, setAppearance] = useState<'light' | 'dark'>(initial?.appearance ?? 'light');
  const [coverError, setCoverError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const validation = useMemo(() => validateThemeCss(css), [css]);
  const canSave = name.length > 0 && name.length <= 32 && validation.ok && !coverError;

  useEffect(() => {
    if (coverError) setCoverError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cover]);

  async function handleCoverChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) {
      setCover(undefined);
      return;
    }
    if (!ALLOWED_COVER_TYPES.includes(file.type)) {
      setCoverError('封面图必须是 PNG / JPEG / WebP / GIF 格式');
      return;
    }
    if (file.size > MAX_COVER_SIZE) {
      setCoverError(`封面图大小 ${(file.size / 1024 / 1024).toFixed(1)}MB 超过限制 2MB`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setCover(reader.result as string);
      setCoverError(null);
    };
    reader.readAsDataURL(file);
  }

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    try {
      const now = Date.now();
      const payload: ThemeCssPayload = {
        id: initial?.id ?? uuid(),
        name,
        cover,
        css,
        appearance,
        created_at: initial?.created_at ?? now,
        updated_at: now,
      };
      await onSave(payload);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!onDelete || !initial?.id) return;
    if (!window.confirm(`确认删除主题 "${name}"？`)) return;
    await onDelete(initial.id);
    onClose();
  }

  return (
    <Transition show as={Fragment}>
      <Dialog onClose={onClose} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="bg-bg-1 rounded-radius-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <Dialog.Title className="px-6 py-4 text-lg font-semibold border-b border-border">
              {mode === 'create' ? '新建自定义主题' : `编辑主题：${name}`}
            </Dialog.Title>

            <div className="p-6 space-y-4">
              {/* 名称 */}
              <div>
                <label htmlFor="theme-name" className="block text-sm font-medium mb-1">
                  主题名称
                </label>
                <input
                  id="theme-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={32}
                  className="w-full px-3 py-2 border border-border rounded-radius-md bg-bg-base"
                />
                {name.length > 32 && (
                  <p className="text-xs text-error mt-1">名称最多 32 字符</p>
                )}
              </div>

              {/* 外观 */}
              <div>
                <label className="block text-sm font-medium mb-1">外观</label>
                <div className="flex gap-2">
                  {(['light', 'dark'] as const).map((a) => (
                    <button
                      key={a}
                      type="button"
                      onClick={() => setAppearance(a)}
                      className={`px-3 py-1.5 rounded-radius-md border ${
                        appearance === a
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border hover:border-border-hover'
                      }`}
                    >
                      {a === 'light' ? '浅色' : '深色'}
                    </button>
                  ))}
                </div>
              </div>

              {/* 封面图 */}
              <div>
                <label htmlFor="theme-cover" className="block text-sm font-medium mb-1">
                  封面图（可选，≤ 2MB）
                </label>
                <input
                  id="theme-cover"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  onChange={handleCoverChange}
                  className="block w-full text-sm"
                />
                {cover && !coverError && (
                  <img src={cover} alt="cover" className="mt-2 w-32 h-20 object-cover rounded" />
                )}
                {coverError && <p className="text-xs text-error mt-1">{coverError}</p>}
              </div>

              {/* CSS 编辑器 */}
              <div>
                <label className="block text-sm font-medium mb-1">CSS（仅允许 16 个白名单变量）</label>
                <CodeMirrorThemeEditor value={css} onChange={setCss} errors={validation.errors} />
                {!validation.ok && (
                  <ul className="mt-2 text-xs text-error space-y-1">
                    {validation.errors.map((e, i) => (
                      <li key={i}>
                        Line {e.line}:{e.col} — {e.message}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="px-6 py-4 border-t border-border flex justify-between">
              <div>
                {mode === 'edit' && onDelete && (
                  <button
                    type="button"
                    onClick={handleDelete}
                    className="px-4 py-2 text-sm text-error hover:bg-error/10 rounded-radius-md"
                  >
                    删除
                  </button>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-sm border border-border rounded-radius-md hover:bg-bg-hover"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={!canSave || saving}
                  className="px-4 py-2 text-sm bg-primary text-white rounded-radius-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary-hover"
                >
                  {saving ? '保存中…' : '保存'}
                </button>
              </div>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </Transition>
  );
}
```

### Step 4.3.3 — 运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/CssThemeModal.test.tsx
```

期望：6 个测试全绿（jsdom 环境）。

**Commit 步骤：** 不执行。

---

# Task Group 5 — ThemeProvider 集成 + ThemeSelector 入口

## Task 5.1: 扩展 ThemeProvider 支持 CSS 主题动态注入

**Goal:** 在 `useTheme` 增加 `cssThemes` 状态和 `setActiveCssTheme` 方法；ThemeProvider 初始化时 `themeCssClient.list()` 批量注入。

### Files

- **Modify:** `/home/fz/project/sage/src/app/providers/useTheme.ts`
- **Modify:** `/home/fz/project/sage/src/app/providers/ThemeProvider.tsx`
- **Create:** `/home/fz/project/sage/src/app/providers/__tests__/ThemeProvider.cssTheme.test.tsx`

### Step 5.1.1 — 扩展 useTheme 类型

替换 `/home/fz/project/sage/src/app/providers/useTheme.ts` 全部内容：

```typescript
import { createContext, useContext } from 'react';

import type { ThemeCssPayload } from '../../shared/types/themeCss';

export type ThemeMode = 'light' | 'dark' | 'system';

export type ActiveThemeSource =
  | { kind: 'preset'; id: string }
  | { kind: 'css'; id: string };

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: 'light' | 'dark';
  setMode: (mode: ThemeMode) => void;
  /** 当前激活的 preset ID */
  presetId: string;
  /** 切换 preset 主题 */
  setPresetId: (id: string) => void;
  /** CSS 主题列表（启动时加载） */
  cssThemes: ThemeCssPayload[];
  /** 当前激活主题的来源 */
  activeSource: ActiveThemeSource;
  /** 切换到指定 CSS 主题 */
  setActiveCssTheme: (id: string) => void;
  /** 切换回 preset 主题 */
  setActivePreset: (id: string) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within a <ThemeProvider>');
  }
  return ctx;
}
```

### Step 5.1.2 — 修改 ThemeProvider 实现

替换 `/home/fz/project/sage/src/app/providers/ThemeProvider.tsx` 全部内容：

```typescript
import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { getThemeById, DEFAULT_THEME_ID, type ThemeColors } from '../../entities/theme/presets';
import {
  loadTheme,
  loadThemePreset,
  saveTheme,
  saveThemePreset,
} from '../../entities/theme/storage';
import { themeCssClient } from '../../shared/api/themeCssClient';
import type { ThemeCssPayload } from '../../shared/types/themeCss';
import { injectPersistedStyle } from '../../features/theme/backgroundInjector';

import { ThemeContext, type ThemeMode, type ActiveThemeSource } from './useTheme';

const VALID_MODES: ReadonlyArray<ThemeMode> = ['light', 'dark', 'system'];
const ACTIVE_CSS_THEME_KEY = 'sage-active-css-theme';

function resolveSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function camelToCssVar(key: string): string {
  return '--color-' + key.replace(/([A-Z])/g, '-$1').toLowerCase();
}

function hexToRgbTuple(hex: string): string {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `${r} ${g} ${b}`;
}

function applyThemeColors(colors: ThemeColors): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement.style;
  for (const [key, value] of Object.entries(colors)) {
    const cssVar = camelToCssVar(key);
    root.setProperty(cssVar, value);
    if (!value.startsWith('rgba')) {
      root.setProperty(`${cssVar}-rgb`, hexToRgbTuple(value));
    }
  }
}

function resetThemeColors(): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement.style;
  const toRemove: string[] = [];
  for (let i = 0; i < root.length; i++) {
    const prop = root[i];
    if (prop.startsWith('--color-')) {
      toRemove.push(prop);
    }
  }
  toRemove.forEach((p) => root.removeProperty(p));
}

function applyPresetTheme(resolved: 'light' | 'dark', presetId: string): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('dark', resolved === 'dark');
  const preset = getThemeById(presetId);
  if (preset && presetId !== DEFAULT_THEME_ID) {
    const colors = resolved === 'dark' ? preset.darkColors : preset.colors;
    applyThemeColors(colors);
  } else {
    resetThemeColors();
  }
}

interface ThemeProviderProps {
  children: ReactNode;
  defaultMode?: ThemeMode;
}

export function ThemeProvider({ children, defaultMode = 'system' }: ThemeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(defaultMode);
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(() => resolveSystemTheme());
  const [presetId, setPresetIdState] = useState(DEFAULT_THEME_ID);
  const [cssThemes, setCssThemes] = useState<ThemeCssPayload[]>([]);
  const [activeSource, setActiveSourceState] = useState<ActiveThemeSource>({
    kind: 'preset',
    id: DEFAULT_THEME_ID,
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => {
      setSystemTheme(e.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    loadTheme().then((m) => {
      if (m && VALID_MODES.includes(m)) setModeState(m);
    });
    loadThemePreset().then((id) => {
      if (id && getThemeById(id)) setPresetIdState(id);
    });
  }, []);

  // 加载 CSS 主题 + 注入 style 标签
  useEffect(() => {
    void themeCssClient.list().then((themes) => {
      setCssThemes(themes);
      for (const t of themes) {
        injectPersistedStyle(t.id, t.css);
      }
    });
  }, []);

  // 恢复 active source（CSS 或 preset）
  useEffect(() => {
    try {
      const activeCssId = localStorage.getItem(ACTIVE_CSS_THEME_KEY);
      if (activeCssId) {
        setActiveSourceState({ kind: 'css', id: activeCssId });
      } else {
        setActiveSourceState({ kind: 'preset', id: presetId });
      }
    } catch {
      // 隐私模式
    }
  }, [presetId]);

  const resolved: 'light' | 'dark' = mode === 'system' ? systemTheme : mode;

  useEffect(() => {
    if (activeSource.kind === 'preset') {
      applyPresetTheme(resolved, activeSource.id);
    }
    // CSS 主题的 dark 类由 injectPersistedStyle 中的 [data-theme="dark"] 处理
  }, [resolved, activeSource]);

  const setMode = useCallback((next: ThemeMode): void => {
    setModeState(next);
    void saveTheme(next);
  }, []);

  const setPresetId = useCallback((id: string): void => {
    if (!getThemeById(id)) return;
    setPresetIdState(id);
    setActiveSourceState({ kind: 'preset', id });
    try {
      localStorage.removeItem(ACTIVE_CSS_THEME_KEY);
    } catch {
      // ignore
    }
    void saveThemePreset(id);
  }, []);

  const setActiveCssTheme = useCallback((id: string): void => {
    setActiveSourceState({ kind: 'css', id });
    try {
      localStorage.setItem(ACTIVE_CSS_THEME_KEY, id);
    } catch {
      // ignore
    }
  }, []);

  const setActivePreset = useCallback((id: string): void => {
    setPresetId(id);
  }, [setPresetId]);

  return (
    <ThemeContext.Provider
      value={{
        mode,
        resolved,
        setMode,
        presetId,
        setPresetId,
        cssThemes,
        activeSource,
        setActiveCssTheme,
        setActivePreset,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}
```

### Step 5.1.3 — 写测试

创建文件 `/home/fz/project/sage/src/app/providers/__tests__/ThemeProvider.cssTheme.test.tsx`：

```typescript
// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const listMock = vi.fn();
vi.mock('../../../shared/api/themeCssClient', () => ({
  themeCssClient: { list: listMock },
}));

const injectMock = vi.fn();
vi.mock('../../../features/theme/backgroundInjector', () => ({
  injectPersistedStyle: injectMock,
  removePersistedStyle: vi.fn(),
}));

import { ThemeProvider } from '../ThemeProvider';
import { useTheme } from '../useTheme';

function Reader() {
  const ctx = useTheme();
  return (
    <div>
      <span data-testid="css-count">{ctx.cssThemes.length}</span>
      <span data-testid="active-source-kind">{ctx.activeSource.kind}</span>
      <span data-testid="active-source-id">{ctx.activeSource.id}</span>
    </div>
  );
}

beforeEach(() => {
  listMock.mockReset();
  injectMock.mockReset();
  localStorage.clear();
});

describe('ThemeProvider CSS theme integration', () => {
  it('loads CSS themes on mount', async () => {
    listMock.mockResolvedValue([
      { id: 'a', name: 'A', css: ':root{}', appearance: 'light', created_at: 1, updated_at: 1 },
      { id: 'b', name: 'B', css: ':root{}', appearance: 'dark', created_at: 1, updated_at: 1 },
    ]);
    render(
      <ThemeProvider>
        <Reader />
      </ThemeProvider>
    );
    await waitFor(() => {
      expect(screen.getByTestId('css-count').textContent).toBe('2');
    });
    expect(injectMock).toHaveBeenCalledTimes(2);
  });

  it('falls back to preset when no active css theme in localStorage', async () => {
    listMock.mockResolvedValue([]);
    render(
      <ThemeProvider>
        <Reader />
      </ThemeProvider>
    );
    await waitFor(() => {
      expect(screen.getByTestId('active-source-kind').textContent).toBe('preset');
    });
  });

  it('restores active css theme from localStorage', async () => {
    listMock.mockResolvedValue([
      { id: 'a', name: 'A', css: ':root{}', appearance: 'light', created_at: 1, updated_at: 1 },
    ]);
    localStorage.setItem('sage-active-css-theme', 'a');
    render(
      <ThemeProvider>
        <Reader />
      </ThemeProvider>
    );
    await waitFor(() => {
      expect(screen.getByTestId('active-source-kind').textContent).toBe('css');
      expect(screen.getByTestId('active-source-id').textContent).toBe('a');
    });
  });
});
```

### Step 5.1.4 — 运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/ThemeProvider.cssTheme.test.tsx
```

期望：3 个测试全绿。

### Step 5.1.5 — 验证现有 ThemeProvider 测试不破坏

```bash
cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/ThemeProvider.test.tsx
```

期望：所有现有测试通过（如有失败需调整 useTheme 的接口兼容性）。

**Commit 步骤：** 不执行。

---

## Task 5.2: 在 ThemeSelector.tsx 增加"新建自定义"按钮

**Goal:** 在 `src/pages/settings/ThemeSelector.tsx` 增加：
1. 列表底部加 `[+ 新建自定义]` 按钮
2. 每个 CSS 主题显示封面缩略图（若有）
3. 点击 CSS 主题切换到 `setActiveCssTheme`
4. 点击"新建自定义"打开 CssThemeModal

### Files

- **Modify:** `/home/fz/project/sage/src/pages/settings/ThemeSelector.tsx`
- **Create:** `/home/fz/project/sage/src/pages/settings/__tests__/ThemeSelector.cssTheme.test.tsx`

### Step 5.2.1 — 修改 ThemeSelector

替换 `/home/fz/project/sage/src/pages/settings/ThemeSelector.tsx` 全部内容：

```typescript
/**
 * 主题选择器 — 6 个预设主题 + CSS 自定义主题
 */

import { clsx } from 'clsx';
import { Plus } from 'lucide-react';
import { useState } from 'react';

import { useTheme } from '../../app/providers/useTheme';
import { themePresets } from '../../entities/theme/presets';
import { CssThemeModal } from '../../features/theme/CssThemeModal';
import { themeCssClient } from '../../shared/api/themeCssClient';
import type { ThemeCssPayload } from '../../shared/types/themeCss';

export function ThemeSelector() {
  const {
    presetId,
    setPresetId,
    resolved,
    cssThemes,
    activeSource,
    setActiveCssTheme,
  } = useTheme();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ThemeCssPayload | undefined>();
  const [list, setList] = useState(cssThemes);

  // 同步外部 cssThemes
  if (list !== cssThemes) setList(cssThemes);

  async function handleSave(payload: ThemeCssPayload) {
    await themeCssClient.save(payload);
    const updated = await themeCssClient.list();
    setList(updated);
  }

  async function handleDelete(id: string) {
    await themeCssClient.delete(id);
    const updated = await themeCssClient.list();
    setList(updated);
  }

  return (
    <div className="space-y-4">
      {/* 预设主题 */}
      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">内置主题</h3>
        <div className="grid grid-cols-3 gap-3">
          {themePresets.map((preset) => {
            const isActive = activeSource.kind === 'preset' && activeSource.id === preset.id;
            const colors = resolved === 'dark' ? preset.darkColors : preset.colors;
            const previewColor = colors.primary;

            return (
              <button
                key={preset.id}
                onClick={() => setPresetId(preset.id)}
                className={clsx(
                  'flex items-center gap-2.5 px-3 py-2.5 rounded-radius-md border text-left transition-all',
                  isActive
                    ? 'border-primary bg-primary/5 ring-1 ring-primary/30'
                    : 'border-border hover:border-border-hover hover:bg-bg-hover',
                )}
                type="button"
              >
                <div
                  className="w-6 h-6 rounded-full flex-shrink-0 border border-border"
                  style={{ backgroundColor: previewColor }}
                />
                <div className="min-w-0">
                  <div className={clsx('text-sm font-medium', isActive ? 'text-primary' : 'text-text')}>
                    {preset.name}
                  </div>
                  <div className="text-[11px] text-text-muted truncate">{preset.description}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* CSS 自定义主题 */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-text-secondary">自定义 CSS 主题</h3>
          <button
            type="button"
            onClick={() => {
              setEditing(undefined);
              setModalOpen(true);
            }}
            className="flex items-center gap-1 px-2 py-1 text-xs border border-border rounded-radius-md hover:bg-bg-hover"
          >
            <Plus size={14} /> 新建自定义
          </button>
        </div>
        {list.length === 0 ? (
          <p className="text-xs text-text-muted py-4 text-center border border-dashed border-border rounded-radius-md">
            尚未创建自定义主题
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {list.map((theme) => {
              const isActive = activeSource.kind === 'css' && activeSource.id === theme.id;
              return (
                <div
                  key={theme.id}
                  className={clsx(
                    'relative rounded-radius-md border overflow-hidden cursor-pointer transition-all',
                    isActive
                      ? 'border-primary ring-1 ring-primary/30'
                      : 'border-border hover:border-border-hover',
                  )}
                  onClick={() => setActiveCssTheme(theme.id)}
                  onDoubleClick={() => {
                    setEditing(theme);
                    setModalOpen(true);
                  }}
                >
                  {theme.cover ? (
                    <img src={theme.cover} alt={theme.name} className="w-full h-20 object-cover" />
                  ) : (
                    <div className="w-full h-20 bg-bg-2 flex items-center justify-center text-text-muted text-xs">
                      {theme.appearance === 'dark' ? '深色' : '浅色'}
                    </div>
                  )}
                  <div className="px-2 py-1.5">
                    <div className={clsx('text-sm font-medium truncate', isActive ? 'text-primary' : 'text-text')}>
                      {theme.name}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 模态框 */}
      {modalOpen && (
        <CssThemeModal
          mode={editing ? 'edit' : 'create'}
          initial={editing}
          onSave={handleSave}
          onDelete={handleDelete}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  );
}
```

### Step 5.2.2 — 写测试

创建文件 `/home/fz/project/sage/src/pages/settings/__tests__/ThemeSelector.cssTheme.test.tsx`：

```typescript
// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const cssClientMock = {
  list: vi.fn(),
  save: vi.fn(),
  delete: vi.fn(),
  get: vi.fn(),
};
vi.mock('../../../shared/api/themeCssClient', () => ({
  themeCssClient: cssClientMock,
}));

const useThemeMock = vi.fn();
vi.mock('../../../app/providers/useTheme', () => ({
  useTheme: () => useThemeMock(),
}));

import { ThemeSelector } from '../ThemeSelector';

describe('ThemeSelector CSS theme integration', () => {
  beforeEach(() => {
    cssClientMock.list.mockReset();
    cssClientMock.save.mockReset();
    cssClientMock.delete.mockReset();
    useThemeMock.mockReset();
  });

  it('renders new custom button', () => {
    useThemeMock.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: [],
      activeSource: { kind: 'preset', id: 'indigo' },
      setActiveCssTheme: vi.fn(),
    });
    cssClientMock.list.mockResolvedValue([]);
    render(<ThemeSelector />);
    expect(screen.getByText('新建自定义')).toBeInTheDocument();
  });

  it('opens modal on new custom click', () => {
    useThemeMock.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: [],
      activeSource: { kind: 'preset', id: 'indigo' },
      setActiveCssTheme: vi.fn(),
    });
    cssClientMock.list.mockResolvedValue([]);
    render(<ThemeSelector />);
    fireEvent.click(screen.getByText('新建自定义'));
    expect(screen.getByText('新建自定义主题')).toBeInTheDocument();
  });

  it('renders existing CSS themes from list', async () => {
    useThemeMock.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: [
        { id: 'a', name: 'My Theme', css: ':root{}', appearance: 'light', created_at: 1, updated_at: 1 },
      ],
      activeSource: { kind: 'preset', id: 'indigo' },
      setActiveCssTheme: vi.fn(),
    });
    cssClientMock.list.mockResolvedValue([]);
    render(<ThemeSelector />);
    await waitFor(() => {
      expect(screen.getByText('My Theme')).toBeInTheDocument();
    });
  });
});
```

### Step 5.2.3 — 运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/pages/settings/__tests__/ThemeSelector.cssTheme.test.tsx
```

期望：3 个测试全绿。

**Commit 步骤：** 不执行。

---

## Task 5.3: 全栈集成验证

**Goal:** 启动后端 + 前端，手动验证：
1. 打开 Settings → Theme
2. 点 `[+ 新建自定义]`
3. 填写名称 + 编辑 CSS（默认模板）
4. 点 `[保存]`
5. 看到新主题出现在"自定义 CSS 主题"列表
6. 点击新主题，页面背景实时变化
7. 关闭重启 app，新主题依然存在

### Files

无新增文件，纯手动验证。

### Step 5.3.1 — 启动后端

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py
```

健康检查：

```bash
curl http://127.0.0.1:8765/health
```

期望：返回 `{"status": "ok"}`。

### Step 5.3.2 — 启动前端

```bash
cd /home/fz/project/sage && npm run dev
```

浏览器打开 `http://localhost:1420`。

### Step 5.3.3 — 验证 IPC 端点

```bash
# 列出主题
curl http://127.0.0.1:8765/api/theme/list

# 保存一个测试主题
curl -X POST http://127.0.0.1:8765/api/theme/save -H "Content-Type: application/json" -d '{
  "id": "test-1",
  "name": "Test",
  "css": ":root { --bg-base: #ff0000; --primary: #00ff00; }",
  "appearance": "light",
  "created_at": 1700000000000,
  "updated_at": 1700000000000
}'

# 列出应包含 test-1
curl http://127.0.0.1:8765/api/theme/list

# 删除
curl -X POST http://127.0.0.1:8765/api/theme/delete -H "Content-Type: application/json" -d '{"id": "test-1"}'
```

### Step 5.3.4 — 检查后端文件落盘

```bash
ls /home/fz/project/sage/backend/data/themes/
```

期望：看到 `test-1.json` 落盘后再被删除（delete 后文件应消失）。

### Step 5.3.5 — 端到端测试

启动 Electron 桌面端：

```bash
cd /home/fz/project/sage && npm run electron:dev
```

手动完成 5.3 节 Goal 中的 7 步验证。

**Commit 步骤：** 不执行。

---

# 完成标准

## 覆盖率

```bash
# 前端
cd /home/fz/project/sage && npm run test:coverage

# 后端
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ --cov=backend.services.theme_storage --cov=backend.api.theme_router --cov-report=term-missing
```

**必须达到：**
- `src/features/theme/themeCssValidator.ts` ≥ 100%
- `src/shared/api/themeCssClient.ts` ≥ 90%
- `backend/services/theme_storage.py` ≥ 95%
- `backend/api/theme_router.py` ≥ 90%
- 整体 ≥ 82%

## 现有主题不破坏

```bash
cd /home/fz/project/sage && npx vitest run src/entities/theme/__tests__/
```

期望：所有现有测试通过。

## 类型检查

```bash
cd /home/fz/project/sage && npm run typecheck
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m mypy backend/services/theme_storage.py backend/api/theme_router.py
```

期望：0 错误。

## Lint

```bash
cd /home/fz/project/sage && npm run lint
```

期望：0 errors（warnings 允许）。

---

# 风险与依赖

| 风险 | 缓解 |
|---|---|
| CodeMirror 体积 150KB | 用户已知 trade-off（spec §3） |
| 后端 `data/themes/` 目录权限 | 启动时 `mkdir(parents=True, exist_ok=True)`（已实现） |
| IPC 5s 超时 | themeCssClient.list() 失败时返回 `[]`（已实现） |
| 主题文件被外部删除 | 启动 list() 时跳过损坏文件 + warning（已实现） |
| JSON 损坏 | ThemeStorage.list() 跳过损坏文件（已实现） |
| 封面图 > 2MB | Modal 实时校验 + 错误提示（已实现） |
| 危险 CSS（@import 等） | themeCssValidator 拒绝（已实现） |
| 并发保存冲突 | 原子写 `tempfile + os.replace`（已实现） |
| Electron main 进程路径差异 | Task 2.3 给出两套方案（electron/main.ts 或 src-tauri） |
| Python 3.8 兼容性 | release/win7 分支不在本 Phase 范围 |

---

# 后续 Phase 衔接

- **Phase 4 — 装饰性主题扩展**：复用 `ThemeCssPayload` 增加 `background_image` 字段。
- **Phase 7 — 新会话欢迎屏**：用 `cssThemes` 的 `cover` 字段作欢迎屏背景。
- **Phase 8 — 定时任务**：把主题作为 cron job 上下文变量（不影响本 Phase）。

---

**计划完成。** 等待用户审阅 → 启动 TDD 实施。
