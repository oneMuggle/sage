// electron/__tests__/feedbackSyncer.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

const loggerMocks = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock('../logger', () => ({ logger: loggerMocks }));

import type { FeedbackConfig } from '../feedback/feedbackConfig';
import { FeedbackSyncer } from '../feedback/feedbackSyncer';
import type { fetchCompat } from '../fetchCompat';

type FetchFn = typeof fetchCompat;

const BACKEND = 'http://127.0.0.1:8790';
const MANAGER = 'http://manager.internal:8900';

const CONVERSATION = {
  id: 'c-1',
  title: '导出乱码',
  status: 'open' as const,
  app_version: '0.4.9',
  os_info: 'linux',
  last_activity_at: 3000,
  created_at: 1000,
  updated_at: 3000,
};

const PENDING_MESSAGE = {
  id: 'm-1',
  conversation_id: 'c-1',
  role: 'user' as const,
  body: '导出后中文变乱码',
  media_ids: [],
  created_at: 2000,
  synced_at: null,
};

const ADMIN_MESSAGE = {
  id: 'a-1',
  conversation_id: 'c-1',
  role: 'admin' as const,
  body: '已复现，正在修',
  media_ids: [],
  created_at: 4000,
  synced_at: null,
};

interface FetchCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

interface RouteResult {
  status: number;
  body: unknown;
}

type Router = (call: FetchCall) => RouteResult | undefined;

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function makeFetch(router: Router): { fn: FetchFn; calls: FetchCall[] } {
  const calls: FetchCall[] = [];
  const fn = (async (url: unknown, init?: RequestInit) => {
    const call: FetchCall = {
      url: String(url),
      method: init?.method ?? 'GET',
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const result = router(call);
    if (!result) throw new Error(`unexpected fetch: ${call.method} ${call.url}`);
    return jsonResponse(result.status, result.body);
  }) as unknown as FetchFn;
  return { fn, calls };
}

function defaultRouter(overrides: { remotePostStatus?: number } = {}): Router {
  const remotePostStatus = overrides.remotePostStatus ?? 200;
  return (call) => {
    const { url, method } = call;
    if (method === 'GET' && url === `${BACKEND}/api/v1/feedback/conversations?limit=50`) {
      return { status: 200, body: [CONVERSATION] };
    }
    if (method === 'GET' && url === `${BACKEND}/api/v1/feedback/conversations/c-1/pending`) {
      return { status: 200, body: [PENDING_MESSAGE] };
    }
    if (method === 'POST' && url === `${MANAGER}/api/v1/feedback/conversations/c-1/messages`) {
      return { status: remotePostStatus, body: { received: remotePostStatus === 200 } };
    }
    if (method === 'POST' && url === `${BACKEND}/api/v1/feedback/messages/m-1/synced`) {
      return { status: 200, body: {} };
    }
    if (method === 'GET' && url === `${BACKEND}/api/v1/feedback/conversations/c-1`) {
      return {
        status: 200,
        body: { conversation: CONVERSATION, messages: [PENDING_MESSAGE, ADMIN_MESSAGE] },
      };
    }
    if (
      method === 'GET' &&
      url === `${MANAGER}/api/v1/feedback/conversations/c-1/messages?since=4000`
    ) {
      return {
        status: 200,
        body: [
          { id: 'a-2', role: 'admin', body: '修好了', created_at: 5000 },
          { id: 'm-1', role: 'user', body: '导出后中文变乱码', created_at: 2000 },
        ],
      };
    }
    if (method === 'POST' && url === `${BACKEND}/api/v1/feedback/conversations/c-1/messages`) {
      return { status: 200, body: { received: true } };
    }
    return undefined;
  };
}

function makeConfig(
  state: Partial<{ configured: boolean; url: string; secret: string; uuid: string }> = {},
): FeedbackConfig {
  const s = {
    configured: true,
    url: MANAGER,
    secret: 'sekret',
    uuid: 'uuid-install-1',
    ...state,
  };
  return {
    isConfigured: () => s.configured,
    getManagerUrl: () => s.url,
    getSharedSecret: () => s.secret,
    getInstallationUuid: () => s.uuid,
  } as unknown as FeedbackConfig;
}

function makeSyncer(opts: { router?: Router; config?: FeedbackConfig } = {}) {
  const { fn, calls } = makeFetch(opts.router ?? defaultRouter());
  const scheduled: Array<{ fn: () => void; ms: number }> = [];
  const syncer = new FeedbackSyncer({
    getBackendUrl: () => BACKEND,
    getAuthToken: () => 'local-token',
    config: opts.config ?? makeConfig(),
    fetchImpl: fn,
    scheduleTimeout: (cb, ms) => {
      scheduled.push({ fn: cb, ms });
      return 0 as unknown as ReturnType<typeof setTimeout>;
    },
  });
  return { syncer, calls, scheduled };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FeedbackSyncer.start', () => {
  it('配置缺失时不排期，仅记录 idle 日志', () => {
    const { syncer, scheduled } = makeSyncer({ config: makeConfig({ configured: false }) });
    syncer.start();
    expect(scheduled).toHaveLength(0);
    expect(loggerMocks.info).toHaveBeenCalledWith(expect.stringContaining('not configured'));
  });

  it('配置就绪时立即排期首轮（延迟 0）', () => {
    const { syncer, scheduled } = makeSyncer();
    syncer.start();
    expect(scheduled).toHaveLength(1);
    expect(scheduled[0].ms).toBe(0);
  });

  it('stop() 后已排期的 tick 不再执行', async () => {
    const { syncer, scheduled, calls } = makeSyncer();
    syncer.start();
    syncer.stop();
    scheduled[0].fn();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(calls).toHaveLength(0);
    expect(syncer.getBackoffIndex()).toBe(0);
  });
});

