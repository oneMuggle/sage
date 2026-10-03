import { beforeEach, describe, expect, it, vi } from 'vitest';

// Same mocking scheme as invoke.test.ts: keep node-fetch's named exports real, stub only `fetch`.
vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return { ...actual, default: vi.fn() };
});

import nodeFetch from 'node-fetch';
import { invokeBackend } from '../invoke';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;
const BACKEND = 'http://127.0.0.1:8765';

/** Drive a command through the real invokeBackend and return what would hit the wire. */
async function wire(cmd: string, args: Record<string, unknown>) {
  mockedFetch.mockReset();
  mockedFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ ok: true }) });
  await invokeBackend(cmd, args, BACKEND);
  const [url, init] = mockedFetch.mock.calls[0] as [string, { method: string; body?: string }];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : JSON.parse(init.body),
  };
}

// The args below are exactly what src/shared/api/officeApi.ts passes to invoke().
const WS = 'C:/work/space';
const FILE = 'C:/work/space/report.pdf';

describe('Office IPC commands (restored after #857)', () => {
  beforeEach(() => mockedFetch.mockReset());

  it.each([
    ['office_pdf_data', '/api/v1/office/pdf/data'],
    ['office_word_data', '/api/v1/office/word/data'],
    ['office_excel_recalc', '/api/v1/office/excel/recalc'],
    ['office_import_convert_legacy', '/api/v1/office/import/convert-legacy'],
    ['office_pdf_read_form', '/api/v1/office/pdf/read-form'],
  ])(
    '%s -> POST %s with workspace_path + file_path only (backend model is extra=forbid)',
    async (cmd, path) => {
      const r = await wire(cmd, { workspacePath: WS, filePath: FILE });
      expect(r).toEqual({
        url: `${BACKEND}${path}`,
        method: 'POST',
        body: { workspace_path: WS, file_path: FILE },
      });
    },
  );

  it('office_pdf_preview forwards task_id', async () => {
    const r = await wire('office_pdf_preview', {
      workspacePath: WS,
      filePath: FILE,
      task_id: 't-1',
    });
    expect(r).toEqual({
      url: `${BACKEND}/api/v1/office/pdf-preview`,
      method: 'POST',
      body: { workspace_path: WS, file_path: FILE, task_id: 't-1' },
    });
  });

  it('office_template_thumbnail omits the template field that is not set', async () => {
    const r = await wire('office_template_thumbnail', {
      workspacePath: WS,
      templateId: 'resume',
      workspaceTemplate: undefined,
    });
    expect(r.url).toBe(`${BACKEND}/api/v1/office/templates/thumbnail`);
    expect(r.body).toEqual({ workspace_path: WS, template_id: 'resume' });
  });

  it('office_capabilities is a GET and only adds ?force=true when asked', async () => {
    expect(await wire('office_capabilities', {})).toEqual({
      url: `${BACKEND}/api/v1/office/capabilities`,
      method: 'GET',
      body: undefined,
    });
    expect((await wire('office_capabilities', { force: true })).url).toBe(
      `${BACKEND}/api/v1/office/capabilities?force=true`,
    );
  });

  it('office_snapshot_diff is a body-less GET with both ids encoded into the path', async () => {
    const r = await wire('office_snapshot_diff', { docId: 'doc 1', snapshotId: 'snap/2' });
    expect(r).toEqual({
      url: `${BACKEND}/api/v1/office/doc/doc%201/snapshots/snap%2F2/diff`,
      method: 'GET',
      body: undefined,
    });
  });

  it('office_pdf_fill_form keeps PDF field names verbatim while the top level is snake_case', async () => {
    // Real AcroForm names: camelCase, Capitalized, with spaces, already snake_case. The backend
    // matches them exactly and silently ignores misses, so any renaming would leave fields blank.
    const data = {
      firstName: 'Ann',
      Name: 'Ann Lee',
      'Text Field 1': 'x',
      date_of_birth: '1990-01-02',
    };
    const r = await wire('office_pdf_fill_form', {
      workspacePath: WS,
      templatePath: FILE,
      outputFilename: 'report-filled.pdf',
      data,
      flatten: true,
    });
    expect(r.method).toBe('POST');
    expect(r.url).toBe(`${BACKEND}/api/v1/office/pdf/fill-form`);
    expect(r.body).toEqual({
      workspace_path: WS,
      template_path: FILE,
      output_filename: 'report-filled.pdf',
      data,
      flatten: true,
    });
  });
});
