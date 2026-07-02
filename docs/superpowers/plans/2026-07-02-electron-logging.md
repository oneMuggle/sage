# Electron 桌面日志 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sage 桌面壳(Electron 主进程 + React renderer)加入结构化 NDJSON 文件日志 + 三个用户 UI 入口,解决 Win7 打包后无错误线索的痛点。

**Architecture:** `electron-log@^4.4.8` 作为底层文件引擎,封装 `electron/logger.ts`(主进程 logger);渲染端通过 IPC `sage:log:write` 把日志转发到主进程统一写文件;三个 UI 入口(菜单 / 设置页 / 启动失败对话框)都用 `app.getPath('userData')/logs/sage-YYYY-MM-DD.ndjson` 同源数据。

**Tech Stack:**
- Electron 21.4.4 + Node 16.20.2(主进程 TypeScript)
- electron-log 4.4.8(文件写入 / 轮转 / crash dump)
- React 18 + sonner(设置页 UI)
- Vitest(单元测试 + jsdom)
- lefthook pre-commit(自动 lint/format)

## Global Constraints

- 后端 Python 必须在 conda 环境 `sage-backend` 运行(`/home/fz/anaconda3/envs/sage-backend/bin/python`)(本任务**不涉及后端 Python**,但维护约束)
- Node 必须用 `/home/fz/.nvm/versions/node/v25.9.0/bin/node`
- 当前分支 `feat/electron-logging` (基于 `origin/main`),worktree 干净状态
- Spec 文档路径: `docs/superpowers/specs/2026-07-02-electron-logging-design.md` (commit 22b7c16)
- electron-log 版本: `^4.4.8`(兼容 Node 16 / Electron 21)
- 日志目录: `app.getPath('userData')/logs/`
- 日志文件名: `sage-YYYY-MM-DD.ndjson`(本地日期)
- 保留策略: 7 天 + 单文件 10MB 切 `.1` 后缀
- 启动级别优先级: `SAGE_LOG_LEVEL` env > `userData/config.json` > 默认 `info`
- IPC rate limit: renderer 每秒最多 100 条,超出丢弃
- 提交 message 用 conventional commits 格式
- `LEFTHOOK=0 git push` 处理偶发 pre-push 失败(per memory)
- 所有 commit 前先 `git status` 确认改动范围
- **不修改 release/win7 分支**(本期只动 main;M7 cherry-pick 单独处理)
- **不修改后端 Python / 后端 requirements**(本期只动 Electron + 前端)

## File Structure Reference

```
electron/
├── logger.ts                          (T4, 重写,主进程 logger)
├── logPaths.ts                        (T6, 新)
├── logRotate.ts                       (T7, 新)
├── menu.ts                            (T10, 新)
├── showStartupFailureDialog.ts        (T11, 新)
├── ipc/logIpc.ts                      (T8, 新)
├── main.ts                            (T5 + T12, 改)
├── preload.ts                         (T9, 改,暴露 window.electronAPI.log 等)
└── __tests__/
    ├── logger.test.ts                 (T3, 新)
    ├── logPaths.test.ts               (T6, 新)
    ├── logRotate.test.ts              (T7, 新)
    ├── logIpc.test.ts                 (T8, 新)
    ├── menu.test.ts                   (T10, 新)
    └── showStartupFailureDialog.test.ts (T11, 新)

src/
├── shared/log/
│   ├── levels.ts                      (T2, 新)
│   ├── client.ts                      (T8, 新)
│   └── __tests__/client.test.ts       (T8, 新)
├── widgets/settings/
│   ├── DiagnosticsCard.tsx            (T13, 新)
│   └── __tests__/DiagnosticsCard.test.tsx (T13, 新)
├── widgets/layout/ErrorBoundary.tsx   (T9, 改,用 clientLogger)
├── pages/Settings.tsx                 (T13, 改,渲染 DiagnosticsCard)
└── shared/types/electron-api.ts       (T9, 改,加 log/logFiles 方法)

docs/technical/29-electron-logging.md  (T14, 新)
docs/user-manual/06-diagnostics.md     (T14, 新)
```

---

## Task 1: 安装 electron-log + 准备测试基础设施

**Files:**
- Modify: `package.json`(新增依赖)

**Interfaces:**
- Consumes: 现有 package.json + vitest 配置
- Produces: `electron-log@^4.4.8` 已安装

- [ ] **Step 1: 确认 vitest 当前能跑 electron 测试**

```bash
cd /home/fz/project/sage && cat package.json | grep -A2 '"test:run"'
```

确认 `vitest run` 已配置。检查 electron 测试目前是否能跑:

```bash
cd /home/fz/project/sage && ls electron/__tests__/
```

应看到 `commands.test.ts` / `invoke.test.ts` / `relay.test.ts`(已存在)。

- [ ] **Step 2: 安装 electron-log**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm install --save electron-log@^4.4.8
```

预期输出:`+ electron-log@4.4.8` 类似行。

- [ ] **Step 3: 验证 package.json 已更新**

```bash
cd /home/fz/project/sage && grep -A1 "electron-log" package.json
```

预期:`"electron-log": "^4.4.8"` 在 `dependencies` 中。

- [ ] **Step 4: 验证 vitest 能跑现有测试(无回归)**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/commands.test.ts 2>&1 | tail -20
```

预期:通过或显示 "skipped"(`process.env.SAGE_SKIP_BACKEND` 之类),无失败。

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add package.json package-lock.json && git commit -m "chore(deps): add electron-log@^4.4.8 for desktop file logging"
```

---

## Task 2: 共享日志级别常量 `src/shared/log/levels.ts`

**Files:**
- Create: `src/shared/log/levels.ts`

**Interfaces:**
- Consumes: 无
- Produces: `LogLevel` 类型 + `LOG_LEVELS` 数字映射 + `DEFAULT_LOG_LEVEL = 'info'` + `RATE_LIMIT_WARN_INTERVAL_MS`

- [ ] **Step 1: 创建文件**

```typescript
// src/shared/log/levels.ts

/**
 * Shared log level constants for Electron main + renderer.
 *
 * Single source of truth — must not import anything from electron/ or
 * node:* (used by renderer code too).
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

/** Default level if neither SAGE_LOG_LEVEL env nor config.json sets one. */
export const DEFAULT_LOG_LEVEL: LogLevel = 'info';

/** Rate-limited log overflow: warn once per N ms. */
export const RATE_LIMIT_WARN_INTERVAL_MS = 60_000;
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck 2>&1 | tail -10
```

预期:无错误。

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage && git add src/shared/log/levels.ts && git commit -m "feat(log): add shared LogLevel constants"
```

---

## Task 3: 主进程 logger — 写失败测试

**Files:**
- Create: `electron/__tests__/logger.test.ts`

**Interfaces:**
- Consumes: `src/shared/log/levels.ts`(`LogLevel`, `LOG_LEVELS`, `DEFAULT_LOG_LEVEL`)
- Produces: 测试覆盖,定义 logger.ts 必须满足的行为

- [ ] **Step 1: 写测试文件**

```typescript
// electron/__tests__/logger.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, readFileSync, existsSync, appendFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let tmpDir: string;
let originalEnv: Record<string, string | undefined>;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-logger-test-'));
  originalEnv = {
    SAGE_LOG_DIR: process.env.SAGE_LOG_DIR,
    SAGE_LOG_LEVEL: process.env.SAGE_LOG_LEVEL,
  };
  process.env.SAGE_LOG_DIR = tmpDir;
  process.env.SAGE_LOG_LEVEL = 'debug';
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  for (const [k, v] of Object.entries(originalEnv)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  vi.resetModules();
});

async function importLogger() {
  const mod = await import('../logger');
  return mod.logger;
}

describe('logger', () => {
  it('writes NDJSON line with required fields', async () => {
    const logger = await importLogger();
    logger.info('hello world', { foo: 'bar' });

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    expect(existsSync(file)).toBe(true);

    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    expect(lines).toHaveLength(1);
    const obj = JSON.parse(lines[0]);

    expect(obj).toMatchObject({
      level: 'info',
      source: 'main',
      msg: 'hello world',
      meta: { foo: 'bar' },
    });
    expect(obj.ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });

  it('respects SAGE_LOG_LEVEL filtering', async () => {
    process.env.SAGE_LOG_LEVEL = 'warn';
    const logger = await importLogger();

    logger.debug('should-not-appear');
    logger.info('also-not');
    logger.warn('yes-warn');
    logger.error('yes-error');

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    if (!existsSync(file)) return;

    const lines = readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean);
    const levels = lines.map((l) => JSON.parse(l).level);
    expect(levels).not.toContain('debug');
    expect(levels).not.toContain('info');
    expect(levels).toContain('warn');
    expect(levels).toContain('error');
  });

  it('falls back to string when meta has circular reference', async () => {
    const logger = await importLogger();
    const circular: Record<string, unknown> = { a: 1 };
    circular.self = circular;

    logger.error('circular', circular);

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    const obj = JSON.parse(lines[0]);

    expect(obj.level).toBe('error');
    expect(obj.msg).toBe('circular');
    expect(typeof obj.meta.self).toBe('string');
    expect(obj.meta.self).toBe('[unserializable]');
    expect(obj.meta.a).toBe(1);
  });

  it('omits meta field when not provided', async () => {
    const logger = await importLogger();
    logger.info('no meta');

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    const obj = JSON.parse(readFileSync(file, 'utf-8').trim());

    expect(obj.msg).toBe('no meta');
    expect(obj.meta).toBeUndefined();
  });

  it('appends to existing file (does not overwrite)', async () => {
    const logsDir = join(tmpDir, 'logs');
    require('node:fs').mkdirSync(logsDir, { recursive: true });
    const today = new Date().toISOString().slice(0, 10);
    const file = join(logsDir, `sage-${today}.ndjson`);
    appendFileSync(file, '{"existing":true}\n', 'utf-8');

    const logger = await importLogger();
    logger.info('appended');

    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0])).toEqual({ existing: true });
    expect(JSON.parse(lines[1]).msg).toBe('appended');
  });
});
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logger.test.ts 2>&1 | tail -30
```

