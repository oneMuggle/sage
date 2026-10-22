/**
 * Electron smoke test (Phase 4 lightweight CI smoke).
 *
 * Verifies the Win7 IPC bridge contract end-to-end:
 *   1. Electron launches without crashing
 *   2. BrowserWindow appears within 90s on a cold Windows runner
 *   3. window.electronAPI is exposed by preload (preload.ts loaded)
 *   4. Frontend HTML loaded (not blank/white)
 *   5. screenshot saved for human review
 *
 * What this DOES NOT verify:
 *   - Backend spawn + /health (SAGE_SKIP_BACKEND=1 — CI has no conda env)
 *   - chat-stream-{id} NDJSON relay (requires live backend)
 *   - Chromium sandbox policy (smoke launches with --no-sandbox; the product
 *     default on modern Windows remains sandboxed)
 *   - Win7-specific GPU flags (Electron 21 + Win7 D3D11 — covered by Phase 5
 *     self-hosted Win7 runner smoke test)
 *
 * @see docs/superpowers/plans/2026-06-13_*.md (Phase 4 in plan)
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';

const MAIN_JS = path.resolve(process.cwd(), 'dist-electron', 'electron', 'main.js');
const FIRST_WINDOW_TIMEOUT_MS = 90_000;
const SECOND_WINDOW_TIMEOUT_MS = 30_000;
const MAX_MAIN_OUTPUT_LINES = 120;
let app: ElectronApplication | null = null;
const mainOutput: string[] = [];

function rememberMainOutput(stream: 'stdout' | 'stderr', chunk: Buffer): void {
  const text = chunk.toString('utf-8');
  for (const line of text.split(/\r?\n/)) {
    if (line) mainOutput.push(`[${stream}] ${line}`);
  }
  if (mainOutput.length > MAX_MAIN_OUTPUT_LINES) {
    mainOutput.splice(0, mainOutput.length - MAX_MAIN_OUTPUT_LINES);
  }
  if (/error|fatal|cannot|failed|throw|exception/i.test(text)) {
    process.stderr.write(`[electron-main ${stream}] ${text}`);
  }
}

interface MainWindowDiagnostic {
  id: number;
  visible: boolean;
  destroyed: boolean;
  url: string;
  title: string;
}

interface MainDiagnostics {
  isReady: boolean;
  userData: string;
  windows: MainWindowDiagnostic[];
}

async function collectMainDiagnostics(): Promise<string> {
  if (!app) return 'electron app is null';

  const evaluation = app
    .evaluate(({ app: electronApp, BrowserWindow }) => ({
      isReady: electronApp.isReady(),
      userData: electronApp.getPath('userData'),
      windows: BrowserWindow.getAllWindows().map((win) => ({
        id: win.id,
        visible: win.isVisible(),
        destroyed: win.isDestroyed(),
        url: win.webContents.getURL(),
        title: win.getTitle(),
      })),
    }))
    .catch(
      (error: unknown) =>
        `evaluate failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  const diagnostics: MainDiagnostics | string = await Promise.race([
    evaluation,
    new Promise<string>((resolve) => {
      setTimeout(() => resolve('evaluate timed out after 5000ms'), 5_000);
    }),
  ]);
  if (typeof diagnostics === 'string') return diagnostics;

  let logTail = '(log tail unavailable)';
  try {
    const logDir = path.join(diagnostics.userData, 'logs');
    if (existsSync(logDir)) {
      const files = readdirSync(logDir)
        .filter((name) => name.endsWith('.ndjson'))
        .sort();
      const latest = files[files.length - 1];
      if (latest) {
        logTail = readFileSync(path.join(logDir, latest), 'utf-8')
          .trimEnd()
          .split(/\r?\n/)
          .slice(-120)
          .join('\n');
      }
    }
  } catch (error) {
    logTail = `failed to read main log: ${error instanceof Error ? error.message : String(error)}`;
  }

  return [
    `main state: ${JSON.stringify(diagnostics)}`,
    '--- electron main log tail ---',
    logTail,
  ].join('\n');
}

async function waitForFirstWindow(timeoutMs: number): Promise<Page> {
  try {
    return await app!.firstWindow({ timeout: timeoutMs });
  } catch (error) {
    const diagnostics = await collectMainDiagnostics();
    process.stderr.write(
      `\n[electron-smoke] firstWindow timed out after ${timeoutMs}ms\n${diagnostics}\n` +
        `--- electron main output tail ---\n${mainOutput.join('\n')}\n`,
    );
    throw error;
  }
}

test.beforeAll(async () => {
  test.setTimeout(120_000);
  app = await electron.launch({
    args: ['--no-sandbox', MAIN_JS],
    cwd: process.cwd(),
    env: {
      ...process.env,
      SAGE_SKIP_BACKEND: '1',
      // Electron 21's sandboxed renderer access-violates (0xC0000005)
      // during loadFile on the windows-2025-vs2026 20261018.275 runner
      // image, before the page can commit. Reuse main.ts's existing
      // legacy-Windows escape hatch for this smoke only; packaged/user
      // launches do not set it and keep the modern sandbox default.
      SAGE_NO_SANDBOX: '1',
      // This smoke verifies Electron + preload + renderer only. The doctor
      // subprocess probes a Python/conda backend that CI deliberately does
      // not install here, and it runs before createMainWindow().
      SAGE_DOCTOR_ON_START: 'false',
      SAGE_RUNTIME_CHECK_ON_START: 'false',
      CI: 'true',
      NODE_ENV: 'production',
    },
    timeout: 60_000,
  });
  const proc = app.process();
  proc.stdout?.on('data', (chunk: Buffer) => rememberMainOutput('stdout', chunk));
  proc.stderr?.on('data', (chunk: Buffer) => rememberMainOutput('stderr', chunk));
});

test.afterAll(async () => {
  if (app) {
    await app.close();
    app = null;
  }
});

/**
 * 测试失败时把 main 进程的完整现场倒出来。
 *
 * 之前只在 `firstWindow` 超时时打印诊断, 而 renderer 崩溃的失败发生在
 * `waitForLoadState` —— 那条路径没有任何 main 侧上下文, CI 日志里只剩
 * "Navigation failed because page crashed!", 无法区分是 sandbox、GPU
 * 还是 OOM。`mainOutput` 捕获了 main 进程的全部 stdout/stderr (不只是
 * 噪声行), `collectMainDiagnostics` 还会读 electron-log 的 ndjson 尾部,
 * 两者合起来包含 render-process-gone 的 reason/exitCode。
 */
