import type { MessageSource, RagCitation } from '../../shared/api/types';

/**
 * 透明度事件载荷校验（MEDIUM-2 口径）—— 主路径 / 重接路径 / /btw 浮层
 * 三处消费同一 /chat/stream 事件流，各事件载荷契约收敛于此模块，
 * 防伪造/畸形数据进入气泡文案；校验不通过时调用方丢弃该事件。
 */

const VALID_SOURCE_KINDS: readonly string[] = ['web', 'wiki', 'tool', 'memory'];

/** R81/R92: sources_used —— 数组且每项 kind ∈ {web, wiki, tool, memory}。 */
export function isValidSourcesPayload(sources: unknown): sources is MessageSource[] {
  return (
    Array.isArray(sources) &&
    sources.length > 0 &&
    sources.every(
      (s) =>
        typeof s === 'object' &&
        s !== null &&
        VALID_SOURCE_KINDS.includes((s as { kind?: unknown }).kind as string),
    )
  );
}

/** R38: memory_used —— 数组且每项必须有 id (string)。 */
export function isValidMemoriesPayload(
  memories: unknown,
): memories is { id: string; memory_type?: string; preview?: string }[] {
  return (
    Array.isArray(memories) &&
    memories.every(
      (m) =>
        typeof m === 'object' &&
        m !== null &&
        typeof (m as { id?: unknown }).id === 'string',
    )
  );
}

/** R38: skill_activated —— 数组且每项必须有 name (string)。 */
export function isValidSkillsPayload(
  skills: unknown,
): skills is { name: string; triggers_matched?: string[] }[] {
  return (
    Array.isArray(skills) &&
    skills.every(
      (s) =>
        typeof s === 'object' &&
        s !== null &&
        typeof (s as { name?: unknown }).name === 'string',
    )
  );
}

/** R87: attachment_rag_used —— 数组且每项必须有 media_id (string)。 */
export function isValidCitationsPayload(
  citations: unknown,
): citations is RagCitation[] {
  return (
    Array.isArray(citations) &&
    citations.every(
      (c) =>
        typeof c === 'object' &&
        c !== null &&
        typeof (c as { media_id?: unknown }).media_id === 'string',
    )
  );
}

/** R38: compact_triggered —— before/after/removed 必须均为 number。 */
export function isValidCompactPayload(
  compact: unknown,
): compact is { before: number; after: number; removed: number } {
  if (typeof compact !== 'object' || compact === null) return false;
  const c = compact as { before?: unknown; after?: unknown; removed?: unknown };
  return (
    typeof c.before === 'number' &&
    typeof c.after === 'number' &&
    typeof c.removed === 'number'
  );
}
