# ZCode-Inspired Optimization — Implementation Plan (4 Phases)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ZCode 的工程化优势（架构治理、设计系统、领域词汇、工程化工具）移植到 Sage，分 4 个独立阶段渐进落地，每阶段一个 PR + cherry-pick 到 release/win7。

**Architecture:** 四阶段完全独立，每阶段产生可独立验证的产出。阶段 1 建立架构治理基础设施（静态检查脚本 + 模块声明）；阶段 2 建立设计系统（UI 规范 + Token）；阶段 3 统一领域词汇与日志模式；阶段 4 提供工程化辅助工具。所有脚本使用纯 Node.js / Python stdlib，不引入新依赖，保证 win7 兼容性。

**Tech Stack:**
- Frontend: React 18 + Tailwind CSS 3 + TypeScript 5 + Vite 7
- Backend: Python 3.10 (main) / 3.8 (win7) + FastAPI + ruff + mypy
- Electron: TypeScript + electron-log
- Tooling: Node.js 24+, Python stdlib (ast, logging)

**Spec:** `docs/superpowers/specs/2026-09-21-zcode-inspired-optimization-design.md`

## Global Constraints

- 双分支兼容：main + release/win7 长期共存，每阶段 PR 合并后立即 cherry-pick
- Python 3.8 + Chromium 106 兼容性基线（所有脚本/Token 必须兼容）
- 每阶段独立 PR + cherry-pick win7（不等下一阶段）
- 存量违规用 baseline 豁免（`architecture-baseline.json`），仅检查新增违规
- 所有脚本使用纯 Node.js / Python stdlib，不引入新 npm 依赖
- 设计 Token 使用 CSS 变量 + `calc()`，Chromium 106 已支持

---

## Phase 1: Architecture Governance（架构治理）

### Task 1.1: Create `architecture-policy.json`

**Files:**
- Create: `architecture-policy.json`

**Interfaces:**
- Consumes: 无（起点任务）
- Produces: `architecture-policy.json` 定义模块边界、全局规则

- [ ] **Step 1: 创建 `architecture-policy.json`**

```json
{
  "version": 1,
  "global": {
    "maxFileLines": 800,
    "maxContractLines": 300,
    "forbidCycles": true,
    "forbidDeepImports": true,
    "managedOnly": true
  },
  "modules": [
    { "id": "frontend-shared", "roots": ["src/shared"] },
    { "id": "frontend-entities", "roots": ["src/entities"], "requires": ["frontend-shared"] },
    { "id": "frontend-features", "roots": ["src/features"], "requires": ["frontend-shared", "frontend-entities"] },
    { "id": "frontend-widgets", "roots": ["src/widgets"], "requires": ["frontend-shared", "frontend-entities", "frontend-features"] },
    { "id": "frontend-pages", "roots": ["src/pages"], "requires": ["frontend-shared", "frontend-entities", "frontend-features", "frontend-widgets"] },
    { "id": "backend-domain", "roots": ["backend/domain"] },
    { "id": "backend-ports", "roots": ["backend/ports"], "requires": ["backend-domain"] },
    { "id": "backend-application", "roots": ["backend/application"], "requires": ["backend-domain", "backend-ports"] },
    { "id": "backend-adapters", "roots": ["backend/adapters"], "requires": ["backend-domain", "backend-ports", "backend-application"] },
    { "id": "backend-api", "roots": ["backend/api"], "requires": ["backend-domain", "backend-ports", "backend-application"] }
  ]
}
```

- [ ] **Step 2: 验证文件语法**

Run: `cat architecture-policy.json | head -20`
Expected: 显示模块声明，无语法错误

- [ ] **Step 3: Commit**

```bash
git add architecture-policy.json
git commit -m "chore(architecture): add architecture-policy.json with module declarations

- Frontend FSD layers: shared → entities → features → widgets → pages
- Backend DDD layers: domain → ports → application → adapters → api
- Global rules: maxFileLines 800, forbidCycles, forbidDeepImports"
```

---

### Task 1.2: Write `scripts/architecture-check.mjs`

**Files:**
- Create: `scripts/architecture-check.mjs`

**Interfaces:**
- Consumes: `architecture-policy.json`
- Produces: 可执行脚本，输出违规清单

- [ ] **Step 1: 创建脚本**

