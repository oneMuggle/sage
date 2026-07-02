// electron/logRotate.ts
import { readdirSync, statSync, unlinkSync, renameSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { getLogDir, getCurrentLogFile } from './logPaths';
import { logger } from './logger';

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB
const NDJSON_PATTERN = /^sage-\d{4}-\d{2}-\d{2}\.ndjson(\.\d+)?$/;

export function cleanupOlderThan(days: number): void {
  let dir: string;
  try {
    dir = getLogDir();
  } catch (err) {
    logger.warn('logRotate: cannot resolve log dir', { err: String(err) });
    return;
  }
  if (!existsSync(dir)) return;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch (err) {
    logger.warn('logRotate: readdir failed', { dir, err: String(err) });
    return;
  }
  for (const name of entries) {
    if (!NDJSON_PATTERN.test(name)) continue;
    const full = join(dir, name);
    try {
      const st = statSync(full);
      if (st.mtimeMs < cutoff) {
        unlinkSync(full);
        logger.info('logRotate: cleaned up old log', {
          file: name,
          ageDays: Math.round((Date.now() - st.mtimeMs) / 86_400_000),
        });
      }
    } catch (err) {
      logger.warn('logRotate: stat/unlink failed', { file: name, err: String(err) });
    }
  }
}

export function rotateIfOversized(): boolean {
  const file = getCurrentLogFile();
  if (!existsSync(file)) return false;
  try {
    const st = statSync(file);
    if (st.size < MAX_FILE_SIZE_BYTES) return false;
    const rotated = `${file}.1`;
    if (existsSync(rotated)) unlinkSync(rotated);
    renameSync(file, rotated);
    logger.info('logRotate: rotated oversized log', {
      from: file,
      to: rotated,
      sizeMB: Math.round(st.size / 1024 / 1024),
    });
    return true;
  } catch (err) {
    logger.warn('logRotate: rotation failed', { err: String(err) });
    return false;
  }
}