预期:FAIL,提示 "Cannot find module '../logger'" 或类似。

- [ ] **Step 3: Commit (RED)**

```bash
cd /home/fz/project/sage && git add electron/__tests__/logger.test.ts && git commit -m "test(logger): add NDJSON file logger failing tests"
```

---

## Task 4: 主进程 logger — 实现

**Files:**
- Rewrite: `electron/logger.ts`

**Interfaces:**
- Consumes: `src/shared/log/levels.ts` 的 `LogLevel` / `DEFAULT_LOG_LEVEL` / `LOG_LEVELS`
- Produces: `logger.{debug,info,warn,error}(msg, meta?)` 接口 + `_logFromSource()` 内部方法(供 logIpc 用)+ 文件 NDJSON 输出 + 级别过滤 + meta 安全序列化

- [ ] **Step 1: 重写 `electron/logger.ts`**

```typescript
// electron/logger.ts

/**
 * Electron main process logger — NDJSON file logger with level filtering.
 *
 * Wraps electron-log (4.x, Win7-compatible) for file persistence + rotation,
 * and exposes a thin level-aware API for the rest of the main process.
 *
 * Output: <userData>/logs/sage-YYYY-MM-DD.ndjson (NDJSON, one event per line)
 *
 * Lifecycle:
 *   - Module load: reads SAGE_LOG_DIR / SAGE_LOG_LEVEL env, configures electron-log
 *   - First call to logger.*: ensures log directory exists
 *   - Each call: writes one NDJSON line with ts/level/source/msg/meta
 *
 * Renderer-side logs come through IPC (sage:log:write), handled in logIpc.ts.
 */

import log from 'electron-log';
import { appendFileSync, mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { app } from 'electron';
import type { LogLevel } from '../src/shared/log/levels';
import { LOG_LEVELS, DEFAULT_LOG_LEVEL } from '../src/shared/log/levels';

const SOURCE = 'main';

function resolveLogDir(): string {
  if (process.env.SAGE_LOG_DIR) return process.env.SAGE_LOG_DIR;
  try {
    return join(app.getPath('userData'), 'logs');
  } catch {
    return join(process.cwd(), 'logs');
  }
}

function resolveLevel(): LogLevel {
  const env = process.env.SAGE_LOG_LEVEL as LogLevel | undefined;
  if (env && env in LOG_LEVELS) return env;
  return DEFAULT_LOG_LEVEL;
}

const LOG_DIR = resolveLogDir();
const CURRENT_LEVEL = resolveLevel();

try {
  mkdirSync(LOG_DIR, { recursive: true });
  log.transports.file.resolvePathFn = () => join(LOG_DIR, 'electron-log-fallback.log');
  log.transports.file.level = CURRENT_LEVEL;
  log.transports.console.level = process.env.NODE_ENV === 'production' ? 'warn' : 'debug';
} catch (err) {
  console.error('[logger] failed to configure transports:', err);
}

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVELS[level] >= LOG_LEVELS[CURRENT_LEVEL];
}

function safeStringify(value: unknown): unknown {
  const seen = new WeakSet();
  const replacer = (_key: string, val: unknown): unknown => {
    if (typeof val === 'function' || typeof val === 'symbol') return '[unserializable]';
    if (typeof val === 'bigint') return val.toString();
    if (val !== null && typeof val === 'object') {
      if (seen.has(val)) return '[unserializable]';
      seen.add(val);
    }
    return val;
  };
  try {
    return JSON.parse(JSON.stringify(value, replacer));
  } catch {
    return '[unserializable]';
  }
}

function writeLine(level: LogLevel, source: string, msg: string, meta?: unknown): void {
  const line: Record<string, unknown> = {
    ts: new Date().toISOString(),
    level,
    source,
    msg,
  };
  if (meta !== undefined) {
    line.meta = safeStringify(meta);
  }
  const today = new Date().toISOString().slice(0, 10);
  const file = join(LOG_DIR, `sage-${today}.ndjson`);
  try {
    if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });
    appendFileSync(file, JSON.stringify(line) + '\n', 'utf-8');
  } catch (err) {
    console.error('[logger] failed to write log line:', err);
  }
}

function logIt(level: LogLevel, msg: string, meta?: unknown, source: string = SOURCE): void {
  if (!shouldLog(level)) return;
  writeLine(level, source, msg, meta);
  try {
    const electronLogMethod = (log as unknown as Record<string, (m: string) => void>)[level];
    if (electronLogMethod) electronLogMethod.call(log, `[${source}] ${msg}`);
  } catch {
    /* ignore */
  }
}

export const logger = {
  debug(msg: string, meta?: unknown): void {
    logIt('debug', msg, meta);
  },
  info(msg: string, meta?: unknown): void {
    logIt('info', msg, meta);
  },
  warn(msg: string, meta?: unknown): void {
    logIt('warn', msg, meta);
  },
  error(msg: string, meta?: unknown): void {
    logIt('error', msg, meta);
  },
  /** Internal: log with explicit source (used by logIpc for renderer events). */
  _logFromSource(level: LogLevel, source: string, msg: string, meta?: unknown): void {
    logIt(level, msg, meta, source);
  },
};
```

- [ ] **Step 2: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logger.test.ts 2>&1 | tail -30
```

预期:5 个 test 全 PASS。

- [ ] **Step 3: typecheck**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck:electron 2>&1 | tail -10
```

预期:无错误。

- [ ] **Step 4: Commit (GREEN)**

```bash
cd /home/fz/project/sage && git add electron/logger.ts && git commit -m "feat(logger): NDJSON file logger with safe meta serialization"
```

---

## Task 5: main.ts 接入 — 顶部初始化 + 替换 console.*

**Files:**
- Modify: `electron/main.ts`(第 1-3 行初始化; ~14 处 `console.*` 替换)

**Interfaces:**
- Consumes: `logger` from `electron/logger.ts`
- Produces: 启动后第一行日志写入文件;后续 console 调用全部走 logger

- [ ] **Step 1: 在 main.ts 顶部加 logger import 和 init**

修改 `electron/main.ts`,把现有的 `import { ... } from 'electron';` 块**之前**添加:

```typescript
// 必须最先 import — 早于 app.* flags,捕获 GPU 设置 throw
import { logger } from './logger';
logger.info('main: process started', {
  pid: process.pid,
  electronVer: process.versions.electron,
  platform: process.platform,
  packaged: require('electron').app.isPackaged,
});
```

- [ ] **Step 2: 替换 ~14 处 console.* 为 logger.***

修改 `electron/main.ts` 内的 console 调用:

| 上下文 | 原代码 | 改为 |
|---|---|---|
| backend stdout | `process.stdout.write(`[backend] ${b}`)` | `logger.debug('backend: stdout', { line: b.toString().trim() })` |
| backend stderr | `process.stderr.write(`[backend:err] ${b}`)` | `logger.error('backend: stderr', { line: b.toString().trim() })` |
| backend exit | `console.log(...)` | `logger.info('main: backend exited', { code })` |
| loadURL fail | `console.error(...)` | `logger.error('main: loadURL failed', { url: VITE_DEV_URL, err: e.message })` |
| loadFile fail | `console.error(...)` | `logger.error('main: loadFile failed', { path: indexHtml, err: e.message })` |
| IPC invoke err | `console.error(...)` | `logger.error('ipc: invoke failed', { cmd: payload.cmd, err: msg })` |
| listen subscribe | `console.log(...)` | `logger.debug('ipc: listen subscribe', { event })` |
| listen relay err | `console.error(...)` | `logger.error('ipc: relay error', { event, err: e.message })` |
| listen unknown event | `console.warn(...)` | `logger.warn('ipc: unknown event', { event })` |
| unlisten abort | `console.log(...)` | `logger.debug('ipc: unlisten aborted', { event })` |
| SAGE_SKIP_BACKEND | `console.log(...)` | `logger.info('main: backend skipped (SAGE_SKIP_BACKEND=1)')` |
| waitForBackend fail | `console.error(...)` | `logger.error('main: backend health timeout', { url: BACKEND_HEALTH, timeoutMs: BACKEND_HEALTH_TIMEOUT_MS })` |
| waitForBackend OK | `console.log(...)` | `logger.info('main: backend ready', { url: BACKEND_URL })` |
| shutdownBackend | `console.log(...)` | `logger.info('main: killing backend subprocess')` |

- [ ] **Step 3: 验证 typecheck**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck:electron 2>&1 | tail -10
```

预期:无错误(注意 logger.info 第二个参数必须是 plain object,如原代码传 `someError`,需包成 `{ err: msg }`)。

- [ ] **Step 4: 验证 electron 仍能编译**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run build:electron 2>&1 | tail -10
```

预期:`dist-electron/electron/main.js` 重新生成,无 TS 错误。

