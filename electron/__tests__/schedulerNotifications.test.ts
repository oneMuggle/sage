// 后台任务通知轮询器测试 (2026-11-05)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  collectNotificationItems,
  startSchedulerNotificationPoller,
  type PendingNotificationsPayload,
} from '../schedulerNotifications';

describe('collectNotificationItems', () => {
  it('合并定时任务与待办提醒两路队列', () => {
    const payload: PendingNotificationsPayload = {
      scheduled_tasks: [{ title: '✅ 定时任务已完成：日报', body: '内容' }],
      todo_reminders: [{ title: '⏰ 待办紧急', body: '写周报' }],
    };
    expect(collectNotificationItems(payload)).toHaveLength(2);
  });

  it('丢弃没有标题的条目，容忍空载荷', () => {
    const payload: PendingNotificationsPayload = {
      scheduled_tasks: [{ body: 'no title' }, { title: '' }],
      todo_reminders: [{ title: 'ok' }],
    };
    expect(collectNotificationItems(payload)).toEqual([{ title: 'ok' }]);
    expect(collectNotificationItems(null)).toEqual([]);
    expect(collectNotificationItems(undefined)).toEqual([]);
  });
});

describe('startSchedulerNotificationPoller', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('禁用时一次请求都不发', async () => {
    const fetchPending = vi.fn();
    const stop = startSchedulerNotificationPoller({
      fetchPending,
      isEnabled: () => false,
      notify: vi.fn(),
      intervalMs: 1000,
    });
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchPending).not.toHaveBeenCalled();
    stop();
  });

  it('拉取后逐条发通知', async () => {
    const fetchPending = vi.fn().mockResolvedValue({
      scheduled_tasks: [{ title: 'A', body: 'a' }],
      todo_reminders: [{ title: 'B' }],
    });
    const notify = vi.fn();
    const stop = startSchedulerNotificationPoller({
      fetchPending,
      isEnabled: () => true,
      notify,
      intervalMs: 1000,
    });
    await vi.advanceTimersByTimeAsync(1000);
    expect(notify).toHaveBeenCalledWith('A', 'a');
    expect(notify).toHaveBeenCalledWith('B', '');
    stop();
  });

  it('拉取失败只记日志并继续下一轮', async () => {
    const fetchPending = vi
      .fn()
      .mockRejectedValueOnce(new Error('backend down'))
      .mockResolvedValueOnce({ todo_reminders: [{ title: '恢复' }] });
    const log = vi.fn();
    const notify = vi.fn();
    const stop = startSchedulerNotificationPoller({
      fetchPending,
      isEnabled: () => true,
      notify,
      log,
      intervalMs: 1000,
    });
    await vi.advanceTimersByTimeAsync(1000);
    expect(log).toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(notify).toHaveBeenCalledWith('恢复', '');
    stop();
  });

  it('上一轮未完成时跳过本轮', async () => {
    let resolvePending: (value: PendingNotificationsPayload) => void = () => undefined;
    const fetchPending = vi.fn().mockImplementation(
      () =>
        new Promise<PendingNotificationsPayload>((resolve) => {
          resolvePending = resolve;
        }),
    );
    const stop = startSchedulerNotificationPoller({
      fetchPending,
      isEnabled: () => true,
      notify: vi.fn(),
      intervalMs: 1000,
    });
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchPending).toHaveBeenCalledTimes(1);
    resolvePending({});
    await vi.advanceTimersByTimeAsync(0);
    stop();
  });
});
