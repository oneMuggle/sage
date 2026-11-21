import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDesignStore } from '../../../entities/design/designStore';
import { DesignResourcesPanel } from '../DesignResourcesPanel';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
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
});