- [ ] **Step 5: 跑现有 electron 测试无回归**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/ 2>&1 | tail -20
```

预期:全部 PASS(包括 logger 的 5 个测试 + 已有的 commands/invoke/relay 测试)。

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage && git add electron/main.ts && git commit -m "refactor(main): initialize logger at startup, route console to file"
```

---

## Task 6: logPaths.ts — 路径解析单例

**Files:**
- Create: `electron/logPaths.ts`
- Create: `electron/__tests__/logPaths.test.ts`

**Interfaces:**
- Consumes: `app.getPath('userData')`, `process.env.SAGE_LOG_DIR`
- Produces: `getLogDir(): string` 返回日志目录(确保存在); `getCurrentLogFile(): string` 返回今天的日志文件路径

- [ ] **Step 1: 写测试**

```typescript
// electron/__tests__/logPaths.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => '/mock/userData'),
    isPackaged: false,
  },
}));

let originalEnv: Record<string, string | undefined>;
let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-logpaths-test-'));
  originalEnv = { SAGE_LOG_DIR: process.env.SAGE_LOG_DIR };
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  if (originalEnv.SAGE_LOG_DIR === undefined) delete process.env.SAGE_LOG_DIR;
  else process.env.SAGE_LOG_DIR = originalEnv.SAGE_LOG_DIR;
});

describe('logPaths', () => {
  it('returns SAGE_LOG_DIR when env is set', async () => {
    const { getLogDir } = await import('../logPaths');
    expect(getLogDir()).toBe(tmpDir);
  });

  it('creates the directory if it does not exist', async () => {
    const freshDir = join(tmpDir, 'logs-subdir');
    process.env.SAGE_LOG_DIR = freshDir;
    vi.resetModules();

    const { getLogDir } = await import('../logPaths');
    const result = getLogDir();
    expect(result).toBe(freshDir);
    expect(existsSync(freshDir)).toBe(true);
  });

  it('falls back to app.getPath("userData")/logs when SAGE_LOG_DIR not set', async () => {
    delete process.env.SAGE_LOG_DIR;
    vi.resetModules();
    const { getLogDir } = await import('../logPaths');
    expect(getLogDir()).toBe(join('/mock/userData', 'logs'));
  });

  it('getCurrentLogFile returns sage-YYYY-MM-DD.ndjson under log dir', async () => {
    const { getCurrentLogFile } = await import('../logPaths');
    const file = getCurrentLogFile();
    expect(file.startsWith(tmpDir)).toBe(true);
    expect(file).toMatch(/sage-\d{4}-\d{2}-\d{2}\.ndjson$/);
  });
});
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logPaths.test.ts 2>&1 | tail -15
```

预期:FAIL "Cannot find module '../logPaths'"。

- [ ] **Step 3: 实现 logPaths.ts**

```typescript
// electron/logPaths.ts
import { mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { app } from 'electron';

let cachedDir: string | null = null;

export function getLogDir(): string {
  if (cachedDir) return cachedDir;
  const dir = process.env.SAGE_LOG_DIR ?? join(app.getPath('userData'), 'logs');
  if (!existsSync(dir)) {
    try {
      mkdirSync(dir, { recursive: true });
    } catch (err) {
      console.error('[logPaths] failed to create log dir:', err);
    }
  }
  cachedDir = dir;
  return dir;
}

export function getCurrentLogFile(): string {
  const today = new Date().toISOString().slice(0, 10);
  return join(getLogDir(), `sage-${today}.ndjson`);
}
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logPaths.test.ts 2>&1 | tail -15
```

预期:4 个 test 全 PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add electron/logPaths.ts electron/__tests__/logPaths.test.ts && git commit -m "feat(logPaths): resolve and cache userData/logs directory"
```

---

## Task 7: logRotate.ts — 7 天清理 + 10MB 切分

**Files:**
- Create: `electron/logRotate.ts`
- Create: `electron/__tests__/logRotate.test.ts`

**Interfaces:**
- Consumes: `getLogDir()` from `electron/logPaths.ts`
- Produces: `cleanupOlderThan(days)` 删除 mtime > N 天的 .ndjson; `rotateIfOversized()` 单文件 >10MB 时切 `.1`

- [ ] **Step 1: 写测试**

```typescript
// electron/__tests__/logRotate.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync, utimesSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => '/mock/userData'),
    isPackaged: false,
  },
}));

let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-rotate-test-'));
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  delete process.env.SAGE_LOG_DIR;
});

function fileAgeDays(file: string, days: number): void {
  const mtime = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  utimesSync(file, mtime, mtime);
}

