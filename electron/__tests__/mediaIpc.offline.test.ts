import { afterEach, describe, expect, it, vi } from 'vitest';

import { registerMediaIpc } from '../mediaIpc';

const fetchMock = vi.fn();
vi.mock('node-fetch', () => ({ default: (...args: unknown[]) => fetchMock(...args) }));
vi.mock('../logger', () => ({ logger: { info: vi.fn(), error: vi.fn() } }));

function handler() {
  let invoke: (...args: unknown[]) => unknown = () => {};
  registerMediaIpc((_name, fn) => { invoke = fn; }, () => 'http://127.0.0.1:8765', () => 'test-token');
  return invoke;
}

afterEach(() => fetchMock.mockReset());

describe('Electron21 multipart compatibility', () => {
  it('encodes boundary, UTF8 filename and exact binary bytes without WebStreams', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ media_ref: 'm', api_url: '/m' }) });
    const data = new Uint8Array([0, 255, 13, 10, 128, 42]);
    await handler()(null, { buffer: data.buffer, filename: '测试"a.bin', contentType: 'application/octet-stream' });
    const options = fetchMock.mock.calls[0][1];
    const boundary = options.headers['Content-Type'].split('boundary=')[1];
    expect(Buffer.isBuffer(options.body)).toBe(true);
    expect(options.headers['Content-Length']).toBe(String(options.body.length));
    expect(options.headers['X-Sage-Local-Authorization']).toBe('Bearer test-token');
    const prefix = Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="测试%22a.bin"\r\nContent-Type: application/octet-stream\r\n\r\n`);
    expect(options.body.equals(Buffer.concat([prefix, Buffer.from(data), Buffer.from(`\r\n--${boundary}--\r\n`)]))).toBe(true);
  });

  it('accepts MediaRecorder content type parameters', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
    await handler()(null, { buffer: new ArrayBuffer(1), filename: 'recording.webm', contentType: 'audio/webm;codecs=opus' });
    expect(fetchMock.mock.calls[0][1].body.toString()).toContain('Content-Type: audio/webm;codecs=opus');
  });

  it.each([
    { filename: 'a\r\nInjected: yes', contentType: 'text/plain' },
    { filename: 'a', contentType: 'text/plain\r\nInjected: yes' },
  ])('rejects header injection before sending $filename', async (metadata) => {
    await expect(handler()(null, { ...metadata, buffer: new ArrayBuffer(1) })).rejects.toThrow(/Invalid/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
