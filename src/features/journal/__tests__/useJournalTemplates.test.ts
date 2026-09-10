import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { journalApi } from '../../../shared/api/journalApi';
import { useJournalTemplates } from '../useJournalTemplates';

vi.mock('../../../shared/api/journalApi', () => ({
  journalApi: {
    parseTemplate: vi.fn(),
    listSpecs: vi.fn(),
    getSpec: vi.fn(),
    validate: vi.fn(),
    fillFromContent: vi.fn(),
  },
}));

interface FakeWindow {
  electronAPI?: {
    office: {
      pickOfficeFile: (
        kind: string,
      ) => Promise<{ path: string; name: string; sizeBytes: number } | null>;
    };
  };
}

const stubSpec = {
  spec_id: 'spec_001',
  template_filename: 'simple.docx',
  body_pt: 12,
  heading_pt: 14,
  line_spacing: 1.5,
  margins_cm: 2.5,
  headings: [{ keyword: '引言', level: 1, expected_pt: 14 }],
  citation_style: 'gb-t-7714',
};

beforeEach(() => {
  vi.clearAllMocks();
  // Reset window.electronAPI stub between tests
  (window as unknown as FakeWindow).electronAPI = {
    office: { pickOfficeFile: vi.fn() },
  };
});

describe('useJournalTemplates', () => {
  it('starts with empty state', () => {
    const { result } = renderHook(() => useJournalTemplates());
    expect(result.current.spec).toBeNull();
    expect(result.current.content.title).toBe('');
    expect(result.current.violations).toEqual([]);
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('pickTemplate opens dialog and parses on success', async () => {
    const picked = { path: '/abs/simple.docx', name: 'simple.docx', sizeBytes: 1024 };
    const pickMock = (window as unknown as FakeWindow).electronAPI!.office.pickOfficeFile;
    (pickMock as ReturnType<typeof vi.fn>).mockResolvedValue(picked);
    vi.mocked(journalApi.parseTemplate).mockResolvedValue({ spec: stubSpec });

    const { result } = renderHook(() => useJournalTemplates());
    await act(async () => {
      const spec = await result.current.pickTemplate();
      expect(spec).toEqual(stubSpec);
    });
    await waitFor(() => expect(result.current.spec).toEqual(stubSpec));
    expect(journalApi.parseTemplate).toHaveBeenCalledWith('/abs/simple.docx');
  });

  it('pickTemplate returns null on user cancel', async () => {
    const pickMock = (window as unknown as FakeWindow).electronAPI!.office.pickOfficeFile;
    (pickMock as ReturnType<typeof vi.fn>).mockResolvedValue(null);

    const { result } = renderHook(() => useJournalTemplates());
    await act(async () => {
      const spec = await result.current.pickTemplate();
      expect(spec).toBeNull();
    });
    expect(result.current.spec).toBeNull();
    expect(journalApi.parseTemplate).not.toHaveBeenCalled();
  });

  it('setContent merges patches immutably', () => {
    const { result } = renderHook(() => useJournalTemplates());
    act(() => result.current.setContent({ title: 'New' }));
    expect(result.current.content.title).toBe('New');
    expect(result.current.content.abstract).toBe('');
    // Section-level field is preserved
    expect(result.current.content.sections.keywords).toBe('');
  });

  it('fillFromContent without spec sets error', async () => {
    const { result } = renderHook(() => useJournalTemplates());
    await act(async () => {
      const r = await result.current.fillFromContent('/ws', 'out.docx');
      expect(r).toBeNull();
    });
    expect(result.current.error).toMatch(/未选择期刊模板/);
    expect(journalApi.fillFromContent).not.toHaveBeenCalled();
  });
});
