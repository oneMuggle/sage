import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useLaneBoardStore } from '../../../entities/orchestration/laneBoardStore';
import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import type { Lane } from '../../../shared/api/types';
import { DeliveryDrawerHost } from '../DeliveryDrawerHost';

// 两个交付抽屉各自带编排 / office 依赖；本文件只测宿主的分支选择
// （解哪条 lane、给什么坐标、缺料时是否静默），抽屉内部行为由各自模块负责。
vi.mock('../../orchestration/LaneDetailDrawer', () => ({
  LaneDetailDrawer: ({ lane }: { lane: { lane_id: string } }) => (
    <div data-testid="lane-detail-drawer">{lane.lane_id}</div>
  ),
}));
vi.mock('../../../features/office/OfficeDeliveryDrawer', () => ({
  OfficeDeliveryDrawer: ({ entryId }: { entryId: string }) => (
    <div data-testid="office-delivery-drawer">{entryId}</div>
  ),
}));

function makeLane(laneId: string): Lane {
  return {
    lane_id: laneId,
    task_id: 't1',
    agent_id: null,
    status: 'succeeded',
    created_at: 0,
    started_at: null,
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'default',
    metadata: {},
  };
}

describe('DeliveryDrawerHost · 交付抽屉分支（Task 11 重写后）', () => {
  afterEach(() => {
    useTaskCenterStore.setState({ delivery: null, shellStream: null, tasks: {} });
    useLaneBoardStore.setState({ lanes: [] });
  });

  it('lane 交付：board 上有该 lane 时渲染 lane 抽屉', () => {
    useLaneBoardStore.setState({ lanes: [makeLane('l1')] });
    useTaskCenterStore.setState({ delivery: { kind: 'lane', laneId: 'l1' } });
    render(<DeliveryDrawerHost />);
    expect(screen.getByTestId('lane-detail-drawer').textContent).toBe('l1');
  });

  it('lane 交付：board 上没有该 lane 时不渲染任何抽屉', () => {
    useLaneBoardStore.setState({ lanes: [makeLane('other')] });
    useTaskCenterStore.setState({ delivery: { kind: 'lane', laneId: 'l1' } });
    render(<DeliveryDrawerHost />);
    expect(screen.queryByTestId('lane-detail-drawer')).toBeNull();
  });

  it('office 交付：delivery.ref 直接给出坐标时渲染 office 抽屉', () => {
    useTaskCenterStore.setState({
      delivery: {
        kind: 'office',
        entryId: 'e1',
        ref: { workspacePath: '/ws', filePath: 'a.docx', formatSpec: null },
      },
    });
    render(<DeliveryDrawerHost />);
    expect(screen.getByTestId('office-delivery-drawer').textContent).toBe('e1');
  });

  it('office 交付：无 ref 时回落到条目的 deliveryRef', () => {
    useTaskCenterStore.setState({
      delivery: { kind: 'office', entryId: 'e1' },
      tasks: {
        e1: {
          id: 'e1',
          kind: 'office',
          title: '生成文档',
          startedAt: 0,
          status: 'awaiting_approval',
          deliveryRef: { workspacePath: '/ws', filePath: 'b.docx', formatSpec: null },
        },
      },
    });
    render(<DeliveryDrawerHost />);
    expect(screen.getByTestId('office-delivery-drawer').textContent).toBe('e1');
  });

  it('office 交付：既无 ref 也无条目时不渲染任何抽屉', () => {
    useTaskCenterStore.setState({ delivery: { kind: 'office', entryId: 'e1' } });
    render(<DeliveryDrawerHost />);
    expect(screen.queryByTestId('office-delivery-drawer')).toBeNull();
  });
});
