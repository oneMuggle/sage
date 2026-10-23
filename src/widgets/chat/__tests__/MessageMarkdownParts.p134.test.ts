import { describe, expect, it } from 'vitest';

import {
  evaluateMessageMarkdownPartsAudit,
  exportMessageMarkdownPartsAuditJson,
} from '../MessageMarkdownParts';

describe('MessageMarkdownParts audit diagnostics (Phase P134)', () => {
  it('validates balanced markdown parts', () => {
    const report = evaluateMessageMarkdownPartsAudit({
      blockCount: 5,
      codeBlockCount: 2,
      tableCount: 1,
      unfinishedFenceCount: 0,
    });
    expect(report.healthy).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags unclosed fences and part count mismatch', () => {
    const parsed = JSON.parse(
      exportMessageMarkdownPartsAuditJson({
        blockCount: 2,
        codeBlockCount: 2,
        tableCount: 2,
        unfinishedFenceCount: 1,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('unclosed_markdown_code_fence');
    expect(parsed.issueCodes).toContain('part_count_mismatch');
  });
});
