// U5 (2026-09-18): 待发送队列 store 语义。
// 队列从 useChat 的 component-local ref 迁入 chatStreamStore 后，这里锁住
// 三条迁移期最容易丢的行为：payload 完整、按会话隔离、暂停位不再自动 flush。
import { beforeEach, describe, expect, it } from 'vitest';

import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';

const store = () => useChatStreamStore.getState();

describe('chatStreamStore — U5 pending queue', () => {
  beforeEach(() => {
    store().resetAll();
  });

  it('keeps the full send payload so a flushed message replays attachments', () => {
    const item = store().enqueueChat('s1', {
      content: '把第三章改成表格',
      orchestrationMode: 'force_multi',
      opts: { images: ['data:image/png;base64,AAA'], planMode: true },
    });

    expect(item.content).toBe('把第三章改成表格');
    expect(item.sessionId).toBe('s1');
    const queued = store().sessions['s1'].pendingQueue;
    expect(queued).toEqual([item]);
    expect(queued[0].opts?.images).toEqual(['data:image/png;base64,AAA']);
    expect(queued[0].opts?.planMode).toBe(true);
    expect(queued[0].orchestrationMode).toBe('force_multi');
  });

  it('shifts FIFO and takes by id without touching the rest', () => {
    const a = store().enqueueChat('s1', { content: 'A' });
    store().enqueueChat('s1', { content: 'B' });
    const c = store().enqueueChat('s1', { content: 'C' });

    expect(store().takeChatFromQueue('s1', c.id)?.content).toBe('C');
    expect(store().shiftChatQueue('s1')).toEqual(a);
    expect(store().shiftChatQueue('s1')?.content).toBe('B');
    expect(store().shiftChatQueue('s1')).toBeNull();
    expect(store().takeChatFromQueue('s1', 'missing')).toBeNull();
  });

  it('reorders to front and clears (also releasing the paused flag)', () => {
    const a = store().enqueueChat('s1', { content: 'A' });
    store().enqueueChat('s1', { content: 'B' });
    store().setChatQueuePaused('s1', true);

    store().moveChatToQueueFront('s1', a.id);
    expect(store().sessions['s1'].pendingQueue.map((m) => m.content)).toEqual(['A', 'B']);

    store().clearChatQueue('s1');
    expect(store().sessions['s1'].pendingQueue).toEqual([]);
    expect(store().sessions['s1'].queuePaused).toBe(false);
  });

  it('keeps queues isolated per session (S3 parallel sessions)', () => {
    store().enqueueChat('s1', { content: 'A' });
    expect(selectSessionSlots(store(), 's2').pendingQueue).toEqual([]);
    expect(store().shiftChatQueue('s2')).toBeNull();
    expect(store().shiftChatQueue('s1')?.content).toBe('A');
  });

  it('leaves the queue untouched when a new stream starts', () => {
    store().enqueueChat('s1', { content: 'queued while streaming' });
    store().startStream('s1', 'm1', { initialContent: '🤔' });
    expect(store().sessions['s1'].pendingQueue).toHaveLength(1);
    expect(store().sessions['s1'].streaming).not.toBeNull();
  });
});