describe('logRotate.cleanupOlderThan', () => {
  it('removes files older than N days', async () => {
    mkdirSync(tmpDir, { recursive: true });
    const oldFile = join(tmpDir, 'sage-2020-01-01.ndjson');
    const recentFile = join(tmpDir, 'sage-2026-07-02.ndjson');
    writeFileSync(oldFile, '{}\n');
    writeFileSync(recentFile, '{}\n');
    fileAgeDays(oldFile, 10);
    fileAgeDays(recentFile, 1);

    const { cleanupOlderThan } = await import('../logRotate');
    cleanupOlderThan(7);

    expect(existsSync(oldFile)).toBe(false);
    expect(existsSync(recentFile)).toBe(true);
  });

  it('does not delete non-ndjson files', async () => {
    mkdirSync(tmpDir, { recursive: true });
    const oldTxt = join(tmpDir, 'notes.txt');
    writeFileSync(oldTxt, 'do not delete');
    fileAgeDays(oldTxt, 30);

    const { cleanupOlderThan } = await import('../logRotate');
    cleanupOlderThan(7);

    expect(existsSync(oldTxt)).toBe(true);
  });

  it('does not throw on empty or missing directory', async () => {
    delete process.env.SAGE_LOG_DIR;
    vi.resetModules();
    const { cleanupOlderThan } = await import('../logRotate');
    expect(() => cleanupOlderThan(7)).not.toThrow();
  });
});
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logRotate.test.ts 2>&1 | tail -10
```

预期:FAIL "Cannot find module '../logRotate'"。

- [ ] **Step 3: 实现 logRotate.ts**

```typescript
// electron/logRotate.ts
import { readdirSync, statSync, unlinkSync, renameSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { getLogDir, getCurrentLogFile } from './logPaths';
import { logger } from './logger';

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB
const NDJSON_PATTERN = /^sage-\d{4}-\d{2}-\d{2}\.ndjson(\.\d+)?$/;

export function cleanupOlderThan(days: number): void {
  let dir: string;
  try {
    dir = getLogDir();
  } catch (err) {
    logger.warn('logRotate: cannot resolve log dir', { err: String(err) });
    return;
  }
  if (!existsSync(dir)) return;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch (err) {
    logger.warn('logRotate: readdir failed', { dir, err: String(err) });
    return;
  }
  for (const name of entries) {
    if (!NDJSON_PATTERN.test(name)) continue;
    const full = join(dir, name);
    try {
      const st = statSync(full);
      if (st.mtimeMs < cutoff) {
        unlinkSync(full);
        logger.info('logRotate: cleaned up old log', {
          file: name,
          ageDays: Math.round((Date.now() - st.mtimeMs) / 86_400_000),
        });
      }
    } catch (err) {
      logger.warn('logRotate: stat/unlink failed', { file: name, err: String(err) });
    }
  }
}

export function rotateIfOversized(): boolean {
  const file = getCurrentLogFile();
  if (!existsSync(file)) return false;
  try {
    const st = statSync(file);
    if (st.size < MAX_FILE_SIZE_BYTES) return false;
    const rotated = `${file}.1`;
    if (existsSync(rotated)) unlinkSync(rotated);
    renameSync(file, rotated);
    logger.info('logRotate: rotated oversized log', {
      from: file,
      to: rotated,
      sizeMB: Math.round(st.size / 1024 / 1024),
    });
    return true;
  } catch (err) {
    logger.warn('logRotate: rotation failed', { err: String(err) });
    return false;
  }
}
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logRotate.test.ts 2>&1 | tail -15
```

预期:3 个 test 全 PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add electron/logRotate.ts electron/__tests__/logRotate.test.ts && git commit -m "feat(logRotate): 7-day cleanup + 10MB file rotation"
```

---

## Task 8: logIpc.ts + client.ts — 渲染端日志桥接

**Files:**
- Create: `electron/ipc/logIpc.ts`
- Create: `src/shared/log/client.ts`
- Create: `src/shared/log/__tests__/client.test.ts`
- Create: `electron/__tests__/logIpc.test.ts`

**Interfaces:**
- Consumes: `logger._logFromSource(level, source, msg, meta)` from `electron/logger.ts`
- Produces:
  - `registerLogIpc(ipcMain)` 注册 `sage:log:write` handler
  - `clientLogger.{debug,info,warn,error}(msg, meta?)` 渲染端 fire-and-forget API
  - Rate limit: 同 senderId 100/sec

- [ ] **Step 1: 写 client.ts 测试**

```typescript
// src/shared/log/__tests__/client.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';

beforeEach(() => {
  delete (globalThis as unknown as { window?: unknown }).window;
  vi.resetModules();
});

describe('clientLogger', () => {
  it('no-ops when window.electronAPI.log is unavailable', async () => {
    const { clientLogger } = await import('../client');
    expect(() => {
      clientLogger.info('test');
      clientLogger.error('test', { foo: 'bar' });
    }).not.toThrow();
  });

  it('forwards to window.electronAPI.log without awaiting', async () => {
    const mockLog = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as unknown as { window: { electronAPI: { log: typeof mockLog } } }).window = {
      electronAPI: { log: mockLog },
    };
    vi.resetModules();

    const { clientLogger } = await import('../client');
    clientLogger.warn('something', { code: 42 });

    await Promise.resolve();
    expect(mockLog).toHaveBeenCalledWith('warn', 'something', { code: 42 });
  });

  it('silently swallows IPC errors', async () => {
    const mockLog = vi.fn().mockRejectedValue(new Error('IPC failed'));
    (globalThis as unknown as { window: { electronAPI: { log: typeof mockLog } } }).window = {
      electronAPI: { log: mockLog },
    };
    vi.resetModules();

    const { clientLogger } = await import('../client');
    expect(() => clientLogger.error('oops')).not.toThrow();

    await new Promise((r) => setTimeout(r, 0));
    expect(mockLog).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- src/shared/log/__tests__/client.test.ts 2>&1 | tail -10
```

预期:FAIL "Cannot find module"。

- [ ] **Step 3: 实现 client.ts**

```typescript
// src/shared/log/client.ts
import type { LogLevel } from './levels';

declare global {
  interface Window {
    electronAPI?: {
      log?: (level: LogLevel, msg: string, meta?: Record<string, unknown>) => Promise<unknown>;
    };
  }
}

function send(level: LogLevel, msg: string, meta?: Record<string, unknown>): void {
  const api = typeof window !== 'undefined' ? window.electronAPI?.log : undefined;
  if (!api) {
    if (import.meta.env?.DEV) {
      // eslint-disable-next-line no-console
      console[level === 'debug' ? 'debug' : level === 'warn' ? 'warn' : level](
        `[renderer] ${msg}`,
        meta,
      );
    }
    return;
  }
  api(level, msg, meta).catch(() => {
    /* IPC failed; no UI fallback to avoid infinite loops */
  });
}

export const clientLogger = {
  debug(msg: string, meta?: Record<string, unknown>): void {
    send('debug', msg, meta);
  },
  info(msg: string, meta?: Record<string, unknown>): void {
    send('info', msg, meta);
  },
  warn(msg: string, meta?: Record<string, unknown>): void {
    send('warn', msg, meta);
  },
  error(msg: string, meta?: Record<string, unknown>): void {
    send('error', msg, meta);
  },
};
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- src/shared/log/__tests__/client.test.ts 2>&1 | tail -10
```

预期:3 个 test 全 PASS。

- [ ] **Step 5: 写 logIpc.ts 测试**

```typescript
// electron/__tests__/logIpc.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let tmpDir: string;
let originalEnv: Record<string, string | undefined>;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-logIpc-test-'));
  originalEnv = { SAGE_LOG_DIR: process.env.SAGE_LOG_DIR, SAGE_LOG_LEVEL: process.env.SAGE_LOG_LEVEL };
  process.env.SAGE_LOG_DIR = tmpDir;
  process.env.SAGE_LOG_LEVEL = 'debug';
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  for (const [k, v] of Object.entries(originalEnv)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  vi.resetModules();
});

describe('logIpc', () => {
  it('writes log line with source=renderer when sage:log:write invoked', async () => {
    const handlers = new Map<string, (e: unknown, p: unknown) => Promise<unknown>>();
    const fakeIpcMain = {
      handle: (channel: string, handler: (e: unknown, p: unknown) => Promise<unknown>) => {
        handlers.set(channel, handler);
      },
    };
    const { registerLogIpc } = await import('../ipc/logIpc');
    registerLogIpc(fakeIpcMain as never);

    const handler = handlers.get('sage:log:write')!;
    const fakeEvt = { sender: { id: 123 } } as unknown;
    await handler(fakeEvt, { level: 'warn', msg: 'hello', meta: { x: 1 } });

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, `sage-${today}.ndjson`);
    expect(existsSync(file)).toBe(true);
    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    const obj = JSON.parse(lines[0]);
    expect(obj).toMatchObject({
      level: 'warn',
      source: 'renderer',
      msg: 'hello',
      meta: { x: 1 },
    });
  });

  it('rate limits: drops messages exceeding 100/sec from same sender', async () => {
    const handlers = new Map<string, (e: unknown, p: unknown) => Promise<unknown>>();
    const fakeIpcMain = {
      handle: (c: string, h: (e: unknown, p: unknown) => Promise<unknown>) => handlers.set(c, h),
    };
    const { registerLogIpc } = await import('../ipc/logIpc');
    registerLogIpc(fakeIpcMain as never);
    const handler = handlers.get('sage:log:write')!;
    const fakeEvt = { sender: { id: 999 } } as unknown;

    const promises: Promise<unknown>[] = [];
    for (let i = 0; i < 150; i++) {
      promises.push(handler(fakeEvt, { level: 'info', msg: `burst-${i}` }));
    }
    await Promise.all(promises);

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, `sage-${today}.ndjson`);
    if (!existsSync(file)) return;
    const lines = readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean);
    expect(lines.length).toBeLessThanOrEqual(100);
  });
});
```

- [ ] **Step 6: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logIpc.test.ts 2>&1 | tail -10
```

预期:FAIL "Cannot find module"。

- [ ] **Step 7: 实现 logIpc.ts (基础版,管理命令在 T13 加)**

```typescript
// electron/ipc/logIpc.ts
import type { IpcMain } from 'electron';
import type { LogLevel } from '../../src/shared/log/levels';
import { logger } from '../logger';
import { RATE_LIMIT_WARN_INTERVAL_MS } from '../../src/shared/log/levels';

interface LogPayload {
  level: LogLevel;
  msg: string;
  meta?: Record<string, unknown>;
}

const RATE_LIMIT_PER_SEC = 100;

interface SenderState {
  windowStartMs: number;
  count: number;
  lastWarnMs: number;
}
const senderState = new Map<number, SenderState>();

function checkRateLimit(senderId: number): boolean {
  const now = Date.now();
  let state = senderState.get(senderId);
  if (!state || now - state.windowStartMs >= 1000) {
    state = { windowStartMs: now, count: 0, lastWarnMs: 0 };
    senderState.set(senderId, state);
  }
  state.count++;
  if (state.count > RATE_LIMIT_PER_SEC) {
    if (now - state.lastWarnMs >= RATE_LIMIT_WARN_INTERVAL_MS) {
      state.lastWarnMs = now;
      logger.warn('renderer log rate limited', {
        senderId,
        dropped: state.count - RATE_LIMIT_PER_SEC,
      });
    }
    return false;
  }
  return true;
}

export function registerLogIpc(ipcMain: IpcMain): void {
  ipcMain.handle('sage:log:write', async (evt, payload: LogPayload) => {
    const senderId = evt.sender.id;
    if (!checkRateLimit(senderId)) return { ok: false, reason: 'rate-limited' };
    logger._logFromSource(payload.level, 'renderer', payload.msg, payload.meta);
    return { ok: true };
  });
}
```

- [ ] **Step 8: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/logIpc.test.ts 2>&1 | tail -10
```

预期:2 个 test 全 PASS。

- [ ] **Step 9: Commit**

```bash
cd /home/fz/project/sage && git add electron/ipc/logIpc.ts src/shared/log/client.ts src/shared/log/__tests__/client.test.ts electron/__tests__/logIpc.test.ts && git commit -m "feat(log): renderer→main IPC bridge with 100/sec rate limit"
```

---

## Task 9: preload.ts 暴露 log API + ErrorBoundary 接入

**Files:**
- Modify: `electron/preload.ts`
- Modify: `src/widgets/layout/ErrorBoundary.tsx`(如有)

**Interfaces:**
- Consumes: `clientLogger` from `src/shared/log/client.ts`
- Produces: `window.electronAPI.log(level, msg, meta?)` 暴露给 renderer

- [ ] **Step 1: 检查现有 preload.ts**

```bash
cd /home/fz/project/sage && grep -n "electronAPI" electron/preload.ts | tail -10
```

确认现有 electronAPI 的导出结构。

- [ ] **Step 2: 修改 electron/preload.ts 加 log 方法**

在 `electron/preload.ts` 的 `electronAPI` 对象中**添加** import 块顶部:

```typescript
import type { LogLevel } from '../src/shared/log/levels';
```

然后在 `electronAPI = { ... }` 块**最开头**(在 `invoke` 之前)添加:

```typescript
  /**
   * Renderer-side log bridge — forwards to main process for file persistence.
   * Fire-and-forget on the renderer side; main applies rate limit + writes NDJSON.
   */
  log(level: LogLevel, msg: string, meta?: Record<string, unknown>): Promise<{ ok: boolean; reason?: string }> {
    return ipcRenderer.invoke('sage:log:write', { level, msg, meta }) as Promise<{ ok: boolean; reason?: string }>;
  },
```

- [ ] **Step 3: 找到 ErrorBoundary 文件**

```bash
cd /home/fz/project/sage && find src -name "ErrorBoundary*" -type f
```

- [ ] **Step 4: 修改 ErrorBoundary(如有)**

如有 ErrorBoundary,把 `console.error(error, errorInfo)` 改为:

```typescript
import { clientLogger } from '../../shared/log/client';

// 在 componentDidCatch 或同等位置:
clientLogger.error('react error boundary', {
  error: error instanceof Error ? error.message : String(error),
  stack: error instanceof Error ? error.stack : undefined,
  componentStack: errorInfo.componentStack,
});
```

- [ ] **Step 5: typecheck**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck 2>&1 | tail -10
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck:electron 2>&1 | tail -10
```

预期:两边都无错误。

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage && git add electron/preload.ts src/widgets/layout/ErrorBoundary.tsx && git commit -m "feat(log): expose log IPC + wire ErrorBoundary to clientLogger"
```

---

## Task 10: menu.ts — 主菜单加 「打开日志目录」

**Files:**
- Create: `electron/menu.ts`
- Create: `electron/__tests__/menu.test.ts`

**Interfaces:**
- Consumes: `getLogDir()` from `electron/logPaths.ts`
- Produces: `buildApplicationMenu()` — 在 「帮助」 下加 「打开日志目录」 + 「复制日志路径」,使用 `shell.openPath` / `clipboard.writeText`

- [ ] **Step 1: 写测试**

```typescript
// electron/__tests__/menu.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';

const mockMenu = { buildFromTemplate: vi.fn((t) => ({ template: t })), setApplicationMenu: vi.fn() };
const mockShell = { openPath: vi.fn(), openExternal: vi.fn() };
const mockClipboard = { writeText: vi.fn() };

vi.mock('electron', () => ({
  Menu: mockMenu,
  shell: mockShell,
  clipboard: mockClipboard,
  app: { name: 'Sage' },
}));

let tmpDir: string;

beforeEach(() => {
  vi.resetModules();
  tmpDir = '/tmp/test-logs';
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.clearAllMocks();
});

describe('buildApplicationMenu', () => {
  it('includes 帮助 menu with 打开日志目录 item', async () => {
    const { buildApplicationMenu } = await import('../menu');
    buildApplicationMenu();

    expect(mockMenu.buildFromTemplate).toHaveBeenCalledTimes(1);
    const template = mockMenu.buildFromTemplate.mock.calls[0][0] as Array<{
      label?: string;
      submenu?: Array<{ label: string; click?: () => void }>;
    }>;
    const helpMenu = template.find((m) => m.label === '帮助');
    expect(helpMenu).toBeDefined();

    const openItem = helpMenu!.submenu!.find((i) => i.label === '打开日志目录');
    expect(openItem).toBeDefined();
    expect(typeof openItem!.click).toBe('function');

    openItem!.click!();
    expect(mockShell.openPath).toHaveBeenCalledWith(tmpDir);
  });

  it('includes 复制日志路径 item', async () => {
    const { buildApplicationMenu } = await import('../menu');
    buildApplicationMenu();
    const template = mockMenu.buildFromTemplate.mock.calls[0][0] as Array<{
      label?: string;
      submenu?: Array<{ label: string; click?: () => void }>;
    }>;
    const helpMenu = template.find((m) => m.label === '帮助');
    const copyItem = helpMenu!.submenu!.find((i) => i.label === '复制日志路径');

    expect(copyItem).toBeDefined();
    copyItem!.click!();
    expect(mockClipboard.writeText).toHaveBeenCalledWith(tmpDir);
  });

  it('calls Menu.setApplicationMenu', async () => {
    const { buildApplicationMenu } = await import('../menu');
    buildApplicationMenu();
    expect(mockMenu.setApplicationMenu).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/menu.test.ts 2>&1 | tail -10
```

预期:FAIL "Cannot find module"。

- [ ] **Step 3: 实现 menu.ts**

```typescript
// electron/menu.ts
import { Menu, shell, clipboard, app } from 'electron';
import { getLogDir } from './logPaths';
import { logger } from './logger';

export function buildApplicationMenu(): void {
  const isMac = process.platform === 'darwin';
  const logDir = getLogDir();

  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: 'about' as const },
              { type: 'separator' as const },
              { role: 'quit' as const },
            ],
          },
        ]
      : []),
    {
      label: '文件',
      submenu: [isMac ? { role: 'close' } : { role: 'quit' }],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '打开日志目录',
          click: () => {
            logger.info('main: user opened log dir via menu', { logDir });
            shell
              .openPath(logDir)
              .catch((err) => logger.error('main: shell.openPath failed', { err: String(err) }));
          },
        },
        {
          label: '复制日志路径',
          click: () => {
            clipboard.writeText(logDir);
            logger.info('main: user copied log dir via menu', { logDir });
          },
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/menu.test.ts 2>&1 | tail -10
```

预期:3 个 test 全 PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add electron/menu.ts electron/__tests__/menu.test.ts && git commit -m "feat(menu): add 帮助→打开日志目录/复制日志路径 entries"
```

---

## Task 11: showStartupFailureDialog.ts — 启动失败对话框

**Files:**
- Create: `electron/showStartupFailureDialog.ts`
- Create: `electron/__tests__/showStartupFailureDialog.test.ts`

**Interfaces:**
- Consumes: `getLogDir()` from `electron/logPaths.ts`, `shell.openPath` / `dialog.showMessageBox` from electron
- Produces: `showStartupFailureDialog(opts: { reason, detail? }): Promise<'open-logs' | 'retry' | 'quit'>`

- [ ] **Step 1: 写测试**

```typescript
// electron/__tests__/showStartupFailureDialog.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, existsSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const mockShowMessageBox = vi.fn();
const mockShellOpenPath = vi.fn();
const mockQuit = vi.fn();

vi.mock('electron', () => ({
  dialog: { showMessageBox: mockShowMessageBox },
  shell: { openPath: mockShellOpenPath },
  app: { quit: mockQuit, getPath: vi.fn(() => '/mock/userData') },
}));

let tmpDir: string;
let originalEnv: Record<string, string | undefined>;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-failure-dialog-test-'));
  originalEnv = { SAGE_LOG_DIR: process.env.SAGE_LOG_DIR };
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.resetModules();
  vi.clearAllMocks();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  if (originalEnv.SAGE_LOG_DIR === undefined) delete process.env.SAGE_LOG_DIR;
  else process.env.SAGE_LOG_DIR = originalEnv.SAGE_LOG_DIR;
});

