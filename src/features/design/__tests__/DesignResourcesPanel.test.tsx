import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '../../../entities/design/designApi';
import { useDesignStore } from '../../../entities/design/designStore';
import { DesignResourcesPanel } from '../DesignResourcesPanel';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

vi.mock('../../../entities/design/designApi', () => ({
  previewSource: vi.fn(),
}));

describe('DesignResourcesPanel', () => {
  beforeEach(() => {
    useDesignStore.setState({
      sourceBinding: null,
      loadingProject: false,
      errorProject: null,
      bindSource: vi.fn(),
      unbindSource: vi.fn(),
      refreshWithSource: vi.fn(),
      embedChart: vi.fn(),
    } as never);
    // jsdom 环境下没有 electronAPI.selectFile，绑定按钮应当禁用
    Object.defineProperty(window, 'electronAPI', { value: undefined, configurable: true });
  });

  it('shows the empty state when no data source is bound', () => {
    render(<DesignResourcesPanel projectId="p1" />);
    expect(screen.getByText('design.resources.sourceNone')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'design.resources.bind' })).toBeDisabled();
  });

  it('shows the chart form with embed disabled when required fields are empty', () => {
    render(<DesignResourcesPanel projectId="p1" />);
    const embedButton = screen.getByRole('button', { name: 'design.resources.embed' });
    expect(embedButton).toBeDisabled();
  });

  it('previews the chosen file before binding', async () => {
    Object.defineProperty(window, 'electronAPI', {
      value: { selectFile: vi.fn().mockResolvedValue('/tmp/data.csv') },
      configurable: true,
    });
    vi.mocked(api.previewSource).mockResolvedValue({
      ok: true,
      kind: 'csv',
      sheets: [
        { name: 'data', row_count: 2, columns: ['name', 'value'], sample: [] },
      ],
    });

    render(<DesignResourcesPanel projectId="p1" />);
    fireEvent.click(screen.getByRole('button', { name: 'design.resources.bind' }));

    await waitFor(() => expect(screen.getByText('name')).toBeTruthy());
    expect(screen.getByText('value')).toBeTruthy();
    expect(api.previewSource).toHaveBeenCalledWith('/tmp/data.csv');

    fireEvent.click(screen.getByRole('button', { name: 'design.resources.confirmBind' }));
    await waitFor(() =>
      expect(useDesignStore.getState().bindSource).toHaveBeenCalledWith(
        'p1',
        '/tmp/data.csv',
      ),
    );
  });
});
