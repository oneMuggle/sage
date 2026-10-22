import { describe, expect, it } from 'vitest';

import {
  formatMessageJumpJson,
  formatMessageJumpSummary,
  JUMP_FLASH_MS,
  normalizeHeadingText,
} from '../useMessageJump';

describe('useMessageJump audit helpers', () => {
  it('normalizes markdown headings and formats jump summary', () => {
    expect(normalizeHeadingText('## **Hello** `World` ###')).toBe(
      '## hello world',
    );
    expect(formatMessageJumpSummary(50, 'msg-9', 120)).toBe(
      'window=50/120 · flash=msg-9',
    );
  });

  it('serializes message jump audit JSON', () => {
    expect(JSON.parse(formatMessageJumpJson(30, null, 80))).toEqual({
      effectiveWindow: 30,
      totalMessages: 80,
      flashId: null,
      flashDurationMs: JUMP_FLASH_MS,
    });
  });
});