test.afterEach(async (_fixtures, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  const diagnostics = await collectMainDiagnostics();
  process.stderr.write(
    `\n[electron-smoke] test failed: ${testInfo.title} (${testInfo.status})\n` +
      `${diagnostics}\n` +
      `--- electron main output tail ---\n${mainOutput.join('\n')}\n`,
  );
});

test('Electron launches and exposes electronAPI', async () => {
  test.setTimeout(180_000);
  expect(app, 'electron app must have launched').not.toBeNull();

  // Wait for first BrowserWindow. The root e2e project otherwise inherits
  // Playwright's 30s test timeout, which is too tight for Electron 21 cold
  // starts on current windows-latest images.
  const window = await waitForFirstWindow(FIRST_WINDOW_TIMEOUT_MS);
  // Wait for full page load (HTML + scripts + chunks), not just DOMContentLoaded.
  // dist/ has 300+ vendor chunks (Shiki languages, etc.) — React only mounts after
  // all <script type="module"> entries resolve.
  await window.waitForLoadState('load');

  // Wait for electronAPI to be exposed by preload (contextBridge.exposeInMainWorld
  // is called synchronously but Playwright's firstWindow may resolve before
  // preload finishes — waitForFunction polls until the API is on window).
  // 30s timeout: Electron cold start on Windows CI runner can take 20-30s before
  // preload finishes exposing electronAPI.invoke. 10s was too tight (pre-existing
  // flaky failures — see run 29792790778 trace).
  await window.waitForFunction(
    () =>
      typeof (window as unknown as { electronAPI?: { invoke?: unknown } }).electronAPI?.invoke ===
      'function',
    undefined,
    { timeout: 30_000 },
  );

  // Verify electronAPI.listen also exposed
  const hasListen = await window.evaluate(() => {
    const win = globalThis as unknown as {
      electronAPI?: { listen: unknown };
    };
    return typeof win.electronAPI?.listen === 'function';
  });
  expect(hasListen, 'window.electronAPI.listen must be a function').toBe(true);

  // Verify frontend HTML rendered (not blank). Give React up to 30s to mount —
  // production build has 300+ chunks and renders without backend (SAGE_SKIP_BACKEND=1).
  const bodyText = await window.locator('body').textContent({ timeout: 30_000 });
  expect(bodyText, 'frontend body must have rendered some text').toBeTruthy();
  expect(bodyText!.length, 'frontend body text length > 0').toBeGreaterThan(0);

  // Take screenshot for human review
  await window.screenshot({
    path: 'tests/electron/screenshots/smoke-launch.png',
    fullPage: true,
  });
});

test('invoke IPC bridge round-trips through main process', async () => {
  test.setTimeout(90_000);
  expect(app).not.toBeNull();
  const window = await waitForFirstWindow(SECOND_WINDOW_TIMEOUT_MS);
  await window.waitForLoadState('domcontentloaded');

  // Wait for electronAPI ready (same as first test, 30s timeout to match preload cold-start)
  await window.waitForFunction(
    () =>
      typeof (window as unknown as { electronAPI?: { invoke?: unknown } }).electronAPI?.invoke ===
      'function',
    undefined,
    { timeout: 30_000 },
  );

  // electronAPI.invoke calls ipcRenderer.invoke('sage:invoke', {cmd, args}).
  // Main process will throw "Unknown IPC command" for an unrecognized cmd —
  // that's expected and proves the bridge is wired through main.
  const errorMsg = await window.evaluate(async () => {
    const win = globalThis as unknown as {
      electronAPI?: { invoke: (cmd: string) => Promise<unknown> };
    };
    try {
      await win.electronAPI!.invoke('definitely_not_a_real_command');
      return null; // no error — bridge bypassed main??
    } catch (e) {
      return e instanceof Error ? e.message : String(e);
    }
  });

  // Either we got an error message (bridge works, main rejected cmd)
  // or main allowed it (shouldn't happen for unknown cmd)
  expect(errorMsg, 'invoke must route through main process; unknown cmd should throw').toMatch(
    /Unknown IPC command|definitely_not_a_real_command/i,
  );
});