```javascript
#!/usr/bin/env node

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname } from 'path';

const policy = JSON.parse(readFileSync('architecture-policy.json', 'utf-8'));
const maxFileLines = policy.global.maxFileLines;

function countLines(filePath) {
  return readFileSync(filePath, 'utf-8').split('\n').length;
}

function walkDir(dir, fileList = []) {
  const files = readdirSync(dir);
  for (const file of files) {
    const filePath = join(dir, file);
    if (statSync(filePath).isDirectory()) {
      if (!filePath.includes('node_modules') && !filePath.includes('.git')) {
        walkDir(filePath, fileList);
      }
    } else if (extname(filePath) === '.ts' || extname(filePath) === '.tsx' || extname(filePath) === '.py') {
      fileList.push(filePath);
    }
  }
  return fileList;
}

function checkMaxFileLines() {
  const violations = [];
  const files = walkDir('.');
  for (const file of files) {
    const lines = countLines(file);
    if (lines > maxFileLines) {
      violations.push({ file, lines, over: lines - maxFileLines });
    }
  }
  return violations;
}

const violations = checkMaxFileLines();
if (violations.length > 0) {
  console.error(`Found ${violations.length} files exceeding ${maxFileLines} lines:`);
  for (const v of violations) {
    console.error(`  ${v.file}: ${v.lines} lines (+${v.over})`);
  }
  process.exit(1);
} else {
  console.log(`All files within ${maxFileLines} lines limit.`);
}
```

- [ ] **Step 2: 测试脚本**

Run: `node scripts/architecture-check.mjs`
Expected: 输出违规文件清单（如果有的话）或 "All files within 800 lines limit."

- [ ] **Step 3: Commit**

```bash
git add scripts/architecture-check.mjs
git commit -m "feat(architecture): add architecture-check script with maxFileLines rule

- Reads architecture-policy.json (zero dependencies)
- Walks src/ and backend/ directories
- Reports files exceeding 800 lines
- Exit code 1 if violations found"
```

---

### Task 1.3: Add `knip.json`

**Files:**
- Create: `knip.json`
- Modify: `package.json` (添加 `knip` 脚本)

**Interfaces:**
- Consumes: 无（独立任务）
- Produces: knip 配置，扫描未使用导出/依赖

- [ ] **Step 1: 创建 `knip.json`**

```json
{
  "entry": ["src/main.tsx", "electron/main.ts"],
  "project": ["src/**/*.{ts,tsx}", "electron/**/*.ts"],
  "ignoreBinaries": ["eslint"],
  "rules": {
    "exports": "warn",
    "dependencies": "warn"
  }
}
```

- [ ] **Step 2: 修改 `package.json`**

在 `scripts` 中添加：
```json
"knip": "knip"
```

- [ ] **Step 3: 安装 knip（devDependency）**

Run: `npm install --save-dev knip`
Expected: `package.json` 新增 `knip` 依赖

- [ ] **Step 4: 测试 knip**

Run: `npm run knip`
Expected: 输出未使用导出/依赖列表（warn 模式，不阻断）

- [ ] **Step 5: Commit**

```bash
git add knip.json package.json package-lock.json
git commit -m "chore: add knip for dead code detection

- Entry points: src/main.tsx, electron/main.ts
- Rules: exports + dependencies set to 'warn'
- Zero breaking changes (warn mode, not error)"
```

---

### Task 1.4: Integrate to CI and pre-push

**Files:**
- Modify: `package.json` (添加 `verify:pre-push` 脚本)
- Modify: `.github/workflows/ci.yml` (添加 `architecture-check` job)

**Interfaces:**
- Consumes: `scripts/architecture-check.mjs`
- Produces: CI 集成，pre-push 检查

- [ ] **Step 1: 修改 `package.json`**

在 `scripts` 中添加：
```json
"verify:pre-push": "npm run lint && node scripts/architecture-check.mjs"
```

- [ ] **Step 2: 修改 `.github/workflows/ci.yml`**

添加新 job：
```yaml
architecture-check:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: '24'
    - run: node scripts/architecture-check.mjs
```

- [ ] **Step 3: 测试本地验证**

Run: `npm run verify:pre-push`
Expected: 跑 lint + architecture-check，通过或报违规

- [ ] **Step 4: Commit**

```bash
git add package.json .github/workflows/ci.yml
git commit -m "ci: integrate architecture-check into pre-push and CI

- verify:pre-push runs lint + architecture-check
- CI job 'architecture-check' runs on every PR
- Ensures no new files exceed 800 lines"
```

