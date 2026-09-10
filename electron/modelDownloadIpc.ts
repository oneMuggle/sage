/**
 * 嵌入模型下载 IPC (B2, P11)
 *
 * 把 bge-small-zh ONNX 模型（model.onnx ~90MB + tokenizer.json）下载到
 * userData/models/<dirName>/。单文件直下（不经 zip 解压），SHA-256 校验，
 * .part 临时文件 + rename，失败/取消即清理不留残留。
 *
 * channels:
 *   models:embedder:download  → { baseUrl, dirName, files: [{name, sha256}] }
 *   models:embedder:cancel    → dirName
 *   models:embedder:progress  → {dirName, stage, file?, bytes?, error?} (事件)
 */
import { createHash } from 'crypto';
import { createReadStream, createWriteStream, existsSync, mkdirSync, renameSync, statSync, unlinkSync } from 'fs';
import { join } from 'path';
import type { IpcMain } from 'electron';
import type { BrowserWindow } from 'electron';

import { logger } from './logger';
import { fetchCompat } from './fetchCompat';

interface EmbedderFile {
  name: string;
  sha256: string;
}

interface DownloadRequest {
  baseUrl: string;
  dirName: string;
  files: EmbedderFile[];
}

interface ActiveDownload {
  cancelled: boolean;
}

const active = new Map<string, ActiveDownload>();

async function sha256File(path: string): Promise<string> {
  const hash = createHash('sha256');
  const stream = createReadStream(path);
  for await (const chunk of stream) {
    hash.update(chunk as Buffer);
  }
  return hash.digest('hex');
}

async function downloadToFile(
  url: string,
  destPath: string,
  download: ActiveDownload,
): Promise<number> {
  const res = await fetchCompat(url);
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status} for ${url}`);
  }

  const ws = createWriteStream(destPath);
  let bytes = 0;
  try {
    for await (const chunk of res.body) {
      if (download.cancelled) throw new Error('cancelled');
      const buf = chunk as Buffer;
      bytes += buf.length;
      ws.write(buf);
    }
    ws.end();
  } catch (err) {
    ws.destroy();
    throw err;
  }
  await new Promise<void>((resolve, reject) => {
    ws.on('error', reject);
    ws.on('close', () => resolve());
  });
  return bytes;
}

async function downloadVerified(
  baseUrl: string,
  dirName: string,
  file: EmbedderFile,
  modelsBaseDir: string,
  download: ActiveDownload,
): Promise<number> {
  const url = `${baseUrl.replace(/\/$/, '')}/${file.name}`;
  const targetDir = join(modelsBaseDir, dirName);
  const tmpPath = join(targetDir, `${file.name}.part`);
  const finalPath = join(targetDir, file.name);

  await downloadToFile(url, tmpPath, download);

  const actual = await sha256File(tmpPath);
  if (actual !== file.sha256.toLowerCase()) {
    unlinkSync(tmpPath);
    throw new Error(
      `sha256 mismatch for ${file.name}: got ${actual}, expected ${file.sha256}`,
    );
  }

  if (existsSync(finalPath)) unlinkSync(finalPath);
  renameSync(tmpPath, finalPath);
  return statSync(finalPath).size;
}

export function registerModelDownloadIpc(
  ipcMain: IpcMain,
  opts: {
    modelsBaseDir: () => string;
    getWindow: () => BrowserWindow | null;
  },
): void {
  ipcMain.handle('models:embedder:cancel', (_evt, dirName: string) => {
    const entry = active.get(String(dirName));
    if (entry) entry.cancelled = true;
    return { ok: true };
  });

  ipcMain.handle(
    'models:embedder:download',
    async (_evt, payload: DownloadRequest) => {
      const dirName = String(payload?.dirName ?? '');
      if (!dirName || /[\\/]/.test(dirName) || dirName.includes('..')) {
        return { ok: false, error: 'invalid dirName' };
      }
      const files = Array.isArray(payload?.files) ? payload.files : [];
      if (files.length === 0) return { ok: false, error: 'no files' };
      if (active.has(dirName)) return { ok: false, error: 'already-running' };

      const download: ActiveDownload = { cancelled: false };
      active.set(dirName, download);
      const win: BrowserWindow | null = opts.getWindow();

      const emit = (extra: Record<string, unknown>): void => {
        if (win && !win.isDestroyed()) {
          win.webContents.send('models:embedder:progress', { dirName, ...extra });
        }
      };

      try {
        const targetDir = join(opts.modelsBaseDir(), dirName);
        mkdirSync(targetDir, { recursive: true });
        emit({ stage: 'start' });

        let totalBytes = 0;
        for (const file of files) {
          if (download.cancelled) throw new Error('cancelled');
          const bytes = await downloadVerified(
            payload.baseUrl,
            dirName,
            file,
            opts.modelsBaseDir(),
            download,
          );
          totalBytes += bytes;
          emit({ file: file.name, stage: 'done', bytes });
        }

        emit({ stage: 'complete', totalBytes });
        logger.info('model download: complete', { dirName, totalBytes });
        return { ok: true, totalBytes };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error('model download failed', { dirName, err: message });
        emit({ stage: 'error', error: message });
        return { ok: false, error: message };
      }
    },
  );
}
