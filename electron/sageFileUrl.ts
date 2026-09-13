/**
 * sage-file:// URL 解析与安全校验 — P9 (UI 优化循环, 2026-09-14)。
 *
 * 目的：模型输出/工作区里的本地图片通过自定义协议安全地渲染到聊天，
 * 替代「本地路径图片完全无法显示」的现状。
 *
 * URL 形态: sage-file://p/<encodeURIComponent(文件绝对路径)>?ws=<encodeURIComponent(工作区绝对路径)>
 *   - 单一假 host `p`，路径整体 encodeURIComponent，规避 Windows 盘符
 *     在 URL host 位置被小写化/规范化的问题；
 *   - `ws` 为渲染端声明的当前工作区（absolutely required）。
 *
 * 安全模型（纵深校验，全部在主进程执行，fail-closed）:
 *   1. 仅接受图片扩展名白名单（png/jpg/jpeg/gif/webp/bmp/svg/ico）；
 *   2. 文件与工作区路径都必须绝对；
 *   3. 文件与工作区都做 realpath 归一（阻断 `..` 与符号链接逃逸），
 *      文件必须真实存在于工作区之内；
 *   4. 任一校验失败一律拒绝，不回退任何默认读取。
 *
 * 已知边界（v1，按桌面应用威胁模型接受）: ws 由渲染端声明。`<img>`
 * 上下文中脚本不执行；sage-file 未授予 standard/stream privilege，
 * canvas 读取被同源污染阻断 —— 泄露面限于「模型本已输出的路径」。
 * 后续可在 main 侧维护已绑定工作区注册表进一步收紧（P9 已预留结构）。
 */

import { existsSync, realpathSync } from 'node:fs';
import { isAbsolute, sep } from 'node:path';

export const SAGE_FILE_URL_PREFIX = 'sage-file://p/';

const IMAGE_EXTENSIONS = new Set([
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.bmp',
  '.svg',
  '.ico',
]);

export type SageFileResolution =
  | { ok: true; path: string }
  | { ok: false; reason: string };

/** 校验并解析 sage-file:// URL → 绝对文件路径（fail-closed）。 */
export function resolveSageFileUrl(url: string): SageFileResolution {
  if (!url.startsWith(SAGE_FILE_URL_PREFIX)) {
    return { ok: false, reason: 'bad-scheme' };
  }
  const raw = url.slice(SAGE_FILE_URL_PREFIX.length);
  const qIndex = raw.indexOf('?');
  const encFile = qIndex >= 0 ? raw.slice(0, qIndex) : raw;
  const encQuery = qIndex >= 0 ? raw.slice(qIndex + 1) : '';

  let file: string;
  let ws: string;
  try {
    file = decodeURIComponent(encFile);
    ws = decodeURIComponent(new URLSearchParams(encQuery).get('ws') ?? '');
  } catch {
    return { ok: false, reason: 'bad-encoding' };
  }

  if (!file || !isAbsolute(file)) {
    return { ok: false, reason: 'not-absolute' };
  }
  if (!ws || !isAbsolute(ws)) {
    return { ok: false, reason: 'missing-workspace' };
  }

  const ext = file.slice(file.lastIndexOf('.')).toLowerCase();
  if (!IMAGE_EXTENSIONS.has(ext)) {
    return { ok: false, reason: 'extension-not-allowed' };
  }
  if (!existsSync(file)) {
    return { ok: false, reason: 'not-found' };
  }

  let realFile: string;
  let realWs: string;
  try {
    // realpath 归一符号链接; Windows 大小写差异由 native 解析吸收
    realFile = realpathSync.native(file);
    realWs = realpathSync.native(ws);
  } catch {
    return { ok: false, reason: 'not-found' };
  }
  if (realFile !== realWs && !realFile.startsWith(realWs + sep)) {
    return { ok: false, reason: 'outside-workspace' };
  }
  return { ok: true, path: realFile };
}