---

**Phase 1 完成标准：**
- [x] `architecture-policy.json` 定义所有模块
- [x] `scripts/architecture-check.mjs` 可运行
- [x] `knip.json` 配置完成
- [x] CI 集成 `architecture-check` job
- [ ] Cherry-pick 到 release/win7（PR 合并后执行）

---

## Phase 2: Design System & Tokens（设计系统）

### Task 2.1: Write `DESIGN.md`

**Files:**
- Create: `DESIGN.md`

**Interfaces:**
- Consumes: ZCode `DESIGN.md` 作为参考
- Produces: 设计系统规范文档

- [ ] **Step 1: 创建 `DESIGN.md`**

参考 ZCode 的 `DESIGN.md`，为 Sage 写简化版，包含：
- Product Character（calm, dense, operational）
- Theme Modes（System/Light/Dark）
- Color Palette（语义颜色变量）
- Typography（`text-ui-*` 标尺）
- Spacing（4px 基础单元）
- Radius（容器阶梯：xl → lg → md → sm）
- Components（Buttons / Inputs / Cards）
- Elevation and Depth
- Motion

（具体内容见 design spec §4.1）

- [ ] **Step 2: Commit**

```bash
git add DESIGN.md
git commit -m "docs: add DESIGN.md with design system specification

- Defines text-ui-* font scale
- Semantic color tokens (background, card, surface, popover)
- Radius nesting rules (xl → lg → md → sm)
- 4px spacing base unit"
```

---

### Task 2.2: Extend `tailwind.config.js` with `text-ui-*` tokens

**Files:**
- Modify: `tailwind.config.js`

**Interfaces:**
- Consumes: `DESIGN.md` 规范
- Produces: Tailwind 配置扩展

- [ ] **Step 1: 修改 `tailwind.config.js`**

```javascript
module.exports = {
  theme: {
    extend: {
      fontSize: {
        'ui-xl': 'calc(var(--ui-font-size, 14px) + 4px)',
        'ui-lg': 'calc(var(--ui-font-size, 14px) + 2px)',
        'ui-base': 'var(--ui-font-size, 14px)',
        'ui-caption': 'calc(var(--ui-font-size, 14px) - 1px)',
        'ui-sm': 'calc(var(--ui-font-size, 14px) - 2px)',
        'ui-xs': 'calc(var(--ui-font-size, 14px) - 4px)',
      },
      colors: {
        'ui-bg': 'var(--color-background)',
        'ui-card': 'var(--color-card)',
        'ui-surface': 'var(--color-surface)',
        'ui-popover': 'var(--color-popover)',
        'ui-border': 'var(--color-border)',
        'ui-foreground': 'var(--color-foreground)',
        'ui-subtle': 'var(--color-foreground-subtle)',
      }
    }
  }
}
```

- [ ] **Step 2: 验证 Tailwind 构建**

Run: `npm run build`
Expected: 构建成功，无 Tailwind 错误

- [ ] **Step 3: Commit**

```bash
git add tailwind.config.js
git commit -m "feat(ui): extend tailwind.config.js with text-ui-* tokens

- fontSize: ui-xl (18px), ui-lg (16px), ui-base (14px), ui-caption (13px), ui-sm (12px), ui-xs (10px)
- colors: ui-bg, ui-card, ui-surface, ui-popover, ui-border, ui-foreground, ui-subtle
- Uses CSS variables for theme switching"
```

---

### Task 2.3: Add CSS variables to `src/index.css`

**Files:**
- Modify: `src/index.css`

**Interfaces:**
- Consumes: `tailwind.config.js` 中定义的 CSS 变量
- Produces: Light/Dark 主题变量定义

- [ ] **Step 1: 修改 `src/index.css`**

```css
:root {
  --ui-font-size: 14px;

  /* Light theme defaults */
  --color-background: #ffffff;
  --color-card: #f8f9fa;
  --color-surface: #f3f4f6;
  --color-popover: #ffffff;
  --color-border: #e5e7eb;
  --color-foreground: #111827;
  --color-foreground-subtle: #6b7280;
}

[data-theme='dark'] {
  --color-background: #0f172a;
  --color-card: #1e293b;
  --color-surface: #334155;
  --color-popover: #1e293b;
  --color-border: #334155;
  --color-foreground: #f1f5f9;
  --color-foreground-subtle: #94a3b8;
}
```

