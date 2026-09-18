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
import { isAbsolute, join, sep } from 'node:path';
import { homedir } from 'node:os';

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

export type SageFileResolution = { ok: true; path: string } | { ok: false; reason: string };

/** 展开路径规则中的 ``~`` → 用户主目录（与 backend/office/allowed_paths 行为一致）。 */
function expandHome(p: string): string {
  if (p.startsWith('~')) {
    const rest = p.slice(1).replace(/^\/+/, '');
    return rest.length > 0 ? join(homedir(), rest) : homedir();
  }
  return p;
}

/**
 * 2026-09-17: 检查 ``file``（已 realpath 归一的绝对路径）是否匹配任一
 * ``allowedPaths`` 规则。跨平台：规则端与文件端都统一按 ``/`` 拆段
 * （Windows ``\`` 在拆段前归一为 ``/``），保证 ``~/Documents/**`` 等
 * 规则在 Windows 上同样生效。
 *
 * 支持的语法（精简版，与后端 ``allowed_paths`` 引擎语义一致）:
 *   - ``/abs/path`` — 精确路径或子目录（无通配符时为父目录前缀匹配）
 *   - ``/abs/*`` — 单层通配（不含子目录）
 *   - ``/abs/**`` — 任意子层（含零层）
 *   - ``~/...`` — 相对主目录（``~`` 展开后按上述规则处理）
 */
function matchesAllowedRule(file: string, rule: string): boolean {
  const expandedRule = expandHome(rule);
  // 跨平台归一：规则端与文件端都按 `/` 拆段（Windows `\` 归一为 `/`）。
  const normRule = expandedRule.split(sep).join('/');
  const normFile = file.split(sep).join('/');

  if (!normRule.includes('*')) {
    // 无通配：精确路径相等，或 file 以 ``rule + /`` 开头（规则是父目录）
    return normFile === normRule || normFile.startsWith(normRule + '/');
  }

  const ruleSegments = normRule.split('/').filter((s) => s.length > 0);
  const fileSegments = normFile.split('/').filter((s) => s.length > 0);

  const lastRule = ruleSegments[ruleSegments.length - 1];
  const endsWithDoubleStar = lastRule === '**';
  const effectiveRuleLen = endsWithDoubleStar ? ruleSegments.length - 1 : ruleSegments.length;

  if (!endsWithDoubleStar) {
    // 无 `/**` 结尾：段数必须对齐，逐段 glob 匹配
    if (fileSegments.length !== ruleSegments.length) return false;
    return ruleSegments.every((rs, i) => matchSegment(rs, fileSegments[i]));
  }

  // 末尾 `/**`：file 段数 >= 前缀段数，前缀段逐段匹配
  if (fileSegments.length < effectiveRuleLen) return false;
  for (let i = 0; i < effectiveRuleLen; i += 1) {
    if (!matchSegment(ruleSegments[i], fileSegments[i])) return false;
  }
  return true;
}

/** 单段匹配：`?` 任意单字符、`*` 任意字符序列（不跨 `/`）。 */
function matchSegment(ruleSeg: string, fileSeg: string): boolean {
  if (ruleSeg === '**') return true;
  // 把 glob 转成正则：`?` → `[^/]`，`*` → `[^/]*`，其它 regex 元字符转义
  const re = new RegExp(
    '^' +
      ruleSeg
        .replace(/[.+^${}()|[\]\\]/g, '\\$&')
        .replace(/\?/g, '[^/]')
        .replace(/\*/g, '[^/]*') +
      '$',
  );
  return re.test(fileSeg);
}

/**
 * 2026-09-17: ``allowedByProject`` 接收各项目 id 与其 allowed_paths 列表；
 * 返回 ``file`` 是否匹配其中任一规则。
 */
function isInAllowedPaths(
  realFile: string,
  allowedByProject: ReadonlyArray<ReadonlyArray<string>>,
): boolean {
  for (const paths of allowedByProject) {
    for (const rule of paths) {
      if (matchesAllowedRule(realFile, rule)) return true;
    }
  }
  return false;
}

/** 校验并解析 sage-file:// URL → 绝对文件路径（fail-closed）。 */
export function resolveSageFileUrl(
  url: string,
  registeredRoots: ReadonlySet<string>,
  allowedByProject: ReadonlyArray<ReadonlyArray<string>> = [],
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

  // P13 收紧 + P22 (2026-09-17) allowed_paths: 校验文件落在某个已注册
  // 工作区根内，或命中任一项目的 allowed_paths 规则。两者皆空 → 全拒
  // （fail-closed：尚未绑定任何工作区/项目级扩展就没有可读的文件面）。
  if (registeredRoots.size === 0 && allowedByProject.length === 0) {
    return { ok: false, reason: 'no-registered-workspace' };
  }
  for (const root of registeredRoots) {
    if (realFile === root || realFile.startsWith(root + sep)) {
      return { ok: true, path: realFile };
    }
  }
  if (allowedByProject.length > 0 && isInAllowedPaths(realFile, allowedByProject)) {
    return { ok: true, path: realFile };
  }
  return { ok: false, reason: 'outside-registered-workspace' };
}
