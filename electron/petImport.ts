/**
 * electron/petImport.ts — P2 宠物包导入管线
 * (docs/plans/2026-09-18_desktop-pet-design.md §3)。
 *
 * 流程对齐 office staging 的 plan/commit/discard 分段：
 *   zip 字节 → 内存校验解包（zipRead.ts，零依赖）→ 清单/扩展名/大小/
 *   路径穿越校验 → 写入 quarantine/<token>/ → 渲染端确认（含同 id 覆盖
 *   授权）→ commit 才移入 userData/pets/<id>/。
 *
 * 安全边界（宠物包必须纯数据，禁可执行代码）：
 *   - 扩展名白名单 .json/.css/.png/.webp；唯一 pet.json 清单
 *   - CSS 拒绝 @import / url(网络地址)，图片只按相对路径内联成 data: URL
 *   - 清单字段全部白名单正则校验（id/类名即注入 DOM 的字符串）
 *   - 后端 Python 零触点；两分支同构（Electron 主进程层）
 */
import { randomUUID } from 'node:crypto';
import { copyFile, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { readZip, ZipReadError } from './zipRead';

// ─── 常量与限额 ──────────────────────────────────────────────

export const PET_STATES = [
  'attention',
  'thinking',
  'working',
  'celebrate',
  'failed',
  'reporting',
  'idle',
  'sleeping',
] as const;
export type PetStateName = (typeof PET_STATES)[number];

export const PET_MANIFEST_FILE = 'pet.json';
const ALLOWED_EXT = new Set(['json', 'css', 'png', 'webp']);
const IMAGE_MIME: Record<string, string> = { png: 'image/png', webp: 'image/webp' };
const LIMITS = {
  maxZipBytes: 8 * 1024 * 1024,
  maxEntries: 64,
  maxFileBytes: 2 * 1024 * 1024,
  maxTotalBytes: 5 * 1024 * 1024,
  maxManifestBytes: 64 * 1024,
  maxCssBytes: 256 * 1024,
  maxInlinedCssBytes: 6 * 1024 * 1024,
  quarantineTtlMs: 24 * 60 * 60 * 1000,
};
const ID_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const CLASS_RE = /^[a-z][a-z0-9_-]{0,63}$/;

// ─── 类型（渲染端镜像见 src/shared/types/electron-api.d.ts）──

export interface PetPackManifest {
  id: string;
  name: string;
  author?: string;
  bodyClass: string;
  animations: Partial<Record<PetStateName, string>>;
}

export interface PetImportPlanOk {
  ok: true;
  token: string;
  manifest: PetPackManifest;
  files: Array<{ path: string; sizeBytes: number }>;
  totalBytes: number;
  /** true = userData/pets/<id> 已存在，commit 需显式 overwrite */
  conflict: boolean;
}

export interface PetImportPlanFailed {
  ok: false;
  errors: string[];
}

export type PetImportPlan = PetImportPlanOk | PetImportPlanFailed;

/** 渲染端渲染所需的全部：descriptor 字段 + 已内联 data URL 的 CSS。 */
export interface ImportedPetPack extends PetPackManifest {
  cssText: string;
  installedAt: number;
}

export interface PetImportEnv {
  petsDir: string;
  quarantineDir: string;
}

export interface PetMutationResult {
  ok: boolean;
  error?: string;
}

// ─── 清单校验 ────────────────────────────────────────────────

export function parseManifest(jsonText: string): { manifest?: PetPackManifest; errors: string[] } {
  const errors: string[] = [];
  let data: unknown;
  try {
    data = JSON.parse(jsonText);
  } catch (error) {
    return { errors: [`pet.json 不是合法 JSON：${String(error)}`] };
  }
  if (!data || typeof data !== 'object' || Array.isArray(data))
    return { errors: ['pet.json 必须是对象'] };
  const m = data as Record<string, unknown>;
  if (typeof m.id !== 'string' || !ID_RE.test(m.id)) errors.push('id 缺失或非法（^[a-z0-9][a-z0-9_-]{0,63}$）');
  if (typeof m.name !== 'string' || !m.name || m.name.length > 40)
    errors.push('name 缺失或长度需为 1–40');
  if (typeof m.bodyClass !== 'string' || !CLASS_RE.test(m.bodyClass))
    errors.push('bodyClass 缺失或非法');
  if (m.author !== undefined && (typeof m.author !== 'string' || m.author.length > 40))
    errors.push('author 需为 ≤40 字符字符串');
  const animations: Partial<Record<PetStateName, string>> = {};
  if (!m.animations || typeof m.animations !== 'object' || Array.isArray(m.animations)) {
    errors.push('animations 必须是对象');
  } else {
    for (const [state, cls] of Object.entries(m.animations as Record<string, unknown>)) {
      if (!(PET_STATES as readonly string[]).includes(state)) {
        errors.push(`animations 含未知状态：${state}`);
        continue;
      }
      if (typeof cls !== 'string' || !CLASS_RE.test(cls)) {
        errors.push(`animations.${state} 类名非法`);
        continue;
      }
      animations[state as PetStateName] = cls;
    }
  }
  if (errors.length > 0) return { errors };
  return {
    manifest: {
      id: m.id as string,
      name: m.name as string,
      ...(m.author === undefined ? {} : { author: m.author as string }),
      bodyClass: m.bodyClass as string,
      animations,
    },
    errors,
  };
}

/** CSS 卫生检查：禁 @import（外抓资源）与网络 url()。 */
export function validateCss(cssText: string, label: string): string[] {
  const errors: string[] = [];
  if (/@import/i.test(cssText)) errors.push(`${label} 含 @import，已拒绝`);
  for (const match of cssText.matchAll(/url\(\s*['"]?([^'")]+)/gi)) {
    const ref = match[1] ?? '';
    if (/^(https?:|data:|\/\/)/i.test(ref)) errors.push(`${label} 含网络/内联 url()：${ref.slice(0, 48)}`);
  }
  return errors;
}

// ─── zip → quarantine（plan 阶段）───────────────────────────

/** 所有条目共享单一顶层目录且其下没有 pet.json → 视为打包根目录，剥掉。 */
function detectRootPrefix(names: string[]): string {
  if (names.includes(PET_MANIFEST_FILE)) return '';
  const tops = new Set(names.map((n) => n.split('/')[0]));
  if (tops.size !== 1) return '';
  const [top] = [...tops];
  return top && top !== PET_MANIFEST_FILE ? `${top}/` : '';
}

async function quarantineWrite(dir: string, relPath: string, data: Buffer): Promise<void> {
  const target = path.join(dir, relPath);
  if (!target.startsWith(dir + path.sep)) throw new ZipReadError(`落盘路径越界：${relPath}`);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, data, { flag: 'wx' });
}

export async function planImportFromZip(
  zipBytes: Buffer,
  env: PetImportEnv,
): Promise<PetImportPlan> {
  if (zipBytes.length === 0 || zipBytes.length > LIMITS.maxZipBytes)
    return { ok: false, errors: [`zip 大小需在 1–${LIMITS.maxZipBytes} 字节内`] };
  let entries;
  try {
    entries = readZip(zipBytes, LIMITS);
  } catch (error) {
    const msg = error instanceof ZipReadError || error instanceof Error ? error.message : String(error);
    return { ok: false, errors: [msg] };
  }
  const root = detectRootPrefix(entries.map((e) => e.name));
  const files = entries
    .map((e) => ({ ...e, rel: root ? e.name.slice(root.length) : e.name }))
    .filter((e) => e.rel.length > 0);
  const errors: string[] = [];
  const manifestEntry = files.find((e) => e.rel === PET_MANIFEST_FILE);
  if (!manifestEntry) return { ok: false, errors: [`缺少 ${PET_MANIFEST_FILE}`] };
  if (files.filter((e) => e.rel === PET_MANIFEST_FILE).length > 1)
    return { ok: false, errors: ['存在多个 pet.json'] };
  for (const f of files) {
    const ext = path.posix.extname(f.rel).slice(1).toLowerCase();
    if (!ALLOWED_EXT.has(ext)) errors.push(`扩展名不在白名单：${f.rel}`);
    if (f.rel === PET_MANIFEST_FILE && f.data.length > LIMITS.maxManifestBytes)
      errors.push('pet.json 超过 64KB');
    if (ext === 'css') {
      const cssText = f.data.toString('utf8');
      if (Buffer.byteLength(cssText) > LIMITS.maxCssBytes) errors.push(`CSS 过大：${f.rel}`);
      errors.push(...validateCss(cssText, f.rel));
    }
  }
  if (errors.length > 0) return { ok: false, errors };
  const { manifest, errors: manifestErrors } = parseManifest(manifestEntry.data.toString('utf8'));
  if (!manifest) return { ok: false, errors: manifestErrors };

  const token = randomUUID();
  const stagingDir = path.join(env.quarantineDir, token);
  try {
    await mkdir(stagingDir, { recursive: true });
    for (const f of files) await quarantineWrite(stagingDir, f.rel, f.data);
  } catch (error) {
    await rm(stagingDir, { recursive: true, force: true });
    return { ok: false, errors: [`隔离区写入失败：${String(error)}`] };
  }
  const totalBytes = files.reduce((acc, f) => acc + f.data.length, 0);
  return {
    ok: true,
    token,
    manifest,
    files: files.map((f) => ({ path: f.rel, sizeBytes: f.data.length })),
    totalBytes,
    conflict: await packExists(env, manifest.id),
  };
}

// ─── quarantine → pets（commit / discard）───────────────────

async function packExists(env: PetImportEnv, id: string): Promise<boolean> {
  try {
    await readFile(path.join(env.petsDir, id, PET_MANIFEST_FILE));
    return true;
  } catch {
    return false;
  }
}

async function moveDir(src: string, dest: string): Promise<void> {
  try {
    await rm(dest, { recursive: true, force: true });
    await copyTree(src, dest);
    await rm(src, { recursive: true, force: true });
  } catch (error) {
    await rm(dest, { recursive: true, force: true }).catch(() => undefined);
    throw error;
  }
}

async function copyTree(src: string, dest: string): Promise<void> {
  await mkdir(dest, { recursive: true });
  for (const entry of await readdir(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) await copyTree(s, d);
    else if (entry.isFile()) await copyFile(s, d);
    else throw new Error(`隔离区含非常规文件，拒绝入库：${entry.name}`);
  }
}

export async function commitImport(
  token: string,
  opts: { overwrite: boolean },
  env: PetImportEnv,
): Promise<PetMutationResult> {
  if (!/^[0-9a-f-]{36}$/.test(token)) return { ok: false, error: 'token 非法' };
  const stagingDir = path.join(env.quarantineDir, token);
  let manifestText: string;
  try {
    manifestText = await readFile(path.join(stagingDir, PET_MANIFEST_FILE), 'utf8');
  } catch {
    return { ok: false, error: '隔离区不存在该 token 的待入库包（已过期或取消）' };
  }
  const { manifest, errors } = parseManifest(manifestText);
  if (!manifest) return { ok: false, error: errors.join('；') };
  const dest = path.join(env.petsDir, manifest.id);
  if (!opts.overwrite && (await packExists(env, manifest.id)))
    return { ok: false, error: `宠物包已存在：${manifest.id}（需覆盖授权）` };
  try {
    await moveDir(stagingDir, dest);
  } catch (error) {
    return { ok: false, error: `入库失败：${String(error)}` };
  }
  return { ok: true };
}

/** 幂等：未知 token / 已删除都算成功。 */
export async function discardImport(token: string, env: PetImportEnv): Promise<PetMutationResult> {
  if (!/^[0-9a-f-]{36}$/.test(token)) return { ok: false, error: 'token 非法' };
  await rm(path.join(env.quarantineDir, token), { recursive: true, force: true });
  return { ok: true };
}

/** 启动期清孤儿隔离区（pets 列表读取也顺带触发；纯本地文件，无审计诉求）。 */
export async function sweepStaleQuarantine(
  env: PetImportEnv,
  activeTokens: ReadonlySet<string>,
  now = Date.now(),
): Promise<number> {
  let swept = 0;
  let names: string[] = [];
  try {
    names = await readdir(env.quarantineDir);
  } catch {
    return 0;
  }
  for (const name of names) {
    if (activeTokens.has(name)) continue;
    if (!/^[0-9a-f-]{36}$/.test(name)) continue;
    const dir = path.join(env.quarantineDir, name);
    try {
      const { mtimeMs } = await stat(dir);
      if (now - mtimeMs < LIMITS.quarantineTtlMs) continue;
      await rm(dir, { recursive: true, force: true });
      swept++;
    } catch {
      /* 读取失败的隔离目录保留，不猜测 */
    }
  }
  return swept;
}

// ─── 已安装包读取（list）────────────────────────────────────

const URL_REF_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/gi;

/** CSS 里的相对 url() 全部内联成 data: URL；引用不到文件 / 越界 → 报错。 */
export async function inlineCssAssets(
  cssFiles: Array<{ name: string; text: string }>,
  readPackFile: (relPath: string) => Promise<Buffer | null>,
): Promise<{ cssText?: string; errors: string[] }> {
  const errors: string[] = [];
  const cache = new Map<string, string>();
  const chunks: string[] = [];
  for (const css of cssFiles) {
    const dir = path.posix.dirname(css.name);
    let out = '';
    let cursor = 0;
    for (const match of css.text.matchAll(URL_REF_RE)) {
      const idx = match.index ?? 0;
      out += css.text.slice(cursor, idx);
      cursor = idx + match[0].length;
      const ref = match[2] ?? '';
      const resolved = path.posix.normalize(path.posix.join(dir, ref));
      if (resolved.startsWith('..') || path.posix.isAbsolute(resolved)) {
        errors.push(`${css.name}: url() 越界引用 ${ref}`);
        continue;
      }
      let dataUrl = cache.get(resolved);
      if (!dataUrl) {
        const bytes = await readPackFile(resolved);
        const ext = path.posix.extname(resolved).slice(1).toLowerCase();
        if (bytes === null || !IMAGE_MIME[ext]) {
          errors.push(`${css.name}: url() 引用缺失或非图片：${ref}`);
          continue;
        }
        dataUrl = `data:${IMAGE_MIME[ext]};base64,${bytes.toString('base64')}`;
        cache.set(resolved, dataUrl);
      }
      out += `url("${dataUrl}")`;
    }
    out += css.text.slice(cursor);
    chunks.push(out);
  }
  const cssText = chunks.join('\n');
  if (Buffer.byteLength(cssText) > LIMITS.maxInlinedCssBytes)
    errors.push(`内联后 CSS 超过 ${LIMITS.maxInlinedCssBytes} 字节`);
  return errors.length > 0 ? { errors } : { cssText, errors };
}

async function readDirRecursive(dir: string, prefix = ''): Promise<string[]> {
  const out: string[] = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) out.push(...(await readDirRecursive(path.join(dir, entry.name), rel)));
    else if (entry.isFile()) out.push(rel);
  }
  return out;
}

export async function listInstalledPacks(env: PetImportEnv): Promise<ImportedPetPack[]> {
  const packs: ImportedPetPack[] = [];
  let dirs: string[];
  try {
    dirs = await readdir(env.petsDir, { withFileTypes: true }).then((entries) =>
      entries.filter((e) => e.isDirectory()).map((e) => e.name),
    );
  } catch {
    return [];
  }
  for (const id of dirs) {
    if (!ID_RE.test(id)) continue;
    const dir = path.join(env.petsDir, id);
    try {
      const manifestText = await readFile(path.join(dir, PET_MANIFEST_FILE), 'utf8');
      const { manifest, errors } = parseManifest(manifestText);
      if (!manifest || manifest.id !== id) {
        console.warn(`[petImport] 跳过损坏宠物包 ${id}: ${errors.join('；')}`);
        continue;
      }
      const relFiles = (await readDirRecursive(dir)).sort();
      const cssFiles: Array<{ name: string; text: string }> = [];
      const fileMap = new Map<string, Buffer>();
      for (const rel of relFiles) {
        if (rel === PET_MANIFEST_FILE) continue;
        const bytes = await readFile(path.join(dir, rel));
        if (rel.toLowerCase().endsWith('.css')) cssFiles.push({ name: rel, text: bytes.toString('utf8') });
        fileMap.set(rel, bytes);
      }
      const { cssText, errors: cssErrors } = await inlineCssAssets(cssFiles, async (rel) =>
        fileMap.has(rel) ? (fileMap.get(rel) as Buffer) : null,
      );
      if (!cssText || cssErrors.length > 0) {
        console.warn(`[petImport] 跳过 CSS 非法宠物包 ${id}: ${cssErrors.join('；')}`);
        continue;
      }
      const installedAt = Math.floor((await stat(dir)).mtimeMs);
      packs.push({ ...manifest, cssText, installedAt });
    } catch {
      /* 目录不可读时跳过该包，不影响列表 */
    }
  }
  return packs.sort((a, b) => a.id.localeCompare(b.id));
}

export async function removePack(id: string, env: PetImportEnv): Promise<PetMutationResult> {
  if (!ID_RE.test(id)) return { ok: false, error: 'id 非法' };
  const dir = path.join(env.petsDir, id);
  try {
    await readFile(path.join(dir, PET_MANIFEST_FILE));
  } catch {
    return { ok: false, error: `宠物包不存在：${id}` };
  }
  await rm(dir, { recursive: true, force: true });
  return { ok: true };
}
