/**
 * T11 (2026-09-12): Shared diagnostic export logic.
 *
 * Extracted to its own module so both the IPC handler in main.ts and the
 * tray menu in tray.ts can call it without creating a circular import
 * between those two files.
 *
 * main.ts calls `initDiagnosticExport()` once during app startup (after
 * the backend URL and auth token are known) to inject dependencies.
 * Both consumers then call `runDiagnosticExport()`.
 */
import { app, dialog, shell } from 'electron';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import fetch from 'node-fetch';

import { logger } from './logger';

export interface DiagnosticExportOpts {
  includePrompts: boolean;
  includeHostname: boolean;
}

export type DiagnosticExportResult =
  | { ok: true; path: string }
  | { ok: false; code: string; error: string };

export interface DiagnosticPreviewResult {
  count: number;
  oldestTs: string | null;
  newestTs: string | null;
  sampleUrls: string[];
  version: string;
}

interface DiagnosticDeps {
  backendUrl: string;
  getAuthToken: () => string | null;
}

let deps: DiagnosticDeps | null = null;

/**
 * Called once from main.ts after the backend URL is resolved and the
 * auth token has been assigned. Safe to call multiple times (idempotent).
 */
export function initDiagnosticExport(d: DiagnosticDeps): void {
  deps = d;
}

function requireDeps(): DiagnosticDeps {
  if (!deps) {
    throw new Error('diagnostic export not initialized');
  }
  return deps;
}

export async function runDiagnosticPreview(): Promise<DiagnosticPreviewResult> {
  const d = requireDeps();
  const empty: DiagnosticPreviewResult = {
    count: 0,
    oldestTs: null,
    newestTs: null,
    sampleUrls: [],
    version: '1',
  };
  try {
    const resp = await fetch(`${d.backendUrl}/api/v1/diagnostic/preview`, {
      headers: { Authorization: `Bearer ${d.getAuthToken() ?? ''}` },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return (await resp.json()) as DiagnosticPreviewResult;
  } catch (err) {
    logger.warn('diagnostic.preview failed', { err: String(err) });
    return empty;
  }
}

export async function runDiagnosticExport(
  opts: DiagnosticExportOpts,
): Promise<DiagnosticExportResult> {
  const d = requireDeps();
  try {
    const url =
      `${d.backendUrl}/api/v1/diagnostic/export` +
      `?include_prompts=${opts.includePrompts}` +
      `&include_hostname=${opts.includeHostname}`;
    const resp = await fetch(url, {
      method: 'POST',
      headers: { Authorization: `Bearer ${d.getAuthToken() ?? ''}` },
    });
    if (!resp.ok) {
      const errText = await resp.text();
      return {
        ok: false,
        code: 'backend_error',
        error: `HTTP ${resp.status}: ${errText.slice(0, 200)}`,
      };
    }
    const buf = Buffer.from(await resp.arrayBuffer());

    const stamp = new Date()
      .toISOString()
      .replace(/[:.]/g, '-')
      .replace(/T/, '_')
      .slice(0, 19);
    const defaultName = `sage-diagnostic-${app.getVersion()}-${stamp}.zip`;
    const dl = await dialog.showSaveDialog({
      title: '导出诊断包',
      defaultPath: join(app.getPath('downloads'), defaultName),
      filters: [{ name: 'Zip', extensions: ['zip'] }],
    });
    if (dl.canceled || !dl.filePath) {
      return { ok: false, code: 'dialog_cancelled', error: '用户取消保存' };
    }
    try {
      await writeFile(dl.filePath, buf);
    } catch (err) {
      logger.error('diagnostic.export write failed', {
        err: String(err),
        path: dl.filePath,
      });
      return { ok: false, code: 'write_failed', error: String(err) };
    }
    shell.showItemInFolder(dl.filePath);
    return { ok: true, path: dl.filePath };
  } catch (err) {
    logger.error('diagnostic.export unexpected', { err: String(err) });
    return { ok: false, code: 'zip_generation_failed', error: String(err) };
  }
}
