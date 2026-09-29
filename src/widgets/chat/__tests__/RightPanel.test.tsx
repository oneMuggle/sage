// src/widgets/chat/__tests__/RightPanel.test.tsx
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

const { fetchChangesSpy } = vi.hoisted(() => ({
  fetchChangesSpy: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../../features/artifacts/useArtifacts', () => ({
  useArtifacts: vi.fn(() => ({ artifacts: [], loading: false, refresh: vi.fn() })),
}));
// 批次 C 详情视图用例：ArtifactViewer 拉内容走 useArtifactContent，mock 掉
vi.mock('../../../features/artifacts/useArtifactContent', () => ({
  useArtifactContent: vi.fn(() => ({ content: null, loading: false })),
}));
// R4 批次 B: 变更预取 —— mock store，验证会话切换时 fetch 被触发
vi.mock('../../../features/changes/changesListStore', () => {
  const state = { bySession: {}, fetch: fetchChangesSpy };
  const hook = Object.assign((selector: (s: typeof state) => unknown) => selector(state), {
    getState: () => state,
  });
  return { useChangesListStore: hook };
});

// C3 (2026-08-15): RightPanel → ProgressSection → TaskTreeSection 渲染链挂载即调
// Wave 4 (2026-09-06): PlanCardList 已删,历史编排记录移除
// Fix #2 (2026-09-06): PlanCard 移至 Chat.tsx 主对话区域,ProgressSection 仅保留 TaskTreeSection
// orchRunClient.listRuns();mock 掉避免真实 IPC 抛错。
vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: { listRuns: vi.fn().mockResolvedValue([]) },
}));

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { useStore } from '../../../shared/lib/store';
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
    fireEvent.click(screen.getByRole('button', { name: /产物/ }));
    expect(useRightPanelStore.getState().tab).toBe('artifacts');
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });

  // P0-3 (UI 优化方案 2026-09-12): 左边缘拖拽手柄存在 + 默认宽度
  // 2026-09-29 面板密度调整：默认宽度 320 → 360（5 个 Tab 不再挤在一起）
  it('renders resize handle with default width', () => {
    render(<RightPanel {...props} variant="push" />);
    const handle = screen.getByTestId('right-panel-resize-handle');
    expect(handle).toBeInTheDocument();
    // 默认 360px (localStorage 无持久化值)；push 模式下结构为 aside → 内容容器 → 手柄
    const aside = handle.parentElement?.parentElement;
    expect(aside?.getAttribute('data-testid')).toBe('right-panel');
    expect(aside?.style.width).toBe('360px');
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
      fireEvent.click(screen.getByRole('button', { name: /产物/ }));
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
      const { useArtifactContent } = await import('../../../features/artifacts/useArtifactContent');
      vi.mocked(useArtifactContent).mockReturnValue({
        content: { ok: true, kind: 'markdown', content: '# Hello' },
        loading: false,
        // win7 分支签名差异：useArtifactContent 额外返回 refresh
        refresh: vi.fn(),
      } as never);
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
      fireEvent.click(screen.getByTestId('right-panel-options-toggle'));
      fireEvent.click(screen.getByTestId('right-panel-preset-L'));
      expect(localStorage.getItem('right-panel-width')).toBe('720');
    });

    it('overlay variant (窄屏) 不显示最大化按钮', () => {
      render(<RightPanel {...props} variant="overlay" />);
      expect(screen.queryByTestId('right-panel-maximize-toggle')).not.toBeInTheDocument();
    });
  });

  // 2026-09-29 面板密度调整：档位 + 自动展开开关从 Tab 行平铺收进「选项」浮层
  describe('right-panel 面板密度: 选项浮层', () => {
    it('档位按钮默认收起，点开浮层后可见', () => {
      render(<RightPanel {...props} />);
      expect(screen.queryByTestId('right-panel-preset-L')).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId('right-panel-options-toggle'));
      expect(screen.getByTestId('right-panel-preset-S')).toBeInTheDocument();
      expect(screen.getByTestId('right-panel-preset-M')).toBeInTheDocument();
      expect(screen.getByTestId('right-panel-preset-L')).toBeInTheDocument();
    });

    it('点浮层外收起', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByTestId('right-panel-options-toggle'));
      expect(screen.getByTestId('right-panel-preset-L')).toBeInTheDocument();
      fireEvent.mouseDown(document.body);
      expect(screen.queryByTestId('right-panel-preset-L')).not.toBeInTheDocument();
    });

    it('Esc 收起浮层', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByTestId('right-panel-options-toggle'));
      expect(screen.getByTestId('right-panel-preset-L')).toBeInTheDocument();
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.queryByTestId('right-panel-preset-L')).not.toBeInTheDocument();
    });

    it('应用档位后浮层自动收起', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByTestId('right-panel-options-toggle'));
      fireEvent.click(screen.getByTestId('right-panel-preset-M'));
      expect(localStorage.getItem('right-panel-width')).toBe('520');
      expect(screen.queryByTestId('right-panel-preset-M')).not.toBeInTheDocument();
    });

    it('默认档位（360=S）在浮层内高亮', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByTestId('right-panel-options-toggle'));
      expect(screen.getByTestId('right-panel-preset-S')).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByTestId('right-panel-preset-L')).toHaveAttribute('aria-pressed', 'false');
    });
  });

  describe('right-panel R1 批次 B: 产物自动唤起开关', () => {
    // 2026-09-29: 开关从顶栏铃铛按钮移入「选项」浮层，需先展开浮层
    it('auto-open toggle only on artifacts tab, flips localStorage flag', () => {
      render(<RightPanel {...props} />);
      fireEvent.click(screen.getByRole('button', { name: /产物/ }));
      expect(screen.queryByTestId('right-panel-auto-open-toggle')).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId('right-panel-options-toggle'));
      const row = screen.getByTestId('right-panel-auto-open-toggle');
      expect(row).toBeInTheDocument();
      fireEvent.click(row);
      expect(localStorage.getItem('right-panel-auto-open')).toBe('0');
      fireEvent.click(row);
      expect(localStorage.getItem('right-panel-auto-open')).toBe('1');
    });
  });

  // 2026-09-29 面板密度调整: 详情页保留 Tab 行（此前是死胡同）
  describe('right-panel 面板密度: 产物详情页保留 Tab 行', () => {
    async function renderWithArtifactSelected() {
      const { useArtifactContent } = await import('../../../features/artifacts/useArtifactContent');
      vi.mocked(useArtifactContent).mockReturnValue({
        content: { ok: true, kind: 'markdown', content: '# Hello' },
        loading: false,
        // win7 分支签名差异：useArtifactContent 额外返回 refresh
        refresh: vi.fn(),
      } as never);
      const { useArtifacts } = await import('../../../features/artifacts/useArtifacts');
      vi.mocked(useArtifacts).mockReturnValue({
        artifacts: arts,
        loading: false,
        refresh: vi.fn(),
      });
      render(<RightPanel {...props} />);
      act(() => {
        useRightPanelStore.getState().selectArtifact('a1');
      });
    }

    it('详情页仍渲染 5 个 Tab', async () => {
      await renderWithArtifactSelected();
      expect(screen.getByRole('button', { name: '返回' })).toBeInTheDocument();
      expect(screen.getByText('进度')).toBeInTheDocument();
      expect(screen.getByText('目录')).toBeInTheDocument();
      expect(screen.getByText('预览')).toBeInTheDocument();
    });

    it('详情页高亮「产物」Tab', async () => {
      await renderWithArtifactSelected();
      // 该 fixture 有 1 个产物，Tab 的 aria-label 是「产物 (1)」
      expect(screen.getByRole('button', { name: /^产物/ }).className).toContain('border-primary');
    });

    it('详情页点其他 Tab 即离开详情并切换', async () => {
      await renderWithArtifactSelected();
      fireEvent.click(screen.getByRole('button', { name: '进度' }));
      expect(useRightPanelStore.getState().selectedArtifactId).toBeNull();
      expect(useRightPanelStore.getState().tab).toBe('progress');
    });

    it('详情页点「产物」Tab 回列表（不是回详情）', async () => {
      await renderWithArtifactSelected();
      fireEvent.click(screen.getByRole('button', { name: /^产物/ }));
      expect(useRightPanelStore.getState().selectedArtifactId).toBeNull();
      expect(useRightPanelStore.getState().tab).toBe('artifacts');
    });
  });

  describe('right-panel R2 批次 B: overlay 抽屉三件套', () => {
    it('overlay 打开时渲染遮罩，点击遮罩关闭面板', () => {
      render(<RightPanel {...props} variant="overlay" />);
      const backdrop = screen.getByTestId('right-panel-overlay-backdrop');
      expect(backdrop).toBeInTheDocument();
      fireEvent.click(backdrop);
      expect(useRightPanelStore.getState().open).toBe(false);
    });

    it('overlay 关闭态遮罩不可交互（pointer-events-none）', () => {
      useRightPanelStore.setState({ open: false });
      render(<RightPanel {...props} variant="overlay" />);
      expect(screen.getByTestId('right-panel-overlay-backdrop').className).toContain(
        'pointer-events-none',
      );
    });

    it('overlay 打开时 Esc 关闭面板', () => {
      render(<RightPanel {...props} variant="overlay" />);
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(useRightPanelStore.getState().open).toBe(false);
    });

    it('push 模式无遮罩，Esc 不关面板', () => {
      render(<RightPanel {...props} variant="push" />);
      expect(screen.queryByTestId('right-panel-overlay-backdrop')).not.toBeInTheDocument();
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(useRightPanelStore.getState().open).toBe(true);
    });
  });

  describe('right-panel R4 批次 B: 变更预取', () => {
    it('挂载即按会话预取变更列表', () => {
      render(<RightPanel {...props} />);
      expect(fetchChangesSpy).toHaveBeenCalledWith('sess_001');
    });

    it('会话切换时重新预取', () => {
      const { rerender } = render(<RightPanel {...props} sessionId="sA" />);
      fetchChangesSpy.mockClear();
      rerender(<RightPanel {...props} sessionId="sB" />);
      expect(fetchChangesSpy).toHaveBeenCalledWith('sB');
    });
  });
});

