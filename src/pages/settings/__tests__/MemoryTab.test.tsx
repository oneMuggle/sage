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
