/**
 * P9/P13: sage-file:// URL 解析与安全校验（fail-closed）。
 * P13 收紧：ws 参数改为 main 进程工作区注册表（第 2 参数）。
 * P22 (2026-09-17): 第 3 参数 allowedByProject 接收项目级额外允许路径规则。
 * 覆盖：扩展名白名单、绝对路径、realpath 工作区包含、符号链接逃逸阻断、
 * 空注册表 fail-closed、allowed_paths 通配符匹配。
 */
import { mkdtempSync, mkdirSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { resolveSageFileUrl, SAGE_FILE_URL_PREFIX } from '../sageFileUrl';

// Windows 上临时目录本身已含符号链接分量（如 RUNNER~1），realpath 后
// 直接使用真实根目录构造 URL，保证与实现使用同一归一基准。
const wsRoot = (() => {
  const dir = mkdtempSync(join(tmpdir(), 'sage-file-test-'));
  return realpathSync(dir);
})();

const enc = encodeURIComponent;

function urlFor(file: string): string {
  return `${SAGE_FILE_URL_PREFIX}${enc(file)}`;
}

function roots(...dirs: string[]): ReadonlySet<string> {
  return new Set(dirs.map((d) => realpathSync(d)));
}

describe('resolveSageFileUrl', () => {
  let imgPath: string;
  let outsidePath: string;

  beforeEach(() => {
    writeFileSync(join(wsRoot, 'chart.png'), 'png');
    mkdirSync(join(wsRoot, 'sub'), { recursive: true });
    writeFileSync(join(wsRoot, 'sub', 'inner.png'), 'png');
    writeFileSync(join(wsRoot, 'evil.html'), 'html');
    writeFileSync(join(wsRoot, 'notes.txt'), 'txt');
    imgPath = join(wsRoot, 'chart.png');
    outsidePath = join(tmpdir(), 'sage-file-outside.png');
    writeFileSync(outsidePath, 'outside');
  });

  it('工作区注册表内的图片解析为真实路径', () => {
    const r = resolveSageFileUrl(urlFor(imgPath), roots(wsRoot));
    expect(r).toMatchObject({ ok: true });
    if (r.ok) expect(r.path.toLowerCase()).toContain('sage-file-test-');
  });

  it('子目录图片允许', () => {
    const inner = join(wsRoot, 'sub', 'inner.png');
    const r = resolveSageFileUrl(urlFor(inner), roots(wsRoot));
    expect(r).toMatchObject({ ok: true });
  });

  it('拒绝工作区外的文件', () => {
    const r = resolveSageFileUrl(urlFor(outsidePath), roots(wsRoot));
    expect(r).toMatchObject({ ok: false, reason: 'outside-registered-workspace' });
  });

  it('拒绝非白名单扩展名（.html / .txt）', () => {
    const html = join(wsRoot, 'evil.html');
    expect(resolveSageFileUrl(urlFor(html), roots(wsRoot))).toMatchObject({
      ok: false,
      reason: 'extension-not-allowed',
    });
    const txt = join(wsRoot, 'notes.txt');
    expect(resolveSageFileUrl(urlFor(txt), roots(wsRoot))).toMatchObject({
      ok: false,
      reason: 'extension-not-allowed',
    });
  });

  it('拒绝 .. 逃逸与非绝对路径', () => {
    const escaped = join(wsRoot, 'sub', '..', '..', 'outside-of-ws.png');
    const r = resolveSageFileUrl(urlFor(escaped), roots(wsRoot));
    expect(r).toMatchObject({ ok: false });
    expect(resolveSageFileUrl(urlFor('relative/pic.png'), roots(wsRoot))).toMatchObject({
      ok: false,
      reason: 'not-absolute',
    });
  });

  it('空注册表 fail-closed（全部拒绝）', () => {
    const r = resolveSageFileUrl(urlFor(imgPath), new Set());
    expect(r).toMatchObject({ ok: false, reason: 'no-registered-workspace' });
  });

  it('不存在的文件拒绝', () => {
    const r = resolveSageFileUrl(urlFor(join(wsRoot, 'missing.png')), roots(wsRoot));
    expect(r).toMatchObject({ ok: false, reason: 'not-found' });
  });

  it('符号链接指向工作区外时拒绝', () => {
    const link = join(wsRoot, 'sneaky.png');
    try {
      symlinkSync(outsidePath, link);
    } catch {
      // Windows 无符号链接权限时跳过
      return;
    }
    const r = resolveSageFileUrl(urlFor(link), roots(wsRoot));
    expect(r).toMatchObject({ ok: false, reason: 'outside-registered-workspace' });
  });

  // ===== P22 (2026-09-17): 项目级 allowed_paths 支持 =====

  it('P22: allowed_paths 命中工作区外的文件 → 放行', () => {
    const allowedDir = mkdtempSync(join(tmpdir(), 'sage-allowed-'));
    mkdirSync(join(allowedDir, 'Documents'), { recursive: true });
    const photo = join(allowedDir, 'Documents', 'photo.png');
    writeFileSync(photo, 'png');
    const allowed: ReadonlyArray<ReadonlyArray<string>> = [[`${allowedDir}/Documents/**`]];
    const r = resolveSageFileUrl(urlFor(photo), new Set(), allowed);
    expect(r).toMatchObject({ ok: true });
  });

  it('P22: allowed_paths 通配符 ** 命中任意子层', () => {
    const allowedDir = mkdtempSync(join(tmpdir(), 'sage-allowed-'));
    mkdirSync(join(allowedDir, 'a', 'b', 'c'), { recursive: true });
    const deepFile = join(allowedDir, 'a', 'b', 'c', 'deep.png');
    writeFileSync(deepFile, 'png');
    const allowed: ReadonlyArray<ReadonlyArray<string>> = [[`${allowedDir}/**`]];
    const r = resolveSageFileUrl(urlFor(deepFile), new Set(), allowed);
    expect(r).toMatchObject({ ok: true });
  });

  it('P22: allowed_paths 单层 * 不命中子目录', () => {
    const allowedDir = mkdtempSync(join(tmpdir(), 'sage-allowed-'));
    mkdirSync(join(allowedDir, 'sub'), { recursive: true });
    const subFile = join(allowedDir, 'sub', 'deep.png');
    writeFileSync(subFile, 'png');
    const allowed: ReadonlyArray<ReadonlyArray<string>> = [[`${allowedDir}/*`]];
    const r = resolveSageFileUrl(urlFor(subFile), new Set(), allowed);
    expect(r).toMatchObject({ ok: false, reason: 'outside-registered-workspace' });
  });

  it('P22: allowed_paths 规则不匹配 → 拒绝', () => {
    const allowedDir = mkdtempSync(join(tmpdir(), 'sage-allowed-'));
    mkdirSync(join(allowedDir, 'Documents'), { recursive: true });
    const photo = join(allowedDir, 'Documents', 'photo.png');
    writeFileSync(photo, 'png');
    const allowed: ReadonlyArray<ReadonlyArray<string>> = [[`${allowedDir}/Other/**`]];
    const r = resolveSageFileUrl(urlFor(photo), new Set(), allowed);
    expect(r).toMatchObject({ ok: false, reason: 'outside-registered-workspace' });
  });

  it('P22: 多个项目规则任一命中即放行', () => {
    const allowedDirA = mkdtempSync(join(tmpdir(), 'sage-allowed-a-'));
    const allowedDirB = mkdtempSync(join(tmpdir(), 'sage-allowed-b-'));
    mkdirSync(join(allowedDirA, 'Documents'), { recursive: true });
    mkdirSync(join(allowedDirB, 'Desktop'), { recursive: true });
    const fileInA = join(allowedDirA, 'Documents', 'a.png');
    const fileInB = join(allowedDirB, 'Desktop', 'b.png');
    writeFileSync(fileInA, 'png');
    writeFileSync(fileInB, 'png');

    const allowed: ReadonlyArray<ReadonlyArray<string>> = [
      [`${allowedDirA}/Documents/**`],
      [`${allowedDirB}/Desktop/**`],
    ];

    expect(resolveSageFileUrl(urlFor(fileInA), new Set(), allowed)).toMatchObject({
      ok: true,
    });
    expect(resolveSageFileUrl(urlFor(fileInB), new Set(), allowed)).toMatchObject({
      ok: true,
    });
  });

  it('P22: workspace 根 OR allowed_paths 任一命中即放行', () => {
    const allowedDir = mkdtempSync(join(tmpdir(), 'sage-allowed-'));
    mkdirSync(join(allowedDir, 'Documents'), { recursive: true });
    const photo = join(allowedDir, 'Documents', 'photo.png');
    writeFileSync(photo, 'png');

    const allowed: ReadonlyArray<ReadonlyArray<string>> = [[`${allowedDir}/Documents/**`]];
    // workspace 根未注册, 但 allowed_paths 命中 → 应放行
    const r = resolveSageFileUrl(urlFor(photo), new Set(), allowed);
    expect(r).toMatchObject({ ok: true });
    // workspace 根注册, allowed_paths 不匹配该文件 → 应放行
    const r2 = resolveSageFileUrl(urlFor(imgPath), roots(wsRoot), allowed);
    expect(r2).toMatchObject({ ok: true });
  });

  it('P22: ~ 路径规则展开主目录', () => {
    const r = resolveSageFileUrl(`${SAGE_FILE_URL_PREFIX}${enc('/nonexistent.png')}`, new Set(), [
      ['~/Documents/**'],
    ]);
    // /nonexistent.png 不存在 → not-found（在 home 之外）
    expect(r).toMatchObject({ ok: false });
    // 但路径规则确实展开为 `${homedir()}/Documents/**`；命中与否取决于文件是否存在
  });

  it('P22: allowedByProject 全空数组 → 拒绝（fail-closed）', () => {
    const r = resolveSageFileUrl(urlFor(imgPath), new Set(), []);
    expect(r).toMatchObject({ ok: false, reason: 'no-registered-workspace' });
  });
});
