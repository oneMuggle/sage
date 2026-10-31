import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  deleteLatexProfile,
  extractLatexProfile,
  listLatexProfiles,
  saveLatexProfile,
  type LatexProfileExtractResult,
  type LatexProfileRecord,
} from '../../../shared/api/latexApi';
import { LatexProfileLibraryPanel } from '../LatexProfileLibraryPanel';

vi.mock('../../../shared/api/latexApi', () => ({
  listLatexProfiles: vi.fn(),
  extractLatexProfile: vi.fn(),
  saveLatexProfile: vi.fn(),
  deleteLatexProfile: vi.fn(),
}));

const mockedList = vi.mocked(listLatexProfiles);
const mockedExtract = vi.mocked(extractLatexProfile);
const mockedSave = vi.mocked(saveLatexProfile);
const mockedDelete = vi.mocked(deleteLatexProfile);

const PROFILE = {
  required_sections: ['Introduction', 'Conclusion'],
  required_metadata: ['title'],
  allowed_page_sizes: ['A4'],
  required_min_pages: null,
  required_max_pages: 20,
  require_embedded_fonts: true,
  min_image_dpi: 300,
  forbidden_commands: ['write18'],
};

const CANDIDATE: LatexProfileExtractResult = {
  ok: true,
  source_path: 'guidelines.txt',
  profile: PROFILE,
  evidence: [
    {
      field: 'required_max_pages',
      value: 20,
      snippet: 'Maximum length: 20 pages.',
      source: 'guidelines.txt',
      page: 1,
      line: 2,
    },
  ],
  warnings: [{ code: 'heuristic_only', message: '请人工确认' }],
  needs_review: true,
};

const RECORD: LatexProfileRecord = {
  name: 'ieee-2026',
  profile: PROFILE,
  source: 'guidelines.txt',
  evidence: [],
  updated_at: '2026-10-31T09:00:00+00:00',
};

beforeEach(() => {
  mockedList.mockResolvedValue({ profiles: [], warnings: [] });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('LatexProfileLibraryPanel', () => {
  it('extracts a guideline and saves the candidate profile', async () => {
    mockedExtract.mockResolvedValue(CANDIDATE);
    mockedSave.mockResolvedValue({ ...RECORD, name: 'guidelines' });

    render(<LatexProfileLibraryPanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-profile-source'), {
      target: { value: 'guidelines.txt' },
    });
    fireEvent.click(screen.getByTestId('latex-profile-extract'));

    await waitFor(() =>
      expect(mockedExtract).toHaveBeenCalledWith('/ws', '/ws/guidelines.txt'),
    );
    expect(screen.getByTestId('latex-profile-candidate')).toHaveTextContent(
      'required_max_pages',
    );
    expect(screen.getByTestId('latex-profile-name')).toHaveValue('guidelines');

    fireEvent.click(screen.getByTestId('latex-profile-save'));

    await waitFor(() =>
      expect(mockedSave).toHaveBeenCalledWith(
        '/ws',
        'guidelines',
        CANDIDATE.profile,
        'guidelines.txt',
        CANDIDATE.evidence,
      ),
    );
    expect(screen.getByTestId('latex-profile-saved')).toHaveTextContent(
      '已保存：guidelines',
    );
  });

  it('deletes a saved profile', async () => {
    mockedList.mockResolvedValue({ profiles: [RECORD], warnings: [] });
    mockedDelete.mockResolvedValue({ ok: true, name: 'ieee-2026' });

    render(<LatexProfileLibraryPanel workspacePath="/ws" />);

    const deleteButton = await screen.findByTestId(
      'latex-profile-delete-ieee-2026',
    );
    fireEvent.click(deleteButton);

    await waitFor(() =>
      expect(mockedDelete).toHaveBeenCalledWith('/ws', 'ieee-2026'),
    );
  });
});
