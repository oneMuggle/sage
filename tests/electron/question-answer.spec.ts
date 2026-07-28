/**
 * Playwright E2E: M2 part B AskUserQuestion dialog (Electron project).
 *
 * Full pipeline under test (real IPC bridge + NDJSON relay, stubbed backend):
 *
 *   1. Stub backend's gated chat stream emits `acting` →
 *      `ask_user_question` and blocks (like backend UserQuestionGate).
 *   2. Electron relay forwards the NDJSON event to the renderer.
 *   3. useChat writes it to the question store → QuestionDialog mounts.
 *   4. Selecting an option / typing custom text + 提交 invokes
 *      `questions_answer` → main process → POST
 *      /api/v1/questions/{id}/answer on the stub.
 *   5. Stub unblocks the stream → observing → done → dialog closes and
 *      the assistant reply renders.
 *
 * The message marker `__QUESTION_TEST__` switches the stub's attach stream
 * into question-gated mode (see tests/electron/stub_backend.py).
 *
 * Mirrors permission-approval.spec.ts (M1) — the only layer that exercises
 * the real `sage:invoke`/`sage:listen` bridge + relay.ts NDJSON parsing for
 * the new question routes.
 *
 * Run:
 *   npm run build && npm run build:electron
 *   npx playwright test tests/electron/question-answer.spec.ts --project=electron
 */
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const _dirname =
  typeof __dirname !== 'undefined' ? __dirname : path.dirname(fileURLToPath(import.meta.url));

const REPO_ROOT = path.resolve(_dirname, '..', '..');

/** Must match QUESTION_TEST_MARKER in stub_backend.py. */
const QUESTION_MARKER = '__QUESTION_TEST__';

/** Message that triggers the question-gated flow in the stub stream. */
const QUESTION_MESSAGE = `帮我出个报告 ${QUESTION_MARKER}`;

// ---------------------------------------------------------------------------
// Stub backend lifecycle (same pattern as permission-approval.spec.ts)
// ---------------------------------------------------------------------------

function startStub(): Promise<{ proc: ChildProcess; url: string; port: number }> {
  return new Promise((resolve, reject) => {
    const python = process.env.SAGE_PYTHON || 'python3';
    const stubPath = path.resolve(_dirname, 'stub_backend.py');
    const proc = spawn(python, ['-u', stubPath, '0'], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });

    let buf = '';
    let settled = false;

    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        proc.kill('SIGTERM');
        reject(new Error('Stub backend failed to start within 10s'));
      }
    }, 10_000);

    proc.stdout!.on('data', (chunk: Buffer) => {
      buf += chunk.toString('utf-8');
      const m = buf.match(/Stub backend running at (http:\/\/[\d.:]+)/);
      if (m && !settled) {
        settled = true;
        clearTimeout(timer);
        const url = m[1];
        const port = parseInt(url.split(':').pop()!, 10);
        resolve({ proc, url, port });
      }
    });

    proc.stderr!.on('data', () => {
      // Ignore stderr noise; exit handler below rejects on early death.
    });

    proc.on('error', (err: Error) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(err);
      }
    });

    proc.on('exit', (code: number | null) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`Stub backend exited before ready (code=${code})`));
      }
    });
  });
}

async function waitForElectronAPI(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      typeof (globalThis as unknown as { electronAPI?: { invoke?: unknown } }).electronAPI
        ?.invoke === 'function',
    undefined,
    { timeout: 30_000 },
  );
}

/**
 * Minimal valid AppSettings so useChat.sendMessage doesn't bail on
 * "未配置 API 地址" — the stub ignores the endpoint entirely.
 */
