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
      id: 'tc-1',
      name: 'read',
      args: { path: '/a' },
    });
    useChatStreamStore.getState().appendOrUpdateToolCall({
      id: 'tc-2',
      name: 'bash',
      args: { cmd: 'ls' },
    });
    useChatStreamStore.getState().appendOrUpdateToolCall({
      id: 'tc-1',
      name: 'read',
      args: { path: '/a' },
      result: '文件内容',
    });
    const tcs = useChatStreamStore.getState().streamingToolCalls;
    expect(tcs).toHaveLength(2);
    expect(tcs.find((t) => t.id === 'tc-1')?.result).toBe('文件内容');
  });

  it('resetAll 清掉 streaming + toolCalls + taskBoard', () => {
    useChatStreamStore.getState().resetAll();
    useChatStreamStore.getState().startStream('m', { initialContent: '' });
    useChatStreamStore.getState().setTaskBoard({
      runId: 'r1',
      plan: [],
      statuses: {},
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

  // 2026-09-02 bug fix: 验证 reasoning_delta + reasoning_final 不再重复显示
  describe('reasoning 流式去重 (reasoning_final 替换而非追加)', () => {
    it('appendReasoning 累积 reasoning 增量', () => {
      useChatStreamStore.getState().resetAll();
      useChatStreamStore.getState().startStream('msg-1', { initialContent: '' });
      useChatStreamStore.getState().appendReasoning('msg-1', '增量-1');
      useChatStreamStore.getState().appendReasoning('msg-1', '增量-2');
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe('增量-1增量-2');
    });

    it('replaceReasoning 整体替换 reasoning', () => {
      useChatStreamStore.getState().resetAll();
      useChatStreamStore.getState().startStream('msg-1', { initialContent: '' });
      useChatStreamStore.getState().appendReasoning('msg-1', '旧内容');
      useChatStreamStore.getState().replaceReasoning('msg-1', '新内容');
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe('新内容');
    });

    it('replaceReasoning 在 messageId 不匹配时不动 store (跨流保护)', () => {
      useChatStreamStore.getState().resetAll();
      useChatStreamStore.getState().startStream('msg-A', { initialContent: '' });
      useChatStreamStore.getState().appendReasoning('msg-A', 'A 的思考');
      useChatStreamStore.getState().replaceReasoning('msg-B', 'B 的覆盖');
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe('A 的思考');
    });

    it('模拟后端 reasoning_delta + reasoning_final → reasoning 只显示一次', () => {
      // 模拟后端对一个 LLM reasoning 事件的处理:
      //   1) N 个 reasoning_delta (每块一段字符)
      //   2) 1 个 reasoning_final (done_reasoning 全量)
      // 前端必须先 appendReasoning 各 delta, 再 replaceReasoning 全量 ——
      // 若 replaceReasoning 缺失,reasoning 文本会被 append 两次,显示重复。
      useChatStreamStore.getState().resetAll();
      useChatStreamStore.getState().startStream('msg-1', { initialContent: '' });
      const fullReasoning = 'The user said 你好. This is a simple greeting.';
      const chunk1 = fullReasoning.slice(0, 20);
      const chunk2 = fullReasoning.slice(20);
      // 模拟后端流:先 deltas,再 final 全量
      useChatStreamStore.getState().appendReasoning('msg-1', chunk1);
      useChatStreamStore.getState().appendReasoning('msg-1', chunk2);
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe(fullReasoning);
      useChatStreamStore.getState().replaceReasoning('msg-1', fullReasoning);
      // 关键断言:replace 之后文本长度不变,没有重复
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe(fullReasoning);
      expect(useChatStreamStore.getState().streaming?.reasoning).toHaveLength(fullReasoning.length);
    });

    it('多段 reasoning:每段 delta 累加后 final 全量替换,前后段不混淆', () => {
      // LLM 可能 yield 多个 reasoning 事件 (e.g. 计划阶段 1 + 计划阶段 2),
      // 每段都有自己的 reasoning_delta + reasoning_final。
      // 验证: 第二段的 final 不影响第一段累积,且第二段 final 是完整全量。
      useChatStreamStore.getState().resetAll();
      useChatStreamStore.getState().startStream('msg-1', { initialContent: '' });
      // 第一段
      useChatStreamStore.getState().appendReasoning('msg-1', '段1-内容');
      useChatStreamStore.getState().replaceReasoning('msg-1', '段1-内容');
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe('段1-内容');
      // 第二段:append 是继续累积?还是 replace?
      // 当前设计:第二段沿用 append (LLM 把第二段视为增量继续),final 再 replace 全量。
      // 但为了避免问题,设计上更稳妥的做法是:每段都从 0 开始累积,final 全量替换。
      // 此测试记录现状 (append 继续累积) — 若未来改为分段 reset,需相应更新。
      useChatStreamStore.getState().appendReasoning('msg-1', '段2-内容');
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe('段1-内容段2-内容');
      // final 是 done_reasoning 全量 (后端会算 = 段1 + 段2)
      useChatStreamStore.getState().replaceReasoning('msg-1', '段1-内容段2-内容');
      expect(useChatStreamStore.getState().streaming?.reasoning).toBe('段1-内容段2-内容');
    });
  });
});
