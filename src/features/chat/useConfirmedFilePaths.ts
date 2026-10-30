// src/features/chat/useConfirmedFilePaths.ts
//
// 消息文本兜底识别（feat/file-reference-preview M5）：从助手正文提取
// 路径样式的候选 token，消息完成后批量调后端 resolve 确认存在性，只有
// 「工作区内确实存在」的路径才会被渲染成链接，最大限度避免误伤。
// 结果按 (sessionId, path) 模块级缓存；同一批候选复用在途请求。
import { useEffect, useState } from 'react';

import { workspaceApi } from '../../shared/api/workspaceApi';

const EMPTY_SET: ReadonlySet<string> = new Set<string>();

/** 候选 token 的切分正则（空白与常见中英文标点作分隔） */
const TOKEN_RE = /[^\s"'`()（）[\]【】，。；：、!?<>|]+/g;
const TRAILING_PUNCT_RE = /^[\s.,;:!?]+|[\s.,;:!?]+$/g;
const KNOWN_EXT_RE =
  /\.(md|markdown|mdx|txt|log|py|js|ts|tsx|jsx|rs|go|java|c|cpp|h|hpp|cs|rb|php|swift|kt|sh|bash|zsh|ps1|sql|html?|css|scss|yaml|yml|toml|ini|xml|png|jpe?g|gif|webp|svg|bmp|csv|tsv|json|pdf|docx|xlsx|pptx)$/i;

/** 单个 token 是否像文件路径（外链、过长的 token 直接排除） */
export function looksLikeFilePath(token: string): boolean {
  if (!token || token.length > 300) return false;
  if (/^(https?:|mailto:|sage-file:)/i.test(token)) return false;
  if (token.includes('://')) return false;
  const hasSeparator = /[\\/]/.test(token);
  const hasExt = /\.[A-Za-z0-9]{1,8}$/.test(token);
  if (!hasExt) return false;
  // 有分隔符的路径（src/app.ts、C:\a\b.md）直接认可；裸文件名必须命中已知扩展名
  return hasSeparator || KNOWN_EXT_RE.test(token);
}

/** 从文本提取去重后的候选路径（上限 50，与后端 /workspace/resolve 约束一致） */
export function extractFileRefCandidates(text: string): string[] {
  const out: string[] = [];
  for (const match of text.matchAll(TOKEN_RE)) {
    const token = match[0].replace(TRAILING_PUNCT_RE, '');
    if (looksLikeFilePath(token)) out.push(token);
  }
  return Array.from(new Set(out)).slice(0, 50);
}

// 模块级缓存：key = `${sessionId}\u0000${path}` → 是否存在
const resolutionCache = new Map<string, boolean>();
// 在途批量请求：key = sessionId + 排序后的候选列表
const inflightRequests = new Map<string, Promise<void>>();

function cacheKey(sessionId: string, path: string): string {
  return `${sessionId}\u0000${path}`;
}

/**
 * 返回消息文本中「已确认存在于工作区」的路径集合。``enabled`` 为 false
 * （流式生成中）时不发请求、返回空集。
 */
export function useConfirmedFilePaths(
  text: string | null | undefined,
  sessionId: string | null | undefined,
  enabled: boolean,
): ReadonlySet<string> {
  const [confirmed, setConfirmed] = useState<ReadonlySet<string>>(EMPTY_SET);

  useEffect(() => {
    if (!enabled || !sessionId) {
      setConfirmed(EMPTY_SET);
      return;
    }
    const candidates = extractFileRefCandidates(text ?? '');
    if (candidates.length === 0) {
      setConfirmed(EMPTY_SET);
      return;
    }

    let cancelled = false;
    const known = new Map<string, boolean>();
    const unknown: string[] = [];
    for (const candidate of candidates) {
      const hit = resolutionCache.get(cacheKey(sessionId, candidate));
      if (hit === undefined) unknown.push(candidate);
      else known.set(candidate, hit);
    }

    const apply = (fresh: Map<string, boolean>) => {
      if (cancelled) return;
      const result = new Set<string>();
      for (const [path, exists] of known) if (exists) result.add(path);
      for (const [path, exists] of fresh) if (exists) result.add(path);
      setConfirmed(result);
    };

    if (unknown.length === 0) {
      apply(new Map());
      return;
    }

    const inflightKey = `${sessionId}\u0000${unknown.slice().sort().join('\u0001')}`;
    const fillFromCache = () => {
      const fresh = new Map<string, boolean>();
      for (const candidate of unknown) {
        const hit = resolutionCache.get(cacheKey(sessionId, candidate));
        if (hit !== undefined) fresh.set(candidate, hit);
      }
      apply(fresh);
    };

    let request = inflightRequests.get(inflightKey);
    if (!request) {
      request = workspaceApi
        .resolveFiles(sessionId, unknown)
        .then((response) => {
          const fresh = new Map<string, boolean>();
          for (const entry of response.results) {
            fresh.set(entry.path, entry.exists);
            resolutionCache.set(cacheKey(sessionId, entry.path), entry.exists);
          }
          apply(fresh);
        })
        .catch(() => {
          // 解析失败仅意味着不加链接，不影响正文渲染
        })
        .finally(() => {
          inflightRequests.delete(inflightKey);
        });
      inflightRequests.set(inflightKey, request);
    } else {
      // 复用同一批在途请求：完成后从缓存回填本消息
      request.then(fillFromCache).catch(() => {});
    }

    return () => {
      cancelled = true;
    };
  }, [text, sessionId, enabled]);

  return confirmed;
}

export interface MdNodeLike {
  type: string;
  value?: string;
  url?: string;
  children?: MdNodeLike[];
}

/** remark 插件：把已确认存在的文本路径替换为 link 节点（渲染端再拦截为右栏预览） */
export function remarkFileRefLinks(confirmed: ReadonlySet<string>) {
  return () => (tree: unknown) => {
    walkTree(tree as MdNodeLike, confirmed);
  };
}

const SKIP_CHILDREN_TYPES = new Set([
  'link',
  'linkReference',
  'image',
  'imageReference',
  'inlineCode',
  'code',
  'html',
]);

function walkTree(node: MdNodeLike, confirmed: ReadonlySet<string>): void {
  if (!node.children || node.children.length === 0) return;
  const next: MdNodeLike[] = [];
  for (const child of node.children) {
    if (child.type === 'text' && child.value) {
      next.push(...splitTextNode(child.value, confirmed));
      continue;
    }
    if (!SKIP_CHILDREN_TYPES.has(child.type)) walkTree(child, confirmed);
    next.push(child);
  }
  node.children = next;
}

function splitTextNode(value: string, confirmed: ReadonlySet<string>): MdNodeLike[] {
  const parts: MdNodeLike[] = [];
  let last = 0;
  for (const match of value.matchAll(TOKEN_RE)) {
    const raw = match[0];
    const token = raw.replace(TRAILING_PUNCT_RE, '');
    if (!token || !confirmed.has(token)) continue;
    const start = (match.index ?? 0) + raw.indexOf(token);
    if (start < last) continue;
    if (start > last) parts.push({ type: 'text', value: value.slice(last, start) });
    parts.push({
      type: 'link',
      url: token,
      children: [{ type: 'text', value: token }],
    });
    last = start + token.length;
  }
  if (parts.length === 0) return [{ type: 'text', value }];
  if (last < value.length) parts.push({ type: 'text', value: value.slice(last) });
  return parts;
}

/** 测试辅助：清空模块级缓存（生产代码不需要调用） */
export function __clearFileRefResolutionCache(): void {
  resolutionCache.clear();
  inflightRequests.clear();
}
