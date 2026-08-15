/**structural + light behavior test for src/shared/api (B1-RED unit 3: 3 files).

不测 IPC 行为(那需要 Electron runtime),只验 3 文件从新位置正确
导出,且 parseNDJSONStream 在纯 jsdom 下可用 ReadableStream 真测。
*/

import { describe, it, expect, vi, afterEach } from 'vitest';

import * as DesktopEvent from '../desktopEvent';
import * as DesktopInvoke from '../desktopInvoke';
import * as LlmStream from '../llmStream';

describe('src/shared/api/desktopEvent', () => {
  it('exports listen function (Electron IPC subscribe)', () => {
    expect(typeof DesktopEvent.listen).toBe('function');
  });

  it('exports UnlistenFn type (TS 编译时 erases)', () => {
    // type-only:在运行时无值,placeholder 验 type-level 编译通过
    type _T = DesktopEvent.UnlistenFn;
    const _placeholder: _T | null = null;
    expect(_placeholder).toBeNull();
  });
});

describe('src/shared/api/desktopInvoke', () => {
  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).electronAPI;
  });

  it('exports invoke function (Electron IPC request)', () => {
    expect(typeof DesktopInvoke.invoke).toBe('function');
  });

  it('invoke: IPC 剥掉自定义属性后从 message 解析附加 status_code', async () => {
    const invokeMock = vi.fn().mockRejectedValue(
      new Error(
        'Backend POST http://127.0.0.1:8765/api/v1/orch/runs/r1/plan → 409: ' +
          '{"detail":"plan locked after dispatch"}',
      ),
    );
    (window as unknown as Record<string, unknown>).electronAPI = { invoke: invokeMock };
    await expect(
      DesktopInvoke.invoke('orchestration_update_plan', { runId: 'r1', plan: [] }),
    ).rejects.toMatchObject({ status_code: 409 });
  });

  it('invoke: 错误已带 status_code 时保留不重复解析', async () => {
    const err = new Error('whatever') as Error & { status_code?: number };
    err.status_code = 500;
    const invokeMock = vi.fn().mockRejectedValue(err);
    (window as unknown as Record<string, unknown>).electronAPI = { invoke: invokeMock };
    await expect(DesktopInvoke.invoke('list_sessions')).rejects.toMatchObject({
      status_code: 500,
    });
  });
});

describe('src/shared/api/llmStream', () => {
  it('exports parseNDJSONStream async generator function', () => {
    expect(typeof LlmStream.parseNDJSONStream).toBe('function');
  });

  it('parseNDJSONStream: parses one JSON object per line', async () => {
    // 构造 fake NDJSON 流
    const lines = [
      JSON.stringify({ state: 'thinking', iteration: 1, content: 'hello' }),
      JSON.stringify({
        state: 'acting',
        iteration: 1,
        tool_call: { id: 't1', type: 'function', function: { name: 'fn', arguments: '{}' } },
      }),
      JSON.stringify({ state: 'done', iteration: 1 }),
    ];
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(encoder.encode(lines.join('\n') + '\n'));
        controller.close();
      },
    });

    const events: LlmStream.AgentEvent[] = [];
    for await (const evt of LlmStream.parseNDJSONStream(stream)) {
      events.push(evt);
    }

    expect(events).toHaveLength(3);
    expect(events[0].state).toBe('thinking');
    expect(events[0].content).toBe('hello');
    expect(events[1].state).toBe('acting');
    expect(events[1].tool_call?.function.name).toBe('fn');
    expect(events[2].state).toBe('done');
  });

  it('parseNDJSONStream: 容忍单行多个 JSON 与尾部 buffer', async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(
          encoder.encode(
            JSON.stringify({ state: 'thinking', iteration: 0 }) +
              '\n' +
              JSON.stringify({ state: 'done', iteration: 1 }),
          ),
        );
        controller.close();
      },
    });

    const events: LlmStream.AgentEvent[] = [];
    for await (const evt of LlmStream.parseNDJSONStream(stream)) {
      events.push(evt);
    }

    expect(events).toHaveLength(2);
    expect(events[0].state).toBe('thinking');
    expect(events[1].state).toBe('done');
  });

  it('parseNDJSONStream: 跳过损坏行(解析失败的行被忽略)', async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(
          encoder.encode(
            'not-valid-json\n' + JSON.stringify({ state: 'done', iteration: 0 }) + '\n',
          ),
        );
        controller.close();
      },
    });

    const events: LlmStream.AgentEvent[] = [];
    for await (const evt of LlmStream.parseNDJSONStream(stream)) {
      events.push(evt);
    }

    expect(events).toHaveLength(1);
    expect(events[0].state).toBe('done');
  });

  it('exports representative types (TS 编译时 erases, type-only placeholder)', () => {
    type _T =
      | LlmStream.AgentState
      | LlmStream.AgentEvent
      | LlmStream.ToolCallRequestFE
      | LlmStream.ToolCallResultFE;
    const _placeholder: _T | null = null;
    expect(_placeholder).toBeNull();
  });
});
