import { describe, expect, it } from 'vitest';

import type { Message } from '../store';
import { mergeLoadedMessages } from '../store';

function msg(id: string, role: 'user' | 'assistant', content: string): Message {
  return {
    id,
    session_id: 's1',
    role,
    content,
    created_at: 1_700_000_000_000,
  };
}

describe('mergeLoadedMessages 计数感知去重 (R25-D5 对账重复修复)', () => {
  it('本地乐观副本与服务端持久化内容相同 (不同 id) → 去重, 不再双份显示', () => {
    const server = [
      msg('sv-1', 'user', 'hi'),
      msg('sv-2', 'assistant', 'hello there'),
    ];
    const local = [
      msg('local-u', 'user', 'hi'),
      msg('local-a', 'assistant', 'hello there'),
    ];
    const merged = mergeLoadedMessages(server, local, 's1');
    expect(merged.filter((m) => m.role === 'user' && m.content === 'hi')).toHaveLength(1);
    expect(
      merged.filter((m) => m.role === 'assistant' && m.content === 'hello there'),
    ).toHaveLength(1);
    // 服务端副本优先保留
    expect(merged.map((m) => m.id)).toEqual(['sv-1', 'sv-2']);
  });

  it('服务端确实未落库 (如流失败) → 本地乐观消息保留', () => {
    const server = [msg('sv-1', 'user', 'earlier question')];
    const local = [
      msg('local-u', 'user', 'new question'),
      msg('local-a', 'assistant', '🤔 思考中…'),
    ];
    const merged = mergeLoadedMessages(server, local, 's1');
    expect(merged).toHaveLength(3);
    expect(merged.some((m) => m.id === 'local-u')).toBe(true);
    expect(merged.some((m) => m.id === 'local-a')).toBe(true);
  });

  it('重复发送相同内容时按数量对齐, 不误删', () => {
    const server = [
      msg('sv-1', 'user', 'hi'),
      msg('sv-2', 'assistant', 'answer 1'),
      msg('sv-3', 'user', 'hi'),
      msg('sv-4', 'assistant', 'answer 2'),
    ];
    const local = [msg('local-u', 'user', 'hi'), msg('local-a', 'assistant', 'answer 2')];
    const merged = mergeLoadedMessages(server, local, 's1');
    // server 已含 2 份 "hi": local 的 1 份被认领掉; assistant answer 2 亦然
    expect(merged.filter((m) => m.role === 'user')).toHaveLength(2);
    expect(merged).toHaveLength(4);
  });

  it('其它会话的本地消息不参与合并', () => {
    const server = [msg('sv-1', 'user', 'hi')];
    const otherSession = { ...msg('local-x', 'user', 'hi'), session_id: 's2' };
    const merged = mergeLoadedMessages(server, [otherSession], 's1');
    expect(merged).toHaveLength(1);
  });
});
