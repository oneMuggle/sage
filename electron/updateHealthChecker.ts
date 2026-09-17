import { BrowserWindow } from 'electron';
import { fetchCompat } from './fetchCompat';

export interface HealthCheckDetail {
  name: string;
  passed: boolean;
  error?: string;
}

export interface HealthCheckResult {
  passed: boolean;
  details: HealthCheckDetail[];
}

interface HealthCheckerOptions {
  getWindow: () => BrowserWindow | null;
  backendUrl?: string;
  ipcTimeout?: number;
  getAuthToken?: () => string | null;
}

const CHECK_NAMES = ['mainWindow', 'backend', 'database', 'ipc'] as const;

export class LauncherHealthChecker {
  private getWindow: () => BrowserWindow | null;
  private backendUrl: string;
  private ipcTimeout: number;
  private getAuthToken: () => string | null;

  constructor(options: HealthCheckerOptions) {
    this.getWindow = options.getWindow;
    this.backendUrl = options.backendUrl ?? 'http://127.0.0.1:8765';
    this.ipcTimeout = options.ipcTimeout ?? 5000;
    this.getAuthToken = options.getAuthToken ?? (() => null);
  }

  async runPostStartupChecks(): Promise<HealthCheckResult> {
    const checks = [
      this.checkMainWindowLoaded(),
      this.checkPythonBackendHealthy(),
      this.checkDatabaseAccessible(),
      this.checkCoreIpcResponsive(),
    ];

    const results = await Promise.allSettled(checks);

    return {
      passed: results.every((r) => r.status === 'fulfilled'),
      details: results.map((r, i) => ({
        name: CHECK_NAMES[i],
        passed: r.status === 'fulfilled',
        error: r.status === 'rejected' ? (r.reason as Error)?.message : undefined,
      })),
    };
  }

  private async checkMainWindowLoaded(): Promise<void> {
    // Win7 with --disable-gpu uses software compositing which is slower.
    // Give it more time to avoid false-positive health check failures.
    const isWin7 =
      process.platform === 'win32' &&
      typeof process.getSystemVersion === 'function' &&
      process.getSystemVersion().startsWith('6.1');
    const timeout = isWin7 ? 15_000 : 3000;
    const timeoutSeconds = timeout / 1000;
    const pollInterval = 100;
    const start = Date.now();

    while (Date.now() - start < timeout) {
      const win = this.getWindow();
      if (win && !win.isDestroyed() && win.isVisible()) {
        return;
      }
      await this.sleep(pollInterval);
    }

    throw new Error(`Main window not visible within ${timeoutSeconds} seconds`);
  }

  private async checkPythonBackendHealthy(): Promise<void> {
    const maxRetries = 10;
    const retryInterval = 1000;
    const requestTimeout = 2000;

    for (let i = 0; i < maxRetries; i++) {
      try {
        await this.request('/health', requestTimeout, async () => undefined);
        return;
      } catch {
        // Continue retrying; each request releases its timer even on rejection.
      }

      if (i < maxRetries - 1) {
        await this.sleep(retryInterval);
      }
    }

    throw new Error('Python backend failed to become healthy after 10 retries');
  }

  private async checkDatabaseAccessible(): Promise<void> {
    // Read one session through the real repository, using the same local
    // capability as the main-process relay. A status-only /health is not DB proof.
    await this.request('/api/v1/sessions?limit=1&offset=0', this.ipcTimeout, async (response) => {
      const sessions: unknown = await response.json();
      if (!Array.isArray(sessions)) throw new Error('Invalid database probe response');
    });
  }

  private async checkCoreIpcResponsive(): Promise<void> {
    await this.checkMainWindowLoaded();
    const win = this.getWindow();
    if (!win || win.isDestroyed()) throw new Error('Renderer unavailable for IPC probe');
    // Real renderer -> preload -> main -> authenticated backend round trip.
    // No token is injected into the renderer and no mutating command is used.
    const result = await this.bounded(
      win.webContents.executeJavaScript(`(async () => {
        const api = window.electronAPI;
        if (!api || typeof api.invoke !== 'function') throw new Error('IPC bridge unavailable');
        const sessions = await api.invoke('list_sessions', { limit: 1, offset: 0 });
        return Array.isArray(sessions);
      })()`),
      this.ipcTimeout,
      'Core IPC probe timed out',
    );
    if (result !== true) throw new Error('Invalid core IPC probe response');
  }

  private async request(
    path: string,
    timeout: number,
    consume: (response: Awaited<ReturnType<typeof fetchCompat>>) => Promise<void>,
  ): Promise<void> {
    const controller = new AbortController();
    const token = this.getAuthToken();
    const operation = (async () => {
      const response = await fetchCompat(`${this.backendUrl}${path}`, {
        signal: controller.signal,
        headers: token ? { 'X-Sage-Local-Authorization': `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error(`Health probe HTTP ${response.status}`);
      await consume(response);
    })();
    try {
      await this.bounded(operation, timeout, 'Health probe request timed out');
    } finally {
      controller.abort();
    }
  }

  private async bounded<T>(operation: Promise<T>, timeout: number, message: string): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        operation,
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => reject(new Error(message)), timeout);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
