// src/widgets/chat/__tests__/turnGrouping.test.ts
//
// ZCode 启发: 将连续 assistant/tool 消息分组为可折叠 Turn。
// 覆盖 4 个纯函数: groupMessagesIntoTurns / isTurnCollapsible /
// getTurnSummary / getTurnToolCallCount。
import { describe, expect, it } from 'vitest';

import type { Message } from '../../../shared/lib/store';
import {
  getTurnSummary,
  getTurnToolCallCount,
  groupMessagesIntoTurns,
  isTurnCollapsible,
} from '../turnGrouping';

// ---- fixtures ----
const mk = (role: Message['role'], content: string, extra: Partial<Message> = {}): Message =>
  ({
    id: `m-${Math.random().toString(36).slice(2, 8)}`,
    session_id: 'sess-1',
    role,
    content,
    created_at: 1700000000,
    ...extra,
  }) as Message;

const user = (content = 'hi', extra: Partial<Message> = {}) => mk('user', content, extra);
const assistant = (content = 'ok', extra: Partial<Message> = {}) => mk('assistant', content, extra);
const tool = (content = 'tool result', extra: Partial<Message> = {}) => mk('tool', content, extra);
const system = (content = 'sys', extra: Partial<Message> = {}) => mk('system', content, extra);
const topicSep = (content = 'topic boundary') =>
  mk('user', content, { subtype: 'topic_separator' } as Partial<Message>);

// ---- groupMessagesIntoTurns ----
describe('groupMessagesIntoTurns', () => {
  it('returns [] for empty input', () => {
    expect(groupMessagesIntoTurns([])).toEqual([]);
  });

  it('wraps a single user message in a turn', () => {
    const u = user();
    const items = groupMessagesIntoTurns([u]);
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe('turn');
    if (items[0].kind === 'turn') {
      expect(items[0].messages).toEqual([u]);
      expect(items[0].id).toContain('turn-');
    }
  });

  it('groups user + assistant + tool into one turn', () => {
    const u = user();
    const a = assistant();
    const t = tool();
    const items = groupMessagesIntoTurns([u, a, t]);
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe('turn');
    if (items[0].kind === 'turn') {
      expect(items[0].messages).toEqual([u, a, t]);
    }
  });

  it('starts a new turn when a second user message arrives', () => {
    const u1 = user('q1');
    const a1 = assistant('a1');
    const u2 = user('q2');
    const a2 = assistant('a2');
    const items = groupMessagesIntoTurns([u1, a1, u2, a2]);
    expect(items).toHaveLength(2);
    expect(items[0].kind).toBe('turn');
    expect(items[1].kind).toBe('turn');
    if (items[0].kind === 'turn' && items[1].kind === 'turn') {
      expect(items[0].messages).toEqual([u1, a1]);
      expect(items[1].messages).toEqual([u2, a2]);
    }
  });

  it('emits topic_separator as standalone and closes the preceding turn', () => {
    const u1 = user();
    const a1 = assistant();
    const sep = topicSep();
    const u2 = user('q2');
    const items = groupMessagesIntoTurns([u1, a1, sep, u2]);
    expect(items).toHaveLength(3);
    expect(items[0].kind).toBe('turn');
    expect(items[1].kind).toBe('standalone');
    expect(items[2].kind).toBe('turn');
    if (items[1].kind === 'standalone') {
      expect(items[1].message).toBe(sep);
    }
  });

  it('emits system/error messages as standalone', () => {
    const s = system();
    const items = groupMessagesIntoTurns([s]);
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe('standalone');
    if (items[0].kind === 'standalone') {
      expect(items[0].message).toBe(s);
    }
  });

  it('groups orphan assistant into a virtual turn (id contains "orphan")', () => {
    const a = assistant();
    const t = tool();
    const items = groupMessagesIntoTurns([a, t]);
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe('turn');
    if (items[0].kind === 'turn') {
      expect(items[0].id).toContain('orphan');
      expect(items[0].messages).toEqual([a, t]);
    }
  });

  it('handles system message splitting a running turn', () => {
    const u = user();
    const a = assistant('a1');
    const s = system('interrupt');
    const a2 = assistant('a2');
    const items = groupMessagesIntoTurns([u, a, s, a2]);
    expect(items).toHaveLength(3);
    expect(items[0].kind).toBe('turn');
    expect(items[1].kind).toBe('standalone');
    expect(items[2].kind).toBe('turn');
  });
});

// ---- isTurnCollapsible ----
describe('isTurnCollapsible', () => {
  it('returns true when >1 assistant/tool messages', () => {
    expect(isTurnCollapsible([user(), assistant(), tool(), assistant()])).toBe(true);
  });

  it('returns false when only 1 assistant/tool message', () => {
    expect(isTurnCollapsible([user(), assistant()])).toBe(false);
  });

  it('returns false for empty / user-only turns', () => {
    expect(isTurnCollapsible([])).toBe(false);
    expect(isTurnCollapsible([user()])).toBe(false);
  });
});

// ---- getTurnSummary ----
describe('getTurnSummary', () => {
  it('returns the last assistant text', () => {
    const msgs = [user('q'), assistant('first'), assistant('second')];
    expect(getTurnSummary(msgs)).toBe('second');
  });

  it('strips code blocks into [代码块] placeholder', () => {
    const msgs = [assistant('before ```js\nconsole.log(1)\n``` after')];
    expect(getTurnSummary(msgs)).toBe('before [代码块] after');
  });

  it('truncates at maxLen with ellipsis', () => {
    const long = 'a'.repeat(300);
    const msgs = [assistant(long)];
    const out = getTurnSummary(msgs, 50);
    expect(out.length).toBe(51); // 50 + '…'
    expect(out.endsWith('…')).toBe(true);
  });

  it('returns empty string when no assistant text present', () => {
    expect(getTurnSummary([user('q'), tool('result')])).toBe('');
    expect(getTurnSummary([assistant('   ')])).toBe('');
  });
});

// ---- getTurnToolCallCount ----
describe('getTurnToolCallCount', () => {
  it('returns 0 when no tool_calls present', () => {
    expect(getTurnToolCallCount([user(), assistant()])).toBe(0);
  });

  it('counts array-form tool_calls across multiple assistant messages', () => {
    const msgs = [
      assistant('a', {
        tool_calls: [
          { id: 't1', name: 'read', args: {} },
          { id: 't2', name: 'write', args: {} },
        ],
      }),
      assistant('b', { tool_calls: [{ id: 't3', name: 'exec', args: {} }] }),
    ];
    expect(getTurnToolCallCount(msgs)).toBe(3);
  });

  it('parses stringified JSON tool_calls', () => {
    const msgs = [
      assistant('a', {
        tool_calls: JSON.stringify([
          { id: 't1', name: 'read', args: {} },
          { id: 't2', name: 'write', args: {} },
        ]) as unknown as Message['tool_calls'],
      }),
    ];
    expect(getTurnToolCallCount(msgs)).toBe(2);
  });

  it('returns 0 for malformed JSON tool_calls string', () => {
    const msgs = [assistant('a', { tool_calls: 'not-json' as unknown as Message['tool_calls'] })];
    expect(getTurnToolCallCount(msgs)).toBe(0);
  });

  it('ignores null / tool-role tool_calls', () => {
    const msgs = [
      assistant('a', { tool_calls: null }),
      tool('result', { tool_calls: [{ id: 'x', name: 'read', args: {} }] }), // tool role ignored
    ];
    expect(getTurnToolCallCount(msgs)).toBe(0);
  });
});
