import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '../../../entities/design/designApi';
import { DesignOfficeSourcePicker } from '../DesignOfficeSourcePicker';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

vi.mock('../../../entities/design/designApi', () => ({
  listOfficeSources: vi.fn(),
}));

const wordDoc = {
  doc_id: 'd1',
  doc_type: 'word',
  original_filename: '年度总结.docx',
  generated_filename: '年度总结.docx',
  created_at: 1760000000000,
  size_bytes: 2048,
};

describe('DesignOfficeSourcePicker', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('lists documents of the requested type from the office library', async () => {
    vi.mocked(api.listOfficeSources).mockResolvedValue([wordDoc]);

    render(<DesignOfficeSourcePicker docType="word" onSelect={vi.fn()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('年度总结.docx')).toBeTruthy());
    expect(api.listOfficeSources).toHaveBeenCalledWith('word');
  });

  it('shows the empty state when the library has no matching documents', async () => {
    vi.mocked(api.listOfficeSources).mockResolvedValue([]);

    render(<DesignOfficeSourcePicker docType="excel" onSelect={vi.fn()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('design.officePicker.empty')).toBeTruthy());
  });

  it('surfaces a load failure', async () => {
    vi.mocked(api.listOfficeSources).mockRejectedValue(new Error('boom'));

    render(<DesignOfficeSourcePicker docType="word" onSelect={vi.fn()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('design.officePicker.failed')).toBeTruthy());
  });

  it('emits the picked document', async () => {
    vi.mocked(api.listOfficeSources).mockResolvedValue([wordDoc]);
    const onSelect = vi.fn();

    render(<DesignOfficeSourcePicker docType="word" onSelect={onSelect} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('年度总结.docx')).toBeTruthy());
    fireEvent.click(screen.getByText('年度总结.docx'));

    expect(onSelect).toHaveBeenCalledWith(wordDoc);
  });

  it('closes on demand', async () => {
    vi.mocked(api.listOfficeSources).mockResolvedValue([]);
    const onClose = vi.fn();

    render(<DesignOfficeSourcePicker docType="word" onSelect={vi.fn()} onClose={onClose} />);

    await waitFor(() => expect(screen.getByText('design.officePicker.empty')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'design.officePicker.close' }));
    expect(onClose).toHaveBeenCalled();
  });
});
