// src/widgets/chat/changes/__tests__/ReviewAll.test.tsx
//
// right-panel R6: "全部审查" 汇总视图测试 —— 多文件 unified diff 切分、
// 文件节渲染/折叠、截断横幅、二进制占位;ShikiCodeBlock 打桩为同步 <pre>。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChangesListStore } from '../../../../features/changes/changesListStore';
import type { WorkspaceChanges, WorkspaceDiff } from '../../../../shared/api/workspaceApi';
import { ReviewAll } from '../ReviewAll';
import { splitReviewSections } from '../reviewSections';

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

const TWO_FILE_DIFF = [
  'diff --git a/app.ts b/app.ts',
  'index 111..222 100644',
  '--- a/app.ts',
  '+++ b/app.ts',
  '@@ -1,2 +1,2 @@',
  '-old1',
  '+new1',
  'diff --git a/lib/util.ts b/lib/util.ts',
  'index 333..444 100644',
  '--- a/lib/util.ts',
  '+++ b/lib/util.ts',
  '@@ -1,1 +1,1 @@',
  '-x',
  '+y',
].join('\n');

const STATS: WorkspaceChanges = {
  branch: 'main',
  upstream: '',
  ahead: 0,
  behind: 0,
  clean: false,
  changes: [
    { indexStatus: '', worktreeStatus: 'M', path: 'app.ts', insertions: 1, deletions: 1 },
    { indexStatus: '', worktreeStatus: 'M', path: 'lib/util.ts', insertions: 1, deletions: 1 },
  ],
};

describe('splitReviewSections — 多文件 diff 切分', () => {
  it('按 diff --git 切分,路径取 +++ b/ 侧', () => {
    const sections = splitReviewSections(TWO_FILE_DIFF);
    expect(sections).toHaveLength(2);
    expect(sections[0]?.path).toBe('app.ts');
    expect(sections[1]?.path).toBe('lib/util.ts');
    expect(sections[0]?.diffText).toContain('+new1');
    expect(sections[1]?.diffText).toContain('+y');
  });

  it('删除文件（+++ /dev/null）回落到旧侧路径', () => {
    const deleted = [
      'diff --git a/gone.py b/gone.py',
      'deleted file mode 100644',
      '--- a/gone.py',
      '+++ /dev/null',
      '-bye',
    ].join('\n');
    const sections = splitReviewSections(deleted);
    expect(sections).toHaveLength(1);
    expect(sections[0]?.path).toBe('gone.py');
  });

  it('二进制文件标记 binary', () => {
    const binary = ['diff --git a/img.png b/img.png', 'Binary files a/img.png and b/img.png differ'].join('\n');
    const sections = splitReviewSections(binary);
    expect(sections[0]?.binary).toBe(true);
  });

  it('空输入返回空数组', () => {
    expect(splitReviewSections('')).toEqual([]);
  });
});

describe('ReviewAll — 汇总视图 (right-panel R6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useChangesListStore.setState({ bySession: {}, errors: {}, loadingBy: {} });
    mockGetChangeDiff.mockResolvedValue({ diff: TWO_FILE_DIFF, truncated: false });
  });

  it('渲染逐文件小节 + 合计徽章,默认展开 diff 内容', async () => {
    useChangesListStore.setState({ bySession: { s1: STATS } });
    render(<ReviewAll sessionId="s1" onBack={() => {}} />);

    // 两个文件节 + 锚点 chip + 合计徽章（两文件各 +1/−1）
    await waitFor(() => {
      expect(screen.getByTestId('review-all-toggle-app.ts')).toBeInTheDocument();
    });
    expect(screen.getByTestId('review-all-toggle-lib/util.ts')).toBeInTheDocument();
    expect(screen.getByTestId('review-all-jump-app.ts')).toBeInTheDocument();
    expect(screen.getAllByText('+1')).toHaveLength(2);

    // 内容经 ShikiCodeBlock 打桩渲染,整段 diff 在单个文本节点里
    await waitFor(() => {
      expect(screen.getAllByTestId('shiki-stub')).toHaveLength(2);
    });
    expect(screen.getAllByTestId('review-all-section')).toHaveLength(2);
    expect(screen.getAllByTestId('shiki-stub')[0].textContent).toContain('+new1');
    expect(screen.getAllByTestId('shiki-stub')[1].textContent).toContain('+y');
  });

  it('点击文件头折叠/展开该文件 diff', async () => {
    render(<ReviewAll sessionId="s1" onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTestId('review-all-toggle-app.ts')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getAllByTestId('shiki-stub')).toHaveLength(2);
    });

    // 折叠 app.ts → 其 diff 内容消失,lib/util.ts 不受影响（剩 1 个内容块）
    fireEvent.click(screen.getByTestId('review-all-toggle-app.ts'));
    await waitFor(() => {
      expect(screen.getAllByTestId('shiki-stub')).toHaveLength(1);
    });
    expect(screen.getAllByTestId('shiki-stub')[0].textContent).toContain('+y');

    // 再展开恢复
    fireEvent.click(screen.getByTestId('review-all-toggle-app.ts'));
    await waitFor(() => {
      expect(screen.getAllByTestId('shiki-stub')).toHaveLength(2);
    });
    expect(screen.getAllByTestId('shiki-stub')[0].textContent).toContain('+new1');
  });

  it('截断时显示提示横幅', async () => {
    mockGetChangeDiff.mockResolvedValue({ diff: TWO_FILE_DIFF, truncated: true });
    render(<ReviewAll sessionId="s1" onBack={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/已截断显示前 64KiB/)).toBeInTheDocument();
    });
  });

  it('返回按钮触发 onBack', async () => {
    const onBack = vi.fn();
    render(<ReviewAll sessionId="s1" onBack={onBack} />);
    await waitFor(() => {
      expect(screen.getByTestId('review-all-back')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('review-all-back'));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
