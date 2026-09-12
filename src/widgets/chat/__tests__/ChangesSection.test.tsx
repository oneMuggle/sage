// src/widgets/chat/__tests__/ChangesSection.test.tsx
// U1 变更面板组件测试 — workspaceApi 全 mock,不发真实请求。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type {
  WorkspaceChanges,
  WorkspaceCheckpoint,
  WorkspaceDiff,
} from '../../../shared/api/workspaceApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { confirmDialog } from '../../../shared/ui/ConfirmDialog/confirmService';
import { ChangesSection } from '../changes/ChangesSection';

const mockGetChanges = vi.fn<() => Promise<WorkspaceChanges>>();
const mockGetChangeDiff = vi.fn<(path?: string, staged?: boolean) => Promise<WorkspaceDiff>>();
const mockRevertChanges =
  vi.fn<
    (
      ...args: unknown[]
    ) => Promise<{ reverted: string[]; errors: Array<{ path: string; error: string }> }>
  >();
const mockRevertHunks = vi.fn<(...args: unknown[]) => Promise<{ revertedHunks: number }>>();
const mockListCheckpoints = vi.fn<(...args: unknown[]) => Promise<WorkspaceCheckpoint[]>>();
const mockCreateCheckpoint =
  vi.fn<
    (
      ...args: unknown[]
    ) => Promise<{ checkpointId: string; files: number; skipped: string[]; bytes: number }>
  >();
const mockRestoreCheckpoint = vi.fn<(...args: unknown[]) => Promise<{ restored: number }>>();

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: vi.fn(async () => true),
}));
vi.mock('../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    getChanges: () => mockGetChanges(),
    getChangeDiff: (path?: string, staged?: boolean) => mockGetChangeDiff(path, staged),
    revertChanges: (...args: unknown[]) => mockRevertChanges(...args),
    revertChangeHunks: (...args: unknown[]) => mockRevertHunks(...args),
    listCheckpoints: (...args: unknown[]) => mockListCheckpoints(...args),
    createCheckpoint: (...args: unknown[]) => mockCreateCheckpoint(...args),
    restoreCheckpoint: (...args: unknown[]) => mockRestoreCheckpoint(...args),
  },
}));

