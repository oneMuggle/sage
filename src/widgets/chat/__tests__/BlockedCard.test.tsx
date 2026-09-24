// src/widgets/chat/__tests__/BlockedCard.test.tsx
//
// R19-W1: 网页访问拦截可视化卡片 —— 原因映射、目标 URL、建议动作按钮与回调。

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { BlockedAction } from '../../../shared/lib/store';
import { BlockedCard } from '../BlockedCard';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

const actions: BlockedAction[] = [
  { action: 'open_browser', label: '用浏览器打开', params: { url: 'https://example.com/x' } },
  { action: 'configure_credentials', label: '配置登录凭据' },
  { action: 'view_docs', label: '查看文档', params: { url: 'https://example.com/docs' } },
];

describe('BlockedCard（R19-W1 拦截卡片）', () => {
  it('渲染标题、拦截原因文案与目标 URL', () => {
    renderWithI18n(
      <BlockedCard
        blockReason="login_wall"
        blockedUrl="https://example.com/private"
        suggestedActions={actions}
      />,
    );

    expect(screen.getByTestId('blocked-card')).toBeInTheDocument();
    expect(screen.getByText('网页访问被拦截')).toBeInTheDocument();
    expect(screen.getByText('需要登录')).toBeInTheDocument();
    expect(screen.getByText('https://example.com/private')).toBeInTheDocument();
  });

  it('每个 suggestedAction 渲染一个按钮，点击回调透传该动作', () => {
    const onAction = vi.fn();
    renderWithI18n(
      <BlockedCard blockReason="antibot_cf" suggestedActions={actions} onAction={onAction} />,
    );

    const buttons = screen.getAllByTestId(/^blocked-action-/);
    expect(buttons).toHaveLength(actions.length);

    fireEvent.click(screen.getByTestId('blocked-action-open_browser'));
    expect(onAction).toHaveBeenCalledWith(actions[0]);
  });

  it('未提供 suggestedActions 时不渲染任何按钮', () => {
    renderWithI18n(<BlockedCard blockReason="timeout" />);
    expect(screen.queryAllByTestId(/^blocked-action-/)).toHaveLength(0);
  });

  it('未知 blockReason 回退到 generic 文案而非渲染空白', () => {
    renderWithI18n(<BlockedCard blockReason="something_new" />);
    expect(screen.getByText('访问失败')).toBeInTheDocument();
    // 原始枚举值仍以徽章形式保留，便于排查
    expect(screen.getByText('something_new')).toBeInTheDocument();
  });

  it('渲染可读错误详情', () => {
    renderWithI18n(
      <BlockedCard blockReason="http_5xx" errorMessage="服务端返回 503，已重试 3 次" />,
    );
    expect(screen.getByText('服务端返回 503，已重试 3 次')).toBeInTheDocument();
  });

  it('无 onAction 时点击按钮不抛异常（防御性）', () => {
    renderWithI18n(<BlockedCard blockReason="dns" suggestedActions={actions} />);
    expect(() => fireEvent.click(screen.getByTestId('blocked-action-open_browser'))).not.toThrow();
  });

  it('login_to_site 动作渲染为按钮且点击回调正确', () => {
    const onAction = vi.fn();
    const loginActions: BlockedAction[] = [
      {
        action: 'login_to_site',
        label: '登录此站点',
        params: { url: 'https://platfm.agnes-ai.com' },
      },
      {
        action: 'open_browser',
        label: '用浏览器打开',
        params: { url: 'https://platfm.agnes-ai.com' },
      },
    ];
    renderWithI18n(
      <BlockedCard blockReason="login_wall" suggestedActions={loginActions} onAction={onAction} />,
    );

    const loginBtn = screen.getByTestId('blocked-action-login_to_site');
    expect(loginBtn).toBeInTheDocument();
    fireEvent.click(loginBtn);
    expect(onAction).toHaveBeenCalledWith(loginActions[0]);
  });
});