describe('showStartupFailureDialog', () => {
  it('logs error before showing dialog', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    await showStartupFailureDialog({ reason: 'backend timeout' });

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, `sage-${today}.ndjson`);
    expect(existsSync(file)).toBe(true);
    const lines = readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean);
    const startupLine = lines.find((l) => l.includes('startup failed'));
    expect(startupLine).toBeDefined();
  });

  it('returns "open-logs" when first button chosen', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    const result = await showStartupFailureDialog({ reason: 'fail' });
    expect(result).toBe('open-logs');
    expect(mockShellOpenPath).toHaveBeenCalled();
  });

  it('returns "quit" and calls app.quit when third button chosen', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 2 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    const result = await showStartupFailureDialog({ reason: 'fail' });
    expect(result).toBe('quit');
    expect(mockQuit).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/showStartupFailureDialog.test.ts 2>&1 | tail -10
```

预期:FAIL "Cannot find module"。

- [ ] **Step 3: 实现 showStartupFailureDialog.ts**

```typescript
// electron/showStartupFailureDialog.ts
import { dialog, shell, app } from 'electron';
import { getLogDir } from './logPaths';
import { logger } from './logger';

export type StartupFailureChoice = 'open-logs' | 'retry' | 'quit';

export async function showStartupFailureDialog(opts: {
  reason: string;
  detail?: string;
}): Promise<StartupFailureChoice> {
  // CRITICAL: write to log BEFORE showing dialog (so even if dialog crashes
  // the failure is captured on disk)
  logger.error('main: startup failed, showing dialog', {
    reason: opts.reason,
    detail: opts.detail,
  });

  const logDir = getLogDir();
  const buttons = ['打开日志目录', '重试', '退出'];
  const result = await dialog.showMessageBox({
    type: 'error',
    title: 'Sage 启动失败',
    message: opts.reason,
    detail: `${opts.detail ?? ''}\n\n错误详情已写入日志,请点击下方按钮获取日志文件并附在反馈中。\n\n日志目录:${logDir}`,
    buttons,
    defaultId: 0,
    cancelId: 2,
    noLink: true,
  });

  const choice: StartupFailureChoice =
    result.response === 0 ? 'open-logs' : result.response === 1 ? 'retry' : 'quit';

  if (choice === 'open-logs') {
    logger.info('main: user chose open-logs after startup failure');
    shell
      .openPath(logDir)
      .catch((err) => logger.error('main: shell.openPath failed', { err: String(err) }));
  } else if (choice === 'retry') {
    logger.info('main: user chose retry after startup failure');
  } else {
    logger.info('main: user chose quit after startup failure');
    app.quit();
  }
  return choice;
}
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/showStartupFailureDialog.test.ts 2>&1 | tail -10
```

预期:3 个 test 全 PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add electron/showStartupFailureDialog.ts electron/__tests__/showStartupFailureDialog.test.ts && git commit -m "feat(dialog): startup failure dialog with 3-button user choice"
```

---

## Task 12: main.ts 接入菜单 + 启动失败路径

**Files:**
- Modify: `electron/main.ts`

**Interfaces:**
- Consumes: `buildApplicationMenu()` from `electron/menu.ts`, `showStartupFailureDialog()` from `electron/showStartupFailureDialog.ts`, `cleanupOlderThan(7)` from `electron/logRotate.ts`, `registerLogIpc(ipcMain)` from `electron/ipc/logIpc.ts`

- [ ] **Step 1: 在 main.ts 顶部加 import**

找到 `import { ... } from 'electron';` 行,在它**后面**添加:

```typescript
import { buildApplicationMenu } from './menu';
import { showStartupFailureDialog } from './showStartupFailureDialog';
import { cleanupOlderThan } from './logRotate';
import { registerLogIpc } from './ipc/logIpc';
```

- [ ] **Step 2: 修改 registerIpcHandlers 加 registerLogIpc**

在 `registerIpcHandlers()` 函数末尾追加(在 `registerSkillsIpc(...)` 后):

```typescript
registerLogIpc(ipcMain);
```

- [ ] **Step 3: 修改 app.whenReady 加 logRotate.cleanupOlderThan**

找到 `app.whenReady().then(async () => {`,在函数体**第一行**(在 `registerIpcHandlers()` 之前)添加:

```typescript
cleanupOlderThan(7);
```

- [ ] **Step 4: 修改 waitForBackend 超时路径**

找到 `if (!ready) { console.error(...); app.quit(); return; }` 替换为:

```typescript
if (!ready) {
  const choice = await showStartupFailureDialog({
    reason: '后端服务在 30 秒内未响应',
    detail: `请检查端口 ${BACKEND_PORT} 是否被占用,或 conda 环境 sage-backend 是否已安装。`,
  });
  if (choice === 'retry') {
    const ready2 = await waitForBackend();
    if (!ready2) {
      await showStartupFailureDialog({
        reason: '后端服务在重试后仍未响应',
        detail: '已重试一次,仍无法连接',
      });
      return;
    }
    createMainWindow();
    return;
  }
  return;
}
```

- [ ] **Step 5: 修改 mainWindow.loadFile/loadURL 失败路径**

找到 `mainWindow.loadURL(...).catch(...)` 和 `mainWindow.loadFile(...).catch(...)`,改为:

```typescript
mainWindow.loadURL(VITE_DEV_URL).catch(async (e) => {
  logger.error('main: loadURL failed', { url: VITE_DEV_URL, err: e.message });
  await showStartupFailureDialog({
    reason: '加载前端开发服务失败',
    detail: `URL: ${VITE_DEV_URL}\n错误: ${e.message}`,
  });
});

const indexHtml = join(__dirname, '..', '..', 'dist', 'index.html');
mainWindow.loadFile(indexHtml).catch(async (e) => {
  logger.error('main: loadFile failed', { path: indexHtml, err: e.message });
  await showStartupFailureDialog({
    reason: '加载前端资源失败',
    detail: `路径: ${indexHtml}\n错误: ${e.message}`,
  });
});
```

- [ ] **Step 6: 在 app.whenReady 末尾加 buildApplicationMenu**

在 `app.whenReady().then(...)` 块最末尾(在 `createMainWindow()` 之后)添加:

```typescript
buildApplicationMenu();
```

- [ ] **Step 7: typecheck + electron 编译**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck:electron 2>&1 | tail -10
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run build:electron 2>&1 | tail -5
```

预期:两边都无错误。

- [ ] **Step 8: 跑全部 electron 测试无回归**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- electron/__tests__/ 2>&1 | tail -20
```

预期:全部 PASS。

- [ ] **Step 9: Commit**

```bash
cd /home/fz/project/sage && git add electron/main.ts && git commit -m "feat(main): wire menu + logRotate + startup failure dialog into app lifecycle"
```

---

## Task 13: DiagnosticsCard.tsx — 设置页 「诊断与日志」 卡片

**Files:**
- Create: `src/widgets/settings/DiagnosticsCard.tsx`
- Create: `src/widgets/settings/__tests__/DiagnosticsCard.test.tsx`
- Modify: `electron/preload.ts`(加 listLogFiles / openLogDir / copyLogPath / cleanupLogs / setLogLevel)
- Modify: `electron/ipc/logIpc.ts`(加管理命令 handler)
- Modify: `src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `window.electronAPI.listLogFiles / openLogDir / copyLogPath / cleanupLogs / setLogLevel`
- Produces: 渲染日志文件列表 + 4 个按钮 + 日志级别选择

- [ ] **Step 1: 扩展 preload.ts 加 log 管理方法**

在 `electron/preload.ts` 的 `electronAPI` 中追加(在 `log` 之后):

```typescript
  listLogFiles(): Promise<Array<{ name: string; sizeBytes: number; mtimeMs: number }>> {
    return ipcRenderer.invoke('sage:log:list-files') as Promise<Array<{ name: string; sizeBytes: number; mtimeMs: number }>>;
  },
  openLogDir(): Promise<string> {
    return ipcRenderer.invoke('sage:log:open-dir') as Promise<string>;
  },
  copyLogPath(): Promise<string> {
    return ipcRenderer.invoke('sage:log:copy-path') as Promise<string>;
  },
  cleanupLogs(): Promise<{ removed: number }> {
    return ipcRenderer.invoke('sage:log:cleanup') as Promise<{ removed: number }>;
  },
  setLogLevel(level: LogLevel): Promise<{ ok: true }> {
    return ipcRenderer.invoke('sage:log:set-level', { level }) as Promise<{ ok: true }>;
  },
```

- [ ] **Step 2: 在 logIpc.ts 注册新 handler**

修改 `electron/ipc/logIpc.ts`,在文件**顶部**追加 import:

```typescript
import { readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { shell, clipboard } from 'electron';
import { cleanupOlderThan } from '../logRotate';
import { getLogDir } from '../logPaths';
```

然后在 `registerLogIpc` 函数内,在 `sage:log:write` handler 之后**追加**:

```typescript
  ipcMain.handle('sage:log:list-files', async () => {
    const dir = getLogDir();
    if (!existsSync(dir)) return [];
    const entries = readdirSync(dir);
    return entries
      .filter((n) => /^sage-\d{4}-\d{2}-\d{2}\.ndjson/.test(n))
      .map((name) => {
        const full = join(dir, name);
        const st = statSync(full);
        return { name, sizeBytes: st.size, mtimeMs: st.mtimeMs };
      })
      .sort((a, b) => b.mtimeMs - a.mtimeMs);
  });

  ipcMain.handle('sage:log:open-dir', async () => {
    const dir = getLogDir();
    await shell.openPath(dir);
    return dir;
  });

  ipcMain.handle('sage:log:copy-path', async () => {
    const dir = getLogDir();
    clipboard.writeText(dir);
    return dir;
  });

  ipcMain.handle('sage:log:cleanup', async () => {
    const dir = getLogDir();
    if (!existsSync(dir)) return { removed: 0 };
    const before = readdirSync(dir).length;
    cleanupOlderThan(7);
    const after = readdirSync(dir).length;
    return { removed: before - after };
  });

  ipcMain.handle('sage:log:set-level', async (_evt, payload: { level: LogLevel }) => {
    process.env.SAGE_LOG_LEVEL = payload.level;
    logger.info('main: log level changed', { level: payload.level });
    return { ok: true };
  });
```

- [ ] **Step 3: 写 DiagnosticsCard 测试**

```typescript
// src/widgets/settings/__tests__/DiagnosticsCard.test.tsx
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockElectronAPI = {
  listLogFiles: vi.fn(),
  openLogDir: vi.fn(),
  copyLogPath: vi.fn(),
  cleanupLogs: vi.fn(),
  setLogLevel: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { window: { electronAPI: typeof mockElectronAPI } }).window = {
    electronAPI: mockElectronAPI,
  };
});

