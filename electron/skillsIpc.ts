/**
 * Skills "load-new" IPC handlers (PR-C + T-4b).
 *
 * Five channels back the Skills page buttons:
 *
 *   skills:pick-files       → dialog.showOpenDialog (.md filter, multiSelections)
 *   skills:rescan           → POST /api/v1/skills/rescan
 *   skills:import           → POST /api/v1/skills/import (multipart, flat files)
 *   skills:pick-directory   → dialog.showOpenDialog (directory picker)
 *   skills:import-directory → POST /api/v1/skills/import-directory (multipart, relative paths)
 *
 * Design notes:
 *   - This is a *pure module* (no top-level side effects) so it can be
 *     unit-tested by injecting a register(channel, handler) function.
 *     Production callers pass `(c, h) => ipcMain.handle(c, h)`.
 *   - The pick-files handler uses dialog.showOpenDialog with a focused
 *     window if available so the dialog attaches to the Sage window
 *     (modal behavior on Windows/Linux).
 *   - import reads each file from disk and builds a Node 16-compatible multipart
 *     byte payload with an explicit boundary; it does not use global FormData/Blob.
 *     Backend expects field name "files" (multipart list).
 *   - import-directory walks the picked directory and emits multipart parts
 *     whose `filename` is the **posix relative path** (SKILL.md / scripts/x.py /
 *     assets/tpl.html). Backend expects field name "files" and a SKILL.md at
 *     the root; other entries must live under ALLOWED_RESOURCE_DIRS.
 *   - On HTTP error, we surface backend `detail.type` (and `detail.message`)
 *     as the Error message so the renderer can show a friendly toast
 *     that maps 1:1 to backend reason codes.
 */
import { lstatSync, readFileSync, readdirSync, realpathSync } from 'fs';
import { basename, join, resolve } from 'path';
import { randomBytes } from 'crypto';
import { BrowserWindow, dialog } from 'electron';
import { fetchCompat } from './fetchCompat';

/** Default backend base URL; PYTHON_BACKEND_URL overrides (used in CI). */
const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8765';
const MAX_IMPORT_FILE_SIZE_BYTES = 1024 * 1024;
const MAX_IMPORT_FILES = 100;
const MAX_IMPORT_TOTAL_SIZE_BYTES = 10 * 1024 * 1024;

// ── T-4b: directory import constants + helpers ────────────────────────────
// 与后端 backend/skills/skill_md/resources.py 的 ALLOWED_RESOURCE_DIRS 保持
// 同一白名单：只收集根层 SKILL.md + 白名单目录下文件，其他一律忽略。
const MAX_DIRECTORY_DEPTH = 8;
const ALLOWED_RESOURCE_DIRS: ReadonlySet<string> = new Set([
  'scripts',
  'references',
  'assets',
  'templates',
]);

const EXT_TO_CONTENT_TYPE: Readonly<Record<string, string>> = {
  md: 'text/markdown',
  markdown: 'text/markdown',
  py: 'text/x-python',
  js: 'text/javascript',
  ts: 'text/typescript',
  json: 'application/json',
  html: 'text/html',
  xml: 'application/xml',
  yaml: 'application/yaml',
  yml: 'application/yaml',
  txt: 'text/plain',
  sh: 'application/x-sh',
  bash: 'application/x-sh',
  ps1: 'application/x-powershell',
};

function contentTypeFor(filename: string): string {
  const ext = (filename.split('.').pop() ?? '').toLowerCase();
  return EXT_TO_CONTENT_TYPE[ext] ?? 'application/octet-stream';
}

interface CollectedDirectoryEntry {
  relPosix: string;
  absPath: string;
  size: number;
}

/**
 * 深度优先遍历目录，只收集根层 SKILL.md（大小写不敏感）+ 白名单资源目录
 * （scripts/ references/ assets/ templates/）下的文件。
 *
 * 防御：
 *   - 跳过符号链接（lstatSync 判定）
 *   - 跳过隐藏段（./开头 / 空段）
 *   - 深度上限 MAX_DIRECTORY_DEPTH
 */
function collectDirectoryEntries(dirRoot: string): CollectedDirectoryEntry[] {
  const entries: CollectedDirectoryEntry[] = [];
  const maxDepth = MAX_DIRECTORY_DEPTH;

  const isHiddenSegment = (segment: string): boolean => segment === '' || segment.startsWith('.');

  const walk = (abs: string, relParts: string[], depth: number): void => {
    if (depth > maxDepth) return;
    let dirEntries: string[];
    try {
      dirEntries = readdirSync(abs);
    } catch {
      return;
    }
    for (const entry of dirEntries) {
      if (isHiddenSegment(entry)) continue;
      const entryAbs = join(abs, entry);
      const nextParts = [...relParts, entry];
      if (nextParts.length > maxDepth) continue;

      let stat;
      try {
        stat = lstatSync(entryAbs);
      } catch {
        continue;
      }
      if (stat.isSymbolicLink()) continue;

      if (stat.isDirectory()) {
        if (depth === 0) {
          // 根层：只进入白名单资源目录
          if (ALLOWED_RESOURCE_DIRS.has(entry)) walk(entryAbs, nextParts, depth + 1);
        } else {
          // 资源目录内部：继续递归
          walk(entryAbs, nextParts, depth + 1);
        }
        continue;
      }

      if (!stat.isFile()) continue;

      if (depth === 0) {
        // 根层：只接受 SKILL.md
        if (entry.toLowerCase() === 'skill.md') {
          entries.push({ relPosix: 'SKILL.md', absPath: entryAbs, size: stat.size });
        }
        continue;
      }

      entries.push({ relPosix: nextParts.join('/'), absPath: entryAbs, size: stat.size });
    }
  };

  walk(dirRoot, [], 0);
  return entries;
}

