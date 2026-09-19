// src/widgets/chat/changes/__tests__/FileChangeCard.test.tsx
//
// right-panel R5: 聊天流文件修改卡片测试 —— workspaceApi 全 mock;
// ShikiCodeBlock 打桩为同步 <pre>（真实组件异步高亮会引入不必要的
// waitFor 等待,卡片测试只关心展开/加载/错误分支与 store 交互）。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChangesListStore } from '../../../../features/changes/changesListStore';
import { useRightPanelStore } from '../../../../features/right-panel/rightPanelStore';
import type { WorkspaceChanges, WorkspaceDiff } from '../../../../shared/api/workspaceApi';
import { FileChangeCard } from '../FileChangeCard';

const mockGetChangeDiff = vi.fn<(sessionId: string, path: string) => Promise<WorkspaceDiff>>();
const mockGetChanges = vi.fn<(sessionId: string) => Promise<WorkspaceChanges>>();

vi.mock('../../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    getChangeDiff: (sessionId: string, path: string) => mockGetChangeDiff(sessionId, path),
    getChanges: (sessionId: string) => mockGetChanges(sessionId),
  },
}));

vi.mock('../../ShikiCodeBlock', () => ({
  ShikiCodeBlock: ({ children }: { children: string }) => (
    <pre data-testid="shiki-stub">{children}</pre>
  ),
}));

const SAMPLE_CHANGES: WorkspaceChanges = {
  branch: 'main',
  upstream: '',
  ahead: 0,
  behind: 0,
  clean: false,
  changes: [
    { indexStatus: '', worktreeStatus: 'M', path: 'src/app.ts', insertions: 12, deletions: 3 },
  ],
};

function resetStores() {
  useChangesListStore.setState({ bySession: {}, errors: {}, loadingBy: {} });
  useRightPanelStore.setState({ open: false, selectedChangePath: null });
}

describe('FileChangeCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStores();
  });

  it('渲染路径与 +/- 行数徽章（缓存命中时不重复拉列表）', () => {
    useChangesListStore.setState({ bySession: { s1: SAMPLE_CHANGES } });
    render(<FileChangeCard sessionId="s1" path="src/app.ts" />);

    expect(screen.getByText('src/app.ts')).toBeInTheDocument();
    expect(screen.getByText('+12')).toBeInTheDocument();
    expect(screen.getByText('−3')).toBeInTheDocument();
    expect(mockGetChanges).not.toHaveBeenCalled();
  });

  it('缓存未命中时拉一次变更列表（多卡片共享 inflight 去重）', async () => {
    mockGetChanges.mockResolvedValue(SAMPLE_CHANGES);
    render(<FileChangeCard sessionId="s1" path="src/app.ts" />);

    await waitFor(() => {
      expect(mockGetChanges).toHaveBeenCalledWith('s1');
    });
    await waitFor(() => {
      expect(screen.getByText('+12')).toBeInTheDocument();
    });
  });

  it('展开就地懒加载 diff（ShikiCodeBlock 渲染）', async () => {
    mockGetChangeDiff.mockResolvedValue({
      diff: 'diff --git a/src/app.ts b/src/app.ts\n--- a/src/app.ts\n+++ b/src/app.ts\n-old\n+new',
      truncated: false,
    });
    render(<FileChangeCard sessionId="s1" path="src/app.ts" />);

    fireEvent.click(screen.getByTestId('file-change-toggle'));
    await waitFor(() => {
      expect(mockGetChangeDiff).toHaveBeenCalledWith('s1', 'src/app.ts');
    });
    await waitFor(() => {
      expect(screen.getByTestId('shiki-stub')).toBeInTheDocument();
    });
    expect(screen.getByTestId('shiki-stub').textContent).toContain('+new');

    // 再点收起 —— diff 已缓存,不重复请求
    fireEvent.click(screen.getByTestId('file-change-toggle'));
    expect(screen.queryByTestId('shiki-stub')).not.toBeInTheDocument();
    expect(mockGetChangeDiff).toHaveBeenCalledTimes(1);
  });

  it('diff 加载失败就地显示错误', async () => {
    mockGetChangeDiff.mockRejectedValue(new Error('git 不可用'));
    render(<FileChangeCard sessionId="s1" path="src/app.ts" />);

    fireEvent.click(screen.getByTestId('file-change-toggle'));
    await waitFor(() => {
      expect(screen.getByText('git 不可用')).toBeInTheDocument();
    });
  });

  it('面板按钮经 selectChange 直达右侧变更 Tab', () => {
    useChangesListStore.setState({ bySession: { s1: SAMPLE_CHANGES } });
    render(<FileChangeCard sessionId="s1" path="src/app.ts" />);

    fireEvent.click(screen.getByTestId('file-change-open-panel'));
    const state = useRightPanelStore.getState();
    expect(state.open).toBe(true);
    expect(state.tab).toBe('changes');
    expect(state.selectedChangePath).toBe('src/app.ts');
  });
});
