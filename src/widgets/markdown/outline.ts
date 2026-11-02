/**
 * Markdown 大纲（TOC）抽取器 —— 纯函数，零 React 依赖。
 *
 * 设计取舍：
 * - 用正则扫描源文本（而非走 AST） —— 性能 < 1ms/KB，且不需要引入 unified。
 * - 同时处理 ATX (`# h`) / Setext (`h\n===`) / fence 内跳过 —— 覆盖 LLM 输出常见形态。
 * - slug 算法 Unicode 感知（中文 / emoji 友好），重复 slug 用 `-1`/`-2` 后缀。
 */

export type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

export interface RawHeading {
  /** 标题层级（1 = h1） */
  level: HeadingLevel;
  /** 纯文本（去除 markdown 语法字符后的可读文本） */
  text: string;
  /** 在源 markdown 中的起始行号（1-based，匹配 mdast node.position.start.line） */
  line: number;
}

export interface TocEntry {
  /** 与 h* 渲染的 id 完全一致 —— TOC 点击滚动靠这个匹配 */
  id: string;
  level: HeadingLevel;
  text: string;
  /** 0 = h1, 1 = h2 ... 供 UI 缩进用 */
  depth: number;
}

export interface MarkdownOutlineData {
  entries: TocEntry[];
  /** 标题总数，供 UI "大纲 · 12 项" 显示 */
  count: number;
}

/**
 * 把标题文本规范化成 URL-safe 的 anchor id。
 * Unicode  aware —— 中文、日文、韩文都保留（\p{L}\p{N}）。
 */
export function slugifyHeading(text: string): string {
  const slug = text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\-_ ]/gu, '')
    .replace(/\s+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '') || 'section';
  return slug;
}

/**
 * 剥掉 markdown 行内语法 —— 链接、粗体、斜体、代码、图片、删除线。
 * 仅用于生成 TOC 显示文本，不用于解析。
 */
function stripInlineSyntax(raw: string): string {
  return raw
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .trim();
}

/**
 * 从 markdown 源文本扫描出所有标题（ATX + Setext），跳过 fenced code block 内的 `#`。
 *
 * 行号用 1-based（与 mdast node.position.start.line 对齐），这样
 * MessageMarkdownParts 的 byLine map 可以直接 lookup，无需偏移。
 */
export function extractHeadings(source: string): RawHeading[] {
  const lines = source.split('\n');
  const headings: RawHeading[] = [];
  let inFence = false;
  let fenceMarker = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    const fenceMatch = /^(`{3,}|~{3,})/.exec(trimmed);
    if (fenceMatch) {
      if (!inFence) {
        inFence = true;
        fenceMarker = fenceMatch[1][0];
      } else if (trimmed.startsWith(fenceMarker) && /^(`{3,}|~{3,})\s*$/.test(trimmed)) {
        inFence = false;
        fenceMarker = '';
      }
      continue;
    }
    if (inFence) continue;

    const atxMatch = /^(#{1,6})\s+(.+?)(?:\s+#+\s*)?$/.exec(trimmed);
    if (atxMatch) {
      headings.push({
        level: atxMatch[1].length as HeadingLevel,
        text: stripInlineSyntax(atxMatch[2]),
        line: i + 1,
      });
      continue;
    }

    if (i + 1 < lines.length) {
      const next = lines[i + 1].trim();
      if (trimmed.length > 0 && /^=+\s*$/.test(next)) {
        headings.push({ level: 1, text: stripInlineSyntax(trimmed), line: i + 1 });
      } else if (trimmed.length > 0 && /^-+\s*$/.test(next) && !/^\s*-\s+/.test(lines[i])) {
        headings.push({ level: 2, text: stripInlineSyntax(trimmed), line: i + 1 });
      }
    }
  }

  return headings;
}

/**
 * 把 RawHeading 列表转成 TOC 条目，去重 slug。
 * 重复 slug 用 `-1`, `-2` 后缀 —— 与 React 渲染时 heading id 一致。
 */
export function buildMarkdownOutline(
  headings: RawHeading[],
  prefix = 'md',
): MarkdownOutlineData {
  const slugCount = new Map<string, number>();
  const entries: TocEntry[] = headings.map((h) => {
    const base = slugifyHeading(h.text);
    const count = slugCount.get(base) ?? 0;
    slugCount.set(base, count + 1);
    const id = count === 0 ? `${prefix}-${base}` : `${prefix}-${base}-${count}`;
    return {
      id,
      level: h.level,
      text: h.text,
      depth: (h.level - 1) as 0 | 1 | 2 | 3 | 4 | 5,
    };
  });

  return { entries, count: entries.length };
}

/**
 * 给定行号，返回对应的 heading id。
 * 调用方在 h* 渲染时按 line lookup，保证 id 与 TOC 一致。
 */
export function headingIdForLine(
  headings: RawHeading[],
  line: number,
  prefix = 'md',
): string | undefined {
  const h = headings.find((x) => x.line === line);
  if (!h) return undefined;
  const base = slugifyHeading(h.text);
  let index = 0;
  for (const prev of headings) {
    if (prev.line >= h.line) break;
    if (slugifyHeading(prev.text) === base) index++;
  }
  return index === 0 ? `${prefix}-${base}` : `${prefix}-${base}-${index}`;
}
