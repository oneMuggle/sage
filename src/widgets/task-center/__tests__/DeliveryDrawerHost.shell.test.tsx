import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { DeliveryDrawerHost } from '../DeliveryDrawerHost';

// useI18n() 在 <I18nProvider> 之外会 throw —— ShellStreamDrawer 内部要调它
const renderHost = () =>
  render(
    <I18nProvider>
      <DeliveryDrawerHost />
    </I18nProvider>,
  );

describe('DeliveryDrawerHost · shell 输出抽屉（Task 11）', () => {
  afterEach(() => {
    useTaskCenterStore.setState({ shellStream: null, delivery: null });
  });

  it('渲染 ShellStreamDrawer（原挂载点 TaskCenterWidget 已删除）', () => {
    useTaskCenterStore.setState({ shellStream: 'sh-1' });
    renderHost();
    expect(screen.getByTestId('shell-stream-drawer')).toBeTruthy();
  });

  it('无 shellStream 时不渲染 shell 抽屉', () => {
    renderHost();
    expect(screen.queryByTestId('shell-stream-drawer')).toBeNull();
  });
});
