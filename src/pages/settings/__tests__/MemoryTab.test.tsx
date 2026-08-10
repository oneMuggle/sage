// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MemoryTab } from '../MemoryTab';

const mocks = vi.hoisted(() => ({
  getAutoMemory: vi.fn(),
  setAutoMemory: vi.fn(),
  getMemoryRetrieval: vi.fn(),
  setMemoryRetrieval: vi.fn(),
}));

beforeEach(() => {
  mocks.getAutoMemory.mockReset();
  mocks.setAutoMemory.mockReset();
  mocks.getMemoryRetrieval.mockReset();
  mocks.setMemoryRetrieval.mockReset();
  mocks.getAutoMemory.mockResolvedValue(null);
  mocks.setAutoMemory.mockResolvedValue(undefined);
  mocks.getMemoryRetrieval.mockResolvedValue(null);
  mocks.setMemoryRetrieval.mockResolvedValue(undefined);

  // Install electronAPI stub on window
  Object.defineProperty(window, 'electronAPI', {
    configurable: true,
    value: {
      memory: {
        getAutoMemory: (...args: unknown[]) => mocks.getAutoMemory(...args),
        setAutoMemory: (...args: unknown[]) => mocks.setAutoMemory(...args),
        getMemoryRetrieval: (...args: unknown[]) => mocks.getMemoryRetrieval(...args),
        setMemoryRetrieval: (...args: unknown[]) => mocks.setMemoryRetrieval(...args),
      },
    },
  });
});

const baseSettings = {
  streaming: true,
  autoMemory: true,
  // §1.3b f: independent field — "同步到内部服务器" is NOT autoMemory.
  memoryServerSync: false,
  confirmDelete: true,
  compactMode: false,
  endpoints: [],
  modelSelections: {
    chatModel: { endpointId: null, modelId: null },
    visionModel: { endpointId: null, modelId: null },
    embeddingModel: { endpointId: null, modelId: null },
  },
  maxContext: 4096,
  temperature: 0.7,
  proxyMode: 'system' as const,
  proxyUrl: '',
  tlsVersion: '1.2' as const,
  wiki: { useFolderPicker: true },
  version: '3.0.0',
};

function renderTab() {
  return render(
    <MemoryRouter>
      <MemoryTab settings={baseSettings} updateSettings={vi.fn().mockResolvedValue(undefined)} />
    </MemoryRouter>,
  );
}

describe('MemoryTab', () => {
  it('renders the autoMemory toggle as checked when getAutoMemory returns "true"', async () => {
    mocks.getAutoMemory.mockResolvedValue('true');
    renderTab();
    // The autoMemory toggle lives inside the SettingRow whose label is
    // '自动记忆沉淀'. Scope the role query to that row.
    const row = await screen.findByText('自动记忆沉淀');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
  });

  it('renders the autoMemory toggle as unchecked when getAutoMemory returns "false"', async () => {
    mocks.getAutoMemory.mockResolvedValue('false');
    renderTab();
    const row = await screen.findByText('自动记忆沉淀');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'));
  });

  it('defaults to checked when getAutoMemory returns null (default True)', async () => {
    mocks.getAutoMemory.mockResolvedValue(null);
    renderTab();
    const row = await screen.findByText('自动记忆沉淀');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
  });

  it('calls window.electronAPI.memory.setAutoMemory when toggled', async () => {
    mocks.getAutoMemory.mockResolvedValue('true');
    renderTab();
    const row = await screen.findByText('自动记忆沉淀');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(toggle);
    await waitFor(() => expect(mocks.setAutoMemory).toHaveBeenCalledWith({ value: false }));
  });

  it('renders the memoryRetrieval toggle as checked when getMemoryRetrieval returns "true"', async () => {
    mocks.getMemoryRetrieval.mockResolvedValue('true');
    renderTab();
    const row = await screen.findByText('记忆检索注入');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
  });

  it('renders the memoryRetrieval toggle as unchecked when getMemoryRetrieval returns "false"', async () => {
    mocks.getMemoryRetrieval.mockResolvedValue('false');
    renderTab();
    const row = await screen.findByText('记忆检索注入');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'));
  });

  it('toggling 记忆检索注入 calls setMemoryRetrieval and NOT setAutoMemory (independent)', async () => {
    mocks.getAutoMemory.mockResolvedValue('true');
    mocks.getMemoryRetrieval.mockResolvedValue('true');
    renderTab();
    const row = await screen.findByText('记忆检索注入');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(mocks.setMemoryRetrieval).toHaveBeenCalledWith({ value: false }),
    );
    // The auto_memory IPC must NOT be touched by this toggle.
    expect(mocks.setAutoMemory).not.toHaveBeenCalled();
  });

  it('toggling 自动记忆沉淀 calls setAutoMemory and NOT setMemoryRetrieval (independent)', async () => {
    mocks.getAutoMemory.mockResolvedValue('true');
    mocks.getMemoryRetrieval.mockResolvedValue('true');
    renderTab();
    const row = await screen.findByText('自动记忆沉淀');
    const toggle = row.parentElement!.parentElement!.querySelector(
      '[role="switch"]',
    ) as HTMLElement;
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(toggle);
    await waitFor(() => expect(mocks.setAutoMemory).toHaveBeenCalledWith({ value: false }));
    // The memory_retrieval IPC must NOT be touched by this toggle.
    expect(mocks.setMemoryRetrieval).not.toHaveBeenCalled();
  });
});

