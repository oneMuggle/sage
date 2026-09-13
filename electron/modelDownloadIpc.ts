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
 *
 * P5 (2026-09-14): 进度事件通道补 `sage:event:` 前缀 —— preload 的 listen
 * shim 只在 `sage:event:<event>` 上注册（与 #733 修复的 backend:* 同族
 * 问题），裸通道的进度事件永远到不了渲染端。
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
  baseUrl?: string;
  dirName?: string;
  files?: EmbedderFile[];
}

/**
 * P8 (2026-09-14): bge-small-zh-v1.5 ONNX 产物清单（Xenova 转换版，
 * huggingface resolve 端点）。sha256 提取自 2026-09-14 实际下载产物：
 *   tokenizer.json  439,125 B
 *   onnx/model.onnx 94,851,877 B
 * dirName 与 backend/memory/embedder_factory.py DEFAULT_ONNX_MODEL_DIR_NAME
 * 一致（OnnxEmbedder 期望模型目录下平铺 model.onnx + tokenizer.json）。
 * `onnx/` 子路径仅用于远端 URL；落盘取 basename（见 downloadVerified）。
 */
export const EMBEDDER_MODEL_MANIFEST = {
  dirName: 'bge-small-zh-v1.5',
  baseUrl: 'https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/',
  files: [
    { name: 'tokenizer.json', sha256: '48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26' },
    { name: 'onnx/model.onnx', sha256: '69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a' },
  ],
} as const;

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
  // P8: 落盘取 basename —— 清单里的 name 可含远端子路径（onnx/model.onnx），
  // 但 OnnxEmbedder 期望模型目录平铺（model.onnx / tokenizer.json）。
  const saveName = file.name.split('/').pop() ?? file.name;
  const tmpPath = join(targetDir, `${saveName}.part`);
  const finalPath = join(targetDir, saveName);

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
    async (_evt, payload: DownloadRequest = {}) => {
      // P8: payload 缺省字段回落到内置清单（渲染端只需无参调用）
      const manifest = EMBEDDER_MODEL_MANIFEST;
      const dirName = String(payload?.dirName ?? manifest.dirName);
      if (!dirName || /[\\/]/.test(dirName) || dirName.includes('..')) {
        return { ok: false, error: 'invalid dirName' };
      }
      const files: EmbedderFile[] = Array.isArray(payload?.files)
        ? payload.files
        : [...manifest.files];
      const baseUrl = String(payload?.baseUrl ?? manifest.baseUrl);
      if (files.length === 0) return { ok: false, error: 'no files' };
      if (active.has(dirName)) return { ok: false, error: 'already-running' };

      const download: ActiveDownload = { cancelled: false };
      active.set(dirName, download);
      const win: BrowserWindow | null = opts.getWindow();

      const emit = (extra: Record<string, unknown>): void => {
        if (win && !win.isDestroyed()) {
          win.webContents.send('sage:event:models:embedder:progress', { dirName, ...extra });
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
            baseUrl,
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
      } finally {
        // P8: 失败/取消后清出进行中表 —— 否则同 dirName 永远 already-running，
        // 只能重启应用才能重试。
        active.delete(dirName);
      }
    },
  );
}
