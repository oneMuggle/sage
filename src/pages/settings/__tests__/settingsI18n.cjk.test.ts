/**
 * P3 i18n 守卫 —— 设置页不得再出现硬编码中文（§4.5）。
 *
 * 背景：设置页此前大量区块标题 / 行标签 / 提示文案直接写死中文，英文界面
 * 下这些位置仍显示中文。本守卫把「JSX 文本不得出现 CJK」钉成自动化断言，
 * 防止后续 PR 把中文文案重新塞回 JSX。
 *
 * 三条断言：
 * 1. JSX 文本节点（剥离注释与字符串字面量后的裸文本）不得含 CJK；
 * 2. 用户可见 JSX 属性（placeholder / title / aria-label / label / desc …）
 *    不得含 CJK；
 * 3. 用户可见的字符串 sink（toast / setError / new Error / alert）不得含 CJK。
 *
 * 有意豁免（不进断言）：
 * - 注释里的中文 —— 说明性注释不是 UI 文案；
 * - 审计快照格式化函数（`formatXxxAuditSnapshot` / `formatXxxAuditJson`）——
 *   它们产出的是**审计产物**而非界面文案，审计导出 tab 统一消费，允许保持中文；
 * - `RemoteWorkspacesTab` 的 `L(zh, en)` 双语 helper —— 已经是双语实现，
 *   中文串只作为英文 locale 的对照存在，不会出现在英文界面。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SETTINGS_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');

/**
 * CJK 统一表意文字 + 全角标点 + 中日韩符号。
 * 显式写码位而非字面量，避免「看起来像 U+F900 的字符其实是 U+8C48」这类错位。
 */
const CJK = /[⺀-鿿豈-﫿︰-﹏＀-￯]/;

/** 用户可见的 JSX 属性：值必须是双引号字符串字面量。 */
const USER_FACING_ATTR = /\b(placeholder|title|aria-label|alt|label|desc)="([^"]*)"/g;

/** 用户可见的字符串 sink：toast / setError / new Error / alert。 */
const USER_FACING_SINK =
  /\b(?:toast\.(?:error|success|warning|info)|setError|new Error|window\.alert|alert)\(\s*(['"`])(?:(?!\1)[^\\]|\\.)*\1/gs;

interface SettingsSource {
  name: string;
  source: string;
}

function readSettingsSources(): SettingsSource[] {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) {
        if (entry !== '__tests__') walk(path);
        continue;
      }
      if (entry.endsWith('.tsx') && !entry.endsWith('.test.tsx')) files.push(path);
    }
  };
  walk(SETTINGS_DIR);
  return files.map((path) => ({
    name: path.slice(SETTINGS_DIR.length + 1),
    source: readFileSync(path, 'utf8'),
  }));
}

/**
 * 整文件扫描，产出两种视图（长度与换行完全对齐源文件）：
 * - `bare`：注释与字符串字面量内容都被抹成空格，只剩裸文本 —— 用于 JSX 文本断言；
 * - `kept`：只抹掉注释，字符串内容保留 —— 用于属性 / sink 断言。
 *
 * 模板字符串整段（含 `${}` 表达式内部）都算字符串内容，因此审计快照那类
 * 模板会被整段抹掉 —— 这正是计划里要豁免的「审计产物」场景。
 */
