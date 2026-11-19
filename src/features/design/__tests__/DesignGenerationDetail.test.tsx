import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDesignStore } from '../../../entities/design/designStore';
import { DesignVersionPanel } from '../DesignVersionPanel';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

describe('DesignVersionPanel', () => {
  const previewVersion = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    previewVersion.mockClear();
    useDesignStore.setState({
      artifacts: [
        {
          id: 'a2',
          project_id: 'p1',
          version: 2,
          title: 'v2',
          kind: 'html',
          created_at: '2026-11-19T00:00:00Z',
        },
        {
          id: 'a1',
          project_id: 'p1',
          version: 1,
          title: 'v1',
          kind: 'html',
          created_at: '2026-11-19T00:00:00Z',
        },
      ],
      previewArtifact: null,
      loadingProject: false,
      errorProject: null,
      previewVersion,
      restoreVersion: vi.fn().mockResolvedValue(undefined),
    } as never);
  });

  it('shows the newest version first', () => {
    render(<DesignVersionPanel projectId="p1" />);
    const versions = screen.getAllByText(/^v\d+$/);
    expect(versions[0].textContent).toBe('v2');
  });

  it('loads a preview when clicking a version preview button', () => {
    render(<DesignVersionPanel projectId="p1" />);
    fireEvent.click(screen.getAllByRole('button', { name: 'design.version.preview' })[0]);
    expect(previewVersion).toHaveBeenCalledWith('p1', 'a2');
  });

  it('shows the empty state when there are no versions', () => {
    useDesignStore.setState({ artifacts: [] });
    render(<DesignVersionPanel projectId="p1" />);
    expect(screen.getByText('design.version.empty')).toBeTruthy();
  });
});
