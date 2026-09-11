/**
 * T14: Unit tests for diagnosticExport.ts IPC logic.
 *
 * Tests cover:
 * - Dialog cancelled → returns { ok: false, code: 'dialog_cancelled' }
 * - Write failure → returns { ok: false, code: 'write_failed' }
 * - Happy path: fetch returns 200 + zip bytes → writeFile → showItemInFolder → returns { ok: true, path }
 * - Backend error (non-200) → returns { ok: false, code: 'backend_error' }
 * - Preview: returns data on 200, returns empty on fetch failure
 */

import { Buffer } from 'buffer';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/* ---------- mocks ---------- */

const mocks = vi.hoisted(() => ({
  dialog: {
    showSaveDialog: vi.fn(),
  },
  shell: {
    showItemInFolder: vi.fn(),
  },
  app: {
    getVersion: vi.fn(() => '0.4.9-test'),
    getPath: vi.fn((name: string) => {
      if (name === 'downloads') return '/mock/downloads';
      return '/tmp';
    }),
  },
  writeFile: vi.fn(),
  fetch: vi.fn(),
}));

vi.mock('electron', () => ({
  app: mocks.app,
  dialog: mocks.dialog,
  shell: mocks.shell,
}));

vi.mock('node:fs/promises', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs/promises')>();
  return {
    ...actual,
    default: { ...actual, writeFile: mocks.writeFile },
    writeFile: mocks.writeFile,
  };
});

vi.mock('node-fetch', () => ({
  default: mocks.fetch,
}));

// diagnosticExport.ts imports `from './logger'` → resolves to electron/logger.ts
// From this test file (electron/__tests__/), the correct relative path is '../logger'.
vi.mock('../logger', () => ({
  logger: {
    warn: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    debug: vi.fn(),
  },
}));

import {
  initDiagnosticExport,
  runDiagnosticExport,
  runDiagnosticPreview,
} from '../diagnosticExport';

beforeEach(() => {
  vi.clearAllMocks();

  // Initialize deps before each test
  initDiagnosticExport({
    backendUrl: 'http://127.0.0.1:8765',
    getAuthToken: () => 'test-token',
  });
});

/* ---------- runDiagnosticExport ---------- */

describe('runDiagnosticExport', () => {
  it('returns dialog_cancelled when user cancels the save dialog', async () => {
    // Fetch succeeds with zip bytes
    mocks.fetch.mockResolvedValue({
      ok: true,
      arrayBuffer: async () => Buffer.from('PK fake zip').buffer,
    });

    // User cancels
    mocks.dialog.showSaveDialog.mockResolvedValue({
      canceled: true,
      filePath: undefined,
    });

    const result = await runDiagnosticExport({
      includePrompts: false,
      includeHostname: false,
    });

    expect(result).toEqual({
      ok: false,
      code: 'dialog_cancelled',
      error: '用户取消保存',
    });
    expect(mocks.writeFile).not.toHaveBeenCalled();
    expect(mocks.shell.showItemInFolder).not.toHaveBeenCalled();
  });

  it('returns write_failed when writeFile throws', async () => {
    mocks.fetch.mockResolvedValue({
      ok: true,
      arrayBuffer: async () => Buffer.from('PK fake zip').buffer,
    });

    mocks.dialog.showSaveDialog.mockResolvedValue({
      canceled: false,
      filePath: '/mock/downloads/test.zip',
    });

    mocks.writeFile.mockRejectedValue(new Error('ENOENT: no such file or directory'));

    const result = await runDiagnosticExport({
      includePrompts: false,
      includeHostname: false,
    });

    expect(result).toEqual({
      ok: false,
      code: 'write_failed',
      error: expect.stringContaining('ENOENT'),
    });
    expect(mocks.shell.showItemInFolder).not.toHaveBeenCalled();
  });

  it('happy path: fetch 200 → writeFile → showItemInFolder → returns ok:true with path', async () => {
    const fakeZipBytes = Buffer.from('PK\x03\x04fake-zip-content');
    mocks.fetch.mockResolvedValue({
      ok: true,
      arrayBuffer: async () => fakeZipBytes.buffer,
    });

    mocks.dialog.showSaveDialog.mockResolvedValue({
      canceled: false,
      filePath: '/mock/downloads/sage-diagnostic-0.4.9-test.zip',
    });

    mocks.writeFile.mockResolvedValue(undefined);

    const result = await runDiagnosticExport({
      includePrompts: true,
      includeHostname: true,
    });

    expect(result).toEqual({
      ok: true,
      path: '/mock/downloads/sage-diagnostic-0.4.9-test.zip',
    });

    // Verify fetch was called with correct URL and auth header
    expect(mocks.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/diagnostic/export'),
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer test-token' },
      }),
    );

    // Verify URL includes query params
    const fetchUrl = mocks.fetch.mock.calls[0][0] as string;
    expect(fetchUrl).toContain('include_prompts=true');
    expect(fetchUrl).toContain('include_hostname=true');

    // Verify writeFile was called with the zip buffer and path
    expect(mocks.writeFile).toHaveBeenCalledWith(
      '/mock/downloads/sage-diagnostic-0.4.9-test.zip',
      expect.any(Buffer),
    );

    // Verify showItemInFolder was called
    expect(mocks.shell.showItemInFolder).toHaveBeenCalledWith(
      '/mock/downloads/sage-diagnostic-0.4.9-test.zip',
    );
  });

  it('returns backend_error when backend returns non-200', async () => {
    mocks.fetch.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'Internal Server Error',
    });

    const result = await runDiagnosticExport({
      includePrompts: false,
      includeHostname: false,
    });

    expect(result).toEqual({
      ok: false,
      code: 'backend_error',
      error: expect.stringContaining('HTTP 500'),
    });

    // Should NOT reach dialog or writeFile
    expect(mocks.dialog.showSaveDialog).not.toHaveBeenCalled();
    expect(mocks.writeFile).not.toHaveBeenCalled();
  });

  it('returns zip_generation_failed when fetch itself throws', async () => {
    mocks.fetch.mockRejectedValue(new Error('ECONNREFUSED'));

    const result = await runDiagnosticExport({
      includePrompts: false,
      includeHostname: false,
    });

    expect(result).toEqual({
      ok: false,
      code: 'zip_generation_failed',
      error: expect.stringContaining('ECONNREFUSED'),
    });
  });
});

/* ---------- runDiagnosticPreview ---------- */

describe('runDiagnosticPreview', () => {
  it('returns preview data on 200', async () => {
    const previewData = {
      count: 42,
      oldestTs: '2026-09-11T10:00:00Z',
      newestTs: '2026-09-11T16:00:00Z',
      sampleUrls: ['http://api/v1/chat/completions'],
      version: '1',
    };

    mocks.fetch.mockResolvedValue({
      ok: true,
      json: async () => previewData,
    });

    const result = await runDiagnosticPreview();
    expect(result).toEqual(previewData);
  });

  it('returns empty preview when fetch fails', async () => {
    mocks.fetch.mockRejectedValue(new Error('network down'));

    const result = await runDiagnosticPreview();

    expect(result).toEqual({
      count: 0,
      oldestTs: null,
      newestTs: null,
      sampleUrls: [],
      version: '1',
    });
  });

  it('returns empty preview when backend returns non-200', async () => {
    mocks.fetch.mockResolvedValue({
      ok: false,
      status: 404,
    });

    const result = await runDiagnosticPreview();

    expect(result).toEqual({
      count: 0,
      oldestTs: null,
      newestTs: null,
      sampleUrls: [],
      version: '1',
    });
  });
});
