import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { PetConfigBridge, PetSnapshotBridge } from '../../shared/types/electron-api';
import { PetPanel } from '../PetPanel';

const config: PetConfigBridge = {
  version: 3,
  enabled: true,
  displayMode: 'desktop',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: true,
  compatibilityMode: 'auto',
  externalApi: false,
  pets: [
    {
      id: 'default',
      petPack: 'dafeiyu',
      size: 'medium',
      followMode: 'focus',
      pinnedSessionId: null,
    },
  ],
  petId: 'default',
  followMode: 'focus',
  pinnedSessionId: null,
};

function summary(sessionId: string, title: string, action: string) {
  return {
    sessionId,
    sessionTitle: title,
    action,
    detail: null,
    toolName: null,
    bubbleKey: null,
    todoDone: 0,
    todoTotal: 0,
    todoActive: null,
    progressKind: null,
    contextUsed: null,
    contextMax: null,
    lastTerminalAction: null,
    lastTerminalAt: null,
    updatedAt: 1,
  };
}

const snapshot: PetSnapshotBridge = {
  action: 'waiting',
  detail: null,
  sessionId: 'a',
  sessionTitle: '会话 A',
  toolName: null,
  bubbleKey: null,
  bubbleKind: null,
  todoDone: 0,
  todoTotal: 0,
  todoActive: null,
  progressKind: null,
  contextUsed: null,
  contextMax: null,
  lastTerminalAction: null,
  lastTerminalAt: null,
  patCount: 0,
  bondDays: 1,
  activeSessions: 3,
  sessions: [
    summary('a', '会话 A', 'waiting'),
    summary('b', '会话 B', 'acting'),
    summary('c', '会话 C', 'thinking'),
    summary('d', '会话 D', 'done'),
  ],
  tasks: [],
  attention: {
    needsYou: 2,
    failed: 1,
    running: 8,
    activeTasks: 0,
    total: 11,
    needsYouSessionIds: ['a'],
  },
  updatedAt: 1,
};

function renderPanel(overrides: Partial<Parameters<typeof PetPanel>[0]> = {}) {
  const props = {
    snapshot,
    config,
    onClose: vi.fn(),
    onOpenSession: vi.fn(),
    onOpenSettings: vi.fn(),
    onPinSession: vi.fn(),
    onCycleFocus: vi.fn(),
    ...overrides,
  };
  render(<PetPanel {...props} />);
  return props;
}

describe('PetPanel', () => {
  it('shows untruncated global counts instead of the five-session slice', () => {
    renderPanel();
    expect(screen.getByText(/8 个进行中/)).toBeInTheDocument();
    expect(screen.getByText(/2 个待处理/)).toBeInTheDocument();
    expect(screen.getByText(/1 个出错/)).toBeInTheDocument();
  });

  it('groups sessions into needs-you / running / other', () => {
    renderPanel();
    expect(screen.getByText('需要处理')).toBeInTheDocument();
    expect(screen.getByText('正在运行')).toBeInTheDocument();
    expect(screen.getByText('其他会话')).toBeInTheDocument();
  });

  it('pins a session without nesting buttons', () => {
    const onPinSession = vi.fn();
    renderPanel({ onPinSession });
    fireEvent.click(screen.getByTestId('pet-pin-b'));
    expect(onPinSession).toHaveBeenCalledWith('b');
  });

  it('offers the next needs-you action', () => {
    const onCycleFocus = vi.fn();
    renderPanel({ onCycleFocus });
    fireEvent.click(screen.getByTestId('pet-next-needs-you'));
    expect(onCycleFocus).toHaveBeenCalled();
  });

  it('reports the pinned label only while the pin is in effect', () => {
    renderPanel({ config: { ...config, followMode: 'pinned', pinnedSessionId: 'a' } });
    expect(screen.getByTestId('pet-panel-follow')).toHaveTextContent('已钉住');
  });

  it('falls back to the focus label when no session is pinned', () => {
    renderPanel({ config: { ...config, followMode: 'pinned', pinnedSessionId: null } });
    expect(screen.getByTestId('pet-panel-follow')).toHaveTextContent('跟随焦点');
  });
});
