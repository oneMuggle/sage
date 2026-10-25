// .tsx although it renders nothing: tsconfig.electron.json only type-checks .ts files under
// electron/, and this file imports src/ modules (a different compiler setup).
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  const { wireFetch } = await import('./fetchStub');
  return { ...actual, default: wireFetch };
});

import { officeApi } from '../../../src/shared/api/officeApi';

import { received, releaseBackend, strictBody, useBackend } from './harness';

/**
 * The 10 Office commands #857 silently dropped, exercised the way the renderer calls them:
 * officeApi method -> real bridge -> fake backend. Every Office request model on the backend is
 * extra="forbid", and the fake backend says 422 to any key it would not accept.
 */

const O = '/api/v1/office';
const WS = 'C:/work/space';
const FILE = 'C:/work/space/report.pdf';
const READ_KEYS = ['workspace_path', 'file_path'] as const;
const READ_REQ = { workspace_path: WS, file_path: FILE };

afterEach(releaseBackend);

describe('Office commands over the real bridge (restored after #857)', () => {
  it.each([
    ['readPdfData', () => officeApi.readPdfData(READ_REQ), '/pdf/data'],
    ['readWordData', () => officeApi.readWordData(READ_REQ), '/word/data'],
    ['recalcExcel', () => officeApi.recalcExcel(READ_REQ), '/excel/recalc'],
    [
      'convertLegacyImport',
      () => officeApi.convertLegacyImport(READ_REQ),
      '/import/convert-legacy',
    ],
    ['readPdfForm', () => officeApi.readPdfForm(READ_REQ), '/pdf/read-form'],
  ] as const)('%s -> POST %s with workspace_path + file_path only', async (_name, call, path) => {
    useBackend([
      {
        method: 'POST',
        path: `${O}${path}`,
        reply: strictBody(READ_KEYS, () => ({ json: { ok: true } })),
      },
    ]);
    await expect(call()).resolves.toMatchObject({ ok: true });
    expect(received('POST', `${O}${path}`)[0].body).toEqual({
      workspace_path: WS,
      file_path: FILE,
    });
  });

  it('pdfPreview forwards task_id', async () => {
    useBackend([
      {
        method: 'POST',
        path: `${O}/pdf-preview`,
        reply: strictBody(['workspace_path', 'file_path', 'task_id'], () => ({
          json: { ok: true },
        })),
      },
    ]);
    await officeApi.pdfPreview({ ...READ_REQ, task_id: 't-1' });
    expect(received('POST', `${O}/pdf-preview`)[0].body).toEqual({ ...READ_REQ, task_id: 't-1' });
  });

  it('templateThumbnail leaves the unset template field out', async () => {
    useBackend([
      {
        method: 'POST',
        path: `${O}/templates/thumbnail`,
        reply: strictBody(['workspace_path', 'template_id', 'workspace_template'], () => ({
          json: { ok: true },
        })),
      },
    ]);
    await officeApi.templateThumbnail({ workspace_path: WS, template_id: 'resume' });
    expect(received('POST', `${O}/templates/thumbnail`)[0].body).toEqual({
      workspace_path: WS,
      template_id: 'resume',
    });
  });

  it('getCapabilities is a GET and only asks for a re-probe when forced', async () => {
    useBackend([
      { method: 'GET', path: `${O}/capabilities`, reply: () => ({ json: { ok: true } }) },
    ]);
    await officeApi.getCapabilities();
    await officeApi.getCapabilities(true);
    const calls = received('GET', `${O}/capabilities`);
    expect(calls.map((c) => c.query)).toEqual(['', '?force=true']);
  });

  it('diffSnapshot is a GET with both ids in the path', async () => {
    useBackend([
      {
        method: 'GET',
        path: `${O}/doc/d1/snapshots/s1/diff`,
        reply: () => ({ json: { changes: [] } }),
      },
    ]);
    await officeApi.diffSnapshot('d1', 's1');
    expect(received('GET', `${O}/doc/d1/snapshots/s1/diff`)).toHaveLength(1);
  });

  it('fillPdfForm hands the backend the PDF field names exactly as typed', async () => {
    // The backend matches `data` keys against the form's field names verbatim and ignores the rest,
    // so a renamed key means a silently empty field. These are real AcroForm naming styles.
    const data = {
      firstName: 'Ann',
      Name: 'Ann Lee',
      'Text Field 1': 'x',
      date_of_birth: '1990-01-02',
    };
    useBackend([
      {
        method: 'POST',
        path: `${O}/pdf/fill-form`,
        reply: strictBody(
          ['workspace_path', 'template_path', 'output_filename', 'data', 'flatten'],
          () => ({ json: { output_path: 'x', filename: 'filled.pdf', file_size_bytes: 1 } }),
        ),
      },
    ]);
    await officeApi.fillPdfForm({
      workspace_path: WS,
      template_path: FILE,
      output_filename: 'filled.pdf',
      data,
      flatten: true,
    });
    expect(received('POST', `${O}/pdf/fill-form`)[0].body).toEqual({
      workspace_path: WS,
      template_path: FILE,
      output_filename: 'filled.pdf',
      data,
      flatten: true,
    });
  });
});