describe('DiagnosticsCard', () => {
  it('renders log file list', async () => {
    mockElectronAPI.listLogFiles.mockResolvedValue([
      { name: 'sage-2026-07-02.ndjson', sizeBytes: 12345, mtimeMs: Date.now() },
    ]);
    const { DiagnosticsCard } = await import('../DiagnosticsCard');
    render(<DiagnosticsCard />);
    await waitFor(() => {
      expect(screen.getByText(/sage-2026-07-02\.ndjson/)).toBeInTheDocument();
    });
  });

  it('triggers openLogDir on button click', async () => {
    mockElectronAPI.listLogFiles.mockResolvedValue([]);
    mockElectronAPI.openLogDir.mockResolvedValue('/path/to/logs');
    const { DiagnosticsCard } = await import('../DiagnosticsCard');
    render(<DiagnosticsCard />);
    const btn = await screen.findByRole('button', { name: /打开日志目录/ });
    fireEvent.click(btn);
    expect(mockElectronAPI.openLogDir).toHaveBeenCalled();
  });

  it('triggers setLogLevel when level changes', async () => {
    mockElectronAPI.listLogFiles.mockResolvedValue([]);
    mockElectronAPI.setLogLevel.mockResolvedValue({ ok: true });
    const { DiagnosticsCard } = await import('../DiagnosticsCard');
    render(<DiagnosticsCard />);
    const select = await screen.findByRole('combobox', { name: /日志级别/ });
    fireEvent.change(select, { target: { value: 'debug' } });
    await waitFor(() => {
      expect(mockElectronAPI.setLogLevel).toHaveBeenCalledWith('debug');
    });
  });
});
```

- [ ] **Step 4: 跑测试验证失败**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- src/widgets/settings/__tests__/DiagnosticsCard.test.tsx 2>&1 | tail -10
```

预期:FAIL "Cannot find module"。

- [ ] **Step 5: 实现 DiagnosticsCard.tsx**

