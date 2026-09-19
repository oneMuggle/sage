// src/widgets/chat/__tests__/VersionHistory.diff.test.tsx
//
// right-panel R3 批次 A: 版本历史 diff 视图 —— 展开对比、SplitDiff 渲染、
// 相同版本提示。SplitDiff mock 成轻量标记（真实组件走 shiki 异步高亮）。

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../../../features/artifacts/artifactApi', () => ({
  listArtifactVersions: vi.fn(),
  getArtifactVersion: vi.fn(),
  readArtifactContent: vi.fn(),
  restoreArtifactVersion: vi.fn(),
}));
vi.mock('../changes/SplitDiff', () => ({
  SplitDiff: ({ diff }: { diff: string }) => <div data-testid="split-diff">{diff}</div>,
}));

import {
  getArtifactVersion,
  listArtifactVersions,
  readArtifactContent,
  type ArtifactVersion,
} from '../../../features/artifacts/artifactApi';
import { VersionHistory } from '../artifacts/VersionHistory';

const mockedList = vi.mocked(listArtifactVersions);
const mockedGet = vi.mocked(getArtifactVersion);
const mockedRead = vi.mocked(readArtifactContent);

const versions: ArtifactVersion[] = [
  {
    artifact_id: 'a1',
    version_num: 1,
    content_hash: 'h1',
    snapshot_path: '/s1',
    created_at: 1700000000000,
    note: 'init',
  },
  {
    artifact_id: 'a1',
    version_num: 2,
    content_hash: 'h2',
    snapshot_path: '/s2',
    created_at: 1700000100000,
    note: null,
  },
];

beforeEach(() => {
  mockedList.mockReset();
  mockedGet.mockReset();
  mockedRead.mockReset();
});

describe('VersionHistory 版本 diff（right-panel R3 批次 A）', () => {
  it('点击对比按钮展开 SplitDiff 渲染版本↔当前差异', async () => {
    mockedList.mockResolvedValue(versions);
    mockedGet.mockResolvedValue({ ...versions[0], content: 'hello\nold' });
    mockedRead.mockResolvedValue({ ok: true, kind: 'text', content: 'hello\nnew' });
    render(<VersionHistory sessionId="s1" artifactId="a1" />);
    fireEvent.click(screen.getByRole('button', { name: /版本历史/ }));
    await waitFor(() => expect(screen.getByText('v1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('version-diff-toggle-1'));
    await waitFor(() => expect(screen.getByTestId('version-diff-view-1')).toBeInTheDocument());
    expect(screen.getByTestId('split-diff')).toHaveTextContent('-old +new');
  });

  it('两版本内容相同时显示相同提示', async () => {
    mockedList.mockResolvedValue(versions);
    mockedGet.mockResolvedValue({ ...versions[1], content: 'same' });
    mockedRead.mockResolvedValue({ ok: true, kind: 'text', content: 'same' });
    render(<VersionHistory sessionId="s1" artifactId="a1" />);
    fireEvent.click(screen.getByRole('button', { name: /版本历史/ }));
    await waitFor(() => expect(screen.getByText('v2')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('version-diff-toggle-2'));
    await waitFor(() => expect(screen.getByText(/两个版本内容相同/)).toBeInTheDocument());
  });

  it('right-panel R4 批次 A: 对比对象可选为其它版本（v2 ↔ v1 互比）', async () => {
    mockedList.mockResolvedValue(versions);
    mockedGet.mockImplementation((_s: string, _a: string, num: number) =>
      Promise.resolve({
        ...versions[num - 1],
        content: num === 2 ? 'hello\nv2 body' : 'hello\nv1 body',
      }),
    );
    mockedRead.mockResolvedValue({ ok: true, kind: 'text', content: 'hello\ncurrent' });
    render(<VersionHistory sessionId="s1" artifactId="a1" />);
    fireEvent.click(screen.getByRole('button', { name: /版本历史/ }));
    await waitFor(() => expect(screen.getByText('v2')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('version-diff-toggle-2'));
    await waitFor(() => expect(screen.getByTestId('split-diff')).toBeInTheDocument());
    // 切换对比对象为 v1
    fireEvent.change(screen.getByTestId('version-diff-against-2'), {
      target: { value: '1' },
    });
    await waitFor(() => expect(mockedGet).toHaveBeenCalledWith('s1', 'a1', 1));
    await waitFor(() =>
      expect(screen.getByTestId('version-diff-view-2')).toBeInTheDocument(),
    );
  });
});
