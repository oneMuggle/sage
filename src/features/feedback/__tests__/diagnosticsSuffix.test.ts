// src/features/feedback/__tests__/diagnosticsSuffix.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/feedbackApi', () => ({
  fetchLogTail: vi.fn(),
}));

import * as feedbackApi from '../../../shared/api/feedbackApi';
import {
  DIAGNOSTICS_MAX_CHARS,
  DIAGNOSTICS_TAIL_LINES,
  collectDiagnosticsSuffix,
  formatDiagnosticsSuffix,
} from '../diagnosticsSuffix';

const mockFetchLogTail = vi.mocked(feedbackApi.fetchLogTail);

const HEADER = '--- diagnostics ---';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('formatDiagnosticsSuffix', () => {
  it('空白日志返回 null', () => {
    expect(formatDiagnosticsSuffix('', HEADER)).toBeNull();
    expect(formatDiagnosticsSuffix('   \n\t\n', HEADER)).toBeNull();
  });

  it('正常日志包成带标题的 markdown 代码块', () => {
    expect(formatDiagnosticsSuffix('line-1\nline-2\n', HEADER)).toBe(
      `${HEADER}\n\n\`\`\`\nline-1\nline-2\n\`\`\``,
    );
  });

  it('超长日志只保留尾部并截到上限', () => {
    const text = 'a'.repeat(DIAGNOSTICS_MAX_CHARS) + 'TAIL-MARKER';
    const out = formatDiagnosticsSuffix(text, HEADER);
    expect(out).not.toBeNull();
    expect(out).toContain('TAIL-MARKER');
    const body = out!.slice(out!.indexOf('```\n') + 4, out!.lastIndexOf('\n```'));
    expect(body).toHaveLength(DIAGNOSTICS_MAX_CHARS);
    expect(body.startsWith('a')).toBe(true);
  });
});

describe('collectDiagnosticsSuffix', () => {
  it('取日志成功时返回格式化后缀', async () => {
    mockFetchLogTail.mockResolvedValue({ text: 'boot ok', lines: ['boot ok'] });

    const out = await collectDiagnosticsSuffix(HEADER);

    expect(mockFetchLogTail).toHaveBeenCalledWith(DIAGNOSTICS_TAIL_LINES);
    expect(out).toBe(`${HEADER}\n\n\`\`\`\nboot ok\n\`\`\``);
  });

  it('取日志失败时返回 null，不抛错', async () => {
    mockFetchLogTail.mockRejectedValue(new Error('backend down'));
    await expect(collectDiagnosticsSuffix(HEADER)).resolves.toBeNull();
  });
});
