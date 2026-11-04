/**
 * P0 (2026-11-04): attachments_processed 事件 → user 消息 client_meta 回写。
 *
 * 回归背景：附件处理结果此前只存在于后端 debug 日志，前端无法展示
 * "已读取/已跳过/失败"。本测试锁定事件消费与 client_meta 合并语义：
 * - 状态写入 user_message_id 指向的消息；
 * - 不覆盖已有的 attachments 元数据；
 * - 畸形/缺 user_message_id 时不崩溃。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../../../shared/lib/store';
import { applyTransparencyAndToolEvents } from '../chatStreamRuntime';

const SID = '11111111-2222-3333-4444-555555555555';
const USER_ID = 'u-cmid-1';

function seedUserMessage() {
  useStore.setState({
    sessions: [],
    currentSessionId: SID,
    messages: [
      {
        id: USER_ID,
        session_id: SID,
        role: 'user',
        content: '看看这个文件',
        created_at: 0,
        client_meta: {
          attachments: [{ name: 'app.py', size: 128, type: 'text/x-python' }],
        },
      },
    ],
    isLoading: false,
    contextPressure: null,
  });
}

function dispatchEvent(payload: Record<string, unknown>) {
  const state = useStore.getState();
  applyTransparencyAndToolEvents(payload as never, {
    sid: SID,
    assistantId: 'assistant-1',
    clientMessageId: 'cmid-1',
    requestId: 'req-1',
    addMessage: state.addMessage,
    updateMessage: state.updateMessage,
  });
}

describe('attachments_processed event', () => {
  beforeEach(() => {
    seedUserMessage();
  });

  it('writes status list into the target user message client_meta', () => {
    dispatchEvent({
      state: 'attachments_processed',
      session_id: SID,
      user_message_id: USER_ID,
      attachments_status: [
        {
          media_id: 'm1',
          filename: 'app.py',
          mime_type: 'text/x-python',
          status: 'ok',
          mode: 'full',
          chars: 42,
        },
        {
          media_id: 'm2',
          filename: 'data.csv',
          mime_type: 'text/csv',
          status: 'skipped',
          reason: 'empty_text',
        },
      ],
    });

    const msg = useStore.getState().messages.find((m) => m.id === USER_ID);
    expect(msg?.client_meta?.attachments_status).toHaveLength(2);
    expect(msg?.client_meta?.attachments_status?.[0]).toMatchObject({
      media_id: 'm1',
      status: 'ok',
      chars: 42,
    });
    expect(msg?.client_meta?.attachments_status?.[1]).toMatchObject({
      media_id: 'm2',
      status: 'skipped',
      reason: 'empty_text',
    });
    // 既有 attachments 元数据必须保留
    expect(msg?.client_meta?.attachments).toHaveLength(1);
  });

  it('falls back to u-<clientMessageId> when user_message_id is absent', () => {
    // 主路径的乐观消息 id 形如 u-<cmid>
    useStore.setState((s) => ({
      messages: s.messages.map((m) => ({ ...m, id: 'u-cmid-1' })),
    }));

    dispatchEvent({
      state: 'attachments_processed',
      session_id: SID,
      attachments_status: [
        { media_id: 'm1', filename: 'app.py', mime_type: 'text/x-python', status: 'ok' },
      ],
    });

    const msg = useStore.getState().messages.find((m) => m.id === 'u-cmid-1');
    expect(msg?.client_meta?.attachments_status).toHaveLength(1);
  });

  it('ignores malformed payloads without crashing', () => {
    expect(() => dispatchEvent({ state: 'attachments_processed', session_id: SID })).not.toThrow();
    expect(() =>
      dispatchEvent({
        state: 'attachments_processed',
        session_id: SID,
        user_message_id: 'missing-message',
        attachments_status: [
          { media_id: 'm1', filename: 'a.py', mime_type: 'text/plain', status: 'ok' },
        ],
      }),
    ).not.toThrow();
  });
});
