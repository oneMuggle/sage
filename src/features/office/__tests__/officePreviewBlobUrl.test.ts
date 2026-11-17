// officePreviewBlobUrl — data URL 本地解码回归测试。
//
// 2026-11-17: 打包版 CSP 的 connect-src 不含 data:，fetch(data:) 会被拦截；
// docx 高保真改走本地解码后，这里固定解析行为（base64 / percent / 非法输入）。

import { afterEach, describe, expect, it, vi } from 'vitest';

import { dataUrlToBlob, dataUrlToBlobUrl } from '../officePreviewBlobUrl';

const originalCreateObjectURL = URL.createObjectURL;

afterEach(() => {
  URL.createObjectURL = originalCreateObjectURL;
  vi.restoreAllMocks();
});

describe('dataUrlToBlob', () => {
  it('decodes base64 payloads and keeps the mime type', async () => {
    const blob = dataUrlToBlob('data:text/plain;base64,aGVsbG8=');
    expect(blob.type).toBe('text/plain');
    expect(await blob.text()).toBe('hello');
  });

  it('decodes percent-encoded payloads', async () => {
    const blob = dataUrlToBlob('data:text/plain,hello%20world');
    expect(await blob.text()).toBe('hello world');
  });

  it('falls back to application/octet-stream when the mime is missing', () => {
    const blob = dataUrlToBlob('data:;base64,aGVsbG8=');
    expect(blob.type).toBe('application/octet-stream');
  });

  it('throws on malformed input so callers can fall back to structured view', () => {
    expect(() => dataUrlToBlob('not-a-data-url')).toThrow('invalid data URL');
  });
});

describe('dataUrlToBlobUrl', () => {
  it('wraps the decoded blob in an object URL', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:mock-pdf');
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;

    await expect(dataUrlToBlobUrl('data:text/plain;base64,aGVsbG8=')).resolves.toBe(
      'blob:mock-pdf',
    );
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob);
  });
});
