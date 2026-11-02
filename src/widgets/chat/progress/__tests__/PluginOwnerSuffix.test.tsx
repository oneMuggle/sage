// src/widgets/chat/progress/__tests__/PluginOwnerSuffix.test.tsx
//
// R114: 编排子代理实时行的插件归属后缀 —— 等待审批徽章与实时事件行在
// 工具名后追加「（所属插件: <name>）」；名单供数由 usePluginNames 承担
// （其契约在 hook 套件），这里只 mock 返回值测渲染结合。
//
// 2026-11-02 进度面板优化后实时事件行从 TaskTreeSection 迁入
// TaskDetailView：列表页只保留审批徽章，详情页同时有审批徽章与事件行，
// 本套件同时覆盖两处。
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskBoard } from '../../../../features/send-message/useChat';
import { TaskDetailView } from '../TaskDetailView';
import { TaskTreeSection } from '../TaskTreeSection';

const usePluginNamesMock = vi.fn();
vi.mock('../../../../shared/lib/hooks/usePluginNames', () => ({
  usePluginNames: (...a: unknown[]) => usePluginNamesMock(...a),
}));

const boardWithLive: TaskBoard = {
  runId: 'orch-1',
  plan: [{ task_id: 't1', agent_id: 'researcher', goal: '搜集资料' }],
  statuses: {
    t1: {
      state: 'task_status',
      run_id: 'orch-1',
      task_id: 't1',
      status: 'running',
      agent_id: 'researcher',
      goal: '搜集资料',
      error: null,
      output_preview: null,
    },
  },
  live: {
    t1: {
      liveStep: null,
      waitingApproval: 'plugin__demo__echo',
      events: [
        {
          state: 'subagent_event',
          run_id: 'orch-1',
          task_id: 't1',
          agent_id: 'researcher',
          goal: '搜集资料',
          phase: 'tool_call',
          tool_name: 'plugin__demo__echo',
        },
        {
          state: 'subagent_event',
          run_id: 'orch-1',
          task_id: 't1',
          agent_id: 'researcher',
          goal: '搜集资料',
          phase: 'tool_result',
          tool_name: 'read_file',
        },
      ],
    },
  },
};

function renderDetail() {
  return render(<TaskDetailView board={boardWithLive} taskId="t1" onBack={() => {}} />);
}

beforeEach(() => {
  usePluginNamesMock.mockReset().mockReturnValue(null);
});

describe('插件归属后缀（R114）', () => {
  it('名单可用：列表徽章 / 详情徽章 / 插件事件行带后缀，内置工具事件行不带', () => {
    usePluginNamesMock.mockReturnValue(['demo']);

    const { unmount } = render(<TaskTreeSection board={boardWithLive} />);
    expect(screen.getByTestId('task-tree-approval-t1')).toHaveTextContent(
      '⏳ 等待审批: plugin__demo__echo（所属插件: demo）',
    );
    expect(usePluginNamesMock).toHaveBeenCalledWith(true);
    unmount();

    usePluginNamesMock.mockClear();
    renderDetail();
    expect(screen.getByTestId('task-detail-approval')).toHaveTextContent(
      '⏳ 等待审批: plugin__demo__echo（所属插件: demo）',
    );
    expect(usePluginNamesMock).toHaveBeenCalledWith(true);
    const list = screen.getByTestId('task-detail-events');
    expect(list.textContent).toContain('🔧 plugin__demo__echo（所属插件: demo）');
    expect(list.textContent).toContain('👀 read_file');
    expect(list.textContent?.match(/所属插件/g)).toHaveLength(1);
  });

  it('名单不可用：列表徽章 / 详情徽章 / 事件行都不加后缀', () => {
    const { unmount } = render(<TaskTreeSection board={boardWithLive} />);
    expect(screen.getByTestId('task-tree-approval-t1')).toHaveTextContent(
      '⏳ 等待审批: plugin__demo__echo',
    );
    expect(screen.getByTestId('task-tree-approval-t1')).not.toHaveTextContent('所属插件');
    unmount();

    renderDetail();
    expect(screen.getByTestId('task-detail-approval')).toHaveTextContent(
      '⏳ 等待审批: plugin__demo__echo',
    );
    expect(screen.getByTestId('task-detail-approval')).not.toHaveTextContent('所属插件');
    expect(screen.getByTestId('task-detail-events').textContent).not.toContain('所属插件');
  });
});
