// src/widgets/chat/__tests__/Message.pluginOwner.test.tsx
//
// R111: 转录通用工具卡片的插件归属后缀 —— 命中权威名单时显示
// 「所属插件: <name>」；名单不可用 / 内置工具不显示。名单供数
// 由 usePluginNames 承担（其缓存/降级在 hook 套件覆盖），这里
// 只 mock 该 hook 的返回值测渲染结合。

import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const usePluginNamesMock = vi.fn();
vi.mock('../../../shared/lib/hooks/usePluginNames', () => ({
  usePluginNames: (...a: unknown[]) => usePluginNamesMock(...a),
}));

const pluginMsg: MessageType = {
  id: 'm1',
  session_id: 's',
  role: 'assistant',
  content: '已调用插件工具',
  created_at: 0,
  tool_calls: [{ id: 'tc-1', name: 'plugin__demo__echo', args: {} }],
};

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

beforeEach(() => {
  usePluginNamesMock.mockReset().mockReturnValue(null);
});

describe('Message 插件工具归属后缀（R111）', () => {
  it('名单命中时在裸工具名后显示所属插件', () => {
    usePluginNamesMock.mockReturnValue(['demo']);
    renderWithI18n(<Message message={pluginMsg} />);
    const owner = screen.getByTestId('tool-call-plugin-owner-0');
    expect(owner).toHaveTextContent('所属插件: demo');
  });

  it('名单不可用时不显示后缀（整体降级）', () => {
    renderWithI18n(<Message message={pluginMsg} />);
    expect(screen.queryByTestId('tool-call-plugin-owner-0')).not.toBeInTheDocument();
  });

  it('内置工具即使名单可用也不显示后缀', () => {
    usePluginNamesMock.mockReturnValue(['demo']);
    const builtinMsg: MessageType = {
      ...pluginMsg,
      tool_calls: [{ id: 'tc-2', name: 'read_file', args: { path: '/tmp/a.txt' } }],
    };
    renderWithI18n(<Message message={builtinMsg} />);
    expect(screen.queryByTestId('tool-call-plugin-owner-0')).not.toBeInTheDocument();
  });
});
