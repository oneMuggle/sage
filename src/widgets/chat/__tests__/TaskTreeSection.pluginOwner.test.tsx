// src/widgets/chat/__tests__/TaskTreeSection.pluginOwner.test.tsx
//
// R114: 编排任务树实时行的插件归属后缀 —— 等待审批徽章与事
// 件行在工具名后追加「（所属插件: <name>）」；名单供数由
// usePluginNames 承担（其契约在 hook 套件），这里只 mock
// 返回值测渲染结合。既有 TaskTree 套件无 live 夹具、门控关，
// 不受影响。

import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskBoard } from '../../../features/send-message/useChat';
import { TaskTreeSection } from '../progress/TaskTreeSection';

const usePluginNamesMock = vi.fn();
vi.mock('../../../shared/lib/hooks/usePluginNames', () => ({
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

beforeEach(() => {
  usePluginNamesMock.mockReset().mockReturnValue(null);
});

describe('TaskTreeSection 实时行插件归属（R114）', () => {
  it('等待审批徽章与插件事件行带归属后缀，内置工具事件行不带', () => {
    usePluginNamesMock.mockReturnValue(['demo']);
    render(<TaskTreeSection board={boardWithLive} />);
    expect(screen.getByTestId('task-tree-approval-t1')).toHaveTextContent(
      '⏳ 等待审批: plugin__demo__echo（所属插件: demo）',
    );
    expect(usePluginNamesMock).toHaveBeenCalledWith(true);
    const list = screen.getByTestId('task-tree-events-t1');
    expect(list.textContent).toContain('🔧 plugin__demo__echo（所属插件: demo）');
    expect(list.textContent).toContain('👀 read_file');
    expect(list.textContent?.match(/所属插件/g)).toHaveLength(1);
  });

  it('名单不可用时徽章与事件行都不加后缀', () => {
    render(<TaskTreeSection board={boardWithLive} />);
    expect(screen.getByTestId('task-tree-approval-t1')).toHaveTextContent(
      '⏳ 等待审批: plugin__demo__echo',
    );
    expect(screen.getByTestId('task-tree-approval-t1')).not.toHaveTextContent('所属插件');
    expect(screen.getByTestId('task-tree-events-t1').textContent).not.toContain('所属插件');
  });
});
