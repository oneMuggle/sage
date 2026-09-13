/**
 * P9: sage-file:// URL 解析与安全校验（fail-closed）。
 * 覆盖：扩展名白名单、绝对路径、realpath 工作区包含、符号链接逃逸阻断。
 */
import { mkdtempSync, mkdirSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import {
  resolveSageFileUrl,
  SAGE_FILE_URL_PREFIX,
} from '../sageFileUrl';

// Windows 上临时目录本身已含符号链接分量（如 RUNNER~1），realpath 后
// 直接使用真实根目录构造 URL，保证与实现使用同一归一基准。
const wsRoot = (() => {
  const dir = mkdtempSync(join(tmpdir(), 'sage-file-test-'));
  return realpathSync(dir);
})();

const enc = encodeURIComponent;

function urlFor(file: string, ws: string): string {
  return `${SAGE_FILE_URL_PREFIX}${enc(file)}?ws=${enc(ws)}`;
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

  it('工作区内的图片解析为真实路径', () => {
    const r = resolveSageFileUrl(urlFor(imgPath, wsRoot));
    expect(r).toMatchObject({ ok: true });
    if (r.ok) expect(r.path.toLowerCase()).toContain('sage-file-test-');
  });

  it('子目录图片允许', () => {
    const inner = join(wsRoot, 'sub', 'inner.png');
    const r = resolveSageFileUrl(urlFor(inner, wsRoot));
    expect(r).toMatchObject({ ok: true });
  });

  it('拒绝工作区外的文件', () => {
    const r = resolveSageFileUrl(urlFor(outsidePath, wsRoot));
    expect(r).toMatchObject({ ok: false, reason: 'outside-workspace' });
  });

  it('拒绝非白名单扩展名（.html / .txt）', () => {
    const html = join(wsRoot, 'evil.html');
    expect(resolveSageFileUrl(urlFor(html, wsRoot))).toMatchObject({
      ok: false,
      reason: 'extension-not-allowed',
    });
    const txt = join(wsRoot, 'notes.txt');
    expect(resolveSageFileUrl(urlFor(txt, wsRoot))).toMatchObject({
      ok: false,
      reason: 'extension-not-allowed',
    });
  });

  it('拒绝 .. 逃逸与非绝对路径', () => {
    const escaped = join(wsRoot, 'sub', '..', '..', 'outside-of-ws.png');
    const r = resolveSageFileUrl(urlFor(escaped, wsRoot));
    // .. 逃逸后落到工作区外 → outside-workspace（或 not-found）
    expect(r).toMatchObject({ ok: false });
    expect(resolveSageFileUrl(urlFor('relative/pic.png', wsRoot))).toMatchObject({
      ok: false,
      reason: 'not-absolute',
    });
  });

  it('缺少 ws 参数时拒绝（fail-closed）', () => {
    const r = resolveSageFileUrl(`${SAGE_FILE_URL_PREFIX}${enc(imgPath)}`);
    expect(r).toMatchObject({ ok: false, reason: 'missing-workspace' });
  });

  it('不存在的文件拒绝', () => {
    const r = resolveSageFileUrl(urlFor(join(wsRoot, 'missing.png'), wsRoot));
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
    const r = resolveSageFileUrl(urlFor(link, wsRoot));
    expect(r).toMatchObject({ ok: false, reason: 'outside-workspace' });
  });
});