describe('FeedbackSyncer.syncOnce', () => {
  it('提交 pending 用户消息、标记 synced，并拉取管理员回复', async () => {
    const { syncer, calls } = makeSyncer();

    const stats = await syncer.syncOnce();

    expect(stats).toEqual({ submitted: 1, received: 1, errors: 0 });

    const remotePost = calls.find(
      (c) =>
        c.method === 'POST' && c.url === `${MANAGER}/api/v1/feedback/conversations/c-1/messages`,
    );
    expect(remotePost?.body).toMatchObject({
      id: 'm-1',
      role: 'user',
      body: '导出后中文变乱码',
      created_at: 2000,
    });
    expect(remotePost?.headers.Authorization).toBe('Bearer sekret');
    expect(remotePost?.headers['X-Client-Id']).toBe('uuid-install-1');

    const markSynced = calls.find((c) => c.url.endsWith('/api/v1/feedback/messages/m-1/synced'));
    expect(markSynced?.method).toBe('POST');
    expect(markSynced?.headers.Authorization).toBe('Bearer local-token');

    const adminWrite = calls.find(
      (c) =>
        c.method === 'POST' && c.url === `${BACKEND}/api/v1/feedback/conversations/c-1/messages`,
    );
    expect(adminWrite?.body).toMatchObject({
      id: 'a-2',
      role: 'admin',
      body: '修好了',
      media_ids: [],
    });
  });

  it('拉取回复时用本地最新 admin 消息时间戳作为 since', async () => {
    const { syncer, calls } = makeSyncer();
    await syncer.syncOnce();
    const poll = calls.find((c) => c.method === 'GET' && c.url.includes('/messages?since='));
    expect(poll?.url).toBe(`${MANAGER}/api/v1/feedback/conversations/c-1/messages?since=4000`);
  });

  it('非 open 会话跳过提交与拉取', async () => {
    const resolved = { ...CONVERSATION, status: 'resolved' as const };
    const { syncer, calls } = makeSyncer({
      router: (call) =>
        call.method === 'GET' && call.url.startsWith(`${BACKEND}/api/v1/feedback/conversations?`)
          ? { status: 200, body: [resolved] }
          : undefined,
    });

    const stats = await syncer.syncOnce();

    expect(stats).toEqual({ submitted: 0, received: 0, errors: 0 });
    expect(calls).toHaveLength(1);
  });

  it('远端提交失败时不标记 synced、也不拉取回复', async () => {
    const { syncer, calls } = makeSyncer({ router: defaultRouter({ remotePostStatus: 500 }) });

    const stats = await syncer.syncOnce();

    expect(stats).toEqual({ submitted: 0, received: 0, errors: 1 });
    expect(calls.some((c) => c.url.endsWith('/synced'))).toBe(false);
    expect(calls.some((c) => c.url.includes('?since='))).toBe(false);
    expect(calls.some((c) => c.url === `${BACKEND}/api/v1/feedback/conversations/c-1`)).toBe(false);
  });

  it('inFlight 期间并发调用直接返回零值', async () => {
    const { syncer } = makeSyncer();
    const first = syncer.syncOnce();
    const second = await syncer.syncOnce();
    expect(second).toEqual({ submitted: 0, received: 0, errors: 0 });
    await first;
  });
});

describe('FeedbackSyncer 退避', () => {
  it('tick 失败后升一档退避并按 5 分钟排下一轮', async () => {
    const { syncer, scheduled } = makeSyncer({
      router: (call) =>
        call.method === 'GET' && call.url.startsWith(`${BACKEND}/api/v1/feedback/conversations?`)
          ? { status: 500, body: {} }
          : undefined,
    });

    syncer.start();
    scheduled[0].fn();

    await vi.waitFor(() => expect(syncer.getBackoffIndex()).toBe(1));
    expect(scheduled[1]?.ms).toBe(5 * 60 * 1000);
  });
});
