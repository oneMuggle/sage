// src/widgets/chat/__tests__/RightPanel.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../features/artifacts/useArtifacts', () => ({
  useArtifacts: vi.fn(() => ({ artifacts: [], loading: false, refresh: vi.fn() })),
}));

// Progress tab 渲染链含 PlanCardList，挂载即调 orchRunClient.listRuns()；
// mock 掉避免 unhandled rejection（coverage 模式下 vitest 会因此 exit 1）。
vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: { listRuns: vi.fn().mockResolvedValue([]) },
}));

import { RightPanel } from '../RightPanel';

const props = {
  open: true,
  onToggle: vi.fn(),
  iteration: 0,
  streamingState: null,
  toolCalls: [],
  isLoading: false,
  sessionId: 'sess_001',
};

describe('RightPanel', () => {
  it('renders both tabs', () => {
    render(<RightPanel {...props} />);
    expect(screen.getByText('Progress')).toBeInTheDocument();
    expect(screen.getByText('Artifacts')).toBeInTheDocument();
  });

  it('switches to Artifacts tab', () => {
    render(<RightPanel {...props} />);
    fireEvent.click(screen.getByText('Artifacts'));
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });
});

describe('RightPanel - close button', () => {
  it('list view (Progress tab) renders close button with correct aria-label', () => {
    render(<RightPanel {...props} />);
    expect(screen.getByRole('button', { name: '关闭右侧面板' })).toBeInTheDocument();
  });

  it('clicking close button in Progress tab invokes onToggle', () => {
    const onToggle = vi.fn();
    render(<RightPanel {...props} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('clicking close button in Artifacts tab invokes onToggle', () => {
    const onToggle = vi.fn();
    render(<RightPanel {...props} onToggle={onToggle} />);
    fireEvent.click(screen.getByText('Artifacts'));
    fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
