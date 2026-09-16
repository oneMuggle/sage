/**
 * sage-file:// URL 解析与安全校验 — P13 收紧版 (UI 优化循环, 2026-09-14)。
 *
 * 目的：模型输出/工作区里的本地图片通过自定义协议安全地渲染到聊天，
 * 替代「本地路径图片完全无法显示」的现状。
 *
 * URL 形态: sage-file://p/<encodeURIComponent(文件绝对路径)>
 *   - 单一假 host `p`，路径整体 encodeURIComponent，规避 Windows 盘符
 *     在 URL host 位置被小写化/规范化的问题。
 *   - P13 收紧：不再携带渲染端自声明的 ?ws= 参数 —— 文件是否允许读取
 *     由主进程维护的已注册工作区根注册表决定（sageFileProtocol.ts）。
 *
 * 安全模型（纵深校验，全部在主进程执行，fail-closed）:
 *   1. 仅接受图片扩展名白名单（png/jpg/jpeg/gif/webp/bmp/svg/ico）；
 *   2. 路径必须绝对；
 *   3. realpath 归一后必须落在某个已注册工作区根内 —— 阻断 `..` 与
 *      符号链接逃逸；文件不存在即拒绝；
 *   4. 注册表为空时全部拒绝（fail-closed：尚未绑定任何工作区就没有
 *      可读的文件面）。
 *
 * 已知边界（按桌面应用威胁模型接受）: `<img>` 上下文中脚本不执行；
 * sage-file 未授予 standard/stream privilege，canvas 读取被同源污染
 * 阻断 —— 泄露面限于「模型本已输出的路径」。
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
export function resolveSageFileUrl(
  url: string,
  registeredRoots: ReadonlySet<string>,
): SageFileResolution {
  if (!url.startsWith(SAGE_FILE_URL_PREFIX)) {
    return { ok: false, reason: 'bad-scheme' };
  }
  const raw = url.slice(SAGE_FILE_URL_PREFIX.length);
  const qIndex = raw.indexOf('?');
  const encFile = qIndex >= 0 ? raw.slice(0, qIndex) : raw;

  let file: string;
  try {
    file = decodeURIComponent(encFile);
    // P22: 防双重编码逃逸 —— 解码后再检查是否仍含编码字符
    if (/%[0-9a-fA-F]{2}/.test(file)) {
      file = decodeURIComponent(file);
    }
  } catch {
    return { ok: false, reason: 'bad-encoding' };
  }
  // P22: 解码后路径中不允许出现 null byte 或控制字符
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f]/.test(file)) {
    return { ok: false, reason: 'invalid-characters' };
  }
  if (!file || !isAbsolute(file)) {
    return { ok: false, reason: 'not-absolute' };
  }
  const ext = file.slice(file.lastIndexOf('.')).toLowerCase();
  if (!IMAGE_EXTENSIONS.has(ext)) {
    return { ok: false, reason: 'extension-not-allowed' };
  }
  if (!existsSync(file)) {
    return { ok: false, reason: 'not-found' };
  }
  let realFile: string;
  try {
    realFile = realpathSync.native(file);
  } catch {
    return { ok: false, reason: 'not-found' };
  }

  // P13: 校验文件落在某个已注册工作区根内（fail-closed：空注册表全拒）
  if (registeredRoots.size === 0) {
    return { ok: false, reason: 'no-registered-workspace' };
  }
  for (const root of registeredRoots) {
    if (realFile === root || realFile.startsWith(root + sep)) {
      return { ok: true, path: realFile };
    }
  }
  return { ok: false, reason: 'outside-registered-workspace' };
}
