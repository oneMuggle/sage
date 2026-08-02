// src/widgets/chat/__tests__/ArtifactsSection.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { ArtifactsSection } from '../artifacts/ArtifactsSection';

const arts: Artifact[] = [
  { id: 'a1', session_id: 's', tool_call_id: null, path: '/a.md', name: 'a.md', kind: 'markdown', size: 100, created_at: 1 },
  { id: 'a2', session_id: 's', tool_call_id: null, path: '/b.py', name: 'b.py', kind: 'code', size: 200, created_at: 2 },
];
const base = { loading: false, sessionId: 'sess_001', onRefresh: () => {}, onSelect: () => {}, onReveal: () => {} };

describe('ArtifactsSection', () => {
  it('shows empty state', () => {
    render(<ArtifactsSection artifacts={[]} {...base} />);
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });

  it('renders artifact list', () => {
    render(<ArtifactsSection artifacts={arts} {...base} />);
    expect(screen.getByText('a.md')).toBeInTheDocument();
    expect(screen.getByText('b.py')).toBeInTheDocument();
  });

  it('calls onRefresh', () => {
    const onRefresh = vi.fn();
    render(<ArtifactsSection artifacts={[]} {...base} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole('button', { name: /刷新/ }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('asks to select session when sessionId null', () => {
    render(<ArtifactsSection artifacts={[]} {...base} sessionId={null} />);
    expect(screen.getByText(/请先选择会话/)).toBeInTheDocument();
  });
});
