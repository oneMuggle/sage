// src/widgets/chat/__tests__/ArtifactRow.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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

  it('copies artifact item JSON to clipboard without triggering row select', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const onSelect = vi.fn();
    render(<ArtifactRow artifact={sample} onSelect={onSelect} />);

    fireEvent.click(screen.getByTestId('artifact-copy-json-a1'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining('"/tmp/test.md"'));
    });
    expect(onSelect).not.toHaveBeenCalled();
  });
});
