import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { TaskCenterCard } from '../TaskCenterCard';
import type { UnifiedTaskEntry } from '../unifiedTaskModel';

// useI18n() 在 <I18nProvider> 之外会直接 throw —— 所有组件测试必须包裹
const wrap = (ui: React.ReactElement) => <I18nProvider>{ui}</I18nProvider>;
const renderCard = (ui: React.ReactElement) => render(wrap(ui));

const makeEntry = (over: Partial<UnifiedTaskEntry> = {}): UnifiedTaskEntry => ({
  id: 'goal:g1',
  source: 'goal',
  title: '整理文献',
  status: 'running',
  startedAt: 1,
  updatedAt: null,
  percent: 40,
  error: null,
  cancellable: true,
  detailPath: '/goals/g1',
  openTarget: null,
  cancelRef: { source: 'goal', rawId: 'g1' },
  meta: {},
  ...over,
});

const actions = {
  cancel: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  runNow: vi.fn(),
  open: vi.fn(),
  clearFinished: vi.fn(),
};

describe('TaskCenterCard', () => {
  it('渲染标题与来源标签', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    expect(screen.getByText('整理文献')).toBeTruthy();
    expect(screen.getByText('闲时目标')).toBeTruthy();
  });

  it('percent 非 null 时渲染进度条，否则渲染耗时', () => {
    const { rerender } = renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    expect(screen.getByRole('progressbar')).toBeTruthy();

    rerender(
      wrap(
        <TaskCenterCard
          entry={makeEntry({ percent: null, startedAt: Date.now() - 65_000 })}
          actions={actions}
        />,
      ),
    );
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.getByText(/1m/)).toBeTruthy();
  });

  it('可取消时点取消按钮调 actions.cancel', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    fireEvent.click(screen.getByRole('button', { name: /取消/ }));
    expect(actions.cancel).toHaveBeenCalledWith(expect.objectContaining({ id: 'goal:g1' }));
  });

  it('不可取消时不渲染取消按钮', () => {
    renderCard(<TaskCenterCard entry={makeEntry({ cancellable: false })} actions={actions} />);
    expect(screen.queryByRole('button', { name: /取消/ })).toBeNull();
  });

  it('点击卡片主体调 actions.open', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    fireEvent.click(screen.getByRole('button', { name: /整理文献/ }));
    expect(actions.open).toHaveBeenCalled();
  });

  it('failed 状态渲染错误文案', () => {
    renderCard(
      <TaskCenterCard
        entry={makeEntry({ status: 'failed', error: '模型超时' })}
        actions={actions}
      />,
    );
    expect(screen.getByText('模型超时')).toBeTruthy();
  });

  it('compact 模式隐藏来源标签', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} compact />);
    expect(screen.queryByText('闲时目标')).toBeNull();
  });
});
