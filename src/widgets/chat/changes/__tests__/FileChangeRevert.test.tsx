// src/widgets/chat/changes/__tests__/FileChangeRevert.test.tsx
//
// P2-1 撤销可反悔：两处补强
// 1. 逐文件回滚此前**零二次确认**（P1-8 全量替换时漏网 —— 它既不在设置页，
//    也不是行内删除按钮）。回滚是不可逆写操作，必须显式确认。
// 2. 新增「全部回滚 (N)」：apply_patch 一次动 N 个文件时，逐个回滚要点 N 次。
//
// 撤销的语义是对准「这次改动」而不是「这次审批」：审批本身已有「拒绝」按钮，
// 用户想反悔的是已经落盘的副作用。这与记忆的 undo-write 对称。
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChangesListStore } from '../../../../features/changes/changesListStore';
import type { WorkspaceChanges, WorkspaceDiff } from '../../../../shared/api/workspaceApi';
import { resolveConfirm } from '../../../../shared/ui/ConfirmDialog/confirmService';
import { FileChangeCard, FileChangeCards } from '../FileChangeCard';

const mockGetChangeDiff = vi.fn<(s: string, p: string) => Promise<WorkspaceDiff>>();
const mockGetChanges = vi.fn<(s: string) => Promise<WorkspaceChanges>>();
const mockRevertChanges = vi.fn<
  (
    s: string,
    paths: string[],
    deleteUntracked?: boolean,
  ) => Promise<{
    reverted: string[];
    errors: Array<{ path: string; error: string }>;
  }>
>();

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

vi.mock('../../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    getChangeDiff: (s: string, p: string) => mockGetChangeDiff(s, p),
    getChanges: (s: string) => mockGetChanges(s),
    revertChanges: (s: string, p: string[], d?: boolean) => mockRevertChanges(s, p, d),
  },
}));

vi.mock('../../ShikiCodeBlock', () => ({
  ShikiCodeBlock: ({ children }: { children: string }) => (
    <pre data-testid="shiki-stub">{children}</pre>
  ),
}));

const SAMPLE: WorkspaceChanges = {
  branch: 'main',
  upstream: '',
  ahead: 0,
  behind: 0,
  clean: false,
  changes: [
    { indexStatus: '', worktreeStatus: 'M', path: 'src/app.ts', insertions: 1, deletions: 0 },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  useChangesListStore.setState({ bySession: { s1: SAMPLE }, errors: {}, loadingBy: {} } as never);
  mockGetChanges.mockResolvedValue(SAMPLE);
  mockGetChangeDiff.mockResolvedValue({ diff: 'x', truncated: false } as unknown as WorkspaceDiff);
  mockRevertChanges.mockResolvedValue({ reverted: ['src/app.ts'], errors: [] });
});

/** confirmDialog 是 Promise，宿主在测试里手动应答 */
async function clickAndConfirm(btn: HTMLElement, confirmed: boolean) {
  await act(async () => {
    fireEvent.click(btn);
  });
  await waitFor(() => expect(mockRevertChanges).not.toHaveBeenCalled());
  await act(async () => {
    resolveConfirm(confirmed);
  });
}

describe('逐文件回滚需要显式确认 (P2-1)', () => {
  it('取消确认时不调用 API', async () => {
    render(<FileChangeCard sessionId="s1" path="src/app.ts" />);
    await clickAndConfirm(screen.getByTestId('file-change-revert'), false);
    expect(mockRevertChanges).not.toHaveBeenCalled();
  });

  it('确认后执行回滚', async () => {
    render(<FileChangeCard sessionId="s1" path="src/app.ts" />);
    await clickAndConfirm(screen.getByTestId('file-change-revert'), true);
    // 第三个参数是 deleteUntracked（默认 false，不删未跟踪文件）
    await waitFor(() =>
      expect(mockRevertChanges).toHaveBeenCalledWith('s1', ['src/app.ts'], false),
    );
  });
});

