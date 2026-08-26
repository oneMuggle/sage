/**
 * Helper: launch the Python stub backend (tests/electron/stub_backend.py)
 * as a child process and resolve once it has bound a port and printed
 * its STUB_URL handshake.
 *
 * Usage:
 *   const stub = new StubBackend();
 *   await stub.start();
 *   // stub.url, stub.port, stub.process available
 *   ...
 *   stub.stop();
 *
 * Notes (deviations from the brief):
 *   - ESM __dirname shim: `package.json` has `"type": "module"`, so a
 *     bare `__dirname` reference inside Playwright's ESM-loaded helper
 *     crashes at module evaluation. We mirror the established
 *     `fileURLToPath(import.meta.url)` pattern used by
 *     tests/electron/tiers/stub/smoke/office.spec.ts and
 *     tests/electron/tiers/live/deep/skillmd.spec.ts.
 *   - Positional port arg: stub_backend.py uses
 *     `int(sys.argv[1]) if len(sys.argv) > 1 else 0`, NOT
 *     `--port=0`. Spawning with `--port=0` would crash with
 *     `ValueError: invalid literal for int() with base 10: '--port=0'`.
 *   - Handshake: stub_backend.py prints `STUB_URL=http://127.0.0.1:<port>`
 *     to stdout (added by Task 9). We parse that line, NOT the older
 *     "Stub backend running at ..." format.
 *   - Python interpreter resolution: stub_backend.py is pure stdlib
 *     (http.server + sqlite3 + json) and does NOT require the conda
 *     `sage-backend` env. To stay portable across local dev (conda) and
 *     CI runners (system Python only), `resolvePythonPath()` walks:
 *       1. `SAGE_PYTHON_PATH` env override (explicit, for exotic setups)
 *       2. Common Linux system paths (`/usr/bin/python3`, `/usr/local/bin/python3`)
 *       3. Local dev conda fallback (`/home/fz/anaconda3/envs/sage-backend/bin/python`)
 *       4. Bare `python3` (let spawn resolve via PATH)
 *     CI failures from `ENOENT` on the conda path motivated this fix
 *     (see .superpowers/sdd/2026-08-25-electron-e2e-automation/progress.md
 *     "CI RED — stub-smoke spawn python ENOENT").
 */
import { spawn, ChildProcessByStdio } from 'node:child_process';
import { Readable } from 'node:stream';
import { existsSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const _filename = typeof __filename !== 'undefined' ? __filename : fileURLToPath(import.meta.url);
const _dirname = typeof __dirname !== 'undefined' ? __dirname : path.dirname(_filename);

/**
 * Resolve a usable Python interpreter path for `stub_backend.py`.
 * Pure stdlib — does NOT need the conda `sage-backend` env.
 *
 * Order:
 *   1. `SAGE_PYTHON_PATH` env var (explicit override)
 *   2. `/usr/bin/python3` (standard Ubuntu/Debian path, CI runners)
 *   3. `/usr/local/bin/python3` (Homebrew / macOS Intel path)
 *   4. Local conda fallback `/home/fz/anaconda3/envs/sage-backend/bin/python`
 *      (legacy default — local dev machines with conda installed)
 *   5. Bare `python3` (last resort: rely on PATH lookup at spawn time)
 *
 * @returns absolute path or executable name accepted by Node spawn()
 */
export function resolvePythonPath(): string {
  const envOverride = process.env.SAGE_PYTHON_PATH;
  if (envOverride && existsSync(envOverride)) {
    return envOverride;
  }
  const candidates = [
    '/usr/bin/python3',
    '/usr/local/bin/python3',
    '/home/fz/anaconda3/envs/sage-backend/bin/python',
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  // Final fallback: let spawn resolve via PATH. CI runners almost
  // always have `python3` on PATH even if /usr/bin/python3 doesn't exist.
  return 'python3';
}

export class StubBackend {
  process: ChildProcessByStdio<null, Readable, Readable> | null = null;
  url = '';
  port = 0;

  constructor(private pythonPath: string = resolvePythonPath()) {}

  async start(): Promise<void> {
    const stubScript = path.resolve(_dirname, '..', 'stub_backend.py');
    if (!existsSync(stubScript)) {
      throw new Error(`stub_backend.py not found at ${stubScript}`);
    }

    return new Promise((resolve, reject) => {
      // Positional port arg (see Notes above).
      this.process = spawn(this.pythonPath, [stubScript, '0'], {
        env: { ...process.env, SAGE_STUB_PORT: '0', PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      let buffer = '';
      const timer = setTimeout(() => {
        reject(new Error('stub backend startup timeout (10s)'));
      }, 10_000);

      this.process.stdout.on('data', (chunk) => {
        buffer += chunk.toString('utf-8');
        const match = buffer.match(/STUB_URL=(http:\/\/127\.0\.0\.1:\d+)/);
        if (match) {
          this.url = match[1];
          this.port = parseInt(this.url.split(':').pop()!, 10);
          clearTimeout(timer);
          resolve();
        }
      });

      this.process.stderr?.on('data', (chunk) => {
        process.stderr.write(`[stub] ${chunk}`);
      });

      this.process.on('error', (err) => {
        clearTimeout(timer);
        reject(err);
      });

      this.process.on('exit', (code) => {
        if (!this.url) {
          clearTimeout(timer);
          reject(new Error(`stub backend exited before handshake (code=${code})`));
        }
      });
    });
  }

  stop(): void {
    if (this.process) {
      this.process.kill('SIGTERM');
      this.process = null;
    }
  }
}
