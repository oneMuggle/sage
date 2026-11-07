// webhookDelivery 测试（2026-11-06 Phase 3/4）
import { describe, expect, it, vi } from 'vitest';

import {
  buildSlackPayload,
  buildWebhookPayload,
  buildWebhookSignature,
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

const noSleep = async (): Promise<void> => undefined;

function flushAsync(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

const PREFS = {
  webhookUrl: 'https://hook.example/generic',
  slackWebhookUrl: '',
  webhookSecret: '',
};

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

describe('buildWebhookSignature', () => {
  it('returns a deterministic sha256 HMAC', () => {
    const sig = buildWebhookSignature('secret', '{"a":1}');
    expect(sig.startsWith('sha256=')).toBe(true);
    expect(sig).toBe(buildWebhookSignature('secret', '{"a":1}'));
    expect(sig).not.toBe(buildWebhookSignature('other', '{"a":1}'));
  });
});

describe('createWebhookDeliver', () => {
  it('does nothing when no urls configured', async () => {
    const fetchImpl = vi.fn();
    const deliver = createWebhookDeliver(
      () => ({ webhookUrl: '', slackWebhookUrl: '  ', webhookSecret: '' }),
      { fetchImpl, sleep: noSleep },
    );
    deliver(ITEM);
    await flushAsync();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('posts to both generic and Slack urls', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true });
    const deliver = createWebhookDeliver(
      () => ({
        webhookUrl: 'https://hook.example/generic',
        slackWebhookUrl: 'https://hooks.slack.com/x',
        webhookSecret: '',
      }),
      { fetchImpl, sleep: noSleep },
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
    expect(genericInit.headers['X-Sage-Signature']).toBeUndefined();

    const [slackUrl, slackInit] = fetchImpl.mock.calls[1];
    expect(slackUrl).toBe('https://hooks.slack.com/x');
    expect(JSON.parse(slackInit.body)).toEqual({
      text: '✅ 定时任务已完成：日报\nexit=0',
    });
  });

  it('adds the HMAC signature header when a secret is configured', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true });
    const deliver = createWebhookDeliver(() => ({ ...PREFS, webhookSecret: 'top-secret' }), {
      fetchImpl,
      sleep: noSleep,
    });
    deliver(ITEM);
    await flushAsync();

    const [, init] = fetchImpl.mock.calls[0];
    const expected = buildWebhookSignature('top-secret', init.body);
    expect(init.headers['X-Sage-Signature']).toBe(expected);
  });

  it('retries on rejection and succeeds on the second attempt', async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ ok: true });
    const sleep = vi.fn().mockResolvedValue(undefined);
    const deliver = createWebhookDeliver(() => PREFS, { fetchImpl, sleep });
    deliver(ITEM);
    await flushAsync();
    await flushAsync();

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledWith(1000);
  });

  it('retries non-2xx responses and gives up after 3 attempts', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 500 });
    const sleep = vi.fn().mockResolvedValue(undefined);
    const log = vi.fn();
    const deliver = createWebhookDeliver(() => PREFS, { fetchImpl, sleep, log });
    deliver(ITEM);
    await flushAsync();
    await flushAsync();
    await flushAsync();

    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(sleep.mock.calls.map((c) => c[0])).toEqual([1000, 3000]);
    expect(log).toHaveBeenCalledWith(
      'webhook: generic delivery failed after 3 attempts',
      expect.objectContaining({ error: expect.stringContaining('HTTP 500') }),
    );
  });

  it('isolates generic failures and still delivers Slack', async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error('down'))
      .mockRejectedValueOnce(new Error('down'))
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce({ ok: true });
    const sleep = vi.fn().mockResolvedValue(undefined);
    const log = vi.fn();
    const deliver = createWebhookDeliver(
      () => ({ ...PREFS, slackWebhookUrl: 'https://hooks.slack.com/x' }),
      { fetchImpl, sleep, log },
    );
    deliver(ITEM);
    await flushAsync();
    await flushAsync();
    await flushAsync();

    expect(fetchImpl).toHaveBeenCalledTimes(4);
    expect(log).toHaveBeenCalledWith(
      'webhook: generic delivery failed after 3 attempts',
      expect.anything(),
    );
    const [slackUrl] = fetchImpl.mock.calls[3];
    expect(slackUrl).toBe('https://hooks.slack.com/x');
  });

  it('re-reads prefs on each delivery', async () => {
    let url = '';
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true });
    const deliver = createWebhookDeliver(
      () => ({ webhookUrl: url, slackWebhookUrl: '', webhookSecret: '' }),
      { fetchImpl, sleep: noSleep },
    );

    deliver(ITEM);
    await flushAsync();
    expect(fetchImpl).not.toHaveBeenCalled();

    url = 'https://hook.example/late';
    deliver(ITEM);
    await flushAsync();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
