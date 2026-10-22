// electron/loadFileRetry.ts

/**
 * Retry wrapper for Electron's BrowserWindow.loadFile().
 *
 * Background (2026-10-22): Electron smoke test on GitHub-hosted Windows
 * runners (windows-2025-vs2026) intermittently fails with
 * `[Error] ERR_FAILED (-2) loading 'file:///...dist/index.html'` during
 * cold start. The same commit sometimes passes, sometimes fails; the
 * failure is at Chromium's net layer before renderer paint, and is
 * attributed to transient runner-side sandbox / AV interference with
 * the freshly-spawned renderer process.
 *
 * This helper retries loadFile up to `maxAttempts` times with a short
 * delay between attempts, turning a flaky single-shot failure into a
 * resilient multi-shot load. It is intentionally decoupled from Electron
 * (the loader is injected) so the retry logic can be unit-tested without
 * mocking the electron module.
 *
 * Usage in electron/main.ts:
 *   import { loadFileWithRetry, DEFAULT_MAX_LOAD_FILE_ATTEMPTS } from './loadFileRetry';
 *   await loadFileWithRetry((p) => win.loadFile(p), indexHtml);
 */

/** Default delay between loadFile attempts (ms). */
export const LOAD_FILE_RETRY_DELAY_MS = 2_000;

/** Default maximum attempts (initial + retries). 2 = one retry. */
export const DEFAULT_MAX_LOAD_FILE_ATTEMPTS = 2;

/**
 * Retry an async loader up to `maxAttempts` times. Returns when the
 * loader resolves; throws the last rejection if every attempt fails.
 *
 * Kept pure (no electron / logger imports) so unit tests can exercise
 * the retry state machine with a plain injected function.
 *
 * @param loader   Async function that performs the load. Receives the
 *                 caller-supplied `arg` on each attempt.
 * @param arg      Argument forwarded to the loader (e.g. file path).
 * @param maxAttempts Total attempts allowed (must be >= 1). Defaults to
 *                    DEFAULT_MAX_LOAD_FILE_ATTEMPTS.
 */
export async function loadFileWithRetry<TArg, TResult>(
  loader: (arg: TArg) => Promise<TResult>,
  arg: TArg,
  maxAttempts: number = DEFAULT_MAX_LOAD_FILE_ATTEMPTS,
): Promise<TResult> {
  if (maxAttempts < 1) {
    throw new RangeError(
      `loadFileWithRetry: maxAttempts must be >= 1, got ${maxAttempts}`,
    );
  }
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await loader(arg);
    } catch (err) {
      lastError = err;
      if (attempt < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, LOAD_FILE_RETRY_DELAY_MS));
      }
    }
  }
  throw lastError;
}
