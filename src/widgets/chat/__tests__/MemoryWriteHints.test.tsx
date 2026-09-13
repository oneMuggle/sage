// src/widgets/chat/__tests__/MemoryWriteHints.test.tsx
// 对标 S2: 流结束后内联"🧠 记住了"提示 + 撤销。memoryApi 全 mock，
// 流结束跳变通过真实 chatStreamStore 的 startStream/clearStream 模拟。
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import type { MemoryWritesResponse } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { MemoryWriteHints } from '../MemoryWriteHints';

const getRecentWrites =
  vi.fn<(sessionId: string, afterSeq?: number, limit?: number) => Promise<MemoryWritesResponse>>();
const undoWrite = vi.fn<(sessionId: string, id: string) => Promise<void>>();

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    getRecentWrites: (...a: [string, number?, number?]) => getRecentWrites(...a),
    undoWrite: (...a: [string, string]) => undoWrite(...a),
  },
}));

function renderHints(sessionId: string | null) {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryWriteHints sessionId={sessionId} />
    </I18nProvider>,
  );
}

async function finishStream(sid: string): Promise<void> {
  act(() => {
    useChatStreamStore.getState().startStream(sid, 'm1');
  });
  act(() => {
    useChatStreamStore.getState().clearStream(sid, 'm1');
  });
  // 首次轮询延迟 1.2s；再多刷几轮微任务让 setState 落地
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1300);
  });
  await act(async () => {
    await Promise.resolve();
  });
}

describe('MemoryWriteHints', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    useChatStreamStore.setState({ sessions: {} });
    getRecentWrites.mockResolvedValue({ items: [], latest_seq: 0 });
    undoWrite.mockResolvedValue(undefined);
  });

  it('无会话时不渲染也不请求', () => {
    const { container } = renderHints(null);
    expect(container.querySelector('[data-testid="memory-write-hints"]')).toBeNull();
    expect(getRecentWrites).not.toHaveBeenCalled();
  });

  it('挂载时只推进游标，不显示历史写入', async () => {
    getRecentWrites.mockResolvedValueOnce({
      items: [
        {
          seq: 3,
          id: 'old',
          kind: 'memory',
          content: '历史',
          category: 'fact',
          memory_type: 'auto',
          session_id: 's1',
          created_at: 1,
        },
      ],
      latest_seq: 3,
    });
    const { container } = renderHints('s1');
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[data-testid="memory-write-hint"]')).toBeNull();
  });

  it('流结束后拉取增量并显示"记住了"，可撤销', async () => {
    getRecentWrites
      .mockResolvedValueOnce({ items: [], latest_seq: 5 }) // mount cursor
      .mockResolvedValueOnce({
        items: [
          {
            seq: 6,
            id: 'm-new',
            kind: 'memory',
            content: '用户喜欢火锅',
            category: 'preference',
            memory_type: 'auto',
            session_id: 's1',
            created_at: 2,
          },
        ],
        latest_seq: 6,
      });
    renderHints('s1');
    await act(async () => {
      await Promise.resolve();
    });
    await finishStream('s1');

    expect(getRecentWrites).toHaveBeenLastCalledWith('s1', 5, 10);
    expect(screen.getByTestId('memory-write-hint')).toBeInTheDocument();
    expect(screen.getByText('用户喜欢火锅')).toBeInTheDocument();
    expect(screen.getByText('🧠 记住了')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByTestId('memory-write-undo'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(undoWrite).toHaveBeenCalledWith('s1', 'm-new');
    expect(screen.queryByTestId('memory-write-hint')).toBeNull();
  });

  it('画像写入显示专属文案', async () => {
    getRecentWrites.mockResolvedValueOnce({ items: [], latest_seq: 0 }).mockResolvedValueOnce({
      items: [
        {
          seq: 1,
          id: 'p1',
          kind: 'profile',
          content: '偏好简洁回答',
          category: 'preference',
          memory_type: 'profile',
          session_id: 's1',
          created_at: 2,
        },
      ],
      latest_seq: 1,
    });
    renderHints('s1');
    await act(async () => {
      await Promise.resolve();
    });
    await finishStream('s1');
    expect(screen.getByText('🧠 更新了关于你的画像')).toBeInTheDocument();
  });
});
