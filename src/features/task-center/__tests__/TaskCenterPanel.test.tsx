import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { TaskCenterPanel } from '../TaskCenterPanel';
import { useTaskCenterStore } from '../taskCenterStore';
import { resetUnifiedTaskStore } from '../unifiedTaskStore';

// useI18n() 在 <I18nProvider> 之外会 throw —— 面板及其子卡片都调它
function renderPanel(variant: 'compact' | 'full') {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <TaskCenterPanel variant={variant} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

function seed(count: number, status: 'running' | 'failed' = 'running'): void {
  const tasks: Record<string, unknown> = {};
  for (let i = 0; i < count; i += 1) {
    tasks[`r${i}`] = { id: `r${i}`, kind: 'office', title: `任务 ${i}`, startedAt: i, status };
  }
  useTaskCenterStore.setState({ tasks: tasks as never });
}

describe('TaskCenterPanel', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
    resetUnifiedTaskStore();
  });

  it('空态显示占位文案', () => {
    renderPanel('compact');
    expect(screen.getByText('暂无正在进行的任务')).toBeTruthy();
  });

  it('compact 每组最多 3 条并显示"还有 N 条"', () => {
    seed(5);
    renderPanel('compact');
    expect(screen.getByText('任务 0')).toBeTruthy();
    expect(screen.getByText('任务 2')).toBeTruthy();
    expect(screen.queryByText('任务 3')).toBeNull();
    expect(screen.getByText(/还有 2 条/)).toBeTruthy();
  });

  it('full 模式展示全部并显示分组标题', () => {
    seed(5);
    renderPanel('full');
    expect(screen.getByText('任务 4')).toBeTruthy();
    expect(screen.getByText('进行中')).toBeTruthy();
  });

  it('compact 模式不显示已完成组', () => {
    useTaskCenterStore.setState({
      tasks: {
        bad: { id: 'bad', kind: 'office', title: '失败的', startedAt: 1, status: 'failed' },
        done: { id: 'done', kind: 'office', title: '完成的', startedAt: 9, status: 'succeeded' },
      } as never,
    });
    renderPanel('compact');
    expect(screen.queryByText('已完成')).toBeNull();
    // '失败' 恰好出现两次：分组标题 + 卡片状态标签。计数断言可发现分组标题被移除。
    expect(screen.getAllByText('失败')).toHaveLength(2);
  });

  it('full 模式显示已完成组与清除按钮', () => {
    useTaskCenterStore.setState({
      tasks: {
        done: { id: 'done', kind: 'office', title: '完成的', startedAt: 9, status: 'succeeded' },
      } as never,
    });
    renderPanel('full');
    // '已完成' 恰好出现两次：分组标题 + 卡片状态标签（清除按钮文案是"清除已完成"，不精确匹配）。
    expect(screen.getAllByText('已完成')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /清除已完成/ })).toBeTruthy();
  });
});
