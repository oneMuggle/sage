// W1: RewindDialog —— 消息级「回滚到此处」对话框。
// 覆盖：快照列表渲染与默认选中、晚于消息的快照过滤、无快照降级、
// 确认调用序列（先 restore 后 fork）、restore 失败中止。

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    listCheckpoints: vi.fn(),
    restoreCheckpoint: vi.fn(),
  },
}));

vi.mock('../../../../shared/api/sessionApi', () => ({
  sessionApi: {
    fork: vi.fn(),
  },
}));

import { sessionApi } from '../../../../shared/api/sessionApi';
import { workspaceApi } from '../../../../shared/api/workspaceApi';
import { I18nProvider } from '../../../../shared/lib/i18n';
import { RewindDialog } from '../RewindDialog';

// jsdom 不实现 ResizeObserver，但 @headlessui Dialog 内部使用它
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const mockList = vi.mocked(workspaceApi.listCheckpoints);
const mockRestore = vi.mocked(workspaceApi.restoreCheckpoint);
const mockFork = vi.mocked(sessionApi.fork);

// 消息时刻：2026-09-27T12:00:00 本地时间
const MESSAGE_AT = new Date(2026, 8, 27, 12, 0, 0).getTime();

function ckpt(id: string, createdAt: Date, files = 2) {
  // 后端 created_at 为本地时区无 TZ 后缀字符串（strftime 产物）
  const pad = (n: number) => String(n).padStart(2, '0');
  const iso = `${createdAt.getFullYear()}-${pad(createdAt.getMonth() + 1)}-${pad(
    createdAt.getDate(),
  )}T${pad(createdAt.getHours())}:${pad(createdAt.getMinutes())}:${pad(createdAt.getSeconds())}`;
  return { checkpointId: id, createdAt: iso, bytes: 100, files };
}

function renderDialog(overrides?: { messageCreatedAt?: number; onForked?: (id: string) => void }) {
  const onForked = overrides?.onForked ?? vi.fn();
  const onClose = vi.fn();
  render(
    <I18nProvider defaultLocale="zh">
      <RewindDialog
        isOpen
        sessionId="s1"
        messageId="m9"
        messageCreatedAt={overrides?.messageCreatedAt ?? MESSAGE_AT}
        onClose={onClose}
        onForked={onForked}
      />
    </I18nProvider>,
  );
  return { onForked, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('RewindDialog', () => {
  it('渲染合格快照（新→旧）并默认选中最近一个不晚于消息时刻的快照', async () => {
    mockList.mockResolvedValue([
      ckpt('ck-old', new Date(2026, 8, 26, 9, 0, 0)),
      ckpt('ck-new', new Date(2026, 8, 27, 10, 0, 0)),
      ckpt('ck-future', new Date(2026, 8, 27, 15, 0, 0)), // 晚于消息，应被过滤
    ]);
    renderDialog();
    await waitFor(() => expect(screen.getByTestId('rewind-checkpoint-ck-new')).toBeInTheDocument());
    expect(screen.queryByTestId('rewind-checkpoint-ck-future')).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId('rewind-checkpoint-ck-new').querySelector('input')).toBeChecked(),
    );
    expect(screen.getByTestId('rewind-scope-both').querySelector('input')).toBeChecked();
  });

  it('无合格快照时降级为仅对话且不可选文件范围', async () => {
    mockList.mockResolvedValue([ckpt('ck-future', new Date(2026, 8, 28, 9, 0, 0))]);
    renderDialog();
    await waitFor(() => expect(screen.getByTestId('rewind-no-snapshots')).toBeInTheDocument());
    const bothInput = screen.getByTestId('rewind-scope-both').querySelector('input');
    expect(bothInput).toBeDisabled();
    expect(screen.getByTestId('rewind-scope-conversation').querySelector('input')).toBeChecked();
  });

  it('确认（对话+文件）：先 restore 后 fork，并回调新会话 id', async () => {
    mockList.mockResolvedValue([
      ckpt('ck-old', new Date(2026, 8, 26, 9, 0, 0)),
      ckpt('ck-new', new Date(2026, 8, 27, 10, 0, 0)),
    ]);
    mockRestore.mockResolvedValue({ restored: 2 });
    mockFork.mockResolvedValue({ id: 'fork-1' } as never);
    const { onForked } = renderDialog();
    // 等默认快照选中（scope 归一为 both），避免与加载竞态
    await waitFor(() =>
      expect(screen.getByTestId('rewind-checkpoint-ck-new').querySelector('input')).toBeChecked(),
    );
    fireEvent.click(screen.getByTestId('rewind-confirm'));
    await waitFor(() => expect(onForked).toHaveBeenCalledWith('fork-1'));
    expect(mockRestore).toHaveBeenCalledWith('s1', 'ck-new');
    expect(mockFork).toHaveBeenCalledWith('s1', 'm9');
    expect(mockRestore.mock.invocationCallOrder[0]).toBeLessThan(mockFork.mock.invocationCallOrder[0]);
  });

  it('restore 失败时中止：不 fork，展示错误', async () => {
    mockList.mockResolvedValue([ckpt('ck-new', new Date(2026, 8, 27, 10, 0, 0))]);
    mockRestore.mockRejectedValue(new Error('workspace locked'));
    renderDialog();
    await waitFor(() => expect(screen.getByTestId('rewind-confirm')).toBeEnabled());
    fireEvent.click(screen.getByTestId('rewind-confirm'));
    await waitFor(() => expect(screen.getByTestId('rewind-error')).toHaveTextContent('workspace locked'));
    expect(mockFork).not.toHaveBeenCalled();
  });

  it('仅对话模式：跳过 restore 直接 fork', async () => {
    mockList.mockResolvedValue([ckpt('ck-new', new Date(2026, 8, 27, 10, 0, 0))]);
    mockFork.mockResolvedValue({ id: 'fork-2' } as never);
    const { onForked } = renderDialog();
    await waitFor(() => expect(screen.getByTestId('rewind-confirm')).toBeEnabled());
    fireEvent.click(screen.getByTestId('rewind-scope-conversation'));
    fireEvent.click(screen.getByTestId('rewind-confirm'));
    await waitFor(() => expect(onForked).toHaveBeenCalledWith('fork-2'));
    expect(mockRestore).not.toHaveBeenCalled();
  });
});
