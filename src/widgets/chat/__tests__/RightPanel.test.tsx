// src/widgets/chat/__tests__/RightPanel.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../features/artifacts/useArtifacts', () => ({
  useArtifacts: vi.fn(() => ({ artifacts: [], loading: false, refresh: vi.fn() })),
}));

// C3 (2026-08-15): RightPanel → ProgressSection → TaskTreeSection 渲染链挂载即调
// Wave 4 (2026-09-06): PlanCardList 已删,历史编排记录移除
// Fix #2 (2026-09-06): PlanCard 移至 Chat.tsx 主对话区域,ProgressSection 仅保留 TaskTreeSection
// orchRunClient.listRuns();mock 掉避免真实 IPC 抛错。
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
    expect(screen.getByText('进度')).toBeInTheDocument();
    expect(screen.getByText('产物')).toBeInTheDocument();
  });

  it('switches to Artifacts tab', () => {
    render(<RightPanel {...props} />);
    fireEvent.click(screen.getByText('产物'));
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });

  // P0-3 (UI 优化方案 2026-09-12): 左边缘拖拽手柄存在 + 默认宽度 320px
  it('renders resize handle with default width', () => {
    render(<RightPanel {...props} />);
    const handle = screen.getByTestId('right-panel-resize-handle');
    expect(handle).toBeInTheDocument();
    // 默认 320px (localStorage 无持久化值)
    const aside = handle.parentElement;
    expect(aside?.style.width).toBe('320px');
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
    fireEvent.click(screen.getByText('产物'));
    fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
