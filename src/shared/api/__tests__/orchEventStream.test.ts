/**
 * r96: orchEventStream 单测——NDJSON 行解析、信封校验、流式消费与错误路径。
 *
 * vitest node 环境无 window → subscribeOrchEvents 走 direct fetch 兜底路径，
 * 用 stub fetch 返回手工 ReadableStream 语义（getReader）覆盖分块/残行/限流。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { parseOrchEventFromIpc, parseOrchEventLine, subscribeOrchEvents } from '../orchEventStream';
import type { RunEvent } from '../orchEvents';

function envelope(overrides: Partial<RunEvent> = {}): RunEvent {
  return {
    event_id: 'e-1',
    run_id: 'r-1',
    seq: 1,
    event_type: 'task.started',
    occurred_at: 100,
    producer: 'lane-executor',
    producer_generation: 1,
    entity: { task_id: 't1' },
    payload: {},
    visibility: 'user',
    schema_version: '1',
    ...overrides,
  };
}

function ndjsonResponse(
  chunks: string[],
  init?: { ok?: boolean; status?: number; statusText?: string; bytesPerChunk?: number },
) {
  const full = chunks.join('');
  let pos = 0;
  const step = init?.bytesPerChunk ?? 8;
  const reader = {
    read: async () => {
      if (pos < full.length) {
        // 默认每次 8 字节，制造跨 chunk 断行；大 payload 用 bytesPerChunk 一步到位
        const next = full.slice(pos, pos + step);
        pos += step;
        return { done: false, value: new TextEncoder().encode(next) };
      }
      return { done: true, value: undefined };
    },
    releaseLock: () => {},
  };
  return {
    ok: init?.ok ?? true,
    status: init?.status ?? 200,
    statusText: init?.statusText ?? 'OK',
    body: { getReader: () => reader },
  } as unknown as Response;

}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseOrchEventLine', () => {
  it('合法信封解析为 RunEvent', () => {
    const line = JSON.stringify(envelope());
    const parsed = parseOrchEventLine(line);
    expect(parsed).not.toBeNull();
    expect(parsed?.event_id).toBe('e-1');
    expect(parsed?.event_type).toBe('task.started');
  });

  it('未知 event_type 拒绝', () => {
    expect(parseOrchEventLine(JSON.stringify(envelope({ event_type: 'bogus.event' as never })))).toBeNull();
  });

  it('缺字段 / seq 非法 / visibility 非法 / entity 非对象 拒绝', () => {
    const missing = envelope() as unknown as Record<string, unknown>;
    delete missing.producer;
    expect(parseOrchEventLine(JSON.stringify(missing))).toBeNull();
    expect(parseOrchEventLine(JSON.stringify(envelope({ seq: -1 })))).toBeNull();
    expect(parseOrchEventLine(JSON.stringify(envelope({ visibility: 'everyone' as never })))).toBeNull();
    expect(parseOrchEventLine(JSON.stringify(envelope({ entity: 't1' as never })))).toBeNull();
  });

  it('非 JSON / 空行 / 数组 / 超长行返回 null', () => {
    expect(parseOrchEventLine('not json')).toBeNull();
    expect(parseOrchEventLine('   ')).toBeNull();
    expect(parseOrchEventLine('[]')).toBeNull();
    expect(parseOrchEventLine('x'.repeat(256 * 1024 + 1))).toBeNull();
  });

  it('parseOrchEventFromIpc: 对象信封通过，垃圾拒绝', () => {
    expect(parseOrchEventFromIpc(envelope())?.seq).toBe(1);
    expect(parseOrchEventFromIpc('hello')).toBeNull();
    expect(parseOrchEventFromIpc(null)).toBeNull();
  });
});

describe('subscribeOrchEvents（direct fetch 兜底）', () => {
  it('跨 chunk 断行的 NDJSON 按序产出，残行在流结束时冲刷', async () => {
    const events = [
      envelope({ seq: 1, event_id: 'e-1', event_type: 'run.started' }),
      envelope({ seq: 2, event_id: 'e-2', event_type: 'task.started' }),
      envelope({ seq: 3, event_id: 'e-3', event_type: 'task.succeeded' }),
    ];
    const payload = events.map((e) => JSON.stringify(e)).join('\n') + '\n' + JSON.stringify(events[0]).slice(0, 5);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ndjsonResponse([payload])));

    const got: RunEvent[] = [];
    for await (const ev of subscribeOrchEvents({ runId: 'r-1' })) {
      got.push(ev);
    }
    expect(got.map((e) => e.event_id)).toEqual(['e-1', 'e-2', 'e-3']);
  });

  it('携带 afterSeq 时请求对应 URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ndjsonResponse(['']));
    vi.stubGlobal('fetch', fetchMock);
    for await (const _ of subscribeOrchEvents({ runId: 'run/9', afterSeq: 42 })) {
      // 无事件
    }
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/orch/runs/run%2F9/events?after_seq=42',
      expect.objectContaining({ headers: { Accept: 'application/x-ndjson' } }),
    );
  });

  it('HTTP 非 2xx 触发 onError 并抛错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ndjsonResponse([], { ok: false, status: 500, statusText: 'boom' })));
    const onError = vi.fn();
    await expect(async () => {
      for await (const _ of subscribeOrchEvents({ runId: 'r', onError })) {
        // 不产出
      }
    }).rejects.toThrow(/500 boom/);
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('AbortError 静默结束不抛错', async () => {
    const abortErr = Object.assign(new Error('aborted'), { name: 'AbortError' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortErr));
    const consumed: RunEvent[] = [];
    for await (const ev of subscribeOrchEvents({ runId: 'r' })) {
      consumed.push(ev);
    }
    expect(consumed).toEqual([]);
  });

  it('普通 fetch 失败触发 onError 并抛出', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('net down')));
    const onError = vi.fn();
    await expect(async () => {
      for await (const _ of subscribeOrchEvents({ runId: 'r', onError })) {
        // 不产出
      }
    }).rejects.toThrow('net down');
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('超过单行字节上限抛专用错误', async () => {
    const big = envelope({ payload: { pad: 'x'.repeat(256 * 1024 + 10) } });
    // 单块投递：避免默认 8 字节分块在超长行上的 O(n²) 缓冲拷贝拖垮测试
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ndjsonResponse([JSON.stringify(big) + '\n'], { bytesPerChunk: Number.POSITIVE_INFINITY })));
    await expect(async () => {
      for await (const _ of subscribeOrchEvents({ runId: 'r' })) {
        // 不产出
      }
    }).rejects.toThrow('line exceeded limit');
  });
});