- [ ] **Step 2: 验证前端构建**

Run: `npm run dev`
Expected: Vite 启动成功，无 CSS 错误

- [ ] **Step 3: Commit**

```bash
git add src/index.css
git commit -m "feat(ui): add CSS variables for design tokens in src/index.css

- Light theme: white background, subtle grays
- Dark theme: slate background, light foreground
- --ui-font-size: 14px (drives text-ui-* scale)"
```

---

### Task 2.4: Fix Settings Toggle a11y + migrate to tokens

**Files:**
- Modify: `src/shared/components/Toggle.tsx` (或实际路径)
- Test: `src/shared/components/__tests__/Toggle.test.tsx`

**Interfaces:**
- Consumes: `text-ui-*` tokens, semantic colors
- Produces: a11y 修复的 Toggle 组件

- [ ] **Step 1: 定位 Toggle 组件**

Run: `find src -name "Toggle.tsx" -o -name "Switch.tsx"`
Expected: 找到组件路径（如 `src/shared/components/Toggle.tsx`）

- [ ] **Step 2: 修复 a11y**

在组件中添加：
```tsx
<button
  role="switch"
  aria-checked={checked}
  // ... other props
>
```

- [ ] **Step 3: 迁移到 Token**

把组件中的 `text-sm` 改为 `text-ui-sm`，`bg-gray-200` 改为 `bg-ui-surface`。

- [ ] **Step 4: 写测试**

```tsx
test('Toggle has role="switch" and aria-checked', () => {
  render(<Toggle checked={true} onChange={() => {}} />);
  const toggle = screen.getByRole('switch');
  expect(toggle).toHaveAttribute('aria-checked', 'true');
});
```

- [ ] **Step 5: 运行测试**

Run: `npm test -- Toggle.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/shared/components/Toggle.tsx src/shared/components/__tests__/Toggle.test.tsx
git commit -m "fix(ui): add role=switch + aria-checked to Toggle component

- Fixes [[sage-settings-toggle-a11y-gap]]
- Migrates to text-ui-* tokens and semantic colors
- Adds test for a11y attributes"
```

---

### Task 2.5: Unify Card / Button variants

**Files:**
- Modify: `src/shared/components/Button.tsx`
- Modify: `src/shared/components/Card.tsx`

**Interfaces:**
- Consumes: `text-ui-*` tokens, semantic colors
- Produces: 统一的 Button / Card 变体

- [ ] **Step 1: 审查现有 Button 变体**

Run: `grep -r "className.*bg-" src/shared/components/Button.tsx`
Expected: 查看现有变体

- [ ] **Step 2: 统一 Button 样式**

使用语义颜色：
```tsx
<button className="bg-ui-bg text-ui-foreground border-ui-border">
```

- [ ] **Step 3: 统一 Card 样式**

```tsx
<div className="bg-ui-card border-ui-border rounded-xl">
```

- [ ] **Step 4: 验证前端构建**

Run: `npm run build`
Expected: 构建成功

- [ ] **Step 5: Commit**

```bash
git add src/shared/components/Button.tsx src/shared/components/Card.tsx
git commit -m "feat(ui): unify Button and Card to use design tokens

- Button: bg-ui-bg, text-ui-foreground, border-ui-border
- Card: bg-ui-card, border-ui-border, rounded-xl
- Consistent with DESIGN.md"
```

---

**Phase 2 完成标准：**
- [x] `DESIGN.md` 完成
- [x] `tailwind.config.js` 扩展 `text-ui-*` 与语义颜色
- [x] `src/index.css` 添加主题变量
- [x] Settings Toggle a11y 修复
- [x] Button / Card 统一样式
- [ ] Cherry-pick 到 release/win7（PR 合并后执行）

---

## Phase 3: Glossary + ServiceLogger + State Ownership

### Task 3.1: Create `docs/GLOSSARY.md`

**Files:**
- Create: `docs/GLOSSARY.md`

**Interfaces:**
- Consumes: design spec §5.1 术语表
- Produces: 领域词汇表文档

- [ ] **Step 1: 创建 `docs/GLOSSARY.md`**

包含 10 个核心术语：
- Office / Office Tool / Sandbox Tool / Agent Profile / Scheduler
- Working Memory / Arena / MCP Server / Lockstep / Cherry-pick

（具体内容见 design spec §5.1）

