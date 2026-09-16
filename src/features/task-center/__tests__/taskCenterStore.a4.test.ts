/**
 * A4: taskCenterStore 交付抽屉状态（delivery + deliveryRef）。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { useTaskCenterStore } from '../taskCenterStore';

describe('taskCenterStore 交付抽屉 (A4)', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {}, delivery: null });
  });

  it('初始 delivery 为 null', () => {
    expect(useTaskCenterStore.getState().delivery).toBeNull();
  });

  it('openDelivery/closeDelivery 切换 lane 抽屉', () => {
    useTaskCenterStore.getState().openDelivery({ kind: 'lane', laneId: 'lane-1' });
    expect(useTaskCenterStore.getState().delivery).toEqual({ kind: 'lane', laneId: 'lane-1' });
    useTaskCenterStore.getState().closeDelivery();
    expect(useTaskCenterStore.getState().delivery).toBeNull();
  });

  it('openDelivery 切换 office 抽屉', () => {
    useTaskCenterStore.getState().openDelivery({ kind: 'office', entryId: 'office:generate' });
    expect(useTaskCenterStore.getState().delivery).toEqual({
      kind: 'office',
      entryId: 'office:generate',
    });
  });

  it('updateTask 可写 deliveryRef（awaiting 条目交付坐标）', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('office:generate', 'office', '生成 Word');
    useTaskCenterStore.getState().updateTask('office:generate', {
      status: 'awaiting_approval',
      deliveryRef: { workspacePath: '/ws', filePath: '/ws/a.docx', formatSpec: null },
    });
    const entry = useTaskCenterStore.getState().tasks['office:generate'];
    expect(entry.status).toBe('awaiting_approval');
    expect(entry.deliveryRef).toEqual({
      workspacePath: '/ws',
      filePath: '/ws/a.docx',
      formatSpec: null,
    });
  });
});
