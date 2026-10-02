import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import { useTodoStore } from '../../../entities/todo/todoStore';
import type { Todo } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';

/**
 * UX-IA R3 批次 D（UI 接线）：rail 底部的统一待处理总数。
 *
 * 此前只有「对话」入口的角标（审批 + 提问）。折叠侧栏后所有提醒一并消失，
 * 而折叠往往正是为了让出对话区空间 —— 此刻最需要看到提醒。
 */

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      endpoints: [],
      modelSelections: {
        chatModel: { endpointId: null, modelId: null },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
      maxContext: 4096,
      temperature: 0.7,
    },
    updateSettings: vi.fn(),
  }),
}));

vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: vi.fn().mockResolvedValue({ success: false }),
}));

const PENDING_PERMISSION = {
  request_id: 'req-1',
  tool_name: 'terminal',
  args_summary: '{}',
  risk: 'suspicious' as const,
  message: '需要执行终端命令',
  created_at: 0,
};

function todo(status: Todo['status']): Todo {
  return {
    id: Math.random(),
    title: 't',
    status,
    priority: 'medium',
    is_recurring: false,
    created_at: '',
    updated_at: '',
  };
}

function renderSidebar(props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar width={300} {...props} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  usePermissionState.setState({ currentRequest: null });
  useQuestionState.setState({ currentQuestion: null });
  useTodoStore.setState({ todos: [] });
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

describe('Sidebar — rail 统一待处理总数（批次 D UI 接线）', () => {
  it('无待处理时不渲染总数角标（保持安静）', () => {
    renderSidebar();
    const slot = screen.getByTestId('sidebar-attention-total');
    expect(slot).toBeEmptyDOMElement();
  });

  it('审批挂起时计入总数', () => {
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    renderSidebar();
    expect(
      within(screen.getByTestId('sidebar-attention-total')).getByRole('status'),
    ).toHaveTextContent('1');
  });

  it('待办 pending / in_progress 计入，completed 不计', () => {
    useTodoStore.setState({
      todos: [todo('pending'), todo('in_progress'), todo('completed')],
    });
    renderSidebar();
    expect(
      within(screen.getByTestId('sidebar-attention-total')).getByRole('status'),
    ).toHaveTextContent('2');
  });

  it('多来源合计', () => {
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    useTodoStore.setState({ todos: [todo('pending')] });
    renderSidebar();
    expect(
      within(screen.getByTestId('sidebar-attention-total')).getByRole('status'),
    ).toHaveTextContent('2');
  });

  it('折叠态 rail 仍然显示总数（折叠不该丢提醒）', () => {
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    renderSidebar({ collapsed: true });
    const slot = screen.getByTestId('sidebar-attention-total');
    expect(within(slot).getByRole('status')).toHaveTextContent('1');
  });

  it('总数与「对话」入口的卡点角标并存且语义不同', async () => {
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    useTodoStore.setState({ todos: [todo('pending'), todo('pending')] });
    renderSidebar();
    // 「对话」入口只数审批 + 提问
    const chatLink = screen.getByRole('link', { name: '对话' });
    expect(within(chatLink).getByRole('status')).toHaveTextContent('1');
    // rail 底部总数含待办
    await waitFor(() => {
      expect(
        within(screen.getByTestId('sidebar-attention-total')).getByRole('status'),
      ).toHaveTextContent('3');
    });
  });
});