function analyzeSource(source: string): { bare: string; kept: string } {
  const n = source.length;
  let bare = '';
  let kept = '';

  /** 跳过单/双引号字符串，返回结束引号之后的位置。 */
  const skipQuoted = (start: number): number => {
    const quote = source[start];
    let i = start + 1;
    while (i < n) {
      if (source[i] === '\\') {
        i += 2;
        continue;
      }
      if (source[i] === quote) return i + 1;
      if (source[i] === '\n') return i; // 单/双引号不跨行
      i += 1;
    }
    return i;
  };

  /** 跳过 `${ ... }` 表达式，返回配对 `}` 之后的位置。 */
  const skipExpression = (start: number): number => {
    let depth = 1;
    let i = start;
    while (i < n && depth > 0) {
      const char = source[i];
      if (char === '"' || char === "'") {
        i = skipQuoted(i);
        continue;
      }
      if (char === '`') {
        i = skipTemplate(i);
        continue;
      }
      if (char === '{') depth += 1;
      else if (char === '}') depth -= 1;
      i += 1;
    }
    return i;
  };

  /** 跳过整个模板字符串（含嵌套 `${}` 与嵌套模板），返回结束反引号之后的位置。 */
  const skipTemplate = (start: number): number => {
    let i = start + 1;
    while (i < n) {
      if (source[i] === '\\') {
        i += 2;
        continue;
      }
      if (source[i] === '`') return i + 1;
      if (source[i] === '$' && source[i + 1] === '{') {
        i = skipExpression(i + 2);
        continue;
      }
      i += 1;
    }
    return i;
  };

  let i = 0;
  while (i < n) {
    const char = source[i];
    const next = source[i + 1];

    // 行注释
    if (char === '/' && next === '/') {
      while (i < n && source[i] !== '\n') {
        bare += ' ';
        kept += ' ';
        i += 1;
      }
      continue;
    }

    // 块注释（可跨行）
    if (char === '/' && next === '*') {
      i += 2;
      while (i < n) {
        if (source[i] === '\n') {
          bare += '\n';
          kept += '\n';
        } else {
          bare += ' ';
          kept += ' ';
        }
        if (source[i] === '*' && source[i + 1] === '/') {
          i += 2;
          break;
        }
        i += 1;
      }
      continue;
    }

    // 模板字符串
    if (char === '`') {
      const end = skipTemplate(i);
      const content = source.slice(i + 1, Math.max(i + 1, end - 1));
      bare += content.replace(/[^\n]/g, ' ');
      kept += `\`${content}\``;
      i = end;
      continue;
    }

    // 单/双引号字符串
    if (char === '"' || char === "'") {
      const end = skipQuoted(i);
      const content = source.slice(i + 1, Math.max(i + 1, end - 1));
      bare += content.replace(/[^\n]/g, ' ');
      kept += source.slice(i, end);
      i = end;
      continue;
    }

    bare += char;
    kept += char;
    i += 1;
  }

  return { bare, kept };
}

/** 把匹配位置换算成 1-based 行号。 */
function lineAt(source: string, index: number): number {
  let line = 1;
  for (let i = 0; i < index && i < source.length; i += 1) {
    if (source[i] === '\n') line += 1;
  }
  return line;
}

describe('settings i18n CJK 守卫', () => {
  it('JSX 文本节点不含硬编码中文', () => {
    const violations: string[] = [];
    for (const { name, source } of readSettingsSources()) {
      const { bare } = analyzeSource(source);
      bare.split('\n').forEach((line, index) => {
        if (!CJK.test(line)) return;
        violations.push(`${name}:${index + 1}  ${source.split('\n')[index].trim()}`);
      });
    }
    expect(violations).toEqual([]);
  });

  it('用户可见 JSX 属性不含硬编码中文', () => {
    const violations: string[] = [];
    for (const { name, source } of readSettingsSources()) {
      const { kept } = analyzeSource(source);
      USER_FACING_ATTR.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = USER_FACING_ATTR.exec(kept)) !== null) {
        if (!CJK.test(match[2])) continue;
        violations.push(`${name}:${lineAt(kept, match.index)}  ${match[1]}="${match[2]}"`);
      }
    }
    expect(violations).toEqual([]);
  });

  it('用户可见字符串 sink 不含硬编码中文', () => {
    const violations: string[] = [];
    for (const { name, source } of readSettingsSources()) {
      const { kept } = analyzeSource(source);
      USER_FACING_SINK.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = USER_FACING_SINK.exec(kept)) !== null) {
        if (!CJK.test(match[0])) continue;
        violations.push(`${name}:${lineAt(kept, match.index)}  ${match[0].trim()}`);
      }
    }
    expect(violations).toEqual([]);
  });
});
