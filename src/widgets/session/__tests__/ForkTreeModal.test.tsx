// W2: ForkTreeModal —— 分叉家族树对话框组件测试。

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: { list: vi.fn() },
}));

import { sessionApi } from '../../../shared/api/sessionApi';
import type { Session } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ForkTreeModal } from '../ForkTreeModal';

// jsdom 不实现 ResizeObserver，但 @headlessui Dialog 内部使用它
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const mockList = vi.mocked(sessionApi.list);

const T0 = 1700000000000;

function sess(id: string, forkRoot: string | null, title = `会话-${id}`): Session {
  return {
    id,
    title,
    created_at: T0,
    updated_at: T0,
    last_message_at: null,
    message_count: 1,
    is_pinned: false,
    fork_root: forkRoot,
  };
}

function renderModal(overrides?: { sessionId?: string; activeSessionId?: string; onSwitch?: (id: string) => void }) {
  const session = sess(overrides?.sessionId ?? 'me', overrides?.sessionId === 'me' ? null : 'root');
  const onSwitch = overrides?.onSwitch ?? vi.fn();
  const onClose = vi.fn();
  render(
    <I18nProvider defaultLocale="zh">
      <ForkTreeModal
        isOpen
        session={session}
        activeSessionId={overrides?.activeSessionId ?? 'me'}
        onClose={onClose}
        onSwitch={onSwitch}
      />
    </I18nProvider>,
  );
  return { onSwitch, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ForkTreeModal', () => {
  it('加载后渲染家族节点，当前会话高亮并带「当前」徽标', async () => {
    mockList.mockResolvedValue([sess('root', null), sess('me', 'root')]);
    renderModal({ sessionId: 'me' });
    await waitFor(() => expect(screen.getByTestId('fork-tree-node-root')).toBeInTheDocument());
    expect(screen.getByTestId('fork-tree-node-me')).toBeInTheDocument();
    expect(screen.getByTestId('fork-tree-current-badge')).toBeInTheDocument();
  });

  it('点击节点切换会话并关闭对话框', async () => {
    mockList.mockResolvedValue([sess('root', null), sess('me', 'root')]);
    const onSwitch = vi.fn();
    const { onClose } = renderModal({ sessionId: 'me', onSwitch });
    await waitFor(() => expect(screen.getByTestId('fork-tree-node-root')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('fork-tree-node-root'));
    expect(onSwitch).toHaveBeenCalledWith('root');
    expect(onClose).toHaveBeenCalled();
  });

  it('单节点家族显示空态说明', async () => {
    mockList.mockResolvedValue([sess('lone', null)]);
    renderModal({ sessionId: 'lone' });
    await waitFor(() => expect(screen.getByTestId('fork-tree-single')).toBeInTheDocument());
  });

  it('list 失败时展示错误', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    renderModal({ sessionId: 'me' });
    await waitFor(() => expect(screen.getByTestId('fork-tree-error')).toHaveTextContent('boom'));
  });
});
