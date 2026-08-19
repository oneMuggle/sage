import { describe, expect, it } from 'vitest';
import { useChatStreamStore } from '../chatStreamStore';

describe('chatStreamStore', () => {
  it('startStream 创建新流并清空旧工具调用', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('msg-1', { initialContent: '🤔 思考中…' });
    const s = useChatStreamStore.getState();
    expect(s.streaming?.messageId).toBe('msg-1');
    expect(s.streaming?.content).toBe('🤔 思考中…');
    expect(s.streamingToolCalls).toEqual([]);
  });

  it('appendContent 累积内容（流式逐字）', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('msg-1', { initialContent: '' });
    useChatStreamStore.getState().appendContent('msg-1', '你');
    useChatStreamStore.getState().appendContent('msg-1', '好');
    expect(useChatStreamStore.getState().streaming?.content).toBe('你好');
  });

  it('replaceContent 覆盖（中间态占位）', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('msg-1', { initialContent: '' });
    useChatStreamStore.getState().appendContent('msg-1', '部分回答');
    useChatStreamStore.getState().replaceContent('msg-1', '⚙ 调用工具…');
    expect(useChatStreamStore.getState().streaming?.content).toBe('⚙ 调用工具…');
  });

  it('其它 messageId 的事件被忽略（防止跨流污染）', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('msg-A', { initialContent: 'A' });
    useChatStreamStore.getState().appendContent('msg-B', 'B 的内容'); // 过期事件
    useChatStreamStore.getState().clearStream('msg-B'); // 也不应清掉
    expect(useChatStreamStore.getState().streaming?.messageId).toBe('msg-A');
    expect(useChatStreamStore.getState().streaming?.content).toBe('A');
  });

  it('clearStream(messageId) 只在匹配时清空', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('msg-1', { initialContent: 'X' });
    useChatStreamStore.getState().clearStream('msg-OTHER');
    expect(useChatStreamStore.getState().streaming?.messageId).toBe('msg-1');
    useChatStreamStore.getState().clearStream('msg-1');
    expect(useChatStreamStore.getState().streaming).toBeNull();
  });

  it('appendOrUpdateToolCall 按 id 去重', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('msg-1', { initialContent: '' });
    useChatStreamStore.getState().appendOrUpdateToolCall({
      id: 'tc-1', name: 'read', args: { path: '/a' },
    });
    useChatStreamStore.getState().appendOrUpdateToolCall({
      id: 'tc-2', name: 'bash', args: { cmd: 'ls' },
    });
    useChatStreamStore.getState().appendOrUpdateToolCall({
      id: 'tc-1', name: 'read', args: { path: '/a' }, result: '文件内容',
    });
    const tcs = useChatStreamStore.getState().streamingToolCalls;
    expect(tcs).toHaveLength(2);
    expect(tcs.find((t) => t.id === 'tc-1')?.result).toBe('文件内容');
  });

  it('resetAll 清掉 streaming + toolCalls + taskBoard', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('m', { initialContent: '' });
    useChatStreamStore.getState().setTaskBoard({
      runId: 'r1', plan: [], statuses: {},
    });
    useChatStreamStore.getState().resetAll();
    const s = useChatStreamStore.getState();
    expect(s.streaming).toBeNull();
    expect(s.streamingToolCalls).toEqual([]);
    expect(s.taskBoard).toBeNull();
  });

  it('两个 hook 实例 selector 同一 store → 跨组件共享', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('msg-1', { initialContent: 'X' });
    // 这里只断言通过 .getState() 读到，证明 store 是 module-singleton
    expect(useChatStreamStore.getState().streaming?.content).toBe('X');
  });
});