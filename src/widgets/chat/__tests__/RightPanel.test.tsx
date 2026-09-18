// src/widgets/chat/__tests__/RightPanel.test.tsx
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../../../features/artifacts/useArtifacts', () => ({
  useArtifacts: vi.fn(() => ({ artifacts: [], loading: false, refresh: vi.fn() })),
}));
// 批次 C 详情视图用例：ArtifactViewer 拉内容走 useArtifactContent，mock 掉
vi.mock('../../../features/artifacts/useArtifactContent', () => ({
  useArtifactContent: vi.fn(() => ({ content: null, loading: false })),
}));

// C3 (2026-08-15): RightPanel → ProgressSection → TaskTreeSection 渲染链挂载即调
// Wave 4 (2026-09-06): PlanCardList 已删,历史编排记录移除
// Fix #2 (2026-09-06): PlanCard 移至 Chat.tsx 主对话区域,ProgressSection 仅保留 TaskTreeSection
// orchRunClient.listRuns();mock 掉避免真实 IPC 抛错。
vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: { listRuns: vi.fn().mockResolvedValue([]) },
}));

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { RightPanel } from '../RightPanel';

const props = {
  iteration: 0,
  streamingState: null,
  toolCalls: [],
  isLoading: false,
  sessionId: 'sess_001',
};

const arts: Artifact[] = [
  {
    id: 'a1',
    session_id: 'sess_001',
    tool_call_id: null,
    path: '/tmp/a.md',
    name: 'a.md',
    kind: 'markdown',
    size: 100,
    created_at: 1,
  },
];

function resetStore(overrides: Partial<ReturnType<typeof useRightPanelStore.getState>> = {}) {
  useRightPanelStore.setState({
    open: true,
    tab: 'progress',
    maximized: false,
    selectedArtifactId: null,
    seenArtifactCount: {},
    ...overrides,
  });
}