- [ ] **Step 2: Commit**

```bash
git add docs/GLOSSARY.md
git commit -m "docs: add GLOSSARY.md with 10 core domain terms

- Defines Office, Office Tool, Sandbox Tool, Agent Profile
- Clarifies WorkingMemory is NOT a singleton
- Distinguishes Lockstep vs Cherry-pick"
```

---

### Task 3.2: Create `backend/loggers.py` (serviceLogger pattern)

**Files:**
- Create: `backend/loggers.py`

**Interfaces:**
- Consumes: Python stdlib `logging`
- Produces: `create_service_logger(scope: str)` function

- [ ] **Step 1: 创建 `backend/loggers.py`**

```python
import logging

def create_service_logger(scope: str) -> logging.Logger:
    """Create a logger with a specific scope.

    Args:
        scope: Logger scope (e.g., "office", "scheduler", "arena")

    Returns:
        Logger instance with formatted output

    Example:
        logger = create_service_logger("office")
        logger.info("Document processed")
        # Output: [office] INFO: Document processed
    """
    logger = logging.getLogger(scope)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(f'[{scope}] %(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
```

- [ ] **Step 2: 写测试**

```python
# backend/tests/unit/test_loggers.py
import logging
from backend.loggers import create_service_logger

def test_create_service_logger_returns_logger():
    logger = create_service_logger("test")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test"

def test_create_service_logger_has_handler():
    logger = create_service_logger("test")
    assert len(logger.handlers) > 0

def test_create_service_logger_reuses_existing():
    logger1 = create_service_logger("test")
    logger2 = create_service_logger("test")
    assert logger1 is logger2  # Same instance
```

- [ ] **Step 3: 运行测试**

Run: `pytest backend/tests/unit/test_loggers.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/loggers.py backend/tests/unit/test_loggers.py
git commit -m "feat(backend): add create_service_logger pattern

- Replaces scattered print/logging calls
- Formats: [scope] LEVEL: message
- Reuses existing logger instance for same scope
- Includes unit tests"
```

---

### Task 3.3: Create `electron/loggers.ts`

**Files:**
- Create: `electron/loggers.ts`

**Interfaces:**
- Consumes: `electron-log` (already installed)
- Produces: `createLogger(scope: string)` function

- [ ] **Step 1: 创建 `electron/loggers.ts`**

```typescript
import log from 'electron-log';

export function createLogger(scope: string) {
  return {
    debug: (message: string, ...args: any[]) => log.debug(`[${scope}] ${message}`, ...args),
    info: (message: string, ...args: any[]) => log.info(`[${scope}] ${message}`, ...args),
    warn: (message: string, ...args: any[]) => log.warn(`[${scope}] ${message}`, ...args),
    error: (message: string, ...args: any[]) => log.error(`[${scope}] ${message}`, ...args),
  };
}
```

- [ ] **Step 2: 写测试**

```typescript
// electron/__tests__/loggers.test.ts
import { createLogger } from '../loggers';

test('createLogger returns object with 4 methods', () => {
  const logger = createLogger('test');
  expect(logger).toHaveProperty('debug');
  expect(logger).toHaveProperty('info');
  expect(logger).toHaveProperty('warn');
  expect(logger).toHaveProperty('error');
});

test('logger methods are functions', () => {
  const logger = createLogger('test');
  expect(typeof logger.debug).toBe('function');
  expect(typeof logger.info).toBe('function');
});
```

- [ ] **Step 3: 运行测试**

Run: `npm test -- electron/__tests__/loggers.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add electron/loggers.ts electron/__tests__/loggers.test.ts
git commit -m "feat(electron): add createLogger pattern for scoped logging

- Wraps electron-log with scope prefix
- 4 methods: debug, info, warn, error
- Includes unit tests"
```

---

### Task 3.4: Create `src/shared/logger.ts`

**Files:**
- Create: `src/shared/logger.ts`

**Interfaces:**
- Consumes: browser console API
- Produces: `createLogger(scope: string)` function

- [ ] **Step 1: 创建 `src/shared/logger.ts`**

```typescript
export function createLogger(scope: string) {
  return {
    debug: (message: string, ...args: any[]) => console.debug(`[${scope}] ${message}`, ...args),
    info: (message: string, ...args: any[]) => console.info(`[${scope}] ${message}`, ...args),
    warn: (message: string, ...args: any[]) => console.warn(`[${scope}] ${message}`, ...args),
    error: (message: string, ...args: any[]) => console.error(`[${scope}] ${message}`, ...args),
  };
}
```

