/**
 * A4b — officeApi.lintWord: channel payload + error mapping.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../desktopInvoke';
import { officeApi } from '../officeApi';
import type { OfficeWordLintResult, WordFormatSpec } from '../types';
import { ApiException } from '../utils';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

const SPEC: WordFormatSpec = { numbering: true };

describe('officeApi.lintWord (A4b)', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('invokes office_word_lint with the snake_cased lint payload', async () => {
    const fixture: OfficeWordLintResult = {
      ok: true,
      issue_count: 0,
      error_count: 0,
      warning_count: 0,
      checked_rules: ['numbering'],
      issues: [],
    };
    invokeMock.mockResolvedValueOnce(fixture);

    const result = await officeApi.lintWord({
      workspace_path: '/ws',
      file_path: '/ws/report.docx',
      format_spec: SPEC,
    });

    expect(invokeMock).toHaveBeenCalledWith('office_word_lint', {
      workspacePath: '/ws',
      filePath: '/ws/report.docx',
      formatSpec: SPEC,
    });
    expect(result).toEqual(fixture);
  });

  it('forwards max_size_bytes only when provided (backend extra=forbid)', async () => {
    invokeMock.mockResolvedValueOnce({
      ok: true,
      issue_count: 0,
      error_count: 0,
      warning_count: 0,
      checked_rules: [],
      issues: [],
    });

    await officeApi.lintWord({
      workspace_path: '/ws',
      file_path: '/ws/report.docx',
      format_spec: SPEC,
      max_size_bytes: 1024,
    });

    expect(invokeMock).toHaveBeenCalledWith('office_word_lint', {
      workspacePath: '/ws',
      filePath: '/ws/report.docx',
      formatSpec: SPEC,
      maxSizeBytes: 1024,
    });
  });

  it('maps failures to ApiException', async () => {
    invokeMock.mockRejectedValueOnce(new Error('422 lint failed'));

    await expect(
      officeApi.lintWord({ workspace_path: '/ws', file_path: '/ws/x.docx', format_spec: SPEC }),
    ).rejects.toBeInstanceOf(ApiException);
  });
});
