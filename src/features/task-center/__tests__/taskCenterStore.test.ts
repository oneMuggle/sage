/**
 * P4 第一切片: 任务中心 store 生命周期。
 */
import { describe, expect, it, beforeEach } from 'vitest';

import { useTaskCenterStore } from '../taskCenterStore';

describe('taskCenterStore', () => {
  beforeEach(() => {
    useTaskCenterStore.getState().finishTask('a');
    useTaskCenterStore.getState().finishTask('b');
    useTaskCenterStore.setState({ tasks: {} });
  });

  it('register / finish 生命周期', () => {
    const s1 = useTaskCenterStore.getState();
    s1.registerTask('a', 'office', '生成 PPT');
    expect(Object.keys(useTaskCenterStore.getState().tasks)).toEqual(['a']);

    useTaskCenterStore.getState().finishTask('a');
    expect(useTaskCenterStore.getState().tasks).toEqual({});
  });

  it('重复 register 同 id 不重置 startedAt，但刷新标题', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('a', 'office', '旧标题');
    const first = useTaskCenterStore.getState().tasks.a;
    s.registerTask('a', 'office', '新标题');
    const second = useTaskCenterStore.getState().tasks.a;
    expect(second.startedAt).toBe(first.startedAt);
    expect(second.title).toBe('新标题');
  });

  it('多任务并存，finishTask 只移除自身', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('a', 'office', 'A');
    s.registerTask('b', 'wiki', 'B');
    useTaskCenterStore.getState().finishTask('a');
    expect(Object.keys(useTaskCenterStore.getState().tasks)).toEqual(['b']);
  });
});