/**
 * 把 picked directory 整目录打包成 multipart buffer。
 * 与 buildMultipart() 的区别：filename 是**相对路径**（含 /）。
 * 与 buildMultipart() 的差异是**故意的**：旧端点 filename 不含 / 是有意约束，
 * 新端点 filename 含 / 是协议需求；两者不混用。
 */
function buildDirectoryMultipart(dirRoot: string): { body: Buffer; contentType: string } {
  const entries = collectDirectoryEntries(dirRoot);
  if (entries.length === 0) throw new Error('directory contains no importable files');
  if (entries.length > MAX_IMPORT_FILES) throw new Error('too many files in directory');

  const boundary = `----sage-${randomBytes(16).toString('hex')}`;
  const chunks: Buffer[] = [];
  let totalSize = 0;

  for (const e of entries) {
    if (e.size > MAX_IMPORT_FILE_SIZE_BYTES) {
      throw new Error(`file too large: ${e.relPosix}`);
    }
    totalSize += e.size;
    if (totalSize > MAX_IMPORT_TOTAL_SIZE_BYTES) throw new Error('batch too large');
    if (/[\r\n"]/u.test(e.relPosix)) throw new Error('invalid multipart filename');
    const content = readFileSync(e.absPath);
    const ct = contentTypeFor(e.relPosix);
    chunks.push(
      Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="${e.relPosix}"\r\nContent-Type: ${ct}\r\n\r\n`,
        'utf8',
      ),
      content,
      Buffer.from(`\r\n`, 'utf8'),
    );
  }
  chunks.push(Buffer.from(`--${boundary}--\r\n`, 'utf8'));
  return { body: Buffer.concat(chunks), contentType: `multipart/form-data; boundary=${boundary}` };
}

function getBackendBaseUrl(): string {
  return process.env.PYTHON_BACKEND_URL || DEFAULT_BACKEND_URL;
}

/**
 * Register signature: same shape as Electron's `ipcMain.handle`.
 *
 * We accept any `(channel, handler)` pair — the production wiring
 * passes `ipcMain.handle.bind(ipcMain)`. The handler parameter is
 * loosely typed so test fakes can swap it in without ceremony.
 */
export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

export type SkillsAuthToken = string | (() => string | undefined);

function resolveAuthToken(authToken?: SkillsAuthToken): string | undefined {
  return typeof authToken === 'function' ? authToken() : authToken;
}

function buildMultipart(paths: string[]): { body: Buffer; contentType: string } {
  if (!Array.isArray(paths) || paths.length === 0) throw new Error('no files selected');
  if (paths.length > MAX_IMPORT_FILES) throw new Error('too many files selected');
  const boundary = `----sage-${randomBytes(16).toString('hex')}`;
  const chunks: Buffer[] = [];
  const seen = new Set<string>();
  let totalSize = 0;
  for (const p of paths) {
    if (typeof p !== 'string' || !p) throw new Error('invalid file path');
    const canonical = realpathSync(resolve(p));
    if (seen.has(canonical)) throw new Error('duplicate file');
    seen.add(canonical);
    const stat = lstatSync(p);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('file must be a regular file');
    if (!/\.(?:md|markdown)$/iu.test(basename(p))) throw new Error('file must be Markdown');
    if (stat.size > MAX_IMPORT_FILE_SIZE_BYTES) throw new Error('file too large');
    totalSize += stat.size;
    if (totalSize > MAX_IMPORT_TOTAL_SIZE_BYTES) throw new Error('batch too large');
    const filename = basename(canonical);
    if (/[\r\n"]/u.test(filename)) throw new Error('invalid multipart filename');
    const content = readFileSync(canonical);
    chunks.push(
      Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="${filename}"\r\nContent-Type: text/markdown\r\n\r\n`,
        'utf8',
      ),
      content,
      Buffer.from(`\r\n`, 'utf8'),
    );
  }
  chunks.push(Buffer.from(`--${boundary}--\r\n`, 'utf8'));
  return { body: Buffer.concat(chunks), contentType: `multipart/form-data; boundary=${boundary}` };
}

export function registerSkillsIpc(register: RegisterIpcHandler, authToken?: SkillsAuthToken): void {
  let recentPickedFiles = new Set<string>();
  // T-4b: 上次 pick-directory 选中的目录绝对路径（realpath），null 表示未选/取消。
  let recentPickedDirectory: string | null = null;
  // ── skills:pick-files ─────────────────────────────────────────────────
  // Returns `string[] | null` — selected absolute paths, or null on cancel.
  register('skills:pick-files', async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const result = await dialog.showOpenDialog(focusedWindow ?? undefined!, {
      title: '导入 SKILL.md',
      filters: [{ name: 'SKILL.md', extensions: ['md', 'markdown'] }],
      properties: ['openFile', 'multiSelections'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      recentPickedFiles = new Set();
      return null;
    }
    const canonical = new Set<string>();
    for (const filePath of result.filePaths) {
      const stat = lstatSync(filePath);
      if (!stat.isFile() || stat.isSymbolicLink()) continue;
      canonical.add(realpathSync(resolve(filePath)));
    }
    recentPickedFiles = canonical;
    return [...canonical];
  });

  // ── skills:rescan ─────────────────────────────────────────────────────
  // Forwards to POST /api/v1/skills/rescan (no body). Returns the raw JSON
  // payload: { loaded, skipped, total_loaded }.
  register('skills:rescan', async () => {
    const baseUrl = getBackendBaseUrl();
    const token = resolveAuthToken(authToken);
    const resp = await fetchCompat(`${baseUrl}/api/v1/skills/rescan`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) {
      throw new Error(`rescan failed: HTTP ${resp.status}`);
    }
    return resp.json();
  });

  // ── skills:import ─────────────────────────────────────────────────────
  // Reads each file from disk, builds a Node 16-compatible multipart payload, and
  // POSTs to /api/v1/skills/import. Backend field name is "files".
  // On error, throws an Error whose message starts with backend
  // detail.type so renderer can show reason-specific toast.
  register('skills:import', (async () => {
    const paths = [...recentPickedFiles];
    if (paths.length === 0) throw new Error('no files selected');
    const multipart = buildMultipart(paths);
    const token = resolveAuthToken(authToken);
    const headers: Record<string, string> = {
      'Content-Type': multipart.contentType,
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    const baseUrl = getBackendBaseUrl();
    const resp = await fetchCompat(`${baseUrl}/api/v1/skills/import`, {
      method: 'POST',
      headers,
      body: multipart.body,
    });
    if (!resp.ok) {
      const errBody = (await resp.json().catch(() => ({
        detail: { message: 'unknown' },
      }))) as { detail?: { type?: string; message?: string } };
      throw new Error(
        `${errBody.detail?.type ?? 'import_failed'}: ${errBody.detail?.message ?? ''}`,
      );
    }
    return resp.json();
  }) as (...args: unknown[]) => unknown);

  // ── skills:pick-directory (T-4b) ─────────────────────────────────────
  // Native directory picker; 选中目录存到 recentPickedDirectory，
  // 供 skills:import-directory 读取。返回 picked 目录 realpath 或 null（取消）。
  register('skills:pick-directory', async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const result = await dialog.showOpenDialog(focusedWindow ?? undefined!, {
      title: '选择技能目录',
      properties: ['openDirectory', 'createDirectory'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      recentPickedDirectory = null;
      return null;
    }
    const picked = result.filePaths[0];
    try {
      const stat = lstatSync(picked);
      if (!stat.isDirectory() || stat.isSymbolicLink()) {
        throw new Error('selected path is not a regular directory');
      }
      const canonical = realpathSync(resolve(picked));
      recentPickedDirectory = canonical;
      return canonical;
    } catch (err) {
      recentPickedDirectory = null;
      throw err;
    }
  });

  // ── skills:import-directory (T-4b) ────────────────────────────────────
  // 把「本次 pick 选中的目录」整体打包成 multipart（每个 part 的 filename
  // 是 posix 相对路径）→ POST /api/v1/skills/import-directory。
  //
  // renderer 必须回传 pick 时拿到的路径：主进程比对不一致就拒绝。否则
  // 「A 窗口 pick 完 → B 窗口 pick 覆盖 → A 窗口 import」会静默导入 B 的目录。
  register('skills:import-directory', (async (_event: unknown, pickedPath: unknown) => {
    if (!recentPickedDirectory) throw new Error('no directory selected');
    if (typeof pickedPath !== 'string' || pickedPath !== recentPickedDirectory) {
      throw new Error('directory selection changed, please pick again');
    }
    const multipart = buildDirectoryMultipart(pickedPath);
    const token = resolveAuthToken(authToken);
    const headers: Record<string, string> = {
      'Content-Type': multipart.contentType,
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    const baseUrl = getBackendBaseUrl();
    const resp = await fetchCompat(`${baseUrl}/api/v1/skills/import-directory`, {
      method: 'POST',
      headers,
      body: multipart.body,
    });
    if (!resp.ok) {
      const errBody = (await resp.json().catch(() => ({
        detail: { message: 'unknown' },
      }))) as { detail?: { type?: string; message?: string } };
      throw new Error(
        `${errBody.detail?.type ?? 'import_failed'}: ${errBody.detail?.message ?? ''}`,
      );
    }
    return resp.json();
  }) as (...args: unknown[]) => unknown);
}
