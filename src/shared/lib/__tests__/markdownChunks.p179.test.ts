import { describe, expect, it } from 'vitest';

import {
  auditMarkdownChunksGovernance,
  formatChunkSplitJson,
  formatChunkSplitSummary,
  hasUnclosedFence,
  MIN_CHUNKED_LENGTH,
} from '../markdownChunks';

describe('markdownChunks P179 governance audit', () => {
  it('audits markdownChunks governance contract and chunk split helpers', () => {
    const raw = auditMarkdownChunksGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.markdown_chunks.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.minChunkedLength).toBe(MIN_CHUNKED_LENGTH);
    expect(hasUnclosedFence('```ts\nconst x = 1;')).toBe(true);
    expect(formatChunkSplitSummary('hello')).toContain('0 stable');
    expect(JSON.parse(formatChunkSplitJson('hello')).stableCount).toBe(0);
  });
});
