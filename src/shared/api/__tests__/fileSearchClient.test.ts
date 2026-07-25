import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

vi.mock('../officeApi', () => ({
  officeApi: {
    listDocuments: vi.fn(),
  },
}));

import { invoke } from '../desktopInvoke';
import { fileSearchClient, type FileSearchKind } from '../fileSearchClient';
import { officeApi } from '../officeApi';

const FS_RESULTS = [
  { path: '/w/foo.txt', name: 'foo.txt', size: 100 },
  { path: '/w/sub/bar.md', name: 'bar.md', size: 200 },
];

const OFFICE_DOCS = {
  documents: [
    {
      id: '1',
      doc_type: 'ppt' as const,
      name: 'proposal.pptx',
      file_path: '/w/office/ppt/1/proposal.pptx',
      file_size_bytes: 5000,
      workspace_path: '/w',
      original_filename: null,
      generated_filename: 'proposal.pptx',
      status: 'parsed',
      created_at: 0,
      updated_at: 0,
      metadata: { file_size_bytes: 5000, page_count: 5 },
    },
    {
      id: '2',
      doc_type: 'word' as const,
      name: 'notes.docx',
      file_path: '/w/office/word/2/notes.docx',
      file_size_bytes: 3000,
      workspace_path: '/w',
      original_filename: null,
      generated_filename: 'notes.docx',
      status: 'parsed',
      created_at: 0,
      updated_at: 0,
      metadata: { file_size_bytes: 3000, page_count: 2 },
    },
  ],
};

describe('fileSearchClient.search', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    vi.mocked(officeApi.listDocuments).mockReset();
  });

  it('returns fs results with kind="file" by default', async () => {
    vi.mocked(invoke).mockResolvedValue(FS_RESULTS);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(OFFICE_DOCS as never);
    const out = await fileSearchClient.search('foo');
    expect(out.length).toBeGreaterThan(0);
    const txt = out.find((r) => r.name === 'foo.txt');
    expect(txt?.kind).toBe<FileSearchKind>('file');
  });

  it('infers kind from path extension for fs results', async () => {
    vi.mocked(invoke).mockResolvedValue([{ path: '/w/a.pptx', name: 'a.pptx', size: 1 }]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue({ documents: [] } as never);
    const out = await fileSearchClient.search('a');
    expect(out[0].kind).toBe('office-ppt');
  });

  it('merges office docs as office-* kinds', async () => {
    vi.mocked(invoke).mockResolvedValue([]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(OFFICE_DOCS as never);
    const out = await fileSearchClient.search('prop');
    const ppt = out.find((r) => r.kind === 'office-ppt');
    expect(ppt?.name).toBe('proposal.pptx');
    expect(ppt?.path).toBe('/w/office/ppt/1/proposal.pptx');
  });

  it('office query filter is case-insensitive substring match on name', async () => {
    vi.mocked(invoke).mockResolvedValue([]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(OFFICE_DOCS as never);
    const out = await fileSearchClient.search('PROP');
    expect(out.some((r) => r.name === 'proposal.pptx')).toBe(true);
  });

  it('deduplicates by path (office wins over fs when same path)', async () => {
    vi.mocked(invoke).mockResolvedValue([
      { path: '/w/office/ppt/1/proposal.pptx', name: 'proposal.pptx', size: 100 },
    ]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(OFFICE_DOCS as never);
    const out = await fileSearchClient.search('prop');
    const matches = out.filter((r) => r.path === '/w/office/ppt/1/proposal.pptx');
    expect(matches).toHaveLength(1);
    expect(matches[0].kind).toBe('office-ppt');
  });

  it('falls back to fs-only when office listDocuments fails', async () => {
    vi.mocked(invoke).mockResolvedValue(FS_RESULTS);
    vi.mocked(officeApi.listDocuments).mockRejectedValue(new Error('office down'));
    const out = await fileSearchClient.search('foo');
    expect(out.length).toBe(2);
    expect(out.every((r) => r.kind === 'file')).toBe(true);
  });

  it('preserves order: office results before fs results', async () => {
    vi.mocked(invoke).mockResolvedValue(FS_RESULTS);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(OFFICE_DOCS as never);
    const out = await fileSearchClient.search('');
    const officeIdx = out.findIndex((r) => r.kind !== 'file');
    const fileIdx = out.findIndex((r) => r.kind === 'file');
    expect(officeIdx).toBeLessThan(fileIdx);
    expect(officeIdx).toBe(0);
  });

  it('passes AbortSignal to fs search but ignores for office list', async () => {
    const ctrl = new AbortController();
    vi.mocked(invoke).mockResolvedValue([]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue({ documents: [] } as never);
    await fileSearchClient.search('q', { signal: ctrl.signal });
    expect(invoke).toHaveBeenCalledWith(
      'workspace_search_files',
      { query: 'q', limit: 20 },
      expect.objectContaining({ signal: ctrl.signal }),
    );
  });
});