function settingsPayload(): Record<string, unknown> {
  return {
    streaming: true,
    autoMemory: true,
    confirmDelete: true,
    compactMode: false,
    endpoints: [
      {
        id: 'ep-e2e',
        name: 'E2E Stub',
        baseUrl: 'http://127.0.0.1:9/v1',
        apiKey: 'sk-e2e',
        discoveredModels: [],
        lastDiscoveredAt: null,
      },
    ],
    modelSelections: {
      chatModel: { endpointId: 'ep-e2e', modelId: 'stub-model' },
      visionModel: { endpointId: null, modelId: null },
      embeddingModel: { endpointId: null, modelId: null },
    },
    maxContext: 4096,
    temperature: 0.7,
    proxyMode: 'system',
    proxyUrl: '',
    tlsVersion: '1.2',
    wiki: { useFolderPicker: true },
    version: '3.0.0',
  };
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('AskUserQuestion dialog (M2 part B, stub backend)', () => {
  let stubProc: ChildProcess | null = null;
  let stubUrl = '';
  let stubPort = 0;

  let app: ElectronApplication | null = null;
  let page: Page | null = null;

  test.beforeAll(async () => {
    test.skip(process.env.SAGE_SKIP_E2E === '1', 'SAGE_SKIP_E2E=1 — E2E disabled');

    let stubResult;
    try {
      stubResult = await startStub();
    } catch (err) {
      test.skip(true, `Stub backend failed to start: ${(err as Error).message}`);
      return;
    }
    stubProc = stubResult.proc;
    stubUrl = stubResult.url;
    stubPort = stubResult.port;

    const mainJs = path.resolve(REPO_ROOT, 'dist-electron', 'electron', 'main.js');
    test.skip(
      !fs.existsSync(mainJs),
      'dist-electron/electron/main.js not found — run `npm run build && npm run build:electron` first',
    );

    app = await electron.launch({
      args: [mainJs],
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHON_BACKEND_PORT: String(stubPort),
        SAGE_SKIP_BACKEND: '1',
        NODE_ENV: 'production',
      },
      timeout: 30_000,
    });

    page = await app.firstWindow();
    await page.waitForLoadState('load', { timeout: 30_000 });

    // Seed settings BEFORE React reads them (same rationale as the
    // permission spec: stub 404s on /api/v1/settings).
    await page.evaluate((payload: string) => {
      window.localStorage.setItem('sage-settings', payload);
      window.localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
    }, JSON.stringify(settingsPayload()));
    await page.reload();
    await page.waitForLoadState('load', { timeout: 30_000 });
    await waitForElectronAPI(page);
  });

  test.afterAll(async () => {
    if (app) {
      await app.close();
      app = null;
    }
    page = null;
    if (stubProc) {
      stubProc.kill('SIGTERM');
      stubProc = null;
    }
  });

  test('01: select option — stream ask_user_question shows dialog; answer hits stub', async () => {
    // Welcome screen: type a marker message and submit. Welcome creates a
    // session and navigates to /chat with pendingMessage (auto-sent).
    await page!.evaluate(() => {
      window.location.hash = '#/welcome';
    });
    const welcomeTextarea = page!.locator('[data-testid="welcome-input-card"] textarea');
    await expect(welcomeTextarea).toBeVisible({ timeout: 20_000 });
    await welcomeTextarea.fill(QUESTION_MESSAGE);
    await welcomeTextarea.press('Enter');

    // The gated stub stream emits ask_user_question → dialog mounts.
    const dialog = page!.locator('[data-testid="question-dialog"]');
    await expect(dialog).toBeVisible({ timeout: 25_000 });
    await expect(page!.locator('[data-testid="question-header"]')).toHaveText('输出格式');
    await expect(page!.locator('[data-testid="question-text"]')).toContainText('选择输出格式?');
    await expect(page!.locator('[data-testid="question-option-0"]')).toContainText('Markdown');
    await expect(page!.locator('[data-testid="question-option-1"]')).toContainText('PDF');

    // Submit disabled until a selection / custom text exists.
    await expect(page!.locator('[data-testid="question-submit"]')).toBeDisabled();

    // Stub sanity: exactly one pending question while the dialog is open.
    // (Node-side fetch — Playwright's page.request API context is not
    //  supported for Electron browser contexts.)
    const pendingBefore = (await (
      await fetch(`${stubUrl}/api/v1/questions/pending`)
    ).json()) as unknown[];
    expect(pendingBefore.length).toBe(1);

    await page!.locator('[data-testid="question-option-1"]').click(); // PDF
    await page!.locator('[data-testid="question-submit"]').click();

    // Dialog closes and the stream completes with the answered reply.
    await expect(dialog).toBeHidden({ timeout: 15_000 });
    await expect
      .poll(
        async () => {
          const body = await page!.locator('#main-content').textContent();
          return body ?? '';
        },
        { timeout: 15_000 },
      )
      .toContain('已回答: PDF');

    // The answer round-tripped through Electron IPC → stub.
    const answersBody = (await (
      await fetch(`${stubUrl}/api/v1/_test/question_answers`)
    ).json()) as {
      answers: Array<{ request_id: string; answers: string[]; custom: string | null }>;
    };
    expect(answersBody.answers.length).toBeGreaterThanOrEqual(1);
    const last = answersBody.answers[answersBody.answers.length - 1];
    expect(last.answers).toEqual(['PDF']);
    expect(last.custom).toBeNull();
  });

  test('02: custom text — free-text answer is recorded by the stub', async () => {
    // Second message from the /chat page (session already exists).
    const textarea = page!.locator('#main-content textarea').first();
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill(`再来一次 ${QUESTION_MARKER} 换个格式`);
    await textarea.press('Enter');

    const dialog = page!.locator('[data-testid="question-dialog"]');
    await expect(dialog).toBeVisible({ timeout: 25_000 });

    // Type custom text only (no option selected) → submit enabled.
    await page!.locator('[data-testid="question-custom"]').fill('用 HTML');
    await page!.locator('[data-testid="question-submit"]').click();

    await expect(dialog).toBeHidden({ timeout: 15_000 });
    await expect
      .poll(
        async () => {
          const body = await page!.locator('#main-content').textContent();
          return body ?? '';
        },
        { timeout: 15_000 },
      )
      .toContain('已回答: 用 HTML');

    const answersBody = (await (
      await fetch(`${stubUrl}/api/v1/_test/question_answers`)
    ).json()) as {
      answers: Array<{ answers: string[]; custom: string | null }>;
    };
    const last = answersBody.answers[answersBody.answers.length - 1];
    expect(last.answers).toEqual([]);
    expect(last.custom).toBe('用 HTML');

    await page!.screenshot({
      path: 'tests/electron/screenshots/question-answer-done.png',
      fullPage: true,
    });
  });
});
