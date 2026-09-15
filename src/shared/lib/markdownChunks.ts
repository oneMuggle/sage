/**
 * 流式 markdown 分块切分 — P1 (UI 优化方案 2026-09-13)。
 *
 * 问题：流式期间每个 content_delta 都让 ReactMarkdown 对整条消息全量
 * re-parse，长回答越到后面每个 token 的解析成本越高。
 *
 * 方案：把「已确定的前缀」按空行切成稳定块，每块用 memo 化的渲染器渲染
 * （字符串相等即跳过重解析），只有最后一个 live 块随 delta 实时重解析。
 *
 * 切分安全性约束（保守策略）：
 * - 不在代码围栏（``` / ~~~）内切；
 * - 只在空行处切（块级边界），且下一行不是列表项 —— 避免 GFM 松散列表被
   拆成多个列表导致 ol 重新编号；
 * - 短消息（< MIN_CHUNKED_LENGTH）不切，避免为小消息付出多渲染器开销。
 */

/** 下一行以列表标记开头时不切（含有序/无序/引用块，引用也依赖上下文） */
const LIST_OR_QUOTE_RE = /^\s{0,3}(?:[-*+]\s|\d{1,9}[.)]\s|>)/;
const FENCE_RE = /^\s{0,3}(?:```|~~~)/;
const FENCE_G_RE = /^\s{0,3}(?:```|~~~)/gm;

/** 低于该长度不分块（省掉多渲染器实例的固定开销） */
export const MIN_CHUNKED_LENGTH = 600;

export interface ChunkSplit {
  /** 已确定的前缀块（渲染结果不再随流式变化） */
  stable: string[];
  /** 仍在变化的尾块 */
  live: string;
}

export function splitStableChunks(content: string): ChunkSplit {
  if (content.length < MIN_CHUNKED_LENGTH) {
    return { stable: [], live: content };
  }
  const lines = content.split('\n');
  const stable: string[] = [];
  let chunkStart = 0;
  let fenceCount = 0;
  for (let i = 0; i < lines.length - 1; i++) {
    if (FENCE_RE.test(lines[i])) fenceCount++;
    const insideFence = fenceCount % 2 === 1;
    const isBlankLine = lines[i].trim() === '';
    const nextIsSafe = !LIST_OR_QUOTE_RE.test(lines[i + 1]);
    if (!insideFence && isBlankLine && nextIsSafe) {
      // +'\n' 补回空行自身的行尾分隔符，保证 stable.join('') + live 无损还原原文
      stable.push(lines.slice(chunkStart, i + 1).join('\n') + '\n');
      chunkStart = i + 1;
    }
  }
  if (stable.length === 0) {
    return { stable: [], live: content };
  }
  return { stable, live: lines.slice(chunkStart).join('\n') };
}

/**
 * 流式内容里是否存在未闭合的代码围栏（围栏标记出现奇数次）。
 * 未闭合时 live 块里的 code 会随每个 delta 重复触发 Shiki/mermaid 渲染，
 * 且渲染的是半截内容 —— 应降级为纯文本 <pre>，闭合后再恢复正常渲染。
 */
export function hasUnclosedFence(content: string): boolean {
  const count = content.match(FENCE_G_RE)?.length ?? 0;
  return count % 2 === 1;
}
