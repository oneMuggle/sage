import { beforeEach, describe, expect, it, vi } from 'vitest';

import { backendRequest, BackendRequestError } from '../backendRequest';
import { officeGenerateApi } from '../officeGenerateApi';
import type { OfficeGenerateResult } from '../types';
import { ApiException } from '../utils';

vi.mock('../backendRequest', async () => {
  const actual = await vi.importActual<typeof import('../backendRequest')>('../backendRequest');
  return { ...actual, backendRequest: vi.fn() };
});

const mockedRequest = vi.mocked(backendRequest);

const RESULT = {
  output_path: '/ws/abc123/report.docx',
  filename: 'report.docx',
  file_size_bytes: 12,
  summary: { id: 'abc123' },
} as unknown as OfficeGenerateResult;

describe('officeGenerateApi', () => {
  beforeEach(() => {
    mockedRequest.mockReset();
  });

  it('posts NL generation to /api/v1/office/generate/nl', async () => {
    mockedRequest.mockResolvedValue(RESULT);
    const req = {
      workspace_path: '/ws',
      instruction: '写一份周报',
      doc_type: 'word' as const,
    };

    await expect(officeGenerateApi.generateFromNl(req)).resolves.toBe(RESULT);

    expect(mockedRequest).toHaveBeenCalledWith({
      path: '/api/v1/office/generate/nl',
      method: 'POST',
      body: req,
    });
  });

  it('posts template chat to /api/v1/office/generate/template-chat', async () => {
    mockedRequest.mockResolvedValue(RESULT);
    const req = {
      workspace_path: '/ws',
      template_id: 'weekly_report',
      messages: [{ role: 'user' as const, content: '第 45 周周报' }],
    };

    await officeGenerateApi.generateFromTemplateChat(req);

    expect(mockedRequest).toHaveBeenCalledWith({
      path: '/api/v1/office/generate/template-chat',
      method: 'POST',
      body: req,
    });
  });

  it('posts iterate to /api/v1/office/generate/iterate', async () => {
    mockedRequest.mockResolvedValue(RESULT);
    const req = {
      workspace_path: '/ws',
      source_path: '/ws/report.docx',
      instruction: '语气更正式',
    };

    await officeGenerateApi.iterateDocument(req);

    expect(mockedRequest).toHaveBeenCalledWith({
      path: '/api/v1/office/generate/iterate',
      method: 'POST',
      body: req,
    });
  });

  it('wraps backend failures in ApiException', async () => {
    mockedRequest.mockRejectedValue(new BackendRequestError(422, 'bad json'));

    const call = officeGenerateApi.generateFromNl({
      workspace_path: '/ws',
      instruction: 'x',
      doc_type: 'word',
    });

    await expect(call).rejects.toBeInstanceOf(ApiException);
    await expect(call).rejects.toMatchObject({ message: 'bad json' });
  });
});
