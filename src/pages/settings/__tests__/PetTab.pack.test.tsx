import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type {
  PetConfigBridge,
  PetInstanceBridge,
  PetPackManifestBridge,
} from '../../../shared/types/electron-api';
import { PetTab } from '../PetTab';

const BASE_CONFIG: PetConfigBridge = {
  version: 2,
  enabled: true,
  displayMode: 'desktop',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  followActiveSession: true,
  externalApi: false,
  pets: [{ id: 'default', petPack: 'dafeiyu', size: 'medium' }],
};

const MANIFEST: PetPackManifestBridge = {
  id: 'my-pet',
  name: '小叶灵',
  version: '1.0.0',
  license: 'CC-BY-4.0',
  canvas: { width: 256, height: 256 },
  anchor: { x: 128, y: 236 },
  actions: { idle: ['frames/idle-0.webp'] },
};

interface BridgeOptions {
  packs?: PetPackManifestBridge[];
  config?: PetConfigBridge;
}

function withPacks(config: PetConfigBridge, petPack: string): PetConfigBridge {
  return {
    ...config,
    pets: config.pets.map((pet: PetInstanceBridge, index) =>
      index === 0 ? { ...pet, petPack } : pet,
    ),
  };
}

function installBridge({ packs = [], config = BASE_CONFIG }: BridgeOptions = {}) {
  let currentConfig = { ...config, pets: config.pets.map((pet) => ({ ...pet })) };
  let currentPacks = [...packs];
  const bridge = {
    getConfig: vi.fn(async () => currentConfig),
    setConfig: vi.fn(async (patch: Partial<PetConfigBridge>) => {
      currentConfig = { ...currentConfig, ...patch };
      return currentConfig;
    }),
    getState: vi.fn(),
    onState: vi.fn(() => () => undefined),
    onConfig: vi.fn(() => () => undefined),
    listPacks: vi.fn(async () => currentPacks),
    importPack: vi.fn(async () => {
      currentPacks = [MANIFEST, ...currentPacks];
      currentConfig = withPacks(currentConfig, MANIFEST.id);
      return { ok: true, manifest: MANIFEST, config: currentConfig };
    }),
    exportPack: vi.fn(async () => ({ ok: true, path: '/tmp/my-pet.zip' })),
    deletePack: vi.fn(async (id: string) => {
      currentPacks = currentPacks.filter((pack) => pack.id !== id);
      currentConfig = withPacks(currentConfig, 'dafeiyu');
      return { ok: true };
    }),
  };
  (window as unknown as { electronAPI?: unknown }).electronAPI = { pet: bridge };
  return bridge;
}

function renderTab() {
  return render(
    <I18nProvider>
      <PetTab />
    </I18nProvider>,
  );
}

afterEach(() => {
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  vi.restoreAllMocks();
});

describe('PetTab animation packs', () => {
  it('shows only the import action for the built-in pack', async () => {
    installBridge();
    renderTab();
    await screen.findByTestId('pet-pack-default');
    expect(screen.getByTestId('pet-pack-import')).toBeInTheDocument();
    expect(screen.queryByTestId('pet-pack-export')).not.toBeInTheDocument();
    expect(screen.queryByTestId('pet-pack-delete')).not.toBeInTheDocument();
  });

  it('imports a pack, assigns it to the first pet and manages it', async () => {
    const bridge = installBridge();
    renderTab();
    await screen.findByTestId('pet-pack-default');

    fireEvent.click(screen.getByTestId('pet-pack-import'));
    await waitFor(() => expect(bridge.importPack).toHaveBeenCalledTimes(1));
    await screen.findByTestId('pet-pack-notice');

    expect((screen.getByTestId('pet-pack-default') as HTMLSelectElement).value).toBe('my-pet');
    expect((screen.getByTestId('pet-pack-manage') as HTMLSelectElement).value).toBe('my-pet');
    expect(screen.getByTestId('pet-pack-export')).toBeInTheDocument();
    expect(screen.getByTestId('pet-pack-delete')).toBeInTheDocument();
  });

  it('exports the pack selected in the management row', async () => {
    const bridge = installBridge({
      packs: [MANIFEST],
      config: withPacks(BASE_CONFIG, 'my-pet'),
    });
    renderTab();
    await screen.findByTestId('pet-pack-default');
    fireEvent.click(screen.getByTestId('pet-pack-export'));
    await waitFor(() => expect(bridge.exportPack).toHaveBeenCalledWith('my-pet'));
    expect(await screen.findByTestId('pet-pack-notice')).toHaveTextContent('/tmp/my-pet.zip');
  });

  it('deletes a pack only after a second click and falls back to built-in', async () => {
    const bridge = installBridge({
      packs: [MANIFEST],
      config: withPacks(BASE_CONFIG, 'my-pet'),
    });
    renderTab();
    await screen.findByTestId('pet-pack-default');

    fireEvent.click(screen.getByTestId('pet-pack-delete'));
    expect(bridge.deletePack).not.toHaveBeenCalled();
    expect(screen.getByTestId('pet-pack-delete')).toHaveTextContent('确认删除？');

    fireEvent.click(screen.getByTestId('pet-pack-delete'));
    await waitFor(() => expect(bridge.deletePack).toHaveBeenCalledWith('my-pet'));
    await waitFor(() =>
      expect((screen.getByTestId('pet-pack-default') as HTMLSelectElement).value).toBe('dafeiyu'),
    );
    expect(screen.queryByTestId('pet-pack-delete')).not.toBeInTheDocument();
  });

  it('adds and removes pets up to the cap', async () => {
    const bridge = installBridge();
    renderTab();
    await screen.findByTestId('pet-row-default');

    fireEvent.click(screen.getByTestId('pet-add'));
    await waitFor(() => expect(screen.getAllByTestId(/pet-row-/)).toHaveLength(2));
    const added = bridge.setConfig.mock.calls.at(-1)?.[0] as Partial<PetConfigBridge>;
    expect(added.pets).toHaveLength(2);
    expect(added.pets?.map((pet) => pet.id)).toEqual(['default', 'pet-1']);

    fireEvent.click(screen.getByTestId('pet-remove-pet-1'));
    await waitFor(() => expect(screen.getAllByTestId(/pet-row-/)).toHaveLength(1));
  });

  it('changes size per pet without touching the other', async () => {
    const bridge = installBridge({
      config: {
        ...BASE_CONFIG,
        pets: [
          { id: 'default', petPack: 'dafeiyu', size: 'medium' },
          { id: 'pet-1', petPack: 'dafeiyu', size: 'medium' },
        ],
      },
    });
    renderTab();
    await screen.findByTestId('pet-size-pet-1');

    fireEvent.change(screen.getByTestId('pet-size-pet-1'), { target: { value: 'large' } });
    const patch = bridge.setConfig.mock.calls.at(-1)?.[0] as Partial<PetConfigBridge>;
    expect(patch.pets).toEqual([
      { id: 'default', petPack: 'dafeiyu', size: 'medium' },
      { id: 'pet-1', petPack: 'dafeiyu', size: 'large' },
    ]);
  });
});