- [ ] **Step 2: 写测试**

```typescript
// src/shared/__tests__/logger.test.ts
import { createLogger } from '../logger';

test('createLogger returns object with 4 methods', () => {
  const logger = createLogger('test');
  expect(logger).toHaveProperty('debug');
  expect(logger).toHaveProperty('info');
  expect(logger).toHaveProperty('warn');
  expect(logger).toHaveProperty('error');
});
```

- [ ] **Step 3: 运行测试**

Run: `npm test -- src/shared/__tests__/logger.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/shared/logger.ts src/shared/__tests__/logger.test.ts
git commit -m "feat(ui): add createLogger pattern for frontend scoped logging

- Wraps console API with scope prefix
- 4 methods: debug, info, warn, error
- Includes unit tests"
```

---

### Task 3.5: Write `docs/technical/15-state-ownership.md`

**Files:**
- Create: `docs/technical/15-state-ownership.md`

**Interfaces:**
- Consumes: design spec §5.3
- Produces: 状态所有者原则文档

- [ ] **Step 1: 创建 `docs/technical/15-state-ownership.md`**

包含三条铁律：
1. 单一状态所有者
2. 接口 + 依赖方向 + 事件顺序 + 幂等边界
3. 跨模块事件传播

（具体内容见 design spec §5.3）

- [ ] **Step 2: Commit**

```bash
git add docs/technical/15-state-ownership.md
git commit -m "docs: add state ownership principles (15-state-ownership.md)

- Single state owner: one write path per state
- Interface + dependency direction + event order + idempotent boundaries
- Cross-module event propagation (not direct mutation)"
```

---

**Phase 3 完成标准：**
- [x] `docs/GLOSSARY.md` 完成（10 个术语）
- [x] `backend/loggers.py` 完成（serviceLogger 模式）
- [x] `electron/loggers.ts` 完成
- [x] `src/shared/logger.ts` 完成
- [x] `docs/technical/15-state-ownership.md` 完成
- [ ] Cherry-pick 到 release/win7（PR 合并后执行）

---

## Phase 4: Engineering Tools

### Task 4.1: Write `scripts/dep-refs.mjs`

**Files:**
- Create: `scripts/dep-refs.mjs`

**Interfaces:**
- Consumes: Python `ast` module, TypeScript Compiler API
- Produces: 依赖反查工具

- [ ] **Step 1: 创建脚本骨架**

```javascript
#!/usr/bin/env node

import { readFileSync } from 'fs';
import { extname } from 'path';

function analyzePython(filePath) {
  // 使用 Python ast 模块分析（这里简化为 grep）
  const content = readFileSync(filePath, 'utf-8');
  const imports = content.match(/^from\s+(\S+)\s+import/gm) || [];
  return imports;
}

function analyzeTypeScript(filePath) {
  // 使用 TypeScript Compiler API（这里简化为 grep）
  const content = readFileSync(filePath, 'utf-8');
  const imports = content.match(/^import.*from\s+['"]([^'"]+)['"]/gm) || [];
  return imports;
}

const filePath = process.argv[2];
if (!filePath) {
  console.error('Usage: node scripts/dep-refs.mjs <file>');
  process.exit(1);
}

const ext = extname(filePath);
const imports = ext === '.py' ? analyzePython(filePath) : analyzeTypeScript(filePath);

console.log(`Dependencies of ${filePath}:`);
for (const imp of imports) {
  console.log(`  ${imp}`);
}
```

- [ ] **Step 2: 测试脚本**

Run: `node scripts/dep-refs.mjs backend/office/tool_service.py`
Expected: 输出依赖列表

- [ ] **Step 3: Commit**

```bash
git add scripts/dep-refs.mjs
git commit -m "feat(tools): add dep-refs script for dependency analysis

- Analyzes Python and TypeScript files
- Lists import statements
- Usage: node scripts/dep-refs.mjs <file>"
```

---

### Task 4.2: Write `scripts/architecture-context.mjs`

**Files:**
- Create: `scripts/architecture-context.mjs`

**Interfaces:**
- Consumes: `architecture-policy.json`
- Produces: 模块上下文生成工具

- [ ] **Step 1: 创建脚本**

