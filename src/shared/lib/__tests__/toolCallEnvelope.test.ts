import { describe, expect, it } from 'vitest';

import type { ToolCall } from '../store';
import { normalizeToolCallEnvelope } from '../toolCallEnvelope';

const envelope = (payload: Record<string, unknown>) => JSON.stringify(payload);

function tc(result?: string): ToolCall {
  return { name: 'web_fetch', args: { url: 'https://example.com/x' }, result };
}

describe('normalizeToolCallEnvelope（R19-W1 拦截信封归一化）', () => {
  it('提取信封 content 作为 result，并提升 metadata 到 ToolCall.metadata', () => {
    const raw = envelope({
      content: '该页面需要登录后访问',
      metadata: {
        blockReason: 'login_wall',
        blockedUrl: 'https://example.com/private',
        suggestedActions: [{ action: 'configure_credentials', label: '配置登录凭据' }],
      },
    });

    const out = normalizeToolCallEnvelope(tc(raw));

    expect(out.result).toBe('该页面需要登录后访问');
    expect(out.metadata?.blockReason).toBe('login_wall');
    expect(out.metadata?.blockedUrl).toBe('https://example.com/private');
    expect(out.metadata?.suggestedActions).toEqual([
      { action: 'configure_credentials', label: '配置登录凭据' },
    ]);
  });

  it('保留既有 metadata（如 mediaRefs），信封字段合并而非替换', () => {
    const out = normalizeToolCallEnvelope({
      ...tc(envelope({ content: 'x', metadata: { blockReason: 'timeout' } })),
      metadata: { mediaRefs: [{ id: 'm1', kind: 'image', mime_type: 'image/png' }] },
    });

    expect(out.metadata?.blockReason).toBe('timeout');
    expect(out.metadata?.mediaRefs).toEqual([{ id: 'm1', kind: 'image', mime_type: 'image/png' }]);
  });

  it('普通字符串结果原样返回（引用不变，不产生额外开销）', () => {
    const plain = tc('抓取成功：正文……');
    expect(normalizeToolCallEnvelope(plain)).toBe(plain);
  });

  it('JSON 对象但无 blockReason 时原样返回（如 media_ref 信封）', () => {
    const media = tc(envelope({ media_ref: { id: 'm1' }, api_url: '/api/v1/media/m1' }));
    expect(normalizeToolCallEnvelope(media)).toBe(media);
  });

  it('非法 JSON 不抛异常且原样返回', () => {
    const broken = tc('{not json');
    expect(normalizeToolCallEnvelope(broken)).toBe(broken);
  });

  it('result 缺失或非字符串时原样返回', () => {
    const empty = tc(undefined);
    expect(normalizeToolCallEnvelope(empty)).toBe(empty);
  });

  it('信封 content 为空串时回退为原始 result（不丢信息）', () => {
    const raw = envelope({ content: '', metadata: { blockReason: 'antibot_cf' } });
    const out = normalizeToolCallEnvelope(tc(raw));
    expect(out.result).toBe(raw);
    expect(out.metadata?.blockReason).toBe('antibot_cf');
  });

  it('信封 content 非字符串时回退为原始 result', () => {
    const raw = envelope({ content: 42, metadata: { blockReason: 'http_5xx' } });
    const out = normalizeToolCallEnvelope(tc(raw));
    expect(out.result).toBe(raw);
    expect(out.metadata?.blockReason).toBe('http_5xx');
  });
});