describe('MemoryTab (fix/security-perf-quickwins §1.3b f, cherry-picked)', () => {
  it('renders the 同步到内部服务器 toggle bound to memoryServerSync, NOT autoMemory', () => {
    // autoMemory=true (GeneralTab semantics) but memoryServerSync=false.
    // Pre-fix this was wrongly tied to autoMemory, so the toggle would
    // render in the ON state here.
    const updateSettings = vi.fn().mockResolvedValue(undefined);
    render(
      <MemoryRouter>
        <MemoryTab settings={baseSettings} updateSettings={updateSettings} />
      </MemoryRouter>,
    );

    const labelEl = screen.getByText('同步到内部服务器');
    const settingRow = labelEl.parentElement!.parentElement!;
    const toggle = settingRow.querySelector('button');
    expect(toggle).not.toBeNull();
    expect(toggle!.className).toContain('bg-border');

    // Clicking it should update memoryServerSync, NOT autoMemory.
    fireEvent.click(toggle!);
    expect(updateSettings).toHaveBeenCalledWith({ memoryServerSync: true });
    const calls = updateSettings.mock.calls;
    for (const call of calls) {
      expect(call[0]).not.toHaveProperty('autoMemory');
    }
  });

  it('reflects the memoryServerSync value when already true (independent of autoMemory)', () => {
    const settings = { ...baseSettings, autoMemory: false, memoryServerSync: true };
    render(
      <MemoryRouter>
        <MemoryTab settings={settings} updateSettings={vi.fn().mockResolvedValue(undefined)} />
      </MemoryRouter>,
    );

    const labelEl = screen.getByText('同步到内部服务器');
    const settingRow = labelEl.parentElement!.parentElement!;
    const toggle = settingRow.querySelector('button');
    // ON state — driven by memoryServerSync=true, despite autoMemory=false.
    expect(toggle!.className).toContain('bg-primary');
  });

  it('does NOT hardcode the %APPDATA%\\Sage\\memory.db path display', () => {
    const { container } = render(
      <MemoryRouter>
        <MemoryTab settings={baseSettings} updateSettings={vi.fn().mockResolvedValue(undefined)} />
      </MemoryRouter>,
    );

    // Old bug: there was a readOnly <input value="%APPDATA%\\Sage\\memory.db">.
    // New behavior: only a generic descriptive span. No string match for the
    // hardcoded path anywhere in the rendered tree.
    expect(container.textContent).not.toContain('%APPDATA%');
    expect(container.textContent).not.toContain('Sage\\memory.db');

    const inputs = container.querySelectorAll('input');
    for (const input of inputs) {
      expect(input.getAttribute('value')).not.toContain('%APPDATA%');
    }
  });
});