describe('RightPanel', () => {
  beforeEach(() => {
    localStorage.clear();
    resetStore();
  });

  it('renders both tabs', () => {
    render(<RightPanel {...props} />);
    expect(screen.getByText('进度')).toBeInTheDocument();
    expect(screen.getByText('产物')).toBeInTheDocument();
  });

  it('switches to Artifacts tab via store', () => {
    render(<RightPanel {...props} />);
    fireEvent.click(screen.getByText('产物'));
    expect(useRightPanelStore.getState().tab).toBe('artifacts');
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });

  // P0-3 (UI 优化方案 2026-09-12): 左边缘拖拽手柄存在 + 默认宽度 320px
  it('renders resize handle with default width', () => {
    render(<RightPanel {...props} variant="push" />);
    const handle = screen.getByTestId('right-panel-resize-handle');
    expect(handle).toBeInTheDocument();
    // 默认 320px (localStorage 无持久化值)；push 模式下结构为 aside → 内容容器 → 手柄
    const aside = handle.parentElement?.parentElement;
    expect(aside?.getAttribute('data-testid')).toBe('right-panel');
    expect(aside?.style.width).toBe('320px');
  });

  describe('close button (right-panel R1: 写 store)', () => {
    it('list view renders close button with correct aria-label', () => {
      render(<RightPanel {...props} />);
      expect(screen.getByRole('button', { name: '关闭右侧面板' })).toBeInTheDocument();
    });

    it('clicking close button closes panel via store', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
      expect(useRightPanelStore.getState().open).toBe(false);
      expect(localStorage.getItem('right-panel-open')).toBe('0');
    });

    it('clicking close button in Artifacts tab closes panel', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByText('产物'));
      fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
      expect(useRightPanelStore.getState().open).toBe(false);
    });
  });

  describe('right-panel R1 批次 C: 跨会话清理', () => {
    it('session switch clears selected artifact', async () => {
      const { useArtifacts } = await import('../../../features/artifacts/useArtifacts');
      vi.mocked(useArtifacts).mockReturnValue({
        artifacts: arts,
        loading: false,
        refresh: vi.fn(),
      });
      const { rerender } = render(<RightPanel {...props} sessionId="sess_001" />);
      useRightPanelStore.getState().selectArtifact('a1');
      expect(useRightPanelStore.getState().selectedArtifactId).toBe('a1');
      rerender(<RightPanel {...props} sessionId="sess_002" />);
      expect(useRightPanelStore.getState().selectedArtifactId).toBeNull();
    });

    it('selected artifact resolves to detail view, back clears selection', async () => {
      const { useArtifactContent } = await import(
        '../../../features/artifacts/useArtifactContent'
      );
      vi.mocked(useArtifactContent).mockReturnValue({
        content: { ok: true, kind: 'markdown', content: '# Hello' },
        loading: false,
      });
      const { useArtifacts } = await import('../../../features/artifacts/useArtifacts');
      vi.mocked(useArtifacts).mockReturnValue({
        artifacts: arts,
        loading: false,
        refresh: vi.fn(),
      });
      // 注意：RightPanel 挂载 effect 会清理"上一会话"的选中产物，
      // 因此选中必须在挂载后设置（与生产链路一致：chip 点击发生在挂载后）。
      // store 直改不在 React 事件内，需 act() 触发同步刷新。
      render(<RightPanel {...props} />);
      act(() => {
        useRightPanelStore.getState().selectArtifact('a1');
      });
      expect(screen.getByRole('button', { name: '返回' })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: '返回' }));
      expect(useRightPanelStore.getState().selectedArtifactId).toBeNull();
    });
  });

  describe('right-panel R1 批次 D: 最大化 + 宽度档位', () => {
    it('maximize toggle flips store state', () => {
      render(<RightPanel {...props} variant="push" />);
      const btn = screen.getByTestId('right-panel-maximize-toggle');
      fireEvent.click(btn);
      expect(useRightPanelStore.getState().maximized).toBe(true);
      expect(screen.getByTestId('right-panel').getAttribute('data-maximized')).toBe('true');
      fireEvent.click(screen.getByTestId('right-panel-maximize-toggle'));
      expect(useRightPanelStore.getState().maximized).toBe(false);
    });

    it('Escape exits maximize', () => {
      useRightPanelStore.setState({ maximized: true });
      render(<RightPanel {...props} variant="push" />);
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(useRightPanelStore.getState().maximized).toBe(false);
    });

    it('maximized panel fills container (width 100%)', () => {
      useRightPanelStore.setState({ maximized: true });
      render(<RightPanel {...props} variant="push" />);
      expect(screen.getByTestId('right-panel').style.width).toBe('100%');
      // 最大化时隐藏 resize 手柄
      expect(screen.queryByTestId('right-panel-resize-handle')).not.toBeInTheDocument();
    });

    it('applies width presets and persists', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByTestId('right-panel-preset-L'));
      expect(localStorage.getItem('right-panel-width')).toBe('560');
    });

    it('overlay variant (窄屏) 不显示最大化按钮', () => {
      render(<RightPanel {...props} variant="overlay" />);
      expect(screen.queryByTestId('right-panel-maximize-toggle')).not.toBeInTheDocument();
    });
  });

  describe('right-panel R1 批次 B: 产物自动唤起开关', () => {
    it('bell toggle only on artifacts tab, flips localStorage flag', () => {
      render(<RightPanel {...props} />);
      expect(
        screen.queryByTestId('right-panel-auto-open-toggle'),
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByText('产物'));
      const bell = screen.getByTestId('right-panel-auto-open-toggle');
      expect(bell).toBeInTheDocument();
      fireEvent.click(bell);
      expect(localStorage.getItem('right-panel-auto-open')).toBe('0');
      fireEvent.click(bell);
      expect(localStorage.getItem('right-panel-auto-open')).toBe('1');
    });
  });
});
