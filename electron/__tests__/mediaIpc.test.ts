/**
 * Tests for media:upload-attachment IPC handler.
 *
 * Verifies that backend errors (4xx/5xx with error_code + error fields)
 * are properly propagated to the renderer as thrown Error messages.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';

// Mock node-fetch before importing the module under test
vi.mock('node-fetch', () => ({
  default: vi.fn(),
}));

// Mock formdata-node
vi.mock('formdata-node', () => ({
  FormData: class MockFormData {
    append = vi.fn();
  },
  Blob: class MockBlob {
    constructor(
      public parts: unknown[],
      public options?: { type?: string },
    ) {}
  },
}));

import fetch from 'node-fetch';
import { registerMediaIpc } from '../mediaIpc';

/** Helper to create a mock Response-like object */
function mockResponse(body: string | object, status: number) {
  const bodyStr = typeof body === 'string' ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => JSON.parse(bodyStr),
    text: async () => bodyStr,
  };
}

describe('mediaIpc — media:upload-attachment', () => {
  let handler: (...args: unknown[]) => unknown;
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch = vi.mocked(fetch);

    // Capture the handler registered by registerMediaIpc
    const mockRegister = vi.fn((channel: string, h: (...args: unknown[]) => unknown) => {
      handler = h;
    });

    registerMediaIpc(
      mockRegister,
      () => 'http://127.0.0.1:8765',
      () => 'test-auth-token',
    );
  });

  const makePayload = () => ({
    buffer: new ArrayBuffer(100),
    filename: 'test.txt',
    contentType: 'text/plain',
  });

  it('returns media_ref on success (HTTP 200)', async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse({
        media_ref: { id: 'abc123' },
        api_url: '/api/v1/media/abc123',
        text: 'file content',
      }, 200) as unknown as import('node-fetch').Response,
    );

    const result = await handler({}, makePayload()) as { media_ref: { id: string } };
    expect(result.media_ref.id).toBe('abc123');
  });

  it('throws error with backend message on HTTP 415 (unsupported_type)', async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse({
        error_code: 'unsupported_type',
        error: '不支持的文件类型: exe',
      }, 415) as unknown as import('node-fetch').Response,
    );

    await expect(handler({}, makePayload())).rejects.toThrow('不支持的文件类型: exe');
  });

  it('throws error with backend message on HTTP 413 (too_large)', async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse({
        error_code: 'too_large',
        error: '文件过大 (30000000 bytes)，上限 25MB',
      }, 413) as unknown as import('node-fetch').Response,
    );

    await expect(handler({}, makePayload())).rejects.toThrow('文件过大');
  });

  it('throws error with backend message on HTTP 422 (unsupported_encoding)', async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse({
        error_code: 'unsupported_encoding',
        error: '文本文件编码无法识别（支持 UTF-8 / GBK / GB18030）',
      }, 422) as unknown as import('node-fetch').Response,
    );

    await expect(handler({}, makePayload())).rejects.toThrow('文本文件编码无法识别');
  });

  it('throws error with backend message on HTTP 422 (parse_failed)', async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse({
        error_code: 'parse_failed',
        error: '文档解析失败（格式损坏或内容过大）',
      }, 422) as unknown as import('node-fetch').Response,
    );

    await expect(handler({}, makePayload())).rejects.toThrow('文档解析失败');
  });

  it('throws error with backend message on HTTP 504 (parse_timeout)', async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse({
        error_code: 'parse_timeout',
        error: '文档解析超时（文件可能过大或结构异常）',
      }, 504) as unknown as import('node-fetch').Response,
    );

    await expect(handler({}, makePayload())).rejects.toThrow('文档解析超时');
  });

  it('throws generic error when error response has no error field', async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse('Internal Server Error', 500) as unknown as import('node-fetch').Response,
    );

    await expect(handler({}, makePayload())).rejects.toThrow('Upload failed: HTTP 500');
  });

  it('throws error with backend message even on HTTP 200 if json.error present (backward compat)', async () => {
    // Backward compatibility: if backend still returns 200 + {error}, treat as failure
    mockFetch.mockResolvedValueOnce(
      mockResponse({
        error: '未知错误（旧格式）',
      }, 200) as unknown as import('node-fetch').Response,
    );

    await expect(handler({}, makePayload())).rejects.toThrow('未知错误（旧格式）');
  });
});
