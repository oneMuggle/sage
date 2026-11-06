// webhookDelivery 测试（2026-11-06 Phase 3）
import { describe, expect, it, vi } from 'vitest';

import {
  buildSlackPayload,
  buildWebhookPayload,
  createWebhookDeliver,
} from '../webhookDelivery';

const ITEM = {
  kind: 'scheduled_task',
  title: '✅ 定时任务已完成：日报',
  body: 'exit=0',
  status: 'succeeded',
  session_id: 's-1',
  created_at: '2026-11-06T12:00:00',
};

function flushAsync(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('payload builders', () => {
  it('builds the generic webhook payload', () => {
    expect(buildWebhookPayload(ITEM)).toEqual({
      type: 'sage_notification',
      kind: 'scheduled_task',
      title: '✅ 定时任务已完成：日报',
      body: 'exit=0',
      status: 'succeeded',
      session_id: 's-1',
      created_at: '2026-11-06T12:00:00',
    });
  });

  it('tolerates missing fields', () => {
    expect(buildWebhookPayload({})).toEqual({
      type: 'sage_notification',
      kind: '',
      title: '',
      body: '',
      status: '',
      session_id: '',
      created_at: '',
    });
  });

  it('builds the Slack payload with trimmed text', () => {
    expect(buildSlackPayload(ITEM).text).toBe('✅ 定时任务已完成：日报\nexit=0');
    expect(buildSlackPayload({ title: 'only' }).text).toBe('only');
  });
});

describe('createWebhookDeliver', () => {
  it('does nothing when no urls configured', async () => {
    const fetchImpl = vi.fn();
    const deliver = createWebhookDeliver(
      () => ({ webhookUrl: '', slackWebhookUrl: '  ' }),
      fetchImpl,
    );
    deliver(ITEM);
    await flushAsync();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('posts to both generic and Slack urls', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true });
    const deliver = createWebhookDeliver(
      () => ({ webhookUrl: 'https://hook.example/generic', slackWebhookUrl: 'https://hooks.slack.com/x' }),
      fetchImpl,
    );
    deliver(ITEM);
    await flushAsync();

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const [genericUrl, genericInit] = fetchImpl.mock.calls[0];
    expect(genericUrl).toBe('https://hook.example/generic');
    expect(genericInit.method).toBe('POST');
    expect(JSON.parse(genericInit.body)).toMatchObject({
      type: 'sage_notification',
      kind: 'scheduled_task',
    });

    const [slackUrl, slackInit] = fetchImpl.mock.calls[1];
    expect(slackUrl).toBe('https://hooks.slack.com/x');
    expect(JSON.parse(slackInit.body)).toEqual({
      text: '✅ 定时任务已完成：日报\nexit=0',
    });
  });

  it('isolates generic failures and still delivers Slack', async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce({ ok: true });
    const log = vi.fn();
    const deliver = createWebhookDeliver(
      () => ({ webhookUrl: 'https://hook.example/generic', slackWebhookUrl: 'https://hooks.slack.com/x' }),
      fetchImpl,
      log,
    );
    deliver(ITEM);
    await flushAsync();

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(log).toHaveBeenCalledWith(
      'webhook: generic delivery failed',
      expect.objectContaining({ error: expect.stringContaining('down') }),
    );
  });

  it('re-reads prefs on each delivery', async () => {
    let url = '';
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true });
    const deliver = createWebhookDeliver(() => ({ webhookUrl: url, slackWebhookUrl: '' }), fetchImpl);

    deliver(ITEM);
    await flushAsync();
    expect(fetchImpl).not.toHaveBeenCalled();

    url = 'https://hook.example/late';
    deliver(ITEM);
    await flushAsync();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
