import { BrowserWindow } from 'electron';

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
}

const CHECK_NAMES = ['mainWindow', 'backend', 'database', 'ipc'] as const;

export class LauncherHealthChecker {
  private getWindow: () => BrowserWindow | null;
  private backendUrl: string;
  private ipcTimeout: number;

  constructor(options: HealthCheckerOptions) {
    this.getWindow = options.getWindow;
    this.backendUrl = options.backendUrl ?? 'http://127.0.0.1:8765';
    this.ipcTimeout = options.ipcTimeout ?? 5000;
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
    const timeout = 3000;
    const pollInterval = 100;
    const start = Date.now();

    while (Date.now() - start < timeout) {
      const win = this.getWindow();
      if (win && !win.isDestroyed() && win.isVisible()) {
        return;
      }
      await this.sleep(pollInterval);
    }

    throw new Error('Main window not visible within 3 seconds');
  }

  private async checkPythonBackendHealthy(): Promise<void> {
    const maxRetries = 10;
    const retryInterval = 1000;
    const requestTimeout = 2000;

    for (let i = 0; i < maxRetries; i++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), requestTimeout);

        const response = await fetch(`${this.backendUrl}/health`, {
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (response.ok) {
          return;
        }
      } catch {
        // Continue retrying
      }

      if (i < maxRetries - 1) {
        await this.sleep(retryInterval);
      }
    }

    throw new Error('Python backend failed to become healthy after 10 retries');
  }

  private async checkDatabaseAccessible(): Promise<void> {
    // Stub: will be implemented when vector DB integration is added
    return;
  }

  private async checkCoreIpcResponsive(): Promise<void> {
    // Stub: will be implemented in Task 9 when IPC handlers are defined
    void this.ipcTimeout;
    return;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
