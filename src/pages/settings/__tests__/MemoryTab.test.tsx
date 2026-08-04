// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MemoryTab } from '../MemoryTab';

const mocks = vi.hoisted(() => ({
  getAutoMemory: vi.fn(),
  setAutoMemory: vi.fn(),
}));

beforeEach(() => {
  mocks.getAutoMemory.mockReset();
  mocks.setAutoMemory.mockReset();
  mocks.getAutoMemory.mockResolvedValue(null);
  mocks.setAutoMemory.mockResolvedValue(undefined);

  // Install electronAPI stub on window
  Object.defineProperty(window, 'electronAPI', {
    configurable: true,
    value: {
      memory: {
        getAutoMemory: (...args: unknown[]) => mocks.getAutoMemory(...args),
        setAutoMemory: (...args: unknown[]) => mocks.setAutoMemory(...args),
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
      <MemoryTab
        settings={baseSettings}
        updateSettings={vi.fn().mockResolvedValue(undefined)}
      />
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
    await waitFor(() =>
      expect(mocks.setAutoMemory).toHaveBeenCalledWith({ value: false }),
    );
  });
});