// 对标 U1（ZCode ConversationTurnNavigator）：目录 Tab 顶部渲染轮次导航分组。
// useConversationTurns 从 store.messages 派生——灌入两条 user 消息后断言
// 「轮次」分组出现且条目齐全（点击定位走 messageJumpStore，RightPanel 集成层
// 只验证渲染与分组的出现）。
describe('RightPanel — 轮次导航（U1 对标）', () => {
  it('目录 Tab 顶部渲染轮次导航分组，条目数为全部 user 消息数', () => {
    const now = Date.now();
    useStore.setState({
      messages: [
        {
          id: 'u-msg-1',
          session_id: 'sess_001',
          role: 'user',
          content: '第一轮提问',
          created_at: now,
        },
        {
          id: 'u-msg-2',
          session_id: 'sess_001',
          role: 'user',
          content: '第二轮提问',
          created_at: now + 1,
        },
      ] as never,
    });

    render(<RightPanel {...props} sessionId="sess_001" />);
    fireEvent.click(screen.getByText('目录'));

    expect(screen.getByTestId('turn-list-heading')).toBeInTheDocument();
    expect(screen.getByTestId('turn-item-1')).toBeInTheDocument();
    expect(screen.getByTestId('turn-item-2')).toBeInTheDocument();
  });
});