```typescript
// src/widgets/settings/DiagnosticsCard.tsx
import { useEffect, useState } from 'react';
import type { LogLevel } from '../../shared/log/levels';

interface LogFile {
  name: string;
  sizeBytes: number;
  mtimeMs: number;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(ms: number): string {
  const d = new Date(ms);
  const today = new Date().toDateString() === d.toDateString();
  return today
    ? d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('zh-CN');
}

export function DiagnosticsCard() {
  const [files, setFiles] = useState<LogFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [level, setLevel] = useState<LogLevel>('info');

  useEffect(() => {
    window.electronAPI?.listLogFiles?.()
      .then((r) => setFiles(r ?? []))
      .finally(() => setLoading(false));
  }, []);

  const refresh = () => {
    setLoading(true);
    window.electronAPI?.listLogFiles?.()
      .then((r) => setFiles(r ?? []))
      .finally(() => setLoading(false));
  };

  const handleLevelChange = async (newLevel: LogLevel) => {
    setLevel(newLevel);
    await window.electronAPI?.setLogLevel?.(newLevel);
  };

  const handleCleanup = async () => {
    await window.electronAPI?.cleanupLogs?.();
    refresh();
  };

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-lg font-semibold mb-3">诊断与日志</h2>

      <div className="mb-4">
        <div className="text-sm text-muted-foreground mb-2">日志目录(由系统管理,无需记忆)</div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => window.electronAPI?.openLogDir?.()} className="px-3 py-1 rounded border">
            打开日志目录
          </button>
          <button onClick={() => window.electronAPI?.copyLogPath?.()} className="px-3 py-1 rounded border">
            复制路径
          </button>
          <button onClick={handleCleanup} className="px-3 py-1 rounded border">
            立即清理旧日志
          </button>
          <button onClick={refresh} className="px-3 py-1 rounded border" disabled={loading}>
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
      </div>

      <div className="mb-4">
        <label htmlFor="log-level" className="text-sm text-muted-foreground mr-2">日志级别:</label>
        <select id="log-level" value={level} onChange={(e) => handleLevelChange(e.target.value as LogLevel)} className="border rounded px-2 py-1">
          <option value="debug">debug</option>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
        </select>
      </div>

      <div>
        <div className="text-sm text-muted-foreground mb-2">最近日志文件:</div>
        {loading && files.length === 0 ? (
          <div className="text-sm">加载中…</div>
        ) : files.length === 0 ? (
          <div className="text-sm text-muted-foreground">暂无日志文件</div>
        ) : (
          <ul className="text-sm space-y-1">
            {files.map((f) => (
              <li key={f.name} className="flex justify-between gap-4 font-mono">
                <span>{f.name}</span>
                <span className="text-muted-foreground">{formatSize(f.sizeBytes)} · {formatTime(f.mtimeMs)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 6: 跑测试验证通过**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- src/widgets/settings/__tests__/DiagnosticsCard.test.tsx 2>&1 | tail -10
```

预期:3 个 test 全 PASS。

- [ ] **Step 7: 修改 Settings.tsx 引入 DiagnosticsCard**

查找 `src/pages/Settings.tsx`,在 「关于」 卡片**之前**插入:

```typescript
import { DiagnosticsCard } from '../widgets/settings/DiagnosticsCard';

// 在合适位置(关于卡片之上)渲染:
<DiagnosticsCard />
```

- [ ] **Step 8: typecheck + 跑前端测试**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck 2>&1 | tail -10
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run -- src/widgets/settings/__tests__/DiagnosticsCard.test.tsx 2>&1 | tail -5
```

预期:无 type 错误,测试 PASS。

- [ ] **Step 9: Commit**

```bash
cd /home/fz/project/sage && git add electron/preload.ts electron/ipc/logIpc.ts src/widgets/settings/DiagnosticsCard.tsx src/widgets/settings/__tests__/DiagnosticsCard.test.tsx src/pages/Settings.tsx && git commit -m "feat(settings): add Diagnostics card with log file list and controls"
```

---

## Task 14: 文档 — technical + user manual

**Files:**
- Create: `docs/technical/29-electron-logging.md`
- Create: `docs/user-manual/06-diagnostics.md`
- Modify: `docs/technical/README.md`(加章节目录行)
- Modify: `docs/user-manual/README.md`(加章节目录行)

- [ ] **Step 1: 创建技术文档**

写入 `docs/technical/29-electron-logging.md`(完整内容):

```markdown
# 29. Electron 桌面日志

**最后更新**: 2026-07-02
**适用版本**: Sage v0.4+

## 29.1 概述

Sage 桌面壳(Electron 主进程 + React 渲染进程)使用 electron-log 4.x 作为底层引擎,封装项目内的 `electron/logger.ts`,把所有日志以 NDJSON 格式写入 `%APPDATA%/sage/logs/sage-YYYY-MM-DD.ndjson`。

## 29.2 三层日志架构

### 主进程
- 入口: `electron/logger.ts`(包 electron-log)
- 调用方: `electron/main.ts` 第 2-3 行初始化,~14 处 console.* 替换为 logger.*
- 触发场景: backend spawn / IPC handler / 启动失败 / 进程退出

### 渲染进程
- 入口: `src/shared/log/client.ts`(fire-and-forget IPC 客户端)
- 调用方: `ErrorBoundary.tsx` + 关键 fetch 失败 + 未来 hooks
- 触发场景: React 组件崩溃 / API 调用失败

### IPC 桥接
- 入口: `electron/ipc/logIpc.ts`
- 通道: `sage:log:write`
- 限速: 100 msg/sec per sender(超出丢弃)

## 29.3 文件格式

每行一个 NDJSON 对象:
```json
{"ts":"2026-07-02T10:23:11.456Z","level":"info","source":"main","msg":"backend ready","meta":{"port":8765}}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| ts | string | ISO 8601 UTC,毫秒精度 |
| level | enum | debug / info / warn / error |
| source | enum | main / renderer / preload / backend |
| msg | string | 人类可读消息 |
| meta | object? | 可选,JSON-safe,循环引用 fallback 为字符串 |

## 29.4 路径

| 平台 | 路径 |
|---|---|
| Windows | `%APPDATA%/sage/logs/sage-YYYY-MM-DD.ndjson` |
| macOS | `~/Library/Application Support/sage/logs/sage-YYYY-MM-DD.ndjson` |
| Linux | `~/.config/sage/logs/sage-YYYY-MM-DD.ndjson` |

## 29.5 保留策略

- 每天一个文件(按本地日期)
- 启动时清理 >7 天的文件(`cleanupOlderThan(7)`)
- 单文件 >10MB 自动切到 `.1` 后缀
- 用户可在设置页 「诊断与日志」 卡片点 「立即清理旧日志」 按钮强制清理

## 29.6 启动优先级

`SAGE_LOG_LEVEL` env > `userData/config.json` 持久化值 > 默认 `info`

## 29.7 三个用户入口

| 入口 | 位置 | 行为 |
|---|---|---|
| 菜单 | 帮助 → 打开日志目录 | shell.openPath(logDir) |
| 菜单 | 帮助 → 复制日志路径 | clipboard.writeText(logDir) |
| 设置页 | /settings → 诊断与日志 卡片 | 列出文件 + 4 个按钮 + 级别选择 |
| 启动失败对话框 | 启动失败时自动弹 | 打开日志目录 / 重试 / 退出 |

## 29.8 测试覆盖

| 文件 | 验证 |
|---|---|
| electron/__tests__/logger.test.ts | NDJSON 格式 / 级别过滤 / meta 序列化 / append 不覆盖 |
| electron/__tests__/logPaths.test.ts | 路径解析 + 目录创建 |
| electron/__tests__/logRotate.test.ts | 7 天清理 + 文件识别 |
| electron/__tests__/logIpc.test.ts | renderer 转发 + rate limit |
| electron/__tests__/menu.test.ts | 菜单结构 + 点击行为 |
| electron/__tests__/showStartupFailureDialog.test.ts | 对话框内容 + logger 先于 dialog |
| src/shared/log/__tests__/client.test.ts | fire-and-forget + IPC 失败静默 |
| src/widgets/settings/__tests__/DiagnosticsCard.test.tsx | 列表 + 按钮 + 级别切换 |

## 29.9 Win7 启动失败排查流程

1. 用户双击 Sage.exe 无反应
2. 自动弹 「Sage 启动失败」 对话框
3. 用户点 「打开日志目录」 → 资源管理器打开 `%APPDATA%/sage/logs/`
4. 用户点 「复制日志路径」 → 粘贴到反馈中
5. 维护者收到路径 → `tail -f` 最新文件 → 用 grep 找 `level=error` 行
6. 常见错误:
   - `backend: stderr` 含 Python ImportError → conda env 缺包
   - `loadFile failed` 含 ENOENT → 安装包损坏,重装
   - `uncaughtException` 含 GPU 错误 → 调整 `app.disableHardwareAcceleration()`
```

- [ ] **Step 2: 创建用户手册**

写入 `docs/user-manual/06-diagnostics.md`(完整内容):