const TWO_HUNK_DIFF = [
  'diff --git a/src/app.ts b/src/app.ts',
  'index 111..222 100644',
  '--- a/src/app.ts',
  '+++ b/src/app.ts',
  '@@ -1,3 +1,4 @@',
  ' a1',
  '+a2-new',
  ' a3',
  ' a4',
  '@@ -10,3 +11,4 @@',
  ' b1',
  '+b2-new',
  ' b3',
  ' b4',
].join('\n');

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
    render(
      <I18nProvider>
        <ChangesSection sessionId={null} />
      </I18nProvider>,
    );
    expect(screen.getByText(/请先选择会话/)).toBeInTheDocument();
  });

  it('renders change list with branch and ahead/behind', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );

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
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText(/工作区干净/)).toBeInTheDocument();
    });
  });

  it('shows error message on failure', async () => {
    mockGetChanges.mockRejectedValue(new Error('git 不可用'));
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );
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
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );

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
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('notes.md')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('notes.md'));
    await waitFor(() => {
      expect(screen.getByText(/未跟踪文件/)).toBeInTheDocument();
    });
  });

  it('U19: 勾选 hunk 后撤销所选（0-based 序号传后端）', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockGetChangeDiff.mockResolvedValue({ diff: TWO_HUNK_DIFF, truncated: false });
    mockRevertHunks.mockResolvedValue({ revertedHunks: 1 });
    vi.mocked(confirmDialog).mockClear();
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('src/app.ts')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('src/app.ts'));

    // 两个 hunk,两个勾选框
    await waitFor(() => {
      expect(screen.getByTestId('hunk-checkbox-0')).toBeInTheDocument();
    });
    expect(screen.getByTestId('hunk-checkbox-1')).toBeInTheDocument();

    // 未勾选时按钮禁用
    expect(screen.getByTestId('revert-hunks-button')).toBeDisabled();

    fireEvent.click(screen.getByTestId('hunk-checkbox-0'));
    fireEvent.click(screen.getByTestId('revert-hunks-button'));

    await waitFor(() => {
      expect(mockRevertHunks).toHaveBeenCalledWith('s1', 'src/app.ts', [0]);
    });
    expect(confirmDialog).toHaveBeenCalled();
  });

  it('U19: 文件清单提供撤销入口（受跟踪 → revertChanges，未跟踪 → 删除）', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockRevertChanges.mockResolvedValue({ reverted: ['src/app.ts'], errors: [] });
    vi.mocked(confirmDialog).mockClear();
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('src/app.ts')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: '撤销 src/app.ts' }));
    await waitFor(() => {
      expect(mockRevertChanges).toHaveBeenCalledWith('s1', ['src/app.ts'], false);
    });

    fireEvent.click(screen.getByRole('button', { name: '删除 notes.md' }));
    await waitFor(() => {
      expect(mockRevertChanges).toHaveBeenCalledWith('s1', ['notes.md'], true);
    });
  });

  it("U2': 检查点区默认收起，展开后创建快照并刷新列表", async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockListCheckpoints
      .mockResolvedValueOnce([
        {
          checkpointId: '20260908-120000-ab12cd',
          createdAt: '2026-09-08T12:00:00',
          bytes: 2048,
          files: 3,
        },
      ])
      .mockResolvedValue([
        {
          checkpointId: '20260908-120000-ab12cd',
          createdAt: '2026-09-08T12:00:00',
          bytes: 2048,
          files: 3,
        },
        {
          checkpointId: '20260908-130000-ef34ab',
          createdAt: '2026-09-08T13:00:00',
          bytes: 4096,
          files: 5,
        },
      ]);
    mockCreateCheckpoint.mockResolvedValue({
      checkpointId: '20260908-130000-ef34ab',
      files: 5,
      skipped: [],
      bytes: 4096,
    });
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('src/app.ts')).toBeInTheDocument();
    });
    // 默认收起:检查点标题可见,列表未加载
    expect(screen.queryByTestId('checkpoint-row')).not.toBeInTheDocument();
    expect(mockListCheckpoints).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('checkpoint-toggle'));
    await waitFor(() => {
      expect(screen.getByTestId('checkpoint-row')).toBeInTheDocument();
    });
    expect(mockListCheckpoints).toHaveBeenCalledWith('s1');
    expect(screen.getByText(/20260908-120000-ab12cd/)).toBeInTheDocument();

    // 手动创建 → 列表刷新
    fireEvent.click(screen.getByTestId('create-checkpoint-button'));
    await waitFor(() => {
      expect(mockCreateCheckpoint).toHaveBeenCalledWith('s1');
    });
    await waitFor(() => {
      expect(screen.getByText(/20260908-130000-ef34ab/)).toBeInTheDocument();
    });
  });

  it("U2': 恢复快照需 confirm，成功后刷新变更与快照列表", async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockListCheckpoints.mockResolvedValue([
      {
        checkpointId: '20260908-120000-ab12cd',
        createdAt: '2026-09-08T12:00:00',
        bytes: 2048,
        files: 3,
      },
    ]);
    mockRestoreCheckpoint.mockResolvedValue({ restored: 3 });
    vi.mocked(confirmDialog).mockClear();
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('src/app.ts')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('checkpoint-toggle'));
    await waitFor(() => {
      expect(screen.getByTestId('checkpoint-row')).toBeInTheDocument();
    });

    const callsBefore = mockGetChanges.mock.calls.length;
    fireEvent.click(screen.getByTestId('restore-checkpoint-20260908-120000-ab12cd'));
    await waitFor(() => {
      expect(mockRestoreCheckpoint).toHaveBeenCalledWith('s1', '20260908-120000-ab12cd');
    });
    // 恢复后变更清单 + 快照列表都刷新
    await waitFor(() => {
      expect(mockGetChanges.mock.calls.length).toBeGreaterThan(callsBefore);
      expect(mockListCheckpoints.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    expect(confirmDialog).toHaveBeenCalled();
  });

  it("U2': 未绑定工作区时不渲染检查点区", async () => {
    mockGetChanges.mockRejectedValue(new Error('当前会话尚未绑定工作区'));
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText(/尚未绑定工作区/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId('checkpoint-toggle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('create-checkpoint-button')).not.toBeInTheDocument();
  });

  // ---- P1-3.8 分栏 diff 视图 ----

  it('P1-3.8: 打开 diff 后默认 unified 视图,切换按钮可切换到 split 视图', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockGetChangeDiff.mockResolvedValue({ diff: TWO_HUNK_DIFF, truncated: false });
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );
    // 打开文件 diff
    await waitFor(() => expect(screen.getByText('src/app.ts')).toBeInTheDocument());
    fireEvent.click(screen.getByText('src/app.ts'));
    // unified 视图默认显示:hunk 列表可见
    await waitFor(() => expect(screen.getByTestId('revert-hunks-button')).toBeInTheDocument());
    // split 视图未激活:SplitDiff 组件不在文档中
    expect(screen.queryByTestId('split-diff')).not.toBeInTheDocument();

    // 点击分栏切换
    const toggle = screen.getByTestId('toggle-split-view');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(toggle);

    // split 视图激活:SplitDiff 渲染;unified 的 hunk 列表消失
    await waitFor(() => expect(screen.getByTestId('split-diff')).toBeInTheDocument());
    expect(screen.queryByTestId('revert-hunks-button')).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    // 再次点击切回 unified
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByTestId('revert-hunks-button')).toBeInTheDocument());
    expect(screen.queryByTestId('split-diff')).not.toBeInTheDocument();
  });

  it('P1-3.8: 切换文件时 split 视图自动重置为 unified', async () => {
    mockGetChanges.mockResolvedValue(sampleChanges);
    mockGetChangeDiff.mockResolvedValue({ diff: TWO_HUNK_DIFF, truncated: false });
    render(
      <I18nProvider>
        <ChangesSection sessionId="s1" />
      </I18nProvider>,
    );
    await waitFor(() => expect(screen.getByText('src/app.ts')).toBeInTheDocument());
    // 打开第一个文件,切到 split
    fireEvent.click(screen.getByText('src/app.ts'));
    await waitFor(() => expect(screen.getByTestId('toggle-split-view')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('toggle-split-view'));
    await waitFor(() => expect(screen.getByTestId('split-diff')).toBeInTheDocument());

    // 返回 → 打开另一个文件 → split 应自动重置为 unified
    fireEvent.click(screen.getByLabelText('返回变更列表'));
    await waitFor(() => expect(screen.getByText('src/new.py')).toBeInTheDocument());
    fireEvent.click(screen.getByText('src/new.py'));
    await waitFor(() => {
      expect(screen.getByTestId('toggle-split-view')).toBeInTheDocument();
    });
    expect(screen.getByTestId('toggle-split-view')).toHaveAttribute('aria-pressed', 'false');
    // 未激活 split-diff (该文件是新增,unified 视图显示"未跟踪文件:暂无 diff 内容"等文案)
    expect(screen.queryByTestId('split-diff')).not.toBeInTheDocument();
  });
});
