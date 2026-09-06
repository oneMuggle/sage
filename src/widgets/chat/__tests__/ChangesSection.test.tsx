// src/widgets/chat/__tests__/ChangesSection.test.tsx
// U1 变更面板组件测试 — workspaceApi 全 mock,不发真实请求。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { WorkspaceChanges, WorkspaceDiff } from '../../../shared/api/workspaceApi';
import { ChangesSection } from '../changes/ChangesSection';

const mockGetChanges = vi.fn<() => Promise<WorkspaceChanges>>();
const mockGetChangeDiff = vi.fn<(path?: string, staged?: boolean) => Promise<WorkspaceDiff>>();

vi.mock('../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    getChanges: () => mockGetChanges(),
    getChangeDiff: (path?: string, staged?: boolean) => mockGetChangeDiff(path, staged),
  },
}));

const sampleChanges: WorkspaceChanges = {
  branch: 'main',
  upstream: 'origin/main',
  ahead: 1,
  behind: 0,
  clean: false,
  changes: [
    { indexStatus: '', worktreeStatus: 'M', path: 'src/app.ts' },
    { indexStatus: 'A', worktreeStatus: '', path: 'src/new.py' },
    { indexStatus: '', worktreeStatus: '?', path: 'notes.md' },
  ],
};

describe('ChangesSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('prompts to select session when sessionId null', () => {
    render(<ChangesSection sessionId={null} />);
    expect(screen.getByText(/请先选择会话/)).toBeInTheDocument();
  });

  it('renders change list with branch and ahead/behind', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    render(<ChangesSection sessionId="s1" />);

    await waitFor(() => {
      expect(screen.getByText('src/app.ts')).toBeInTheDocument();
    });
    expect(screen.getByText('src/new.py')).toBeInTheDocument();
    expect(screen.getByText('notes.md')).toBeInTheDocument();
    expect(screen.getByText('main')).toBeInTheDocument();
    expect(screen.getByText(/↑1 ↓0/)).toBeInTheDocument();
    // 状态徽章
    expect(screen.getByText('已修改')).toBeInTheDocument();
    expect(screen.getByText('新增')).toBeInTheDocument();
    expect(screen.getByText('未跟踪')).toBeInTheDocument();
  });

  it('shows clean state', async () => {
    mockGetChanges.mockResolvedValue({
      branch: 'main',
      upstream: '',
      ahead: 0,
      behind: 0,
      clean: true,
      changes: [],
    });
    render(<ChangesSection sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByText(/工作区干净/)).toBeInTheDocument();
    });
  });

  it('shows error message on failure', async () => {
    mockGetChanges.mockRejectedValue(new Error('git 不可用'));
    render(<ChangesSection sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByText(/git 不可用/)).toBeInTheDocument();
    });
  });

  it('opens diff view on file click and goes back', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockGetChangeDiff.mockResolvedValue({
      diff: '--- a/src/app.ts\n+++ b/src/app.ts\n-old\n+new',
      truncated: false,
    });
    render(<ChangesSection sessionId="s1" />);

    await waitFor(() => {
      expect(screen.getByText('src/app.ts')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('src/app.ts'));

    // diff 视图:文件名标题 + diff 内容经 ShikiCodeBlock 渲染(高亮异步,
    // 断言返回的原始 diff 行)
    await waitFor(() => {
      expect(screen.getByText('+new')).toBeInTheDocument();
    });
    expect(mockGetChangeDiff).toHaveBeenCalledWith('s1', 'src/app.ts');

    // 返回列表
    fireEvent.click(screen.getByRole('button', { name: /返回变更列表/ }));
    await waitFor(() => {
      expect(screen.getByText('src/new.py')).toBeInTheDocument();
    });
  });

  it('shows untracked note for empty diff', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockGetChangeDiff.mockResolvedValue({ diff: '', truncated: false });
    render(<ChangesSection sessionId="s1" />);

    await waitFor(() => {
      expect(screen.getByText('notes.md')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('notes.md'));
    await waitFor(() => {
      expect(screen.getByText(/未跟踪文件/)).toBeInTheDocument();
    });
  });
});