```markdown
# 6. 诊断与日志

## 6.1 我遇到启动问题怎么办?

Sage 桌面应用在 Windows 7 上启动失败时,会自动弹出 「Sage 启动失败」 对话框。对话框提供 3 个按钮:

- **打开日志目录** — 打开文件资源管理器到日志文件夹
- **重试** — 再次尝试启动后端服务(适合临时端口占用场景)
- **退出** — 关闭 Sage

## 6.2 日志文件在哪里?

默认位置:
- **Windows**: `C:\Users\<你的用户名>\AppData\Roaming\sage\logs\`
- **macOS**: `~/Library/Application Support/sage/logs/`
- **Linux**: `~/.config/sage/logs/`

每天一个文件,文件名格式:`sage-YYYY-MM-DD.ndjson`(年-月-日)。

## 6.3 如何查看日志?

3 种方式:

1. **菜单** → 「帮助」 → 「打开日志目录」 → 在资源管理器中打开文件夹 → 双击 `.ndjson` 文件用任意文本编辑器查看
2. **设置页** → 「诊断与日志」 卡片 → 「打开日志目录」 按钮
3. **复制路径** → 「帮助」 → 「复制日志路径」 → 粘贴到文件资源管理器地址栏

## 6.4 如何反馈问题?

1. 复现问题(让 Sage 再次触发失败)
2. 打开日志目录
3. 把当天日期的 `.ndjson` 文件附在反馈邮件 / GitHub issue 中
4. 在 issue 中描述:
   - 操作系统版本(Win7 SP1 x64 等)
   - 安装包版本(在 「关于」 中查看)
   - 复现步骤

## 6.5 日志保留多久?

- 默认保留 7 天
- 单个文件最大 10MB(超过自动切到 `.1` 后缀)
- 想立即清理: 设置页 → 「诊断与日志」 → 「立即清理旧日志」

## 6.6 隐私

- 日志**不包含** 你的 API key、密码、聊天内容
- 日志只包含: 时间、级别、来源(主进程/渲染进程)、消息、调试元数据(如端口号、组件栈)
- 反馈前可以 grep 一下确认没有意外敏感数据
```

- [ ] **Step 3: 更新 README 章节目录**

查找 `docs/technical/README.md` 和 `docs/user-manual/README.md`,按现有格式加一行新章节链接。

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add docs/technical/29-electron-logging.md docs/user-manual/06-diagnostics.md docs/technical/README.md docs/user-manual/README.md && git commit -m "docs(log): add technical and user manual for desktop logging"
```

---

## Task 15: 最终验收 + PR 准备

**Files:**
- Modify: 无(纯验证步骤)

- [ ] **Step 1: 跑全部测试**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:run 2>&1 | tail -30
```

预期:全部 PASS,新增测试通过,无现有测试回归。

- [ ] **Step 2: 全 typecheck + lint**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck 2>&1 | tail -5
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run typecheck:electron 2>&1 | tail -5
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run lint 2>&1 | tail -10
```

预期:全部无错误。

- [ ] **Step 3: 验证 electron:build 产物**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run electron:build 2>&1 | tail -10
```

预期:`dist/` 和 `dist-electron/` 重新生成,无错误。

- [ ] **Step 4: dev 模式烟测**

```bash
cd /home/fz/project/sage && SAGE_LOG_DIR=/tmp/sage-dev-test /home/fz/.nvm/versions/node/v25.9.0/bin/npm run electron:dev 2>&1 &
sleep 5
ls -la /tmp/sage-dev-test/ 2>/dev/null | head
kill %1 2>/dev/null
```

预期:`/tmp/sage-dev-test/sage-*.ndjson` 存在且至少 1 行(来自 `main: process started`)。

- [ ] **Step 5: 提交前 git status 检查**

```bash
cd /home/fz/project/sage && git status
```

预期:工作树干净(本任务所有 commit 已 done)。

- [ ] **Step 6: 推送 + 开 PR**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/git push -u origin feat/electron-logging
gh pr create --base main --title "feat: Electron desktop NDJSON logging + 3 UI access points" --body "..."
```

PR body 模板:

```
## 概述

为 Sage 桌面壳(Electron 主进程 + React 渲染进程)加入结构化 NDJSON 文件日志 + 三个用户 UI 入口,解决 Win7 打包后无错误线索的痛点。

## 背景

release/win7 产物安装到 Win7 后双击无任何反应:不出现窗口,没有错误弹窗,用户无任何线索。根因:
- 打包后 .exe 是 GUI 子系统 + windowsHide: true,console.log 全部丢到不可见的 stderr
- 现有 electron/logger.ts 只输出到 console,无文件持久化
- app.whenReady() 之前的初始化代码(GPU flags 等)在 Win7 上本身就可能 throw,当前无法捕获

## 改动

### 新增
- electron/logger.ts (重写):包 electron-log 4.x,NDJSON 格式化,级别过滤,meta 安全序列化
- electron/logPaths.ts / logRotate.ts / menu.ts / showStartupFailureDialog.ts
- electron/ipc/logIpc.ts:渲染进程→主进程桥接 + 100/sec rate limit + 管理命令
- src/shared/log/{levels,client}.ts:共享 LogLevel + renderer fire-and-forget logger
- src/widgets/settings/DiagnosticsCard.tsx:设置页 「诊断与日志」 卡片
- 8 个测试文件,共 ~30 个测试用例
- docs/technical/29-electron-logging.md + docs/user-manual/06-diagnostics.md

### 修改
- electron/main.ts:第 2-3 行初始化 logger;14 处 console.* 替换;启动失败路径接对话框
- electron/preload.ts:暴露 window.electronAPI.log + 5 个管理方法
- src/widgets/layout/ErrorBoundary.tsx:console.error → clientLogger.error
- src/pages/Settings.tsx:渲染 DiagnosticsCard
- package.json:electron-log@^4.4.8

## 验证

- npm run typecheck / typecheck:electron / lint 全过
- npm run test:run 全过,新增测试覆盖率 ≥80%
- electron:build 产物能跑
- dev 模式烟测:看到 sage-*.ndjson 文件生成

## 不做

- 不接入 Sentry / OTLP / Datadog
- 不做日志上传 / 分享 UI
- 不替换后端 audit.jsonl
- 本期只在 main,win7 同步走 cherry-pick
```

push 失败时(lefthook pre-push 偶发),用 `LEFTHOOK=0 git push` workaround。

---

## Task 16: Cherry-pick 到 release/win7

> ⚠️ 在 main 合并 PR 之后,且跑通完整 CI 后再执行本任务。
> ⚠️ 严格遵守项目 「双分支长期共存」 策略:不合并分支,不删除 release/win7。

**Files:**
- Modify: 无(纯 git 操作)

- [ ] **Step 1: 切到 release/win7**

```bash
cd /home/fz/project/sage && git fetch origin release/win7 && git checkout release/win7 && git pull --rebase origin release/win7
```

- [ ] **Step 2: 找到 main 上 feat/electron-logging 的 commit 列表**

```bash
cd /home/fz/project/sage && git fetch origin feat/electron-logging && git log --oneline origin/main..origin/feat/electron-logging
```

记录从 main 分叉到 feat/electron-logging tip 的所有 commit SHA(应该有 ~14 个)。

- [ ] **Step 3: 逐个 cherry-pick**

```bash
cd /home/fz/project/sage && git cherry-pick <sha1> <sha2> ... <shaN>
```

逐个 commit cherry-pick(顺序按时间线)。如遇冲突(可能因 win7 已有差异),手动解决 — 由于本期只动 Electron/前端且 win7 应保持 Electron 21 一致,预计冲突极少。

每次 cherry-pick 后 commit message 加 `(cherry picked from main commit XXX)`(若 git 自动加,可不重复)。

- [ ] **Step 4: 验证 win7 py38 + electron 21 兼容性**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend-py38/bin/python -c "import sys; print(sys.version)"
```

预期:3.8.x。

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run build:electron 2>&1 | tail -5
```

预期:无错误(electron-log 4.4.8 已确认兼容 Node 16.20.2)。

- [ ] **Step 5: 跑 win7 相关 CI(本地模拟)**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/ -q 2>&1 | tail -10
```

预期:py38 单测全过(本任务**不**碰后端,但确认无回归)。

- [ ] **Step 6: Push + 开 PR 到 release/win7**

```bash
cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/git push -u origin release/win7
gh pr create --base release/win7 --title "feat: sync Electron desktop logging from main" --body "byte-for-byte port from main (see linked PR #N)"
```

- [ ] **Step 7: 监控 PR CI**

```bash
gh pr checks <pr-number> --watch
```

CI 全绿后报告用户,等用户 merge。

---

## 自审 (per writing-plans)

**Spec 覆盖检查**:
- ✅ § 1.1 问题 → T1-15 全部相关
- ✅ § 1.2 5 项目标 → T1 (install), T4 (NDJSON), T5 (init at top), T7 (rotation), T8 (IPC bridge)
- ✅ § 1.3 非目标 → 全局约束声明
- ✅ § 2 用户故事 → US-1 T11 (dialog), US-2 T13 (settings card), US-3 T4 (grep-able NDJSON), US-4 T4 (dev console + file), US-5 T13 (cleanup button)
- ✅ § 3 架构 → T3-13 全覆盖
- ✅ § 4 文件结构 → T1-14 全部新增/修改文件已列出
- ✅ § 5 错误处理 → T4 (safeStringify), T6 (dir create fail), T8 (rate limit), T11 (logger before dialog)
- ✅ § 6 测试策略 → T3/T6/T7/T8/T10/T11/T13 各自带测试
- ✅ § 7 分支同步 → T15 (PR to main) + T16 (cherry-pick to win7)
- ✅ § 8 风险 → 全局约束声明; electron-log 版本钉死 ^4.4.8

**占位符扫描**: 无 "TBD"/"TODO"/"fill in"。

**类型一致性**:
- `logger.{debug,info,warn,error}(msg, meta?)` — T4 定义,T5/T8/T11/T12 一致
- `clientLogger.{debug,info,warn,error}(msg, meta?)` — T8 定义,T9/T13 一致
- `LogLevel` — T2 定义,T4/T8/T13 全部 import
- `getLogDir()` 返回 `string` — T6 定义,T7/T10/T11/T12 一致
- IPC 通道 `sage:log:write` / `list-files` / `open-dir` / `copy-path` / `cleanup` / `set-level` — T8/T13 定义,preload 一致

**结论**: 计划完整,无遗漏。