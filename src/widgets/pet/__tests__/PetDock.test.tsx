/**
 * 桌宠 P1: PetDock 渲染/跳转/徽标测试。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { usePetStore } from '../../../features/pet/petStore';
import {
  useChatStreamStore,
  type SessionStreamSlots,
} from '../../../features/send-message/chatStreamStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { PetDock } from '../PetDock';

const slot = (overrides: Partial<SessionStreamSlots> = {}): SessionStreamSlots => ({
  streaming: null,
  streamingToolCalls: [],
  taskBoard: null,
  todos: [],
  completedSteps: [],
  shiftInfo: null,
  ...overrides,
});

const streaming = (messageId: string, state: string) =>
  ({
    messageId,
    content: '',
    reasoning: '',
    state,
    currentAgentId: null,
    iteration: 0,
  }) as SessionStreamSlots['streaming'];

function renderDock() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={['/welcome']}>
        <PetDock />
      </MemoryRouter>
    </I18nProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useChatStreamStore.getState().resetAll();
  usePermissionState.getState().resolve();
  usePetStore.setState({ enabled: false, petId: '', flash: null });
});

describe('PetDock', () => {
  it('开关关闭时不渲染', () => {
    renderDock();
    expect(screen.queryByTestId('pet-dock')).toBeNull();
  });

  it('开启后按流状态渲染对应动画态', () => {
    usePetStore.setState({ enabled: true, petId: 'violet-cat' });
    useChatStreamStore.setState({
      sessions: { s1: slot({ streaming: streaming('m1', 'thinking') }) },
    });
    renderDock();
    const dock = screen.getByTestId('pet-dock');
    expect(dock).toHaveAttribute('data-state', 'thinking');
    expect(screen.getByTestId('pet-visual')).toHaveAttribute('data-pet-id', 'violet-cat');
  });

  it('挂起审批 → attention 态', () => {
    usePetStore.setState({ enabled: true });
    usePermissionState.getState().setFromEvent({ tool_name: 'bash' } as never, 's2');
    renderDock();
    expect(screen.getByTestId('pet-dock')).toHaveAttribute('data-state', 'attention');
  });

  it('点击宠物跳转关联会话', async () => {
    usePetStore.setState({ enabled: true });
    useChatStreamStore.setState({
      sessions: { s7: slot({ streaming: streaming('m9', 'acting') }) },
    });
    renderDock();
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() =>
      expect(useStore.getState().currentSessionId).toBe('s7'),
    );
  });

  it('多会话并行时徽标显示在流会话数；单流不显示', () => {
    usePetStore.setState({ enabled: true });
    useChatStreamStore.setState({
      sessions: {
        a: slot({ streaming: streaming('m1', 'thinking') }),
        b: slot({ streaming: streaming('m2', 'acting') }),
        __btw__: slot({ streaming: streaming('m3', 'thinking') }),
      },
    });
    renderDock();
    expect(screen.getByTestId('pet-badge')).toHaveTextContent('2');
  });
});
