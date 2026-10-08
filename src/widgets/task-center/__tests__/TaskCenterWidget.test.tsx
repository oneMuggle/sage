import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
/**
 * P4 第一块片: TaskCenterWidget 渲染行为。
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, beforeEach } from 'vitest';

import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TaskCenterWidget } from '../TaskCenterWidget';

function renderWidget() {
  return render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">
        <TaskCenterWidget />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('TaskCenterWidget', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
  });

  it('无任务时不渲染', () => {
    renderWidget();
    expect(screen.queryByTestId('task-center')).not.toBeInTheDocument();
  });

  it('有任务时渲染计数胶囊，展开列出条目并可收起', () => {
    useTaskCenterStore.getState().registerTask('office:generate', 'office', '生成 PPT');
    renderWidget();

    expect(screen.getByTestId('task-center')).toBeInTheDocument();
    expect(screen.getByTestId('task-center-toggle')).toHaveTextContent('1');

    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.getByTestId('task-center-list')).toBeInTheDocument();
    expect(screen.getByText('生成 PPT')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.queryByTestId('task-center-list')).not.toBeInTheDocument();
  });

  it('U1: 右侧面板最大化时胶囊标记 data-panel-maximized 并自动收起展开列表', async () => {
    useTaskCenterStore.getState().registerTask('t-u1', 'office', '生成论文.docx');
    useRightPanelStore.setState({ open: true, maximized: false });
    renderWidget();
    const root = screen.getByTestId('task-center');
    expect(root.getAttribute('data-panel-maximized')).toBe('false');
    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.getByTestId('task-center-list')).toBeInTheDocument();

    act(() => {
      useRightPanelStore.setState({ open: true, maximized: true });
    });
    expect(screen.getByTestId('task-center').getAttribute('data-panel-maximized')).toBe('true');
    expect(screen.queryByTestId('task-center-list')).not.toBeInTheDocument();
    useRightPanelStore.setState({ open: true, maximized: false });
  });
});
