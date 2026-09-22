import type { MessageSource } from '../../shared/api/types';

const VALID_SOURCE_KINDS: readonly string[] = ['web', 'wiki', 'tool', 'memory'];

/**
 * R92: sources_used 载荷校验（MEDIUM-2 口径）—— 数组且每项 kind 合法。
 *
 * 主路径 / 重接路径 / /btw 浮层三处消费同一事件，校验收敛于此，
 * 防伪造/畸形数据进入来源区块。
 */
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