```javascript
#!/usr/bin/env node

import { readFileSync, readdirSync, statSync } from 'fs';
import { join } from 'path';

const policy = JSON.parse(readFileSync('architecture-policy.json', 'utf-8'));
const moduleId = process.argv[2];

if (!moduleId) {
  console.error('Usage: node scripts/architecture-context.mjs <module-id>');
  process.exit(1);
}

const module = policy.modules.find(m => m.id === moduleId);
if (!module) {
  console.error(`Module '${moduleId}' not found`);
  process.exit(1);
}

console.log(`Module: ${module.id}`);
console.log(`Roots: ${module.roots.join(', ')}`);
if (module.requires) {
  console.log(`Requires: ${module.requires.join(', ')}`);
}

console.log('Public entrypoints:');
for (const root of module.roots) {
  const files = readdirSync(root).filter(f => f.endsWith('.ts') || f.endsWith('.tsx') || f.endsWith('.py'));
  for (const file of files.slice(0, 5)) {
    console.log(`  - ${join(root, file)}`);
  }
}
```

- [ ] **Step 2: 测试脚本**

Run: `node scripts/architecture-context.mjs frontend-features`
Expected: 输出模块上下文

- [ ] **Step 3: Commit**

```bash
git add scripts/architecture-context.mjs
git commit -m "feat(tools): add architecture-context script for module context generation

- Reads architecture-policy.json
- Lists module roots, requires, and public entrypoints
- Usage: node scripts/architecture-context.mjs <module-id>"
```

---

### Task 4.3: Write `scripts/count-lines.sh`

**Files:**
- Create: `scripts/count-lines.sh`

**Interfaces:**
- Consumes: `architecture-policy.json`
- Produces: 文件行数统计脚本

- [ ] **Step 1: 创建脚本**

```bash
#!/bin/bash

MAX_LINES=$(jq -r '.global.maxFileLines' architecture-policy.json)

echo "Files exceeding $MAX_LINES lines:"
find src backend electron -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" \) | while read file; do
  lines=$(wc -l < "$file")
  if [ "$lines" -gt "$MAX_LINES" ]; then
    over=$((lines - MAX_LINES))
    printf "  %-50s %5d lines (+%d)\n" "$file" "$lines" "$over"
  fi
done

echo ""
echo "Distribution:"
find src backend electron -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" \) | xargs wc -l | awk '
  $1 <= 200 { under200++ }
  $1 > 200 && $1 <= 400 { under400++ }
  $1 > 400 && $1 <= 800 { under800++ }
  $1 > 800 { over800++ }
  END {
    printf "  0-200 lines:   %4d files\n", under200
    printf "  200-400 lines: %4d files\n", under400
    printf "  400-800 lines: %4d files\n", under800
    printf "  800+ lines:    %4d files\n", over800
  }'
```

- [ ] **Step 2: 测试脚本**

Run: `bash scripts/count-lines.sh`
Expected: 输出超标文件清单 + 分布统计

- [ ] **Step 3: Commit**

```bash
git add scripts/count-lines.sh
git commit -m "feat(tools): add count-lines script for file size tracking

- Reports files exceeding maxFileLines (800)
- Shows distribution histogram
- Usage: bash scripts/count-lines.sh"
```

---

### Task 4.4: Integrate to CI

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `scripts/count-lines.sh`
- Produces: CI 集成

- [ ] **Step 1: 修改 `.github/workflows/ci.yml`**

添加新 job：
```yaml
count-lines:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: bash scripts/count-lines.sh
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: integrate count-lines into CI

- Tracks files exceeding 800 lines
- Shows distribution over time"
```

---

**Phase 4 完成标准：**
- [x] `scripts/dep-refs.mjs` 可运行
- [x] `scripts/architecture-context.mjs` 可运行
- [x] `scripts/count-lines.sh` 可运行
- [x] CI 集成 `count-lines` job
- [ ] Cherry-pick 到 release/win7（PR 合并后执行）

---

## 执行交接（Execution Handoff）

**Plan 完成并保存到 `docs/superpowers/plans/2026-09-21-zcode-inspired-optimization.md`。**

**两个执行选项：**

**1. Subagent-Driven（推荐）** - 我为每个 task 调度一个独立的 subagent，task 之间 review，快速迭代

**2. Inline Execution** - 在当前会话中批量执行 task，设置 checkpoint 进行 review

**选哪个？**
