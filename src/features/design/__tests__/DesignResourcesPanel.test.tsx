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

  it('embeds multiple chart series', async () => {
    const embedChart = vi.fn().mockResolvedValue({
      ok: true,
      artifact_id: 'a2',
      version: 2,
      title: 't',
      injected_at_slot: false,
    });
    useDesignStore.setState({ embedChart } as never);

    render(<DesignResourcesPanel projectId="p1" />);

    fireEvent.change(screen.getAllByLabelText('design.resources.seriesName')[0], {
      target: { value: 'Revenue' },
    });
    fireEvent.change(screen.getAllByLabelText('design.resources.values')[0], {
      target: { value: '10, 20' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: /design.resources.addSeries/ }),
    );
    fireEvent.change(screen.getAllByLabelText('design.resources.seriesName')[1], {
      target: { value: 'Cost' },
    });
    fireEvent.change(screen.getAllByLabelText('design.resources.values')[1], {
      target: { value: '5, 8' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'design.resources.embed' }));

    await waitFor(() => expect(embedChart).toHaveBeenCalledTimes(1));
    const chart = vi.mocked(embedChart).mock.calls[0][1] as {
      series: { name: string; y: number[] }[];
    };
    expect(chart.series).toHaveLength(2);
    expect(chart.series[0].name).toBe('Revenue');
    expect(chart.series[1].y).toEqual([5, 8]);
  });
});
