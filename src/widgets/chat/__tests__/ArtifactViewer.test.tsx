// src/widgets/chat/__tests__/ArtifactViewer.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../features/artifacts/useArtifactContent', () => ({ useArtifactContent: vi.fn() }));
vi.mock('../../../features/artifacts/artifactApi', () => ({ revealArtifact: vi.fn() }));

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';
import { ArtifactViewer } from '../artifacts/ArtifactViewer';

const sample: Artifact = {
  id: 'a1', session_id: 'sess_001', tool_call_id: null, path: '/tmp/test.md',
  name: 'test.md', kind: 'markdown', size: 1024, created_at: 1,
};

describe('ArtifactViewer', () => {
  it('renders breadcrumb', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Hello' }, loading: false,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/产物/)).toBeInTheDocument();
    expect(screen.getByText('test.md')).toBeInTheDocument();
  });

  it('calls onBack', () => {
    vi.mocked(useArtifactContent).mockReturnValue({ content: null, loading: false });
    const onBack = vi.fn();
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={onBack} />);
    fireEvent.click(screen.getByRole('button', { name: /返回/ }));
    expect(onBack).toHaveBeenCalled();
  });

  it('renders markdown content', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Title' }, loading: false,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/Title/)).toBeInTheDocument();
  });

  it('renders image', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'image', data_url: 'data:image/png;base64,xxx' }, loading: false,
    });
    render(<ArtifactViewer artifact={{ ...sample, kind: 'image' }} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,xxx');
  });

  it('shows error state', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: false, error: 'File not found' }, loading: false,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/File not found/)).toBeInTheDocument();
  });

  it('renders csv cells without trailing carriage return from CRLF input', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'csv', content: 'a,b\r\n1,2\r\n' }, loading: false,
    });
    const { container } = render(
      <ArtifactViewer artifact={{ ...sample, kind: 'csv' }} sessionId="sess_001" onBack={() => {}} />,
    );
    expect(screen.getByText('2')).toBeInTheDocument();
    const cells = container.querySelectorAll('th, td');
    expect(cells.length).toBeGreaterThan(0);
    cells.forEach((c) => expect(c.textContent).not.toContain('\r'));
  });
});