describe('批量回滚 (P2-1)', () => {
  it('折叠态也提供「全部回滚」入口 —— 不想逐个展开也能反悔', () => {
    render(<FileChangeCards sessionId="s1" paths={['a.ts', 'b.ts', 'c.ts']} />);
    expect(screen.getByTestId('file-change-group')).toBeInTheDocument();
    expect(screen.getByTestId('file-change-revert-all')).toBeInTheDocument();
    expect(screen.getByText('全部回滚 (3)')).toBeInTheDocument();
  });

  it('展开态同样提供入口 —— 行为不因用户先展开就变松', async () => {
    render(<FileChangeCards sessionId="s1" paths={['a.ts']} />);
    expect(screen.queryByTestId('file-change-group')).not.toBeInTheDocument();
    expect(screen.getByTestId('file-change-revert-all')).toBeInTheDocument();
  });

  it('一次调用回滚全部文件，而不是逐个', async () => {
    render(<FileChangeCards sessionId="s1" paths={['a.ts', 'b.ts', 'c.ts']} />);
    await clickAndConfirm(screen.getByTestId('file-change-revert-all'), true);
    await waitFor(() => expect(mockRevertChanges).toHaveBeenCalledTimes(1));
    expect(mockRevertChanges).toHaveBeenCalledWith('s1', ['a.ts', 'b.ts', 'c.ts'], false);
  });

  it('取消确认时不调用 API', async () => {
    render(<FileChangeCards sessionId="s1" paths={['a.ts', 'b.ts']} />);
    await clickAndConfirm(screen.getByTestId('file-change-revert-all'), false);
    expect(mockRevertChanges).not.toHaveBeenCalled();
  });

  it('部分失败如实上报「已回滚 N 个 + 失败清单」，不谎称全部成功', async () => {
    mockRevertChanges.mockResolvedValue({
      reverted: ['a.ts'],
      errors: [{ path: 'b.ts', error: '文件被占用' }],
    });
    render(<FileChangeCards sessionId="s1" paths={['a.ts', 'b.ts']} />);
    await clickAndConfirm(screen.getByTestId('file-change-revert-all'), true);
    await waitFor(() => expect(mockRevertChanges).toHaveBeenCalled());
    // toast.error 被调用即视为如实上报；关键是不能走成功分支
    const { toast } = await import('sonner');
    await waitFor(() => {
      const calls = vi.mocked(toast.error).mock.calls;
      expect(calls.length).toBeGreaterThan(0);
      expect(String(calls[0][0])).toContain('已回滚 1 个');
      expect(String(calls[0][0])).toContain('b.ts');
    });
  });
});

// 未跟踪文件（git porcelain `?`）没有可恢复的旧版本，后端只在显式
// delete_untracked=true 时才肯删。聊天流里 write_file / apply_patch 新建的
// 文件全是这种 —— 不带上这个标记，回滚必然失败且只回一句内部 flag 报错。
describe('未跟踪文件（本次新建）的回滚语义', () => {
  const NEW_FILE: WorkspaceChanges = {
    ...SAMPLE,
    changes: [
      { indexStatus: '?', worktreeStatus: '?', path: 'new.ts', insertions: 3, deletions: 0 },
    ],
  };

  it('逐文件回滚：显式授权删除，且确认框说清「回滚即删除」', async () => {
    useChangesListStore.setState({
      bySession: { s1: NEW_FILE },
      errors: {},
      loadingBy: {},
    } as never);
    render(<FileChangeCard sessionId="s1" path="new.ts" />);
    await clickAndConfirm(screen.getByTestId('file-change-revert'), true);
    await waitFor(() => expect(mockRevertChanges).toHaveBeenCalledWith('s1', ['new.ts'], true));
  });

  it('批量回滚：一个新建文件就带上删除授权，并在确认框里报出个数', async () => {
    useChangesListStore.setState({
      bySession: {
        s1: {
          ...SAMPLE,
          changes: [
            { indexStatus: '', worktreeStatus: 'M', path: 'a.ts', insertions: 1, deletions: 0 },
            { indexStatus: '?', worktreeStatus: '?', path: 'b.ts', insertions: 2, deletions: 0 },
          ],
        },
      },
      errors: {},
      loadingBy: {},
    } as never);
    render(<FileChangeCards sessionId="s1" paths={['a.ts', 'b.ts']} />);
    await clickAndConfirm(screen.getByTestId('file-change-revert-all'), true);
    // 标志整批生效：后端只对确实是未跟踪的路径删文件，a.ts 仍走 git checkout
    await waitFor(() =>
      expect(mockRevertChanges).toHaveBeenCalledWith('s1', ['a.ts', 'b.ts'], true),
    );
  });
});
