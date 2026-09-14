/**
 * R41: 设置页搜索测试 —— 搜索框过滤左侧 tab 列表。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {},
    isLoading: false,
    updateSettings: vi.fn(),
    resetSettings: vi.fn(),
  }),
}));

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockRejectedValue(new Error('test')),
}));

vi.mock('../../shared/api/desktopEvent', () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

import { I18nProvider } from '../../../shared/lib/i18n';
import { MemoryRouter } from 'react-router-dom';
import { Settings } from '../Settings';

const renderSettings = () =>
  render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">
        <Settings />
      </I18nProvider>
    </MemoryRouter>,
  );

describe('Settings — R41 搜索', () => {
  it('渲染搜索框', () => {
    renderSettings();
    expect(screen.getByTestId('settings-search')).toBeInTheDocument();
  });

  it('输入关键词过滤 tab 列表', () => {
    renderSettings();
    const input = screen.getByTestId('settings-search');
    fireEvent.change(input, { target: { value: '端点' } });
    expect(screen.getByText('端点')).toBeInTheDocument();
    expect(screen.queryByText('通用')).not.toBeInTheDocument();
    expect(screen.queryByText('进化')).not.toBeInTheDocument();
  });

  it('清空搜索恢复全部 tab', () => {
    renderSettings();
    const input = screen.getByTestId('settings-search');
    fireEvent.change(input, { target: { value: '端点' } });
    fireEvent.change(input, { target: { value: '' } });
    expect(screen.getByText('通用')).toBeInTheDocument();
    expect(screen.getByText('模型')).toBeInTheDocument();
  });
});
