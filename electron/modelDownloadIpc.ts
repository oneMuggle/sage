/**
 * 本地模型下载 IPC。
 *
 * - 嵌入模型（B2/P8）：bge-small-zh ONNX → userData/models/bge-small-zh-v1.5
 * - 本地 OCR（2026-10-31）：RapidOCR PP-OCRv6 tiny det/rec →
 *   userData/models/rapidocr/{det.onnx,rec.onnx}
 *
 * 单文件直下（不经 zip），SHA-256 校验，.part + rename，失败/取消清理。
 * 进度事件统一走 `sage:event:<prefix>`。
 */
import { createHash } from 'crypto';
import {
  createReadStream,
  createWriteStream,
  existsSync,
  mkdirSync,
  renameSync,
  rmSync,
  statSync,
  unlinkSync,
} from 'fs';
import { join } from 'path';
import type { IpcMain } from 'electron';
import type { BrowserWindow } from 'electron';

import { logger } from './logger';
import { fetchCompat } from './fetchCompat';

interface ModelFile {
  name: string;
  sha256: string;
  /** 落盘文件名（默认取 name 的 basename） */
  saveAs?: string;
}

interface ModelManifest {
  dirName: string;
  baseUrl: string;
  files: readonly ModelFile[];
}

interface DownloadRequest {
  baseUrl?: string;
  dirName?: string;
  files?: ModelFile[];
}

/**
 * P8 (2026-09-14): bge-small-zh-v1.5 ONNX 产物清单（Xenova 转换版）。
 * sha256 提取自 2026-09-14 实际下载产物。
 * dirName 与 backend/memory/embedder_factory.py DEFAULT_ONNX_MODEL_DIR_NAME 一致。
 */
export const EMBEDDER_MODEL_MANIFEST: ModelManifest = {
  dirName: 'bge-small-zh-v1.5',
  baseUrl: 'https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/',
  files: [
    {
      name: 'tokenizer.json',
      sha256: '48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26',
    },
    {
      name: 'onnx/model.onnx',
      sha256: '69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a',
    },
  ],
};

/**
 * 2026-10-31: RapidOCR PP-OCRv6 tiny（det/rec）清单。
 * 模型来源 ModelScope RapidAI/RapidOCR v3.10.0；sha256 为实际下载产物。
 * 落盘名固定 det.onnx / rec.onnx，匹配 backend/services/ocr/engines/rapidocr.py。
 * 体积约 6MB（det 1.8MB + rec 4.3MB），支持中文/英文/繁体。
 */
export const OCR_MODEL_MANIFEST: ModelManifest = {
  dirName: 'rapidocr',
  baseUrl:
    'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/',
  files: [
    {
      name: 'det/PP-OCRv6_det_tiny.onnx',
      saveAs: 'det.onnx',
      sha256: 'f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5',
    },
    {
      name: 'rec/PP-OCRv6_rec_tiny.onnx',
      saveAs: 'rec.onnx',
      sha256: 'e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b',
    },
  ],
};

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
      // 写缓冲满时等待 drain，保持背压（94MB 模型在慢盘上不整文件进内存）。
      if (!ws.write(buf)) {
        await new Promise<void>((resolve) => {
          ws.once('drain', resolve);
        });
      }
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
  file: ModelFile,
  modelsBaseDir: string,
  download: ActiveDownload,
): Promise<number> {
  const url = `${baseUrl.replace(/\/$/, '')}/${file.name}`;
  const targetDir = join(modelsBaseDir, dirName);
  const saveName = file.saveAs ?? file.name.split('/').pop() ?? file.name;
  const tmpPath = join(targetDir, `${saveName}.part`);
  const finalPath = join(targetDir, saveName);

  try {
    await downloadToFile(url, tmpPath, download);
  } catch (err) {
    try {
      unlinkSync(tmpPath);
    } catch {
      // 文件可能尚未创建
    }
    throw err;
  }

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

function registerDownloadHandler(
  ipcMain: IpcMain,
  opts: {
    modelsBaseDir: () => string;
    getWindow: () => BrowserWindow | null;
  },
  channel: string,
  cancelChannel: string,
  eventName: string,
  manifest: ModelManifest,
): void {
  ipcMain.handle(cancelChannel, (_evt, dirName?: string) => {
    const key = `${channel}:${String(dirName ?? manifest.dirName)}`;
    const entry = active.get(key);
    if (entry) entry.cancelled = true;
    return { ok: true };
  });

  ipcMain.handle(channel, async (_evt, payload: DownloadRequest = {}) => {
    const dirName = String(payload?.dirName ?? manifest.dirName);
    if (!dirName || /[\\/]/.test(dirName) || dirName.includes('..')) {
      return { ok: false, error: 'invalid dirName' };
    }
    const files: ModelFile[] = Array.isArray(payload?.files)
      ? payload.files
      : [...manifest.files];
    const baseUrl = String(payload?.baseUrl ?? manifest.baseUrl);
    if (files.length === 0) return { ok: false, error: 'no files' };
    const key = `${channel}:${dirName}`;
    if (active.has(key)) return { ok: false, error: 'already-running' };

    const download: ActiveDownload = { cancelled: false };
    active.set(key, download);
    const win: BrowserWindow | null = opts.getWindow();

    const emit = (extra: Record<string, unknown>): void => {
      if (win && !win.isDestroyed()) {
        win.webContents.send(`sage:event:${eventName}`, { dirName, ...extra });
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
      active.delete(key);
    }
  });
}

export function registerModelDownloadIpc(
  ipcMain: IpcMain,
  opts: {
    modelsBaseDir: () => string;
    getWindow: () => BrowserWindow | null;
  },
): void {
  registerDownloadHandler(
    ipcMain,
    opts,
    'models:embedder:download',
    'models:embedder:cancel',
    'models:embedder:progress',
    EMBEDDER_MODEL_MANIFEST,
  );
  registerDownloadHandler(
    ipcMain,
    opts,
    'models:ocr:download',
    'models:ocr:cancel',
    'models:ocr:progress',
    OCR_MODEL_MANIFEST,
  );

  // 恢复 RapidOCR 包内默认模型：只删除受管的 models/rapidocr 目录。
  ipcMain.handle('models:ocr:reset', () => {
    const targetDir = join(opts.modelsBaseDir(), OCR_MODEL_MANIFEST.dirName);
    try {
      rmSync(targetDir, { recursive: true, force: true });
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
  });
}
