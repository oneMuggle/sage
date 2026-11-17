/**
 * Offline component package IPC.
 *
 * The heavy lifting lives in `backend.cli.components` (signature verification,
 * safe extraction, install metadata). This module only resolves the bundled or
 * conda Python command, streams JSON progress lines to the renderer, and
 * exposes a small typed bridge.
 */
import { spawn, type ChildProcess } from 'child_process';
import { existsSync } from 'fs';
import { isAbsolute } from 'path';
import { createInterface } from 'readline';
import type { BrowserWindow, IpcMain } from 'electron';
import { dialog } from 'electron';

import { resolveModuleLaunchCommand, type ResolveOpts } from './backendLauncher';
import { logger } from './logger';

export interface ComponentProgressEvent {
  event: 'progress';
  phase: string;
  message?: string;
  done?: number;
  total?: number;
}

export interface ComponentResultEvent {
  event: 'result';
  ok: boolean;
  code?: string;
  error?: string;
  installed?: InstalledComponentSummary[];
  discovered?: ComponentPackageSummary[];
  packages?: ComponentPackageSummary[];
  component?: InstalledComponentSummary;
  componentId?: string;
}

export type ComponentCliEvent = ComponentProgressEvent | ComponentResultEvent;

export interface InstalledComponentSummary {
  id: string;
  name: string;
  version: string;
  target: string;
  installedAt: string;
  fileCount: number;
  totalBytes: number;
  sourcePackage: string;
  signatureVerified: boolean;
}

export interface ComponentPackageSummary {
  path: string;
  id: string;
  name: string;
  version: string;
  size: number;
  error?: string;
}

export interface ComponentsListResult {
  ok: boolean;
  installed: InstalledComponentSummary[];
  discovered: ComponentPackageSummary[];
  error?: string;
}

export interface ComponentsScanResult {
  ok: boolean;
  discovered: ComponentPackageSummary[];
  error?: string;
}

export interface ComponentActionResult {
  ok: boolean;
  component?: InstalledComponentSummary;
  componentId?: string;
  error?: string;
  code?: string;
}

export interface ComponentsIpcOptions {
  getWindow: () => BrowserWindow | null;
  resolveOpts: () => ResolveOpts;
  /** `SAGE_BUILD_BRANCH` value so a win7 build rejects main component packs. */
  branch?: string;
}

type SpawnFn = typeof spawn;

export interface RunComponentCliOptions {
  resolveOpts: () => ResolveOpts;
  onEvent?: (event: ComponentCliEvent) => void;
  timeoutMs?: number;
  branch?: string;
  /** Test seam; production uses the real child_process.spawn. */
  spawnFn?: SpawnFn;
}

const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000;
const LIST_TIMEOUT_MS = 60 * 1000;
const ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;

export function parseComponentEvents(output: string): ComponentCliEvent[] {
  const events: ComponentCliEvent[] = [];
  for (const line of output.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('{')) continue;
    try {
      const value = JSON.parse(trimmed) as unknown;
      const event = (value as { event?: unknown } | null)?.event;
      if (typeof event === 'string') events.push(value as ComponentCliEvent);
    } catch {
      // Non-JSON stderr lines are ignored; they are logged separately.
    }
  }
  return events;
}

export function validatePackagePath(path: string): boolean {
  if (typeof path !== 'string' || path.length === 0) return false;
  if (!/\.sagepkg$/i.test(path)) return false;
  return isAbsolute(path) || /^[A-Za-z]:[\\/]/.test(path);
}

export function isValidComponentId(componentId: string): boolean {
  return typeof componentId === 'string' && ID_RE.test(componentId);
}

export function runComponentCli(
  argv: string[],
  opts: RunComponentCliOptions,
): Promise<{ result: ComponentResultEvent | null; stderr: string }> {
  const snapshot = opts.resolveOpts();
  const plan = resolveModuleLaunchCommand(snapshot, 'backend.cli.components', argv);
  if (!plan) {
    return Promise.resolve({
      result: {
        event: 'result',
        ok: false,
        code: 'broken_installer',
        error: '安装包不完整，无法运行组件命令',
      },
      stderr: '',
    });
  }

  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (typeof value === 'string') env[key] = value;
  }
  Object.assign(env, plan.env);
  if (snapshot.isPackaged && snapshot.resourcesPath) {
    env.SAGE_IS_PACKAGED = '1';
    env.SAGE_RESOURCES_DIR = snapshot.resourcesPath;
  }
  if (opts.branch) env.SAGE_COMPONENT_BRANCH = opts.branch;

  logger.info('components: cli start', { args: plan.args.join(' ') });
  const spawnFn = opts.spawnFn ?? spawn;
  return new Promise((resolve) => {
    let child: ChildProcess;
    try {
      child = spawnFn(plan.command, plan.args, {
        cwd: plan.cwd,
        env,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (err) {
      resolve({
        result: {
          event: 'result',
          ok: false,
          code: 'spawn_failed',
          error: err instanceof Error ? err.message : String(err),
        },
        stderr: '',
      });
      return;
    }

    if (!child.stdout || !child.stderr) {
      resolve({
        result: {
          event: 'result',
          ok: false,
          code: 'spawn_failed',
          error: '组件进程缺少输出管道',
        },
        stderr: '',
      });
      return;
    }

    let stderr = '';
    let result: ComponentResultEvent | null = null;
    let settled = false;
    const done = (finalResult: ComponentResultEvent | null): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ result: finalResult, stderr });
    };

    const reader = createInterface({ input: child.stdout });
    reader.on('line', (line) => {
      for (const event of parseComponentEvents(line)) {
        if (event.event === 'progress') {
          opts.onEvent?.(event);
        } else if (event.event === 'result') {
          result = event;
        }
      }
    });

    child.stderr.on('data', (chunk: Buffer | string) => {
      stderr += String(chunk);
      if (stderr.length > 8192) stderr = stderr.slice(-8192);
    });

    const timer = setTimeout(() => {
      child.kill();
      done({
        event: 'result',
        ok: false,
        code: 'timeout',
        error: '组件操作超时，请稍后重试',
      });
    }, opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
    timer.unref?.();

    child.on('error', (err) => {
      done({
        event: 'result',
        ok: false,
        code: 'spawn_failed',
        error: err.message,
      });
    });

    child.on('close', (code) => {
      reader.close();
      if (!result) {
        done({
          event: 'result',
          ok: false,
          code: 'cli_failed',
          error: stderr.trim() || `组件命令退出码 ${String(code)}`,
        });
        return;
      }
      if (!result.ok) {
        logger.warn('components: cli failed', {
          code: result.code ?? '',
          error: result.error ?? '',
        });
      }
      done(result);
    });
  });
}

