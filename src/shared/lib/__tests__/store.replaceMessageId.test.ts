import { beforeEach, describe, expect, it } from 'vitest';

import { mergeLoadedMessages, useStore } from '../store';

interface DraftMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: number;
}

function msg(id: string, role: 'user' | 'assistant', content: string): DraftMessage {
  return {
    id,
    session_id: 's1',
    role,
    content,
    created_at: 1_700_000_000_000,
  };
}

describe('replaceMessageId + client_message_id 乐观 id 对齐', () => {
  beforeEach(() => {
    useStore.setState({ messages: [], currentSessionId: 's1' });
  });

  it('replaceMessageId 原地替换乐观占位 id, 内容保留', () => {
    useStore.setState({ messages: [msg('local-a', 'assistant', 'answer')] });
    useStore.getState().replaceMessageId('local-a', 'server-a');
    const messages = useStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].id).toBe('server-a');
    expect(messages[0].content).toBe('answer');
  });

  it('replaceMessageId 不命中时无副作用', () => {
    const before = [msg('keep-1', 'user', 'hi')];
    useStore.setState({ messages: before });
    useStore.getState().replaceMessageId('nope', 'other');
    expect(useStore.getState().messages).toEqual(before);
  });

  it('乐观 user id 采用 u-<cmid> 后, 对账按 id 精确命中 (零重复)', () => {
    // 服务端落库 id = u-<cmid> (协议), 前端乐观副本同 id
    const server = [msg('u-cmid-1', 'user', 'hi'), msg('sv-a', 'assistant', 'hello')];
    const local = [msg('u-cmid-1', 'user', 'hi')];
    const merged = mergeLoadedMessages(server, local, 's1');
    expect(merged).toHaveLength(2);
    expect(merged.filter((m) => m.id === 'u-cmid-1')).toHaveLength(1);
  });

  it('DONE 未携带 message_id (旧后端) 时乐观 id 保留, 计数去重兜底', () => {
    const server = [msg('sv-1', 'user', 'hi'), msg('sv-2', 'assistant', 'hello')];
    const local = [msg('local-u', 'user', 'hi'), msg('local-a', 'assistant', 'hello')];
    const merged = mergeLoadedMessages(server, local, 's1');
    expect(merged).toHaveLength(2);
  });
});
