// src/widgets/chat/__tests__/ArtifactRow.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { ArtifactRow } from '../artifacts/ArtifactRow';

const sample: Artifact = {
  id: 'a1', session_id: 'sess_001', tool_call_id: null, path: '/tmp/test.md',
  name: 'test.md', kind: 'markdown', size: 1024, created_at: 1722500000000,
};

describe('ArtifactRow', () => {
  it('renders filename and formatted size', () => {
    render(<ArtifactRow artifact={sample} onSelect={() => {}} />);
    expect(screen.getByText('test.md')).toBeInTheDocument();
    expect(screen.getByText(/1\.0 KB/)).toBeInTheDocument();
  });

  it('calls onSelect when clicked', () => {
    const onSelect = vi.fn();
    render(<ArtifactRow artifact={sample} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith(sample);
  });
});