function asListResult(result: ComponentResultEvent | null): ComponentsListResult {
  if (!result) {
    return { ok: false, installed: [], discovered: [], error: '组件命令无返回结果' };
  }
  return {
    ok: result.ok,
    installed: Array.isArray(result.installed) ? result.installed : [],
    discovered: Array.isArray(result.discovered) ? result.discovered : [],
    ...(result.error ? { error: result.error } : {}),
  };
}

function asScanResult(result: ComponentResultEvent | null): ComponentsScanResult {
  if (!result) {
    return { ok: false, discovered: [], error: '组件命令无返回结果' };
  }
  return {
    ok: result.ok,
    discovered: Array.isArray(result.packages) ? result.packages : [],
    ...(result.error ? { error: result.error } : {}),
  };
}

function asActionResult(result: ComponentResultEvent | null): ComponentActionResult {
  if (!result) {
    return { ok: false, error: '组件命令无返回结果' };
  }
  return {
    ok: result.ok,
    ...(result.component ? { component: result.component } : {}),
    ...(result.componentId ? { componentId: result.componentId } : {}),
    ...(result.error ? { error: result.error } : {}),
    ...(result.code ? { code: result.code } : {}),
  };
}

export function registerComponentsIpc(ipcMain: IpcMain, opts: ComponentsIpcOptions): void {
  const emitProgress =
    (op: string) =>
    (event: ComponentCliEvent): void => {
      if (event.event !== 'progress') return;
      const win = opts.getWindow();
      if (win && !win.isDestroyed()) {
        win.webContents.send('sage:event:components:progress', { op, ...event });
      }
    };

  ipcMain.handle('components:list', async () => {
    const { result } = await runComponentCli(['list', '--json'], {
      resolveOpts: opts.resolveOpts,
      branch: opts.branch,
      timeoutMs: LIST_TIMEOUT_MS,
    });
    return asListResult(result);
  });

  ipcMain.handle('components:scan', async () => {
    const { result } = await runComponentCli(['scan', '--json'], {
      resolveOpts: opts.resolveOpts,
      branch: opts.branch,
      timeoutMs: LIST_TIMEOUT_MS,
    });
    return asScanResult(result);
  });

  const importPath = async (packagePath: string): Promise<ComponentActionResult> => {
    if (!validatePackagePath(packagePath) || !existsSync(packagePath)) {
      return { ok: false, error: '请选择有效的 .sagepkg 组件包', code: 'invalid_package' };
    }
    const { result } = await runComponentCli(['import', packagePath, '--json', '--yes'], {
      resolveOpts: opts.resolveOpts,
      branch: opts.branch,
      onEvent: emitProgress('import'),
    });
    return asActionResult(result);
  };

  ipcMain.handle('components:pick-and-import', async () => {
    const win = opts.getWindow();
    const result = await dialog.showOpenDialog({
      ...(win && !win.isDestroyed() ? { browserWindow: win } : {}),
      title: '选择 Sage 离线组件包',
      filters: [{ name: 'Sage component package', extensions: ['sagepkg'] }],
      properties: ['openFile'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { ok: false, error: 'cancelled', code: 'cancelled' };
    }
    return importPath(result.filePaths[0]);
  });

  ipcMain.handle('components:import-path', (_event, packagePath: string) =>
    importPath(String(packagePath ?? '')),
  );

  ipcMain.handle('components:remove', async (_event, componentId: string) => {
    const id = String(componentId ?? '');
    if (!isValidComponentId(id)) {
      return { ok: false, error: '组件 id 格式无效', code: 'invalid_component_id' };
    }
    const { result } = await runComponentCli(['remove', id, '--json', '--yes'], {
      resolveOpts: opts.resolveOpts,
      branch: opts.branch,
      onEvent: emitProgress('remove'),
    });
    return asActionResult(result);
  });
}
