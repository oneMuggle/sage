/**
 * Renderer entry for the standalone pet status panel window.
 *
 * The panel lives in its own BrowserWindow so toggling it never resizes or
 * moves the pet overlay — resizing the overlay made the bottom-anchored
 * sprite jump while the new frame was being painted on XWayland.
 */
import { useCallback, useEffect, useState } from 'react';
import type { PetConfigBridge, PetSnapshotBridge } from '../shared/types/electron-api';

import { PetPanel } from './PetPanel';
import { DEFAULT_CONFIG, EMPTY_SNAPSHOT } from './defaults';

export function PetPanelApp(): JSX.Element {
  const [snapshot, setSnapshot] = useState<PetSnapshotBridge>(EMPTY_SNAPSHOT);
  const [config, setConfig] = useState<PetConfigBridge>(DEFAULT_CONFIG);
  const pet = typeof window !== 'undefined' ? window.electronAPI?.pet : undefined;

  useEffect(() => {
    if (!pet) return undefined;
    let alive = true;
    void pet.getConfig().then((value) => {
      if (alive) setConfig(value);
    });
    void pet.getState().then((value) => {
      if (alive) setSnapshot(value);
    });
    const offState = pet.onState((value) => {
      if (alive) setSnapshot(value);
    });
    const offConfig = pet.onConfig((value) => {
      if (alive) setConfig(value);
    });
    return () => {
      alive = false;
      offState();
      offConfig();
    };
  }, [pet]);

  const closePanel = useCallback(() => {
    pet?.setPanel(false);
  }, [pet]);

  const openSession = useCallback(
    (sessionId: string | null) => {
      if (sessionId) pet?.openSession(sessionId);
    },
    [pet],
  );

  const openSettings = useCallback(() => {
    pet?.openSettings();
  }, [pet]);

  return (
    <PetPanel
      snapshot={snapshot}
      config={config}
      onClose={closePanel}
      onOpenSession={openSession}
      onOpenSettings={openSettings}
    />
  );
}
