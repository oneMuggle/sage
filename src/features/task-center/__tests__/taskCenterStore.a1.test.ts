/**
 * A1 (parity-s4): taskCenterStore 七态状态机。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { TERMINAL_TASK_STATUSES, useTaskCenterStore } from '../taskCenterStore';

describe('taskCenterStore 状态机 (A1)', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
  });

  it('registerTask 默认 status=running', () => {
    useTaskCenterStore.getState().registerTask('a', 'office', '生成 PPT');
    expect(useTaskCenterStore.getState().tasks.a.status).toBe('running');
  });

  it('updateTask 可推进状态与阶段', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('a', 'office', '生成 PPT');
    useTaskCenterStore
      .getState()
      .updateTask('a', { status: 'awaiting_approval', phase: '等待审批' });
    const entry = useTaskCenterStore.getState().tasks.a;
    expect(entry.status).toBe('awaiting_approval');
    expect(entry.phase).toBe('等待审批');
  });

  it('completeTask 标记终态并保留条目', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('a', 'office', '生成 PPT');
    useTaskCenterStore.getState().completeTask('a', 'failed', '模型超时');
    const entry = useTaskCenterStore.getState().tasks.a;
    expect(entry.status).toBe('failed');
    expect(entry.error).toBe('模型超时');
    expect(entry.finishedAt).toEqual(expect.any(Number));
    expect(TERMINAL_TASK_STATUSES.has(entry.status)).toBe(true);
  });

  it('completeTask 目标不存在时 no-op', () => {
    expect(() => useTaskCenterStore.getState().completeTask('nope', 'succeeded')).not.toThrow();
    expect(useTaskCenterStore.getState().tasks).toEqual({});
  });

  it('clearFinished 只清终态、保留运行中', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('run', 'office', '进行中');
    s.registerTask('done', 'wiki', '已完成');
    s.registerTask('err', 'wiki', '失败');
    useTaskCenterStore.getState().completeTask('done', 'succeeded');
    useTaskCenterStore.getState().completeTask('err', 'failed', 'boom');
    useTaskCenterStore.getState().clearFinished();
    expect(Object.keys(useTaskCenterStore.getState().tasks)).toEqual(['run']);
  });

  it('removeTask 移除任意条目', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('a', 'office', 'A');
    useTaskCenterStore.getState().removeTask('a');
    expect(useTaskCenterStore.getState().tasks).toEqual({});
  });

  it('finishTask 保持 legacy 删除语义', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('a', 'office', 'A');
    useTaskCenterStore.getState().finishTask('a');
    expect(useTaskCenterStore.getState().tasks).toEqual({});
  });
});
