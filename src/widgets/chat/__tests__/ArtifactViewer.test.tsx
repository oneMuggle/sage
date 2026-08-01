// src/widgets/chat/__tests__/ArtifactViewer.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../features/artifacts/useArtifactContent', () => ({ useArtifactContent: vi.fn() }));
vi.mock('../../../features/artifacts/artifactApi', () => ({ revealArtifact: vi.fn() }));

import { ArtifactViewer } from '../artifacts/ArtifactViewer';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';
import type { Artifact } from '../../../features/artifacts/artifactApi';

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
});
