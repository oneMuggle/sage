import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PetConfigBridge, PetSnapshotBridge } from '../../../shared/types/electron-api';
import { InAppPet } from '../InAppPet';

const BASE_CONFIG: PetConfigBridge = {
  version: 3,
  enabled: true,
  displayMode: 'in-app',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
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
};

const SNAPSHOT: PetSnapshotBridge = {
  action: 'thinking',
  detail: null,
  sessionId: 'sess-1',
  sessionTitle: '写周报',
  toolName: null,
  bubbleKey: null,
  bubbleKind: null,
  todoDone: 2,
  todoTotal: 5,
  todoActive: '写测试',
  progressKind: 'todo',
  contextUsed: 40_000,
  contextMax: 128_000,
  lastTerminalAction: null,
  lastTerminalAt: null,
  patCount: 3,
  bondDays: 2,
  activeSessions: 1,
  attention: {
    needsYou: 1,
    failed: 0,
    running: 1,
    activeTasks: 0,
    total: 2,
    needsYouSessionIds: ['sess-1'],
  },
  sessions: [
    {
      sessionId: 'sess-1',
      sessionTitle: '写周报',
      action: 'thinking',
      detail: null,
      toolName: null,
      bubbleKey: null,
      todoDone: 2,
      todoTotal: 5,
      todoActive: '写测试',
      progressKind: 'todo',
      contextUsed: 40_000,
      contextMax: 128_000,
      lastTerminalAction: null,
      lastTerminalAt: null,
      updatedAt: 1,
    },
  ],
  tasks: [],
  updatedAt: 1,
};

function installBridge(config: PetConfigBridge) {
  const bridge = {
    getConfig: vi.fn().mockResolvedValue(config),
    getState: vi.fn().mockResolvedValue(SNAPSHOT),
    onState: vi.fn(() => () => undefined),
    getStates: vi.fn(
      async (): Promise<Record<string, PetSnapshotBridge>> => ({ default: SNAPSHOT }),
    ),
    onStates: vi.fn(() => () => undefined),
    onConfig: vi.fn(() => () => undefined),
    openSession: vi.fn(),
    openSettings: vi.fn(),
  };
  (window as unknown as { electronAPI?: unknown }).electronAPI = { pet: bridge };
  return bridge;
}

afterEach(() => {
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
});

describe('InAppPet', () => {
  it('renders the corner dock in in-app mode', async () => {
    installBridge(BASE_CONFIG);
    render(<InAppPet />);
    expect(await screen.findByTestId('in-app-pet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /思考中|Thinking/ })).toBeInTheDocument();
  });

  it('does not render in desktop-only mode', async () => {
    const bridge = installBridge({ ...BASE_CONFIG, displayMode: 'desktop' });
    render(<InAppPet />);
    await waitFor(() => expect(bridge.getConfig).toHaveBeenCalled());
    expect(screen.queryByTestId('in-app-pet')).toBeNull();
  });

  it('opens the current session on click', async () => {
    const bridge = installBridge(BASE_CONFIG);
    render(<InAppPet />);
    const petButton = await screen.findByRole('button', { name: /思考中|Thinking/ });
    petButton.click();
    expect(bridge.openSession).toHaveBeenCalledWith('sess-1');
  });

  it('renders one item per configured pet', async () => {
    installBridge({
      ...BASE_CONFIG,
      pets: [
        {
          id: 'default',
          petPack: 'dafeiyu',
          size: 'medium',
          followMode: 'focus',
          pinnedSessionId: null,
        },
        {
          id: 'pet-2',
          petPack: 'dafeiyu',
          size: 'small',
          followMode: 'focus',
          pinnedSessionId: null,
        },
      ],
    });
    render(<InAppPet />);
    const dock = await screen.findByTestId('in-app-pet');
    expect(dock).toHaveAttribute('data-pet-count', '2');
    expect(screen.getAllByTestId('in-app-pet-item')).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /思考中|Thinking/ })).toHaveLength(2);
  });

  it('renders a different snapshot for each pet', async () => {
    const second: PetSnapshotBridge = {
      ...SNAPSHOT,
      action: 'waiting',
      sessionId: 'sess-2',
      sessionTitle: '会话二',
      attention: {
        needsYou: 2,
        failed: 1,
        running: 1,
        activeTasks: 0,
        total: 4,
        needsYouSessionIds: ['sess-1', 'sess-2'],
      },
    };
    const config: PetConfigBridge = {
      ...BASE_CONFIG,
      pets: [
        {
          id: 'default',
          petPack: 'dafeiyu',
          size: 'medium',
          followMode: 'focus',
          pinnedSessionId: null,
        },
        {
          id: 'pet-2',
          petPack: 'dafeiyu',
          size: 'small',
          followMode: 'pinned',
          pinnedSessionId: 'sess-2',
        },
      ],
    };
    const bridge = installBridge(config);
    bridge.getStates.mockResolvedValue({ default: SNAPSHOT, 'pet-2': second });
    render(<InAppPet />);
    const items = await screen.findAllByTestId('in-app-pet-item');
    expect(items[0]).toHaveAttribute('data-pet-id', 'default');
    expect(items[1]).toHaveAttribute('data-pet-id', 'pet-2');
    expect(await screen.findByRole('button', { name: /等待确认|Waiting/ })).toBeInTheDocument();
  });
});
