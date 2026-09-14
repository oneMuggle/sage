/**
 * A4: TaskCenterWidget 交付待验收接入 —— 待验收条目点击直达交付抽屉。
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { useLaneBoardStore } from '../../../entities/orchestration/laneBoardStore';
import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import type { Lane } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TaskCenterWidget } from '../TaskCenterWidget';

function seedLane(overrides: Partial<Lane> = {}): Lane {
  return {
    lane_id: 'lane-1',
    task_id: 't1',
    agent_id: 'agent-a',
    status: 'succeeded',
    created_at: Date.now(),
    started_at: Date.now(),
    completed_at: Date.now(),
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'standard',
    metadata: {},
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

function renderWidget() {
  return render(
    <MemoryRouter initialEntries={['/chat']}>
      <I18nProvider>
        <LocationProbe />
        <TaskCenterWidget />
      </I18nProvider>
    </MemoryRouter>,
  );
}

function openList() {
  fireEvent.click(screen.getByTestId('task-center-toggle'));
  return screen.getByTestId('task-center-list');
}

describe('TaskCenterWidget 交付接入 (A4)', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {}, delivery: null });
    useLaneBoardStore.setState({ lanes: [], loading: false, error: null, teamIdFilter: null });
    useChatStreamStore.setState({ sessions: {} });
  });

  it('succeeded 未决议 lane 以待验收呈现，点击打开 lane 抽屉（不跳转）', () => {
    useLaneBoardStore.setState({ lanes: [seedLane()] });
    renderWidget();
    const list = openList();

    const buttons = within(list).getAllByRole('button');
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);

    expect(useTaskCenterStore.getState().delivery).toEqual({
      kind: 'lane',
      laneId: 'lane-1',
    });
    expect(screen.getByTestId('location-probe').textContent).toBe('/chat');
  });

  it('已决议 lane 不进胶囊', () => {
    useLaneBoardStore.setState({
      lanes: [seedLane({ metadata: { accepted_at: 1759000001000 } })],
    });
    renderWidget();

    expect(screen.queryByTestId('task-center')).toBeNull();
  });

  it('office awaiting 条目点击打开 office 抽屉（不跳转）', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('office:generate', 'office', 'report.docx');
    useTaskCenterStore.getState().updateTask('office:generate', {
      status: 'awaiting_approval',
      deliveryRef: { workspacePath: '/ws', filePath: '/ws/report.docx', formatSpec: null },
    });
    renderWidget();
    const list = openList();

    const buttons = within(list).getAllByRole('button');
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);

    expect(useTaskCenterStore.getState().delivery).toEqual({
      kind: 'office',
      entryId: 'office:generate',
    });
    expect(screen.getByTestId('location-probe').textContent).toBe('/chat');
  });

  it('awaiting 但无 deliveryRef 的条目仍走 route 跳转', () => {
    const s = useTaskCenterStore.getState();
    s.registerTask('office:generate', 'office', 'report.docx');
    useTaskCenterStore.getState().updateTask('office:generate', { status: 'awaiting_approval' });
    renderWidget();
    const list = openList();

    fireEvent.click(within(list).getAllByRole('button')[0]);

    expect(useTaskCenterStore.getState().delivery).toBeNull();
    expect(screen.getByTestId('location-probe').textContent).toBe('/office');
  });

  it('blocked lane 仍跳转编排页（不进交付抽屉）', () => {
    useLaneBoardStore.setState({ lanes: [seedLane({ status: 'blocked' })] });
    renderWidget();
    const list = openList();

    // 首个按钮是条目（第二个是取消键）。
    fireEvent.click(within(list).getAllByRole('button')[0]);

    expect(useTaskCenterStore.getState().delivery).toBeNull();
    expect(screen.getByTestId('location-probe').textContent).toBe('/orchestration');
  });
});
