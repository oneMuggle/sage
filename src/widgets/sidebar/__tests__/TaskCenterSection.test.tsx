import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { resetUnifiedTaskStore } from '../../../features/task-center/unifiedTaskStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TaskCenterSection } from '../sections/TaskCenterSection';

// useI18n() 在 <I18nProvider> 之外会 throw（SiderSection 内部也调它）
function renderSection(collapsed = false) {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <TaskCenterSection collapsed={collapsed} onToggleCollapsed={() => {}} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('TaskCenterSection', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
    resetUnifiedTaskStore();
  });

  it('渲染"任务"章节头', () => {
    renderSection();
    expect(screen.getByText('任务')).toBeTruthy();
  });

  it('有任务时章节头显示计数', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: 'a', startedAt: 1, status: 'running' },
        r2: { id: 'r2', kind: 'office', title: 'b', startedAt: 1, status: 'failed' },
      } as never,
    });
    renderSection();
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('折叠时不渲染卡片', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: '不应出现', startedAt: 1, status: 'running' },
      } as never,
    });
    renderSection(true);
    expect(screen.queryByText('不应出现')).toBeNull();
  });
});
