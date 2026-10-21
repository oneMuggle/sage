// SessionSessionMenu / SessionSettingsMenu 组件测试（UI 优化 2026-10-14 Phase 2）。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// 顶栏收纳后的子控件在浮层内渲染，用 stub 隔离其内部依赖
vi.mock('../../widgets/chat/PermissionModeSwitch', () => ({
  PermissionModeSwitch: () => <div data-testid="permission-mode-stub" />,
}));
vi.mock('../../widgets/chat/ContextMeter', () => ({
  ContextMeter: () => <div data-testid="context-meter-stub" />,
}));

import { SessionSessionMenu } from '../chat/SessionSessionMenu';
import { SessionSettingsMenu } from '../chat/SessionSettingsMenu';

describe('SessionSessionMenu — + 图标下拉菜单', () => {
  const baseProps = {
    isLoading: false,
    hasConfig: true,
    currentSessionId: 'sess-1',
    onNewTopic: vi.fn(),
    onNewSession: vi.fn(),
    isTempChat: false,
    setTempChatSessions: vi.fn(),
  };

  it('默认收起浮层，点 + 展开三个条目', () => {
    render(<SessionSessionMenu {...baseProps} />);
    expect(screen.queryByTestId('session-session-menu-dropdown')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('session-session-menu-toggle'));
    expect(screen.getByTestId('session-menu-new-session')).toBeInTheDocument();
    expect(screen.getByTestId('session-menu-new-topic')).toBeInTheDocument();
    expect(screen.getByTestId('session-menu-temp-chat')).toBeInTheDocument();
  });

  it('点「新对话」回调 onNewSession 并收起浮层', () => {
    const onNewSession = vi.fn();
    render(<SessionSessionMenu {...baseProps} onNewSession={onNewSession} />);
    fireEvent.click(screen.getByTestId('session-session-menu-toggle'));
    fireEvent.click(screen.getByTestId('session-menu-new-session'));
    expect(onNewSession).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('session-session-menu-dropdown')).not.toBeInTheDocument();
  });

  it('点「新话题」回调 onNewTopic', () => {
    const onNewTopic = vi.fn();
    render(<SessionSessionMenu {...baseProps} onNewTopic={onNewTopic} />);
    fireEvent.click(screen.getByTestId('session-session-menu-toggle'));
    fireEvent.click(screen.getByTestId('session-menu-new-topic'));
    expect(onNewTopic).toHaveBeenCalledTimes(1);
  });

  it('无会话时不渲染临时聊天条目', () => {
    render(<SessionSessionMenu {...baseProps} currentSessionId={null} />);
    fireEvent.click(screen.getByTestId('session-session-menu-toggle'));
    expect(screen.queryByTestId('session-menu-temp-chat')).not.toBeInTheDocument();
  });

  it('isLoading 时「新话题」禁用', () => {
    render(<SessionSessionMenu {...baseProps} isLoading={true} />);
    fireEvent.click(screen.getByTestId('session-session-menu-toggle'));
    expect(screen.getByTestId('session-menu-new-topic')).toBeDisabled();
  });

  it('点浮层外收起', () => {
    render(<SessionSessionMenu {...baseProps} />);
    fireEvent.click(screen.getByTestId('session-session-menu-toggle'));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByTestId('session-session-menu-dropdown')).not.toBeInTheDocument();
  });

  it('Esc 收起浮层', () => {
    render(<SessionSessionMenu {...baseProps} />);
    fireEvent.click(screen.getByTestId('session-session-menu-toggle'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('session-session-menu-dropdown')).not.toBeInTheDocument();
  });
});

describe('SessionSettingsMenu — 齿轮浮层', () => {
  it('默认收起，点齿轮展开权限模式 + 上下文用量', () => {
    render(<SessionSettingsMenu sessionId="sess-1" />);
    expect(screen.queryByTestId('session-settings-menu-dropdown')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('session-settings-menu-toggle'));
    expect(screen.getByTestId('permission-mode-stub')).toBeInTheDocument();
    expect(screen.getByTestId('context-meter-stub')).toBeInTheDocument();
  });

  it('Esc 收起浮层', () => {
    render(<SessionSettingsMenu sessionId="sess-1" />);
    fireEvent.click(screen.getByTestId('session-settings-menu-toggle'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('session-settings-menu-dropdown')).not.toBeInTheDocument();
  });
});
