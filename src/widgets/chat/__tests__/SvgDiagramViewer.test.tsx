import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SvgDiagramViewer } from '../SvgDiagramViewer';

const props = { apiUrl: '/api/v1/media/m1', mimeType: 'image/svg+xml', title: 'd' };

describe('SvgDiagramViewer', () => {
  it('renders the diagram image and toolbar', async () => {
    render(<SvgDiagramViewer {...props} />);
    await waitFor(() => expect(screen.getByTestId('svg-diagram-img')).toBeTruthy());
    expect(screen.getByTestId('svg-diagram-download-svg')).toBeTruthy();
    expect(screen.getByTestId('svg-diagram-fullscreen-open')).toBeTruthy();
  });

  it('zooms in and out via toolbar', () => {
    render(<SvgDiagramViewer {...props} />);
    expect(screen.getByTestId('svg-diagram-zoom-label').textContent).toBe('100%');
    fireEvent.click(screen.getByTestId('svg-diagram-zoom-in'));
    expect(screen.getByTestId('svg-diagram-zoom-label').textContent).toBe('125%');
    fireEvent.click(screen.getByTestId('svg-diagram-zoom-out'));
    expect(screen.getByTestId('svg-diagram-zoom-label').textContent).toBe('100%');
  });

  it('opens and closes fullscreen', () => {
    render(<SvgDiagramViewer {...props} />);
    fireEvent.click(screen.getByTestId('svg-diagram-fullscreen-open'));
    expect(screen.getByTestId('svg-diagram-fullscreen')).toBeTruthy();
    fireEvent.click(screen.getByTestId('svg-diagram-fullscreen-close'));
    expect(screen.queryByTestId('svg-diagram-fullscreen')).toBeNull();
  });

  it('shows error placeholder when the image fails to load', () => {
    render(<SvgDiagramViewer {...props} />);
    fireEvent.error(screen.getByTestId('svg-diagram-img'));
    expect(screen.getByTestId('svg-diagram-error')).toBeTruthy();
  });

  it('renders caption when provided', () => {
    render(<SvgDiagramViewer {...props} caption="流程示意图" />);
    expect(screen.getByTestId('svg-diagram-caption').textContent).toBe('流程示意图');
  });
